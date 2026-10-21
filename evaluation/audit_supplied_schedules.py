"""Read-only import/provenance audit of owner-supplied schedule fixtures.

No report facts, model calls, database writes, source repairs or freshness claims.
"""
from collections import Counter
from hashlib import sha256
import argparse
import json
from pathlib import Path

from app.ingest.native_schedule.dispatch import preview_schedule


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def audit(root=ROOT):
    previous = json.loads((root / 'evaluation/results/prompting-checklist-2026-10-20/'
                           'batch-16/source-discovery/schedules-review.json').read_text())
    hashes = {item['path']: item['sha256'] for item in previous['files']}
    results, previews = [], {}
    for path in sorted((root / 'data/schedules').iterdir()):
        if not path.is_file():
            continue
        key = str(path.relative_to(root))
        item = dict(path=key, bytes=path.stat().st_size, sha256=digest(path),
                    consumed_development_source=True, fresh_report_gold=False)
        item['unchanged_since_batch16'] = item['sha256'] == hashes.get(key)
        try:
            preview = preview_schedule(path)
            tasks = preview.tasks
            ids = {task.source_task_id for task in tasks}
            item.update(source_format=preview.source_format, parser_version=preview.parser_version,
                        selected_project_id=preview.selected_project_id,
                        tasks=len(tasks), leaf_tasks=sum(not task.is_summary for task in tasks),
                        relationships=len(preview.relationships),
                        unique_source_ids=len(ids) == len(tasks),
                        unique_external_ids=len({task.external_id for task in tasks}) == len(tasks),
                        source_hash_verified=preview.source_sha256 == item['sha256'],
                        issues=dict(Counter(issue.code for issue in preview.issues)),
                        unresolved_relationships=sum(
                            relation.predecessor_source_task_id not in ids or
                            relation.successor_source_task_id not in ids
                            for relation in preview.relationships))
            previews[path.suffix] = preview
            item['parsed'] = True
        except Exception as exc:
            # Raw native diagnostics and source text are not audit output.
            item.update(parsed=False, error_type=type(exc).__name__)
        results.append(item)
    pairs = None
    if '.xer' in previews and '.xlsx' in previews:
        a = {task.external_id: task for task in previews['.xer'].tasks}
        b = {task.external_id: task for task in previews['.xlsx'].tasks}
        common = set(a) & set(b)
        pairs = dict(shared_external_ids=len(common), only_xer=len(set(a)-set(b)),
                     only_xlsx=len(set(b)-set(a)),
                     name_disagreements=sum(a[key].name != b[key].name for key in common),
                     summary_disagreements=sum(a[key].is_summary != b[key].is_summary for key in common))
    # Inventory the additionally authorized parent directory; do not load the
    # 1+ GiB Cambridge original into memory or misrepresent it as uploadable.
    original_root = root.parent / 'data'
    originals = []
    for path in sorted(original_root.rglob('*')):
        if path.is_file() and path.suffix.lower() in {'.xlsx', '.xer', '.json'}:
            file_hash = digest(path)
            originals.append(dict(path=str(path.relative_to(root.parent)), bytes=path.stat().st_size,
                                  sha256=file_hash, exceeds_native_upload_10_mib=path.stat().st_size > 10*1024*1024,
                                  identical_schedule_copies=[r['path'] for r in results if r['sha256'] == file_hash],
                                  classification='schedule_or_previous_audit_not_reviewed_report_gold'))
    return dict(scope='Read-only current production parser checks; consumed development schedules',
                files=results, gt10_cross_format=pairs, authorized_parent_inventory=originals,
                contains_fresh_reviewed_reports=False, model_calls=0, database_writes=0,
                source_repairs=0, release_accepted=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    with args.output.open('x') as output:
        output.write(json.dumps(result, indent=2) + '\n')
