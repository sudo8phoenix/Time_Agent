"""Dependency-light integrity checks for the W-03 seed dataset."""
import csv, json
from decimal import Decimal, InvalidOperation
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
WORK_TYPES = {"excavation", "backfill", "rebar_installation", "formwork", "concrete_pour", "curing", "structural_erection", "pipe_spool_erection", "welding", "weld_inspection", "hydrotest", "cable_laying", "cable_termination", "equipment_installation", "other", "unknown"}
EVENT_TYPES = {"actual_progress", "planned_work", "no_work", "blocker", "inspection", "material_delivery", "correction", "unknown"}
MAPPING_STATES = {"suggested", "ambiguous", "unmatched"}

def validate() -> list[str]:
    errors = []
    schedule_path = DATA / "synthetic/schedules/demo-utility-01.csv"
    with schedule_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    ids = {r["activity_id"] for r in rows}
    if len(ids) != 12 or any(r["is_leaf"] != "true" for r in rows): errors.append("schedule must contain 12 executable leaves")
    for r in rows:
        try: date.fromisoformat(r["baseline_date"]); date.fromisoformat(r["planned_start"]); date.fromisoformat(r["planned_finish"])
        except ValueError: errors.append(f"invalid date in {r.get('activity_id')}")
        if r["measurement_basis"] == "quantity_ratio" and (not r["planned_quantity"] or float(r["planned_quantity"]) <= 0): errors.append(f"invalid planned quantity {r['activity_id']}")
        if r["work_type"] not in WORK_TYPES: errors.append(f"unsupported work type {r['activity_id']}")
    def load(name):
        with (DATA / name).open(encoding="utf-8") as f: return [json.loads(line) for line in f if line.strip()]
    reports, labels = load("synthetic/reports/seed-reports.jsonl"), load("synthetic/labels/seed-labels.jsonl")
    report_ids = {r["report_id"] for r in reports}
    if len(labels) != 20 or {x["case_id"] for x in labels} != {f"C{i:02d}" for i in range(1,21)}: errors.append("labels must contain C01-C20")
    for x in labels:
        if x["origin"] != "synthetic" or x["report_id"] not in report_ids: errors.append(f"bad provenance {x['case_id']}")
        if any(a not in ids for a in x["expected_activity_ids"]): errors.append(f"unknown activity in {x['case_id']}")
        if not x["expected_activity_ids"] and not x["expected_match_reason"]: errors.append(f"missing unmatched reason {x['case_id']}")
        if x["expected_mapping_state"] not in MAPPING_STATES: errors.append(f"invalid mapping state {x['case_id']}")
        if x["expected_event_type"] not in EVENT_TYPES: errors.append(f"invalid event type {x['case_id']}")
        if x["expected_quantity"] is not None:
            try:
                if not Decimal(x["expected_quantity"]).is_finite(): raise InvalidOperation
            except (InvalidOperation, ValueError): errors.append(f"invalid quantity {x['case_id']}")
    split = json.loads((DATA / "splits.json").read_text(encoding="utf-8")); seen = {}
    for name, families in split["splits"].items():
        for family in families:
            if family in seen: errors.append(f"family leakage: {family}")
            seen[family] = name
    for x in labels:
        if split["case_assignment"].get(x["case_id"]) != seen.get(x["event_family_id"]): errors.append(f"split mismatch {x['case_id']}")
    return errors

if __name__ == "__main__":
    errors = validate()
    if errors: raise SystemExit("\n".join(errors))
    print("W-03 synthetic seed validation passed")
