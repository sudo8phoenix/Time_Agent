"""Live delivery/blocker identity diagnostics; no persistence or approvals.

Development cases include C06, ambiguous receiving locations and blocked work.
Supplies synthetic observations to isolate matching from extraction quality.
"""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic
from uuid import NAMESPACE_URL, uuid5

from app.agent.schedule_decision import select_activity, shortlist_activities
from app.llm.provider import create_adapter
from app.llm.metrics import capture_provider_metrics
from app.settings import get_settings
from evaluation.live_pacing import wait_before_case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--case-ids', nargs='+')
    parser.add_argument('--short-ids', action='store_true')
    parser.add_argument('--suite', choices=('delivery', 'blocker'), default='delivery')
    parser.add_argument('--batch-size', type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('Use a new evidence directory')
    args.output_dir.mkdir(parents=True)
    schedule = Path('data/synthetic/schedules/demo-utility-01.csv')
    activities = []
    for row in csv.DictReader(schedule.open()):
        activities.append({**row, 'id': str(uuid5(NAMESPACE_URL, row['activity_id'])),
            'external_id': row['activity_id'], 'name': row['activity_name'],
            'wbs': row['wbs_path'], 'is_leaf': row['is_leaf'].lower() == 'true'})
    by_id = {r['id']: r['external_id'] for r in activities}
    cases = [
        ('C06', 'Area A, line 24-XX: 6 spools delivered to the laydown area.', 'PIP-A-ERECT-024'),
        ('DM-02', 'Two spools for line 24-XX arrived in Area B today.', 'PIP-B-ERECT-024'),
        ('DM-03', 'Area A received three spools for line 25-YY today.', 'PIP-A-ERECT-025'),
        ('DM-04', 'Spools for line 24-XX arrived at the laydown yard.', None),
        ('DM-05', 'Four spools arrived at the central yard.', None),
    ]
    blocker_summaries = {}
    if args.suite == 'blocker':
        cases = [
            ('BM-01', 'Area A, line 24-XX: spool erection continued; hydrotesting was held because the permit expired.', 'PIP-A-TEST-024'),
            ('BM-02', 'Area A, footing F-01: 4 m3 concrete was placed; reinforcement fixing was stopped because pump P-101 was unavailable.', 'CIV-A-REBAR-01'),
            ('BM-03', 'Work in Area A was held for an inspection.', None),
        ]
        blocker_summaries = {
            'BM-01': ('Hydrotesting was held.', 'The permit expired.'),
            'BM-02': ('Reinforcement fixing was stopped.', 'Pump P-101 was unavailable.'),
            'BM-03': ('Work was held.', 'An inspection was pending.'),
        }
    if args.case_ids:
        if set(args.case_ids) - {case[0] for case in cases}:
            parser.error('Unknown delivery case identifier')
        cases = [case for case in cases if case[0] in args.case_ids]
    settings = get_settings().model_copy(update={'llm_provider': 'groq', 'selection_provider': 'groq',
        'selection_model': get_settings().groq_model, 'selection_key_slot': 0})
    config = {'scope': __doc__, 'provider': 'groq', 'model': settings.groq_model,
              'schedule_sha256': sha256(schedule.read_bytes()).hexdigest(),
              'source_sha256': {str(p): sha256(p.read_bytes()).hexdigest() for p in
                  [Path(__file__), Path('backend/app/agent/schedule_decision.py'), Path('evaluation/live_pacing.py')]},
              'cases': cases, 'short_ids': args.short_ids, 'suite': args.suite,
              'batch_size': args.batch_size, 'batch_pause_seconds': 60,
              'supplied_blocker_summaries': blocker_summaries,
              'domain_writes': 0, 'human_review_completed': False}
    (args.output_dir/'config.json').write_text(json.dumps(config, indent=2)+'\n')
    rows = []
    for index, (case_id, source, expected) in enumerate(cases):
        wait_before_case(args.output_dir, case_id, index, batch_size=args.batch_size)
        started = monotonic()
        row = {'case_id': case_id, 'state': 'failed', 'passed': False}
        adapter = create_adapter(settings, timeout=60, role='selection')
        def model(**kwargs):
            capture = {'case_id': case_id, 'stage': 'retrieval' if 'candidate_ids' in kwargs['schema']['properties'] else 'selection', 'ok': False}
            original_transport = adapter._transport
            def observed_transport(*args, **options):
                status, body = original_transport(*args, **options)
                # Synthetic diagnostic only: observe response before local schema
                # validation, without altering that validation or the request.
                choices = body.get('choices', []) if isinstance(body, dict) else []
                if status == 200 and choices:
                    capture['finish_reason'] = choices[0].get('finish_reason')
                    try:
                        capture['prevalidation_value'] = json.loads(choices[0]['message']['content'])
                    except (KeyError, TypeError, ValueError):
                        capture['prevalidation_json_unavailable'] = True
                return status, body
            adapter._transport = observed_transport
            try:
                with capture_provider_metrics() as metrics:
                    response = adapter.chat(**kwargs)
                capture.update(ok=True, value=response.value, model=response.model)
                return response
            except Exception as error:
                capture['error_type'] = type(error).__name__
                capture['error_code'] = getattr(error, 'code', 'MODEL_RESPONSE_ERROR')
                capture['retry_after_seconds'] = getattr(error, 'retry_after_seconds', None)
                known = {'Groq response was incomplete': 'INCOMPLETE_RESPONSE',
                    'Groq returned an invalid JSON response': 'INVALID_JSON',
                    'Groq response did not match the requested schema': 'SCHEMA_MISMATCH'}
                capture['response_failure'] = known.get(str(error))
                raise
            finally:
                adapter._transport = original_transport
                capture['provider_metrics'] = metrics
                with (args.output_dir/'calls.jsonl').open('a') as stream:
                    stream.write(json.dumps(capture)+'\n')
        observation = {'event_type': 'material_delivery', 'summary': source,
            'quantity': None, 'unit': None, 'work_type': 'other', 'asset_tags': [],
            'evidence': [{'fragment_id': 'f1', 'quote': source}]}
        if args.suite == 'blocker':
            summary, cause = blocker_summaries[case_id]
            observation.update(event_type='blocker', summary=summary, blocker=cause)
        try:
            candidates = shortlist_activities(observation, 'synthetic', activities,
                model_call=model, associate_delivery=True, compact_context=True, short_ids=args.short_ids)
            proposal = select_activity(observation, candidates, {'f1': source},
                model_call=model, associate_delivery=True, compact_context=True, short_ids=args.short_ids)
            chosen = by_id.get(str(proposal.candidate_id))
            safe = proposal.proposed_effects == {} and proposal.review_state.value == 'pending'
            matched = chosen == expected and (expected is not None or proposal.mapping_state.value in ('ambiguous', 'unmatched'))
            row.update(state='completed', selected_activity=chosen,
                candidate_ids=[by_id[str(c.candidate_id)] for c in candidates],
                proposal=proposal.model_dump(mode='json'), passed=matched and safe)
        except Exception as error:
            row['error_type'] = type(error).__name__
            row['error_code'] = getattr(error, 'code', 'MODEL_RESPONSE_ERROR')
            row['retry_after_seconds'] = getattr(error, 'retry_after_seconds', None)
        row['elapsed_seconds'] = round(monotonic()-started, 3)
        rows.append(row)
        with (args.output_dir/'predictions.jsonl').open('a') as stream:
            stream.write(json.dumps(row)+'\n')
        print(json.dumps({k: row[k] for k in ('case_id', 'state', 'passed', 'elapsed_seconds')}), flush=True)
    summary = {'cases': len(rows), 'passed': sum(r['passed'] for r in rows),
        'failures': [r['case_id'] for r in rows if not r['passed']],
        'scope': 'Development component matching with supplied observations, not unseen extraction or end-to-end acceptance',
        'domain_writes': 0}
    (args.output_dir/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    (args.output_dir/'capture-manifest.json').write_text(json.dumps({'hashes': {
        p.name: sha256(p.read_bytes()).hexdigest() for p in args.output_dir.iterdir() if p.is_file()}}, indent=2)+'\n')


if __name__ == '__main__':
    main()
