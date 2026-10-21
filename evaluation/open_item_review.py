"""Evidence review for the finite evaluations named in the open-item study.

Does not change checklist boxes automatically; saved decisions require inspection.
"""
from collections import Counter
from hashlib import sha256
import argparse
import json
from pathlib import Path

from evaluation.open_item_study import TARGETS, projection, write


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def verify_capture(path):
    manifest = json.loads((path/'capture-manifest.json').read_text())
    for name, expected in manifest.items():
        if sha256((path/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Changed capture: '+name)
    return read_rows(path/'calls.jsonl')


def metrics(rows, expected):
    return dict(scheduled=expected, attempted=len(rows),
        wire_valid=sum(r.get('checks', {}).get('wire_valid', False) for r in rows),
        domain_valid=sum(r.get('checks', {}).get('domain_valid', False) for r in rows),
        grounded_exact=sum(r.get('checks', {}).get('selected_fields_exact', False) for r in rows),
        prompt_tokens=sum((r.get('usage') or {}).get('prompt_tokens', 0) for r in rows),
        completion_tokens=sum((r.get('usage') or {}).get('completion_tokens', 0) for r in rows),
        elapsed_seconds=sum(r.get('elapsed_seconds', 0) for r in rows),
        admission_ms=sum((r.get('metrics', {}).get('groq') or {}).get('admission_ms', 0) for r in rows),
        transport_ms=sum((r.get('metrics', {}).get('groq') or {}).get('transport_ms', 0) for r in rows),
        unknown_usage=sum(r.get('usage') is None for r in rows))


def review(batch, output, *, resumed=None):
    batch, output = Path(batch), Path(output)
    plan = json.loads((batch/'prepared/plan.json').read_text())
    original_summary = json.loads((batch/'live/summary.json').read_text())
    summary = json.loads((batch/'continuation-live-v2/summary.json').read_text())
    if resumed is not None:
        resumed = Path(resumed)
        if summary['stop_reason'] != 'KeyboardInterrupt':
            raise ValueError('Owner-resumed review requires the retained interruption')
        summary = json.loads((resumed/'summary.json').read_text())
    if summary['stop_reason'] or not original_summary['stop_reason']:
        raise ValueError('Expected retained original stop and completed continuation required')
    original_rows = verify_capture(batch/'live')
    first_continuation_rows = verify_capture(batch/'continuation-live')
    continuation_rows = verify_capture(batch/'continuation-live-v2')
    if resumed is not None:
        continuation_rows += verify_capture(resumed)
    diagnostic_rows = []
    for name in ['strict-canary-20b-live', 'strict-canary-120b-live', 'strict-union-live']:
        diagnostic_rows += verify_capture(batch/name)
    expected_continuation = 76 if resumed is not None else 75
    assert len(original_rows) == 24 and len(first_continuation_rows) == 2 and len(continuation_rows) == expected_continuation and len(diagnostic_rows) == 3
    primary_rows = original_rows+first_continuation_rows+[r for r in continuation_rows if not r.get('followup') and not r.get('correct_control')]
    supplement_rows = [r for r in continuation_rows if r.get('followup')]
    control_rows = [r for r in continuation_rows if r.get('correct_control')]
    assert len(supplement_rows) == 11 and len(control_rows) == 1
    control = dict(before=True, after=control_rows[0].get('checks', {}).get('selected_fields_exact', False),
                   source='zero:administrative', id=control_rows[0]['id'])
    all_rows = primary_rows+supplement_rows+control_rows+diagnostic_rows
    by_id = {r['id']: r for r in primary_rows+diagnostic_rows}
    extra = {r['id']: r for r in supplement_rows+control_rows}
    dispositions = []
    def record(item, ids, finding, decision, extra_ids=(), details=None, allow_http_failures=False):
        rows = [by_id[i] for i in ids]+[extra[i] for i in extra_ids]
        if not allow_http_failures and any(r.get('status') != 200 for r in rows):
            raise ValueError(item+' lacks completed provider responses')
        dispositions.append(dict(item_id=item, evaluation_complete=True,
            primary_call_ids=ids, supplement_call_ids=list(extra_ids),
            measurements=metrics(rows, len(ids)+len(extra_ids)), finding=finding,
            decision=decision, details=details, release_accepted=False))
    cases = ['DEV-20261020-01', 'DEV-20261020-02', 'DEV-20261020-04', 'DEV-20261020-06',
             'DEV-20261020-07', 'DEV-20261020-08', 'DEV-20261020-09', 'administrative']
    paired = [f'{arm}:{case}' for case in cases for arm in ['zero', 'few']]
    comparable = ['DEV-20261020-01', 'DEV-20261020-04', 'DEV-20261020-08']
    copy_checks = []
    for identity in paired+[f'reverse:{case}' for case in comparable]:
        row = by_id[identity]
        text = plan['cases'][row['case']]['text']
        returned = row.get('value', {})
        # Only critical exact values absent from the case count as copied demo fields.
        suspicious = []
        for o in returned.get('observations', []):
            for value in [o.get('area'), *o.get('asset_tags', [])]:
                if value in ['Zone Demo', 'Zone Sample', 'DEMO-071', 'DEMO-082'] and value not in text:
                    suspicious.append(value)
            if str(o.get('quantity')) in ['9', '11'] and str(o.get('quantity')) not in text:
                suspicious.append('quantity='+str(o['quantity']))
            if o.get('work_date') in ['2026-09-01', '2026-09-02']:
                suspicious.append('date='+o['work_date'])
        copy_checks.append(dict(id=identity, suspicious_values=suspicious))
    paired_metrics = {arm: metrics([by_id[f'{arm}:{case}'] for case in cases], len(cases))
                      for arm in ['zero', 'few']}
    record('PROMPT-02', paired, 'Paired zero-shot and three-example comparison on eight consumed development cases.',
           'No production adoption; assess exact fields and evidence separately from schema validity.',
           details={'paired_arms': paired_metrics, 'demonstration_count': 3})
    demo_ids = [r['id'] for r in supplement_rows if r['kind'] == 'demos']
    record('PROMPT-03', paired, 'Ordinary/measured/unquantified and hard/multi-event/correction/abstention inputs plus separately measured ordinary and difficult demonstration sets.',
           'Do not infer a universal demonstration policy from this small authored set.', extra_ids=demo_ids,
           details={'input_slices': {'ordinary': cases[:2], 'hard': cases[2:7], 'abstention': ['administrative']},
                    'demonstration_groups': {'ordinary': 2, 'difficult': 2},
                    'ordinary_demonstrations': metrics([r for r in supplement_rows if r.get('arm') == 'ordinary'], 2),
                    'difficult_demonstrations': metrics([r for r in supplement_rows if r.get('arm') == 'difficult'], 2)})
    record('PROMPT-04', [f'{arm}:{case}' for case in comparable for arm in ['few', 'reverse']],
           'Same three demonstrations compared forward/reverse, with exact-value contamination audit.',
           'Retain order sensitivity and suspicious values; do not expand example count.', details={'copy_audit': copy_checks})
    record('PROMPT-05', [f'{arm}:{case}' for case in comparable for arm in ['zero', 'long']],
           'Current V12 long prompt compared with consolidated zero-shot specification under the same wire and domain schema.',
           'Production prompt unchanged; failures in protected event/date/quantity/location/evidence fields prohibit adoption.',
           details={'prompt_characters': {arm: len(plan['prompts'][arm]) for arm in ['zero', 'long']}})
    hard = ['DEV-20261020-04', 'DEV-20261020-07']
    record('PROMPT-06', [f'{a}:{case}' for case in hard for a in ['zero', 'medium']],
           'Low versus medium reasoning on identical correction/multi-event inputs.',
           'No higher-effort escalation or production setting change.',
           details={a: metrics([by_id[f'{a}:{case}'] for case in hard], 2) for a in ['zero', 'medium']})
    native_ids = ['native-False:DEV-20261020-04', 'native-True:DEV-20261020-04', 'strict-union:DEV-20261020-04']
    record('PROMPT-07', native_ids,
           'Identical explicit-union schema and correction input tested under best-effort and strict; strict succeeds in one separate grammar diagnostic and rejects the later matched request. Domain and selected-field results remain separate from HTTP/schema validity.',
           'Inconclusive/do not adopt strict. Both HTTP400s and all unattempted trials stay retained; a successful strict probe does not establish reliability or the cause of rejection.',
           allow_http_failures=True,
           details={'legacy_failure': {'id': 'strict:DEV-20261020-04', 'status': 400, 'cause': 'unknown; error body excluded'},
                    'grammar_probes': [r['id'] for r in diagnostic_rows],
                    'retired_unattempted_pairs': ['native-True:DEV-20261020-07', 'native-False:DEV-20261020-07'],
                    'paired_arms': {str(flag): metrics([by_id[f'native-{flag}:{case}'] for case in hard if f'native-{flag}:{case}' in by_id], 2) for flag in [False, True]},
                    'separate_successful_strict_diagnostic': by_id['strict-union:DEV-20261020-04']['checks']})
    transitions = []
    for case in comparable:
        before = by_id[f'zero:{case}']['checks']['selected_fields_exact']
        after = by_id[f'repair:{case}']['checks']['selected_fields_exact']
        transitions.append(dict(case=case, before=before, after=after,
                                fixed=not before and after, damaged=before and not after))
    record('PROMPT-09', [f'{a}:{case}' for case in comparable for a in ['zero', 'repair']],
           'Exactly one domain/evidence-validator feedback repair per input; gold never enters feedback.',
           'No unconditional repair adoption; retain fixed, damaged and unresolved answers and marginal resource cost.',
           extra_ids=['correct-repair:administrative'],
           details={'transitions': transitions, 'correct_control': control,
                    'added_resources': metrics([by_id[f'repair:{c}'] for c in comparable]+control_rows, 4)})
    repeated = [f'{a}:DEV-20261020-04' for a in ['zero', 'repeat2', 'repeat3']]
    choices = [json.dumps(projection(by_id[i].get('value', {})), sort_keys=True) for i in repeated]
    record('PROMPT-10', repeated+['critic:DEV-20261020-04'],
           'Preregistered three-sample self-consistency and separate 120B review on the correction hard case, at most four calls.',
           'No best-of-N credit or consensus-as-truth; retain majority decision and original errors.',
           details={'majority_votes': Counter(choices).most_common(1)[0][1], 'distinct_decisions': len(set(choices)),
                    'samples': [by_id[i]['checks'] for i in repeated]})
    access = json.loads((batch/'account-access.json').read_text())
    public = json.loads((batch/'provider-sources-v2.json').read_text())
    fresh_preflight = (json.loads((resumed.parent/'preflight.json').read_text())
                       if resumed is not None else None)
    record('MODEL-01', [r['id'] for r in primary_rows if r['kind'] in ['tool', 'guard']]+['zero:DEV-20261020-01', 'large:DEV-20261020-01'],
           'Exact IDs, active catalog entries, current credential listing permissions, public production/preview status and actual inference verified for study roles.',
           'GPT-OSS models are production-listed; both guards are preview/evaluation-only. No plan/quota entitlement or permissions outside tested aliases are inferred.',
           details={'account_access': access, 'sources': public, 'resumed_preflight': fresh_preflight})
    record('MODEL-02', [r['id'] for r in primary_rows if r['kind'] == 'tool']+
           ['zero:DEV-20261020-01', 'large:DEV-20261020-01', 'native-True:DEV-20261020-04', 'medium:DEV-20261020-04', 'canary:20b', 'canary:120b'],
           'Structured output, low/medium reasoning and read-only forced tool calls tested; advertised context/output bounds and guard 512-token limits inventoried.',
           'Minimal strict schemas succeed but full extraction strict is unreliable and not adopted; no maximum-context stress or runtime limit increase.',
           allow_http_failures=True,
           details={'tool_results': {r['model']: r['checks'] for r in primary_rows if r['kind'] == 'tool'},
                    'gpt_context': 131072, 'gpt_max_output': 65536, 'guard_context': 512, 'study_output_cap': 3072})
    compared = cases[:4]
    record('MODEL-03', [f'{arm}:{case}' for case in compared for arm in ['zero', 'large']],
           '20B and 120B receive identical four extraction inputs, prompt, schema, settings and credential slot.',
           'No claims about selection/planner superiority or population model ranking.',
           details={arm: metrics([by_id[f'{arm}:{case}'] for case in compared], 4) for arm in ['zero', 'large']})
    verdict_ids = [r['id'] for r in supplement_rows if r['kind'] == 'verdict']
    record('MODEL-07', [f'{arm}:{case}' for case in comparable for arm in ['zero', 'critic']],
           'Worker final JSON, revised critic output and explicit separate verdict are retained in sealed, distinct capture records.',
           'Critic agreement cannot erase the worker error or approve progress.', extra_ids=verdict_ids,
           details={'explicit_verdicts': [{k: r.get(k) for k in ['id', 'parent', 'value', 'checks']} for r in supplement_rows if r['kind'] == 'verdict']})
    no_events = ['empty', 'administrative', 'unreadable', 'out-of-domain']
    no_event_ids = [f'zero:{case}' for case in no_events]
    if resumed is not None:
        no_event_ids.append('recovery:zero:empty')
    record('QUAL-15', no_event_ids,
           'Actual model no-event behavior measured separately for empty, administrative, unreadable and out-of-domain inputs.',
           'Any fabricated event remains a failure; no empty schema-only success credit on real-event inputs.',
           allow_http_failures=resumed is not None,
           details={identity: by_id[identity].get('checks', {'interrupted': True}) for identity in no_event_ids})
    for item, variants in [('ROB-01', ['paraphrase']), ('ROB-02', ['whitespace', 'case-punctuation']),
                           ('ROB-04', ['quantity', 'date', 'negation', 'unit', 'location']), ('ROB-07', ['renamed'])]:
        changes = []
        original = projection(by_id['zero:DEV-20261020-01'].get('value', {}))
        for case in variants:
            row = by_id[f'zero:{case}']
            expected = projection({'observations': plan['labels'][case]})
            observed = projection(row.get('value', {}))
            changes.append(dict(case=case, original=original, expected=expected, observed=observed,
                                selected_values_match=observed == expected, contract=row.get('checks')))
        record(item, ['zero:DEV-20261020-01']+[f'zero:{case}' for case in variants],
               'Actual structured model outputs compared against fact-preserving or one-fact-mutated development inputs.',
               'Field-level differences and grounding failures remain explicit; no operational robustness estimate.', details={'variants': changes})
    stability = []
    stable_ids = []
    for case in ['DEV-20261020-01', 'DEV-20261020-04']:
        ids = [f'{arm}:{case}' for arm in ['zero', 'repeat2', 'repeat3']]
        stable_ids += ids
        outputs = [projection(by_id[i].get('value', {})) for i in ids]
        stability.append(dict(case=case, repetitions=3, distinct_selected_decisions=len({json.dumps(o, sort_keys=True) for o in outputs}),
                              critical_fields_disagree=any(o != outputs[0] for o in outputs[1:]),
                              all_grounded_exact=[by_id[i]['checks']['selected_fields_exact'] for i in ids]))
    record('ROB-08', stable_ids, 'Identical live settings/input repeated three times for ordinary and correction cases.',
           'Stable wrong decisions remain wrong; no cherry-picking or independent-trial population inference.', details={'stability': stability})
    selection_ids = [r['id'] for r in primary_rows if r['kind'] == 'selection']
    sizing = {}
    for count in [1, 2, 8]:
        for rep in ['full', 'compact']:
            chosen = [r for r in primary_rows if r['kind'] == 'selection' and r['count'] == count and r['representation'] == rep]
            sizing[f'{count}:{rep}'] = metrics(chosen, 3)
    record('RET-12', selection_ids, 'Candidate sizes one/two/eight and full/compact row representations compared on supported, missing-target and unrelated-quote contexts.',
           'No production candidate-size change from this tiny diagnostic; compare tokens and transport separately from shared admission.', details={'matrix': sizing})
    oracle = [f'select:{case}:2:full' for case in ['supported', 'missing']]
    record('RET-15', oracle, 'Same source/correct quote is diagnosed with the correct candidate supplied versus absent.',
           'Oracle context is explicitly diagnostic, never a production retrieval score.',
           details={i: by_id[i].get('value') for i in oracle})
    support_ids = [r['id'] for r in primary_rows if r['kind'] == 'selection' and r['case'] in ['supported', 'unsupported']]
    support = [dict(id=i, checks=by_id[i]['checks'], value=by_id[i].get('value')) for i in support_ids]
    record('RET-16', support_ids,
           'The same report contains installation for one activity and no-work for another; claimed quoted evidence is varied independently of report contents.',
           'Only the quote-supported actual installation may select an activity; unrelated/no-work quotes must abstain.', details={'outcomes': support})
    guards = {}
    for model in list(plan['prices'])[2:]:
        values = [r for r in all_rows if r['kind'] == 'guard' and r['model'] == model]
        tp = sum(r['attack'] and r.get('checks', {}).get('predicted_attack') is True for r in values)
        fp = sum(not r['attack'] and r.get('checks', {}).get('predicted_attack') is True for r in values)
        fn = sum(r['attack'] and r.get('checks', {}).get('predicted_attack') is not True for r in values)
        tn = sum(not r['attack'] and r.get('checks', {}).get('predicted_attack') is False for r in values)
        guards[model] = dict(attempted=len(values), tp=tp, fp=fp, fn=fn, tn=tn,
            precision=tp/(tp+fp) if tp+fp else None, recall=tp/(tp+fn) if tp+fn else None,
            false_positive_rate=fp/3, evasion_rate=fn/3,
            unknown_outputs=sum(r.get('checks', {}).get('unknown_guard_output', False) for r in values),
            resources=metrics(values, 6))
    safe_ids = [r['id'] for r in primary_rows if r['kind'] == 'guard' and not r['attack']]
    record('SAFE-05', safe_ids, 'Legitimate hard-hat/trench, supervisor and evacuation directions scored through both real guard classifiers.',
           'False positives are development observations on three authored examples per model, not deployment prevalence.', details={'guards': guards})
    record('SAFE-06', [r['id'] for r in primary_rows if r['kind'] == 'guard'],
           '22M/86M guards compare the same three legitimate and three attack inputs at frozen threshold 0.5, with calls and timing retained.',
           'No guard adopted: small authored set, preview models, missing independent labels and long-input coverage.',
           details={'guards': guards, 'no_model_guard_baseline': {'calls': 0, 'latency_ms': 0,
                    'policy': 'allow all; this has no classifier verdict', 'attack_passage': '3/3',
                    'legitimate_blocked': '0/3', 'classifier_precision': None,
                    'policy_detection_recall': 0, 'policy_false_positive_rate': 0,
                    'policy_evasion_rate': 1,
                    'timing_scope': 'No added provider call/time by definition; assembled workflow latency is unmeasured.'}})
    record('CAP-13', [], 'All three aliases list required models but return HTTP403 for read-only Batch listing.',
           'Defer Batch until explicit account permission; no batch submitted and no interactive use.', details={'evidence': 'account-access.json', 'guide': 'https://console.groq.com/docs/batch'})
    primary_judges = [r['id'] for r in primary_rows if r['kind'] == 'judge']
    random_judges = [r['id'] for r in supplement_rows if r['kind'] == 'judge']
    record('SCORE-07', primary_judges,
           'Blinded factual pairwise judgments compare concise/verbose wrong answers, both answer orders and a separately seeded-randomized order protocol.',
           'This is style/order bias testing, not judge calibration or independent factual adjudication.', extra_ids=random_judges,
           details={'seed': 20261021, 'outcomes': [dict(id=r['id'], order=r['order'], style=r['style'], checks=r['checks'])
                                                for r in all_rows if r['kind'] == 'judge' and r['id'].startswith('judge:')]})
    assert {r['item_id'] for r in dispositions} == set(TARGETS)
    known_cost = 0
    for row in all_rows:
        prices = plan['prices'][row['model']]
        usage = row.get('usage') or {}
        known_cost += (usage.get('prompt_tokens', 0)*prices['input']+usage.get('completion_tokens', 0)*prices['output'])/1e6
    result = dict(version='open-item-review-v1', evaluations=dispositions,
        calls=dict(original=24, capability_diagnostics=3, first_continuation=2, final_continuation=expected_continuation,
                   total=len(all_rows), recorded_http_responses=sum(type(r.get('status')) is int for r in all_rows),
                   original_unattempted=64, carried_forward=63, retired_original_strict=1, retired_new_strict=2,
                   explicit_interrupted_recovery=int(resumed is not None)), release_accepted=False,
        reserved_usd=summary['combined_budget']['reserved_list_price_usd'],
        known_usage_list_price_estimate_usd=known_cost, unknown_usage_calls=sum(r.get('usage') is None for r in all_rows),
        original_stop_retained=original_summary['stop_reason'],
        first_continuation_stop_retained=json.loads((batch/'continuation-live/summary.json').read_text())['stop_reason'],
        limitations=['AI-authored consumed development; independent annotation/adjudication remains pending.',
                     'Finite evaluation completion does not establish production acceptance or a winning assembled configuration.',
                     'Original semantic, grounding and provider failures remain retained.',
                     'Account plan/organization/quotas, real report prevalence and new validation/holdout remain separate open obligations.'])
    write(output, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resumed', type=Path)
    args = parser.parse_args()
    review(args.batch, args.output, resumed=args.resumed)
