"""Offline preregistration and durable, one-use source-family consumption.

The registry governs callers that use it. It cannot verify human review, detect
undeclared lineage, or prove freshness against exposure history it was not given.
"""
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from evaluation.repeated_development import verify_plan


def pairing(plan):
    arms = set(plan['prompts'])
    pairs, orders = defaultdict(list), []
    for trial in plan['schedule']:
        pairs[(trial['case_id'], trial['repetition'])].append(trial['arm'])
    if not pairs or len(arms) != 2 or any(len(v) != 2 or set(v) != arms for v in pairs.values()):
        raise ValueError('Every case/repetition requires both distinct arms exactly once')
    for key, arm_order in pairs.items():
        orders.append(dict(case_id=key[0], repetition=key[1], first_arm=arm_order[0]))
    return dict(pair_count=len(pairs), arm_count=len(arms), orders=orders,
                counterbalanced=len({v[0] for v in pairs.values()}) == 2,
                quota_conditions_verified=False)


def preregister(prepared, output, *, hypothesis):
    """Seal an existing executable plan without changing its budgets or sources."""
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError('A preregistered hypothesis is required')
    prepared, output = Path(prepared), Path(output)
    plan, _, _ = verify_plan(prepared)
    pairing_result = pairing(plan)
    baseline = next(iter(plan['prompts']))
    lineage = json.loads((Path(plan['fixture_path']).parent/'lineage.json').read_text())['cases']
    membership = [dict(case_id=identity, split='development',
                       group_id=lineage[identity].get('group_id', lineage[identity].get('family')))
                  for identity in sorted({r['case_id'] for r in plan['schedule']})]
    if any(not isinstance(r['group_id'], str) or not r['group_id'].strip() for r in membership):
        raise ValueError('Explicit source families required for registered dataset')
    result = dict(version='study-preregistration-v1', hypothesis=hypothesis,
                  plan_sha256=sha256((prepared/'plan.json').read_bytes()).hexdigest(),
                  baseline_arm=baseline,
                  baseline_prompt_sha256=sha256(plan['prompts'][baseline].encode()).hexdigest(),
                  wire_schema_sha256=plan['wire_schema_sha256'],
                  dataset_label_source_sha256=plan['source_sha256'],
                  model=plan['model'], credential_slot_alias=f"slot_{plan['key_slot']}",
                  comparison=plan['comparison'], primary_metric=plan['primary_metric'],
                  budget=plan['budget'], stop_conditions=plan['stop_conditions'],
                  pairing=pairing_result, consumed_development=True,
                  membership=membership,
                  controls_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                  live_execution_authorized=False, release_accepted=False,
                  limitations=['Current provider capability/price/quota preflight remains mandatory.',
                               'This freezes a development plan; no inference or model comparison was executed.'])
    # Exclusive creation prevents overwriting plans, labels or historical evidence.
    with output.open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    return result


def verify_registration(prepared, registration):
    prepared, registration = Path(prepared), Path(registration)
    record = json.loads(registration.read_text())
    plan, _, _ = verify_plan(prepared)
    if record['plan_sha256'] != sha256((prepared/'plan.json').read_bytes()).hexdigest():
        raise ValueError('Registered plan changed')
    if (record['dataset_label_source_sha256'] != plan['source_sha256'] or
            record['wire_schema_sha256'] != plan['wire_schema_sha256'] or
            record['budget'] != plan['budget'] or record['pairing'] != pairing(plan)):
        raise ValueError('Registration no longer matches executable plan')
    baseline = next(iter(plan['prompts']))
    if (record['baseline_arm'] != baseline or
            record['baseline_prompt_sha256'] != sha256(plan['prompts'][baseline].encode()).hexdigest() or
            record['controls_source_sha256'] != sha256(Path(__file__).read_bytes()).hexdigest() or
            record['model'] != plan['model'] or record['comparison'] != plan['comparison'] or
            record['primary_metric'] != plan['primary_metric'] or
            record['stop_conditions'] != plan['stop_conditions'] or
            record['credential_slot_alias'] != f"slot_{plan['key_slot']}" or
            not isinstance(record['hypothesis'], str) or not record['hypothesis'].strip() or
            record['live_execution_authorized'] is not False or
            record.get('release_accepted') is not False or
            record.get('consumed_development') is not True):
        raise ValueError('Registration identity or control implementation changed')
    lineage = json.loads((Path(plan['fixture_path']).parent/'lineage.json').read_text())['cases']
    expected_membership = [dict(case_id=identity, split='development',
                                group_id=lineage[identity].get('group_id', lineage[identity].get('family')))
                           for identity in sorted({r['case_id'] for r in plan['schedule']})]
    if record['membership'] != expected_membership:
        raise ValueError('Registered split membership changed')
    return record


