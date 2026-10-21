"""Evidence-bounded failure attribution; never infer model errors from HTTP status.

Raw errors and source text are not inspected or exported. A stage-only diagnosis
identifies where a failure surfaced, not its independently proven root cause.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

STAGES = frozenset({'parsing_ocr', 'extraction', 'retrieval', 'selection', 'planning',
                    'tools', 'state', 'approval', 'delivery', 'scoring'})
STAGE_ALIASES = {'parse': 'parsing_ocr', 'ocr': 'parsing_ocr', 'planner': 'planning'}
CODE_CAUSES = {
    'MODEL_RATE_LIMITED': 'quota', 'MODEL_QUOTA_EXHAUSTED': 'quota',
    'MODEL_CAPACITY_TIMEOUT': 'admission_capacity',
    'FROZEN_INPUT_CHANGED': 'evaluation_integrity',
    'HARD_SAFETY_VIOLATION': 'safety',
    'RUN_BUDGET_EXHAUSTED': 'budget',
    'MODEL_IDENTITY_MISMATCH': 'configuration',
    'SCHEDULE_PARSE_TIMEOUT': 'parsing_ocr', 'SCHEDULE_PARSE_FAILED': 'parsing_ocr',
    'SCHEDULE_PARSER_UNAVAILABLE': 'parsing_ocr',
}
CONTENT_CAUSES = {
    'incomplete_output': 'incomplete_output', 'model_refusal': 'model_refusal',
    'native_schema_invalid': 'schema_validation', 'domain_schema_invalid': 'schema_validation',
    'application_validation': 'application_validation',
}
SUCCESS = frozenset({'completed', 'ready_for_review', 'succeeded', 'success'})


def diagnose(*, state, stage=None, error_code=None, http_status=None, failure_category=None):
    """Return only allowlisted labels; unavailable evidence stays explicit."""
    stage = STAGE_ALIASES.get(stage, stage) if isinstance(stage, str) else None
    stage = stage if stage in STAGES else 'unknown'
    code = error_code if isinstance(error_code, str) and error_code in CODE_CAUSES else None
    status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
    if state == 'unattempted':
        return dict(outcome='unattempted', stage=stage, cause='unattempted', attribution='none')
    if code:
        cause, attribution = CODE_CAUSES[code], 'explicit_code'
    elif status == 429:
        cause, attribution = 'quota', 'http_status'
    elif status in {401, 403}:
        cause, attribution = 'provider_access', 'http_status'
    elif status is not None and status >= 400:
        cause, attribution = 'provider_rejection', 'underlying_cause_unknown'
    elif isinstance(failure_category, str) and failure_category in CONTENT_CAUSES:
        cause, attribution = CONTENT_CAUSES[failure_category], 'explicit_category'
    elif state in SUCCESS:
        return dict(outcome='completed', stage=stage, cause='not_assessed', attribution='none')
    else:
        cause, attribution = stage, 'stage_only' if stage != 'unknown' else 'unknown'
    return dict(outcome='failed', stage=stage, cause=cause, attribution=attribution)


def summarize_capture(capture):
    """Read a sealed repeated/assembled capture without changing its historical score."""
    capture = Path(capture).resolve()
    manifest = json.loads((capture / 'capture-manifest.json').read_text())
    if not isinstance(manifest, dict) or not {'config.json', 'summary.json', 'preflight.json'} <= set(manifest):
        raise ValueError('Incomplete capture seal')
    for name, expected in manifest.items():
        if (Path(name).name != name or (capture / name).resolve().parent != capture
                or sha256((capture / name).read_bytes()).hexdigest() != expected):
            raise ValueError('Capture integrity failure')
    config = json.loads((capture / 'config.json').read_text())
    schedule = config['schedule']
    planned = {row['trial_id']: row for row in schedule}
    if len(planned) != len(schedule) or not planned:
        raise ValueError('Invalid trial schedule')

    def read(name):
        return [json.loads(line) for line in (capture / name).read_text().splitlines()] if name in manifest else []

    repeated = 'predictions.jsonl' in manifest
    records = read('predictions.jsonl') if repeated else read('reports.jsonl')
    actual = {}
    for row in records:
        tid = row.get('trial_id')
        if tid not in planned or tid in actual:
            raise ValueError('Duplicate or unscheduled outcome')
        actual[tid] = row
    usage = {}
    for row in read('usage.jsonl'):
        tid = row.get('trial_id')
        if tid not in planned or tid in usage:
            raise ValueError('Duplicate or unscheduled usage')
        usage[tid] = row
    details = []
    for tid in planned:
        row = actual.get(tid, {})
        # A 400 is a provider rejection, not evidence of quota/schema incompatibility.
        diagnosis = diagnose(state=row.get('state', 'unattempted'),
                             stage=row.get('failure_stage', 'extraction' if repeated else None),
                             error_code=row.get('failure_code'), http_status=usage.get(tid, {}).get('status'),
                             failure_category=row.get('failure_category'))
        details.append(dict(trial_sha256=sha256(tid.encode()).hexdigest(), **diagnosis))
    stages = []
    pairs = {(row.get('case_id'), row.get('arm')) for row in schedule}
    for call in read('calls.jsonl'):
        if (call.get('case_id'), call.get('arm')) not in pairs:
            raise ValueError('Unscheduled stage call')
        stages.append(diagnose(state='completed' if call.get('ok') is True else 'failed',
                               stage=call.get('stage'), error_code=call.get('failure_code'),
                               http_status=call.get('http_status')))
    return dict(version='error-taxonomy-v1', capture_manifest_sha256=sha256(
        (capture / 'capture-manifest.json').read_bytes()).hexdigest(),
        scheduled=len(planned), attempted=len(actual),
        outcome_counts=dict(Counter(row['outcome'] for row in details)),
        failure_causes=dict(Counter(row['cause'] for row in details if row['outcome'] == 'failed')),
        stage_failure_causes=dict(Counter(row['cause'] for row in stages if row['outcome'] == 'failed')),
        trials=details, stage_calls=stages, release_accepted=False,
        limitations=['Completed transport/state does not establish semantic correctness.',
                     'Stage-only attribution identifies a failure location, not proven root cause.',
                     'Historical captures may lack stage/code evidence; unknown is retained.',
                     'HTTP 400/5xx do not establish a schema, quota or model-quality root cause.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize_capture(args.capture)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
