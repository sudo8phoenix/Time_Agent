"""Freeze an offline repeated development plan. This module cannot send requests."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from app.llm.extract import MAX_BATCH_CHARS, extraction_schema
from app.prompts.extraction_v1 import V12_PROMPT_VERSION, get_extraction_prompt
from evaluation.paired_pilot import CLAUSE_COVERAGE_SUFFIX, QUANTITY_SUFFIX
from evaluation.strict_schema import build_wire_schema
from evaluation.source_units import UNIT_INSTRUCTIONS, MAP_INSTRUCTIONS, unit_schema, mapped_schema, source_units
from evaluation.prompt_ablation import COMPLETENESS_SUFFIX, CORRECTION_SUFFIX, DATE_BASIS_SUFFIX, ZERO_SHOT, prompts as concise_prompts

FIXTURE = Path('evaluation/fixtures/paired-development-v2')
CONTRACT = Path('evaluation/contracts/development-annotation-contract.md')


COMPARISONS = ('coverage', 'few-shot', 'example-order', 'reasoning', 'strict', 'correction', 'date-basis', 'contract-completeness', 'source-units', 'source-units-concise', 'source-map-concise')
MODEL_PRICES = {'openai/gpt-oss-20b': {'input': .075, 'output': .30},
                'openai/gpt-oss-120b': {'input': .15, 'output': .60}}


def prepare(output, comparison='coverage', *, case_ids=None, repetitions=3, request_seconds=60, strict_all=False,
            model='openai/gpt-oss-20b', output_tokens=1536, continue_content_failures=False):
    if type(continue_content_failures) is not bool:
        raise ValueError('Content-failure continuation must be an explicit boolean')
    if model not in MODEL_PRICES or type(output_tokens) is not int or not 1536 <= output_tokens <= 4096:
        raise ValueError('Use an allowlisted fixed model and 1536–4096 output tokens')
    if type(strict_all) is not bool or (strict_all and comparison == 'strict'):
        raise ValueError('Common strict flag cannot be combined with a strict-flag ablation')
    if comparison not in COMPARISONS:

        raise ValueError('Unsupported comparison')
    if type(request_seconds) is not int or not 30 <= request_seconds <= 180:
        raise ValueError('Use a fixed 30–180 second request deadline')
    cases = json.loads((FIXTURE / 'inputs.json').read_text())
    if type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise ValueError('Use 1–3 preregistered repetitions')
    labels = json.loads((FIXTURE / 'labels.json').read_text())['cases']
    lineage = json.loads((FIXTURE / 'lineage.json').read_text())['cases']
    if any(not c['text'].strip() or len(c['text']) > MAX_BATCH_CHARS for c in cases):
        raise ValueError('Fixture exceeds extraction batch limit or is empty')
    ids = [case['case_id'] for case in cases]
    if len(set(ids)) != len(ids) or set(ids) != set(labels) or set(ids) != set(lineage):
        raise ValueError('Unique input, label and lineage identities must match')
    if case_ids is not None:
        if not case_ids or len(set(case_ids)) != len(case_ids) or set(case_ids) - set(ids):
            raise ValueError('Unknown/duplicate/empty selected case IDs')
        cases = [case for case in cases if case['case_id'] in case_ids]
    _, baseline = get_extraction_prompt(V12_PROMPT_VERSION)
    prompts = {'v12': baseline, 'coverage-and-quantity': baseline + CLAUSE_COVERAGE_SUFFIX + QUANTITY_SUFFIX}
    candidate = prompts['coverage-and-quantity']
    if comparison == 'contract-completeness':
        core = candidate + CORRECTION_SUFFIX + DATE_BASIS_SUFFIX
        prompts = {'date-basis-contract': core, 'complete-contract': core + COMPLETENESS_SUFFIX}
    elif comparison == 'date-basis':
        core = candidate + CORRECTION_SUFFIX
        prompts = {'correction-contract': core, 'date-basis-contract': core + DATE_BASIS_SUFFIX}
    elif comparison == 'source-map-concise':
        core = ZERO_SHOT + CORRECTION_SUFFIX
        prompts = {'flat': core, 'source-map': core + MAP_INSTRUCTIONS}
    elif comparison in {'source-units', 'source-units-concise'}:
        core = ZERO_SHOT if comparison == 'source-units-concise' else candidate + CORRECTION_SUFFIX
        prompts = {'flat': core, 'source-units': core + UNIT_INSTRUCTIONS}
    elif comparison == 'correction':
        prompts = {'coverage-and-quantity': candidate, 'correction-contract': candidate + CORRECTION_SUFFIX}
    elif comparison == 'few-shot':
        prompts = concise_prompts()
    elif comparison == 'example-order':
        prompts = {'forward': concise_prompts()['few-shot'], 'reverse': concise_prompts((2, 1, 0))['few-shot']}
    elif comparison == 'reasoning':
        prompts = {'low': candidate, 'medium': candidate}
    elif comparison == 'strict':
        prompts = {'best-effort': candidate, 'strict': candidate}
    wire, changes = build_wire_schema(extraction_schema())
    schedule = []
    for repetition in range(1, repetitions+1):
        for index, case in enumerate(cases):
            arms = list(prompts)
            if (index + repetition - 1) % 2:
                arms.reverse()
            for arm in arms:
                schedule.append(dict(trial_id=f'{case["case_id"]}-r{repetition}-{arm}',
                                     case_id=case['case_id'], repetition=repetition,
                                     arm=arm, response_mode='source-map' if comparison == 'source-map-concise' and arm == 'source-map' else 'source-units' if comparison in {'source-units', 'source-units-concise'} and arm == 'source-units' else 'flat',
                                     strict=strict_all or comparison == 'strict' and arm == 'strict',
                                     reasoning_effort='medium' if comparison == 'reasoning' and arm == 'medium' else 'low'))
    if len(schedule) > 60:
        raise ValueError('Schedule exceeds 60-call ceiling')
    files = [FIXTURE / name for name in ('inputs.json', 'labels.json', 'lineage.json')]
    files += [CONTRACT, Path(__file__), Path('evaluation/paired_pilot.py'),
              Path('evaluation/strict_schema.py'), Path('evaluation/score_paired_pilot.py'),
              Path('evaluation/repeated_development.py'), Path('evaluation/score_repeated_development.py'),
              Path('evaluation/repeated_preflight.py'), Path('ops/runtime_status.py'),
              Path('evaluation/experiment_guard.py'), Path('evaluation/error_taxonomy.py'),
              Path('evaluation/study_controls.py'),
              Path('evaluation/frozen_acceptance.py'), Path('evaluation/score_frozen_acceptance.py'),
              Path('evaluation/prompt_ablation.py'), Path('evaluation/source_units.py'),
              Path('backend/app/llm/hosted.py'), Path('backend/app/llm/metrics.py'),
              Path('backend/app/settings.py'),
              Path('backend/app/prompts/extraction_v1.py'), Path('backend/app/llm/extract.py'),
              Path('backend/app/schemas/observation.py'), Path('backend/app/schemas/common.py'),
              Path('backend/app/schemas/events.py'), Path('backend/app/llm/groq.py'),
              Path('backend/app/llm/openrouter.py')]
    plan = dict(scope='AI-authored consumed development; unaccepted candidate; no inference',
                execution_status='prepared; requires current sanitized provider/runtime preflight',
                model=model, key_slot=2,
                fixture_path=str(FIXTURE / 'inputs.json'),
                prices_per_million=MODEL_PRICES[model],
                price_source='https://console.groq.com/docs/model/' + model,
                price_checked='2026-10-20', admission='existing shared provider scope',
                comparison=comparison, strict_all=strict_all,
                continue_content_failures=continue_content_failures,
                content_failure_policy=('Count known invalid model outputs as failures, continue other scheduled trials; no retry/repair'
                                        if continue_content_failures else 'Stop at the first invalid model output'),
                prompt_definition=('Identical date-basis instructions; only required summary/evidence completeness suffix changes'
                                   if comparison == 'contract-completeness' else 'Identical correction-contract instructions; only explicit date-provenance suffix changes'
                                   if comparison == 'date-basis' else 'Decomposition experiment: source-unit slots/input and native schema versus flat output; same facts/model/domain fields'
                                   if comparison in {'source-units', 'source-units-concise', 'source-map-concise'} else 'Identical V12+coverage+quantity instructions; only explicit correction suffix changes'
                                   if comparison == 'correction' else 'V12 contains examples; neither arm is zero-shot; only suffix changes'
                                   if comparison == 'coverage' else
                                   'Identical concise instructions; only three development demonstrations change'
                                   if comparison == 'few-shot' else
                                   'Identical examples/instructions; only demonstration order changes'
                                   if comparison == 'example-order' else
                                   'Identical prompt/schema/model; only reasoning effort changes'
                                   if comparison == 'reasoning' else
                                   'Identical prompt/schema/model; only strict flag changes'),
                prompt_version=V12_PROMPT_VERSION, prompts=prompts,
                wire_schema_sha256=sha256(json.dumps(wire, sort_keys=True).encode()).hexdigest(),
                wire_schema_changes=changes, schedule=schedule,
                primary_metric='all-scheduled raw selected-field exact rate; paired by case and repetition',
                secondary_metrics=['normalized selected fields', 'event precision/recall', 'wire/domain validity',
                                   'per-family variability', 'completion including failed/unattempted trials',
                                   'calls/measured tokens/list-price estimate', 'admission/transport/stage seconds'],
                uncertainty='repeats are correlated; report paired case/family counts, not 60 independent reports',
                review_required=['evidence entailment', 'correction semantics/summary', 'injection handling'],
                budget=dict(calls=len(schedule), reserved_tokens=160000 if len(schedule) == 4 else 2400000,
                            list_price_usd=.05 if len(schedule) == 4 else 1.00,
                            wall_seconds=max(360, len(schedule) * request_seconds) if len(schedule) == 4 else 10800,
                            request_seconds=request_seconds, output_tokens_per_call=output_tokens,
                            retries=0, repairs=0, concurrency=1),
                stop_conditions=['hard safety violation', 'schema/scorer/annotation defect',
                                 'quota/identity/configuration uncertainty', 'any fixed budget exhausted',
                                 'provider rejection: retain attempt and remaining unattempted trials'],
                labels_in_requests=False,
                strict_comparison='Identical derived wire schema in both arms; compare strict separately from prompt/reasoning experiments',
                source_sha256={str(p): sha256(p.read_bytes()).hexdigest() for p in files})
    output.mkdir(parents=True, exist_ok=False)
    if comparison in {'source-units', 'source-units-concise'}:
        units_wire, units_changes = build_wire_schema(unit_schema(wire))
        plan['unit_wire_schema_changes'] = units_changes
        plan['unit_wire_schema_sha256'] = sha256(json.dumps(units_wire, sort_keys=True).encode()).hexdigest()
        plan['projection_contract'] = 'Native unit response retained; source-order concatenation only; no added/changed/deduplicated facts'
        (output / 'unit-wire-schema.json').write_text(json.dumps(units_wire, indent=2)+'\n')
    if comparison == 'source-map-concise':
        maps = {case['case_id']: build_wire_schema(mapped_schema(wire, source_units(case['text'], split_semicolons=False)))[0] for case in cases}
        plan['unit_map_schema_sha256'] = {key: sha256(json.dumps(value, sort_keys=True).encode()).hexdigest() for key, value in maps.items()}
        plan['projection_contract'] = 'Fixed literal source-unit keys; source-order concatenation only; no field repairs or duplicate removal'
        (output / 'unit-map-schemas.json').write_text(json.dumps(maps, indent=2)+'\n')
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    (output / 'wire-schema.json').write_text(json.dumps(wire, indent=2) + '\n')
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--comparison', choices=COMPARISONS, default='coverage')
    parser.add_argument('--case-ids', nargs='+')
    parser.add_argument('--request-seconds', type=int, default=60)
    parser.add_argument('--strict-all', action='store_true')
    parser.add_argument('--continue-content-failures', action='store_true')
    parser.add_argument('--model', choices=MODEL_PRICES, default='openai/gpt-oss-20b')
    parser.add_argument('--output-tokens', type=int, default=1536)
    parser.add_argument('--repetitions', type=int, default=3)
    args = parser.parse_args()
    prepare(args.output, args.comparison, case_ids=args.case_ids, repetitions=args.repetitions, request_seconds=args.request_seconds, strict_all=args.strict_all,
            model=args.model, output_tokens=args.output_tokens, continue_content_failures=args.continue_content_failures)
