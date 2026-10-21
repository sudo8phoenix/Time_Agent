"""Conservative input/schedule exposure inventory without opening label files."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

NAMES = {'inputs.json', 'inputs.jsonl', 'config.json', 'plan.json', 'lineage.json'}
FIELDS = ('case_id', 'group_id', 'event_family_id', 'family', 'parent_fixture')


def identities(value):
    if isinstance(value, list):
        return [row for child in value for row in identities(child)]
    if not isinstance(value, dict):
        return []
    result = []
    row = {key: value[key] for key in FIELDS if isinstance(value.get(key), str)}
    if row:
        result.append(row)
    if isinstance(value.get('case_ids'), list):
        result.extend({'case_id': item} for item in value['case_ids'] if isinstance(item, str))
    # Only known input/schedule containers; do not traverse prompts/raw predictions.
    for key in ('schedule', 'splits'):
        child = value.get(key)
        if isinstance(child, dict):
            child = list(child.values())
        result.extend(identities(child))
    # A lineage's cases map is metadata, whereas label files are never opened.
    child = value.get('cases')
    if isinstance(child, dict):
        for cid, info in child.items():
            if isinstance(info, dict):
                result.append({'case_id': cid, **{k: info[k] for k in FIELDS if isinstance(info.get(k), str)}})
    return result


def inventory(roots):
    files = []
    for root in roots:
        for path in sorted(p for p in root.rglob('*') if p.is_file() and p.name in NAMES):
            data = path.read_bytes()
            try:
                values = ([json.loads(line) for line in data.decode().splitlines() if line.strip()]
                          if path.suffix == '.jsonl' else json.loads(data))
                rows = identities(values)
                error = None
            except (ValueError, UnicodeError):
                rows, error = [], 'invalid JSON/encoding; contents not exported'
            files.append(dict(path=str(path), sha256=sha256(data).hexdigest(),
                              identity_rows=rows, error=error))
    return dict(version='source-exposure-v1', files=files,
                limitations=['Planned and authored source exposure is not proof of inference.',
                             'Absent identities are never proof of unseen data.',
                             'Known lineage metadata is incomplete; cross-family independence still needs review.',
                             'Labels and arbitrary capture bodies are not opened or exported.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roots', type=Path, nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.output.open('x') as stream:
        stream.write(json.dumps(inventory(args.roots), indent=2) + '\n')
