"""Inventory consumed case identities from saved predictions without opening labels.

This is conservative exposure evidence, not proof that unlisted cases are unseen.
No provider calls, environment loading, database access, or prediction text export.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


IDENTITY_FIELDS = ("case_id", "group_id", "event_family_id", "project_id", "family")
CAPTURE_NAMES = {"predictions.jsonl", "reviewed-predictions.jsonl",
                 "estimated-predictions.jsonl", "calibration-predictions.jsonl",
                 "model-outputs.jsonl", "reports.jsonl", "calls.jsonl", "usage.jsonl"}


def inventory(root: Path) -> dict:
    captures = []
    identities: set[str] = set()
    for path in sorted(path for path in root.rglob("*.jsonl") if path.name in CAPTURE_NAMES):
        rows = []
        errors = []
        data = path.read_bytes()
        mode = 'unknown'
        config = path.parent/'config.json'
        if config.is_file():
            try:
                declared = json.loads(config.read_text()).get('execution_mode')
                if declared in {'live_groq', 'injected_transport'}:
                    mode = declared
            except (ValueError, UnicodeError, AttributeError, TypeError):
                pass
        for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("not an object")
                identity = {key: row[key] for key in IDENTITY_FIELDS
                            if isinstance(row.get(key), (str, int)) and not isinstance(row[key], bool)}
                if not str(identity.get("case_id", "")).strip():
                    raise ValueError("missing case identity")
                identities.add(str(identity["case_id"]))
                rows.append(identity)
            except (ValueError, TypeError):
                # Never echo malformed lines, which may contain source text.
                errors.append({"line": number, "error": "invalid or missing case identity"})
        captures.append({"path": path.relative_to(root).as_posix(),
                         "execution_mode": mode,
                         "sha256": sha256(data).hexdigest(), "attempt_rows": len(rows),
                         "case_identities": rows, "errors": errors})
    return {"version": "capture-inventory-v3", "scope": "allowlisted saved prediction/output/report/call/usage JSONL",
            "included_filenames": sorted(CAPTURE_NAMES),
            "limitations": ["Absent IDs are not proven unseen; other capture formats and lineage review remain required.",
                            "Case IDs may collide across independent datasets; paths retain their context.",
                            "Failed and repeated prediction rows remain included as exposure evidence."],
            "capture_count": len(captures), "unique_case_id_count": len(identities),
            "captures": captures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("evaluation/results"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.root.is_dir():
        parser.error("root must be an existing capture directory")
    if args.output.exists():
        parser.error("output already exists; retain previous inventory")
    result = inventory(args.root)
    with args.output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
