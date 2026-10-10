"""Recheck provisional schedule/scenario disjointness; exit nonzero on leakage."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = ROOT / "data/schedule-audit-2026-10-09"
HERE = Path(__file__).resolve().parent


def check() -> dict:
    raw = (AUDIT / "provisional-splits.json").read_bytes()
    splits = json.loads(raw)
    partitions = splits["partitions"]
    memberships = {}
    for partition, ids in partitions.items():
        for project_id in ids:
            if project_id in memberships:
                raise ValueError(f"cross-partition project: {project_id}")
            memberships[project_id] = partition
    if len(memberships) != 299:
        raise ValueError("Cambridge project count changed")
    groups = splits["groups"]
    for index, group in enumerate(groups):
        if len({memberships.get(pid) for pid in group}) != 1:
            raise ValueError(f"group {index} crosses partitions")
    reports = [json.loads(line) for line in (HERE / "reports.jsonl").read_text().splitlines()]
    labels = [json.loads(line) for line in (HERE / "proposed-labels.jsonl").read_text().splitlines()]
    if {r["id"] for r in reports} != {l["report_id"] for l in labels}:
        raise ValueError("report/label mismatch")
    families = {}
    for row in reports:
        if row["project_family"] != "GT10BLDG" or row["split"] != "development":
            raise ValueError("GT10 scenario outside development")
        previous = families.setdefault(row["scenario_family"], row["split"])
        if previous != row["split"]:
            raise ValueError("scenario family split")
    if any(label["label_status"] != "ai_proposed_unreviewed" for label in labels):
        raise ValueError("unreviewed labels misrepresented")
    return {"status":"structural_checks_passed_not_frozen", "provisional_sha256":hashlib.sha256(raw).hexdigest(),
            "source_sha256":splits["source_sha256"], "label_sha256":hashlib.sha256((HERE / "proposed-labels.jsonl").read_bytes()).hexdigest(),
            "projects":{key:len(value) for key,value in partitions.items()}, "groups":len(groups),
            "gt10_scenario_count":len(reports), "review_status":"pending_independent_review"}


if __name__ == "__main__":
    print(json.dumps(check(), indent=2))
