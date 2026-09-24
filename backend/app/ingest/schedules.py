"""Canonical schedule CSV parser and persistence helpers."""
import csv
import hashlib
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..db.models import Activity, ActivityState, Project, ScheduleVersion

REQUIRED = ("activity_id", "activity_name", "wbs_path", "discipline", "work_type", "area", "asset_tags", "is_leaf", "measurement_basis", "planned_quantity", "unit", "planned_start", "planned_finish", "baseline_date", "baseline_quantity", "actual_start", "actual_finish", "aliases")
UNITS = {"m", "m2", "m3", "kg", "t", "spool", "joint", "point", "each"}
DISCIPLINES = {"civil", "structural", "piping", "mechanical", "electrical", "instrumentation", "other", "unknown"}
WORK_TYPES = {"excavation", "backfill", "rebar_installation", "formwork", "concrete_pour", "curing", "structural_erection", "pipe_spool_erection", "welding", "weld_inspection", "hydrotest", "cable_laying", "cable_termination", "equipment_installation", "other", "unknown"}
BASIS = {"quantity_ratio", "manual_physical", "milestone", "unsupported"}

def _date(value, row, field, errors):
    if not value: return None
    try: return date.fromisoformat(value)
    except ValueError: errors.append({"row": row, "field": field, "message": "must be ISO date YYYY-MM-DD"}); return None

def parse_schedule_csv(raw: bytes | str):
    if isinstance(raw, str): raw = raw.encode()
    digest = hashlib.sha256(raw).hexdigest()
    errors = []
    try: text = raw.decode("utf-8-sig")
    except UnicodeDecodeError: return None, digest, [{"row": 1, "field": "file", "message": "must be UTF-8 CSV"}]
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    missing = [x for x in REQUIRED if x not in headers]
    extra = [x for x in headers if x not in REQUIRED]
    if missing: errors.append({"row": 1, "field": "columns", "message": f"missing required columns: {', '.join(missing)}"})
    if extra: errors.append({"row": 1, "field": "columns", "message": f"unknown columns: {', '.join(extra)}"})
    rows, ids = [], set()
    for number, item in enumerate(reader, 2):
        # DictReader stores surplus comma-separated values under a ``None``
        # key.  Treat that as a validation error instead of allowing an
        # AttributeError to partially enter the request path.
        surplus = item.pop(None, None)
        if surplus:
            errors.append({"row": number, "field": "columns", "message": "too many values for header"})
        row = {k: (v or "").strip() for k, v in item.items() if k is not None}
        def req(field):
            if not row.get(field): errors.append({"row": number, "field": field, "message": "required"})
        for field in ("activity_id", "activity_name", "wbs_path", "discipline", "work_type", "is_leaf", "measurement_basis", "baseline_date"): req(field)
        ident = row.get("activity_id", "")
        if ident in ids: errors.append({"row": number, "field": "activity_id", "message": "duplicate activity ID"})
        if ident: ids.add(ident)
        if row.get("is_leaf") not in ("true", "false"): errors.append({"row": number, "field": "is_leaf", "message": "must be true or false"})
        if row.get("discipline") not in DISCIPLINES: errors.append({"row": number, "field": "discipline", "message": "invalid discipline"})
        if row.get("work_type") not in WORK_TYPES: errors.append({"row": number, "field": "work_type", "message": "invalid work_type"})
        basis = row.get("measurement_basis")
        if basis not in BASIS: errors.append({"row": number, "field": "measurement_basis", "message": "invalid measurement basis"})
        values = {"planned_start": _date(row.get("planned_start"), number, "planned_start", errors), "planned_finish": _date(row.get("planned_finish"), number, "planned_finish", errors), "baseline_date": _date(row.get("baseline_date"), number, "baseline_date", errors), "actual_start": _date(row.get("actual_start"), number, "actual_start", errors), "actual_finish": _date(row.get("actual_finish"), number, "actual_finish", errors)}
        for a,b in (("planned_start","planned_finish"),("actual_start","actual_finish")):
            if values[a] and values[b] and values[a] > values[b]: errors.append({"row": number, "field": a, "message": f"{a} cannot exceed {b}"})
        nums = {}
        for field in ("planned_quantity", "baseline_quantity"):
            if row.get(field):
                try: nums[field] = Decimal(row[field])
                except (InvalidOperation, ValueError): errors.append({"row": number, "field": field, "message": "must be a finite decimal"}); continue
                if not nums[field].is_finite() or nums[field] < 0: errors.append({"row": number, "field": field, "message": "must be finite and non-negative"})
        if basis == "quantity_ratio":
            if "planned_quantity" not in nums or nums["planned_quantity"] <= 0: errors.append({"row": number, "field": "planned_quantity", "message": "required and greater than zero"})
            if row.get("unit") not in UNITS: errors.append({"row": number, "field": "unit", "message": "recognised unit required"})
            if "baseline_quantity" not in nums: errors.append({"row": number, "field": "baseline_quantity", "message": "required for quantity_ratio"})
            elif "planned_quantity" in nums and nums["baseline_quantity"] > nums["planned_quantity"]: errors.append({"row": number, "field": "baseline_quantity", "message": "cannot exceed planned_quantity"})
        elif basis == "milestone" and (row.get("planned_quantity") or row.get("unit")): errors.append({"row": number, "field": "measurement_basis", "message": "milestones cannot have quantity or unit"})
        rows.append((row, values, nums, number))
    return (rows if not errors else None), digest, errors

def stage_schedule(db: Session, project: Project, raw: bytes | str):
    parsed, digest, errors = parse_schedule_csv(raw)
    if errors: return None, digest, errors, False
    existing = db.scalar(select(ScheduleVersion).where(ScheduleVersion.project_id == project.id, ScheduleVersion.content_sha256 == digest))
    if existing: return existing, digest, [], True
    latest = db.scalar(select(func.max(ScheduleVersion.version_number)).where(ScheduleVersion.project_id == project.id)) or 0
    version = ScheduleVersion(project_id=project.id, version_number=latest + 1, content_sha256=digest, state="staged")
    db.add(version); db.flush()
    for row, vals, nums, _ in parsed:
        db.add(Activity(schedule_version_id=version.id, external_id=row["activity_id"], name=row["activity_name"], wbs=row["wbs_path"], discipline=row["discipline"], work_type=row["work_type"], area=row.get("area") or None, asset_tags=row.get("asset_tags") or None, aliases=row.get("aliases") or None, is_leaf=row["is_leaf"] == "true", measurement_basis=row["measurement_basis"], planned_quantity=nums.get("planned_quantity"), unit=row.get("unit") or None, baseline_date=vals["baseline_date"], baseline_quantity=nums.get("baseline_quantity"), planned_start=vals["planned_start"], planned_finish=vals["planned_finish"], actual_start=vals["actual_start"], actual_finish=vals["actual_finish"]))
    return version, digest, [], False