def configuration_digest(configuration):
    return sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest()


class ConsumptionRegistry:
    """Atomic persistent family reservation; no reset or overwrite operation."""
    def __init__(self, path):
        self.path = Path(path)
        with sqlite3.connect(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS consumed (
                family TEXT PRIMARY KEY, split TEXT NOT NULL,
                configuration_sha256 TEXT NOT NULL, dataset_sha256 TEXT NOT NULL,
                recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')

    def snapshot(self):
        with sqlite3.connect(self.path) as db:
            return [dict(family=r[0], split=r[1], configuration_sha256=r[2], dataset_sha256=r[3], recorded_at=r[4])
                    for r in db.execute('SELECT * FROM consumed ORDER BY family')]

    def reserve(self, rows, *, split, configuration_sha256, dataset_sha256, tuning_status):
        for value in (configuration_sha256, dataset_sha256):
            if (not isinstance(value, str) or len(value) != 64 or
                    any(c not in '0123456789abcdef' for c in value)):
                raise ValueError('Frozen configuration/dataset hashes required')
        if split not in {'development', 'validation', 'holdout'}:
            raise ValueError('Unknown split')
        if split == 'holdout' and tuning_status != 'stopped':
            raise ValueError('Stop tuning before consuming holdout families')
        families = set()
        if not rows:
            raise ValueError('Source-family inventory required')
        for row in rows:
            group = row.get('group_id')
            parents = row.get('parent_group_ids', [])
            if (not isinstance(group, str) or not group.strip() or group != group.strip() or
                    not isinstance(parents, list) or
                    any(not isinstance(p, str) or not p.strip() or p != p.strip() for p in parents)):
                raise ValueError('Explicit source families required')
            families.update([group, *parents])
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = {r[0] for r in db.execute('SELECT family FROM consumed')}
            if families & existing:
                raise ValueError('Source family already consumed; use a new family')
            db.executemany('INSERT INTO consumed (family, split, configuration_sha256, dataset_sha256) VALUES (?, ?, ?, ?)', [
                (family, split, configuration_sha256, dataset_sha256) for family in sorted(families)])
        return dict(families_reserved=len(families), split=split, configuration_sha256=configuration_sha256,
                    dataset_sha256=dataset_sha256, release_accepted=False)


def guard_holdout(rows, manifest, *, registry, configuration, dataset_sha256):
    """Reserve before inference; rejected/failed captures still consume the family."""
    control = manifest.get('holdout_control', {})
    expected = configuration_digest(configuration)
    if (control.get('tuning_status') != 'stopped' or
            control.get('configuration_sha256') != expected or registry is None):
        raise ValueError('Holdout requires stopped tuning, a matching frozen configuration and consumption registry')
    return ConsumptionRegistry(registry).reserve(
        rows, split='holdout', configuration_sha256=expected,
        dataset_sha256=dataset_sha256, tuning_status='stopped')


def verify_holdout_result(config, manifest, *, historical_diagnostic=False):
    """Gate the scorer before labels/results are parsed; preserve explicit reanalysis."""
    if config.get('split') != 'holdout':
        return dict(holdout=False, historical_diagnostic=False, release_accepted=False)
    if historical_diagnostic:
        return dict(holdout=True, historical_diagnostic=True, fresh_acceptance_evidence=False,
                    release_accepted=False)
    control, reservation = manifest.get('holdout_control', {}), config.get('holdout_reservation')
    if not isinstance(reservation, dict):
        raise ValueError('Holdout result lacks a retained pre-inference family reservation')
    names = ('provider', 'model', 'key_slot', 'prompt_version', 'prompt_sha256',
             'timeout_seconds', 'source_sha256')
    if any(name not in config for name in names):
        raise ValueError('Holdout result lacks frozen configuration')
    expected = configuration_digest({name: config[name] for name in names})
    if (control.get('tuning_status') != 'stopped' or
            control.get('configuration_sha256') != expected or
            reservation.get('configuration_sha256') != expected or
            reservation.get('dataset_sha256') != config.get('inputs_sha256') or
            type(reservation.get('families_reserved')) is not int or reservation['families_reserved'] < 1):
        raise ValueError('Holdout result configuration or consumption reservation changed')
    return dict(holdout=True, historical_diagnostic=False, release_accepted=False,
                limitation='Reservation does not prove independent review or complete historical exposure coverage.')
