"""Live, label-isolated comparison of v1 Groq and v2 Groq + Super VL reports.

Uses PostgreSQL runtime checkpoints and pending proposal persistence in the local
progress_test database only. Never calls approval or writes production settings.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
import traceback
from pathlib import Path
from statistics import median
from time import perf_counter
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.agent import runtime
from app.db.models import Activity, AgentRun, AgentTask, Fragment, Job, Observation, ProgressEvent, Project, Proposal, Report, ScheduleVersion
from app.llm import provider
from app.llm import ollama
from app.settings import get_settings
from evaluation.provider_pacing import ProviderPacer
from evaluation.report_scoring import SCORING_VERSION, normalized_scores
from evaluation.runtime_probe import observe_ownership, renewing_lease

PLANNER = "nvidia/nemotron-3.5-super-vl:free"
CASE_IDS = ("EXP-C001", "EXP-C121", "EXP-C166", "EXP-C196", "EXP-C256", "EXP-C286")
SEED_CASE_IDS = ("C01", "C02", "C03", "C16", "C18", "C19")
ROOT = Path(__file__).resolve().parents[1]


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def load_cases(case_ids=CASE_IDS, dataset="expanded"):
    """Return source inputs separately from labels; neither adapter sees labels."""
    if dataset not in {"expanded", "seed"}:
        raise ValueError(f"Unknown evaluation dataset: {dataset}")
    if dataset == "seed":
        report_path = ROOT / "data/synthetic/reports/seed-reports.jsonl"
        label_path = ROOT / "data/synthetic/labels/seed-labels.jsonl"
        schedule_path = ROOT / "data/synthetic/schedules/demo-utility-01.csv"
        default_ids = SEED_CASE_IDS
    else:
        report_path = ROOT / "data/synthetic/expanded/reports.jsonl"
        label_path = ROOT / "data/synthetic/expanded/labels.jsonl"
        schedule_path = ROOT / "data/synthetic/expanded/schedule.csv"
        default_ids = CASE_IDS
    if case_ids is CASE_IDS:
        case_ids = default_ids
    reports = {row["report_id"]: row for row in map(json.loads, report_path.read_text().splitlines())}
    labels = {row["case_id"]: row for row in map(json.loads, label_path.read_text().splitlines())}
    cases = []
    for case_id in case_ids:
        label = labels[case_id]
        report = reports[label["report_id"]]
        ordinal = int(label["fragment_locator"].split(":")[1])
        source = (report.get("text", report.get("content", "")).splitlines()[ordinal - 1])
        if "|" in source or not source.strip():
            raise ValueError("fixture locator requires reviewed source alignment")
        if "primary_case_type" in label:
            family = label["primary_case_type"]
        else:
            reason = (label.get("expected_match_reason") or "").lower()
            family = ("prompt_injection" if "prompt injection" in reason else
                      "date_conflict" if label.get("expected_workflow_outcome") == "date_conflict" else
                      "ambiguous_match" if label.get("expected_mapping_state") == "ambiguous" else
                      "unmatched" if label.get("expected_mapping_state") == "unmatched" else
                      "planned_work" if label.get("expected_event_type") == "planned_work" else
                      "actual_progress")
        if dataset == "seed":
            family = {"C01": "unambiguous_actual", "C02": "ambiguous_match",
                "C03": "future_plan_or_no_work", "C16": "unmatched",
                "C18": "messy_date_unit", "C19": "injection_or_unreadable"}.get(case_id, family)
        cases.append({"case_id": case_id, "report_date": report["report_date"],
            "text": source, "locator": label["fragment_locator"],
            "family": family, "label": label, "schedule_path": str(schedule_path),
            "dataset": dataset})
    return cases


def score_case(case, row):
    ready = row.get("state") == "ready_for_review"
    selected = set(row.get("selected_activity_ids", []))
    label = case["label"]
    expected = set(label["expected_activity_ids"])
    abstention = label["expected_mapping_state"] in {"unmatched", "ambiguous"}
    correct = ready and (not selected if abstention else bool(selected) and selected <= expected)
    observations = row.get("observations", [])
    expected_quantity = label.get("expected_quantity")
    quantity_correct = None
    if expected_quantity is not None:
        quantity_correct = ready and any(item.get("quantity") is not None and
            Decimal(str(item["quantity"])) == Decimal(expected_quantity) for item in observations)
    event_correct = ready and any(item.get("event_type") == label["expected_event_type"] for item in observations)
    return {"mapping_correct": correct, "safe_abstention": ready and not selected if abstention else None,
            "quantity_correct": quantity_correct, "event_type_correct": event_correct,
            "abstention_expected": abstention,
            "label_status": "synthetic_unadjudicated",
            **normalized_scores(case, row),
            "unsupported_persisted_evidence": sum(
                evidence.get("quote", "") not in case["text"] for item in observations
                for evidence in item.get("evidence", []))}


def summarize(rows):
    result = {}
    for arm in ("v1_groq", "v2_super_vl", "v2_deterministic"):
        group = [row for row in rows if row["arm"] == arm]
        abstentions = [row for row in group if row["scores"]["abstention_expected"]]
        quantities = [row for row in group if row["scores"]["quantity_correct"] is not None]
        normalized = [row for row in group if row["scores"].get("normalized_quantity_correct") is not None]
        result[arm] = {
            "scoring_version": SCORING_VERSION,
            "normalized_quantity_correct": sum(r["scores"]["normalized_quantity_correct"] for r in normalized),
            "normalized_quantity_cases": len(normalized),
            "exact_mapping_correct": sum(r["scores"].get("exact_mapping_correct", False) for r in group),
            "cases": len(group), "ready": sum(r["state"] == "ready_for_review" for r in group),
            "mapping_correct": sum(r["scores"]["mapping_correct"] for r in group),
            "safe_abstentions": sum(r["scores"]["safe_abstention"] is True for r in abstentions),
            "abstention_cases": len(abstentions),
            "quantity_correct": sum(r["scores"]["quantity_correct"] for r in quantities),
            "quantity_cases": len(quantities),
            "unsupported_persisted_evidence": sum(r["scores"]["unsupported_persisted_evidence"] for r in group),
            "ledger_writes": sum(r["ledger_writes"] for r in group),
            "model_calls": sum(len(r["calls"]) for r in group),
            "live_request_count": sum(not c.get("replayed", False) for r in group for c in r["calls"]),
            "replayed_calls": sum(c.get("replayed", False) for r in group for c in r["calls"]),
            "planner_calls": sum(c["stage"] == "planner" for r in group for c in r["calls"]),
            "failed_model_calls": sum(not c["ok"] for r in group for c in r["calls"]),
            "median_ms": (median(r["elapsed_ms"] for r in group)
                          if group and not any(r.get("specialist_execution") == "replayed_baseline" for r in group)
                          else None),
            "failure_codes": sorted({r["error_code"] for r in group if r.get("error_code")}),
        }
    return result


class Recorder:
    def __init__(self, *, journal=None, replay_specialists=False):
        self.journal = journal
        self.factory = provider.create_adapter
        self.calls = []
        self.case_id = None
        self.arm = None
        self.pacer = ProviderPacer()
        self.replay_specialists = replay_specialists
        self.baseline_queues = {}
        self.replay_queue = []

    def create(self, settings, **options):
        adapter = self.factory(settings, **options)
        role = options.get("role")
        recorder = self
        class RecordedAdapter:
            def chat(self, **kwargs):
                properties = kwargs.get("schema", {}).get("properties", {})
                stage = "planner" if role == "orchestrator" else "extraction" if "observations" in properties else "retrieval" if "candidate_ids" in properties else "selection"
                call = {"stage": stage, "model": adapter.model, "ok": False, "replayed": False}
                original_transport = adapter._transport
                def transport(*args):
                    payload = args[2] if len(args) > 2 else {}
                    payload_fingerprint = ollama._hash(payload)
                    call["payload_fingerprint"] = payload_fingerprint
                    specialist = stage != "planner"
                    if recorder.replay_specialists and recorder.arm in {"v2_super_vl", "v2_deterministic"} and specialist:
                        if not recorder.replay_queue:
                            call["replay_mismatch"] = "baseline specialist call queue exhausted"
                            raise EvaluationReplayMismatch(call["replay_mismatch"])
                        baseline = recorder.replay_queue.pop(0)
                        expected_fingerprint = baseline.get("payload_fingerprint")
                        if not expected_fingerprint:
                            # Legacy successful journals used settings_hash for the full Groq payload hash.
                            expected_fingerprint = baseline.get("settings_hash") if baseline.get("ok") else None
                        if expected_fingerprint != payload_fingerprint:
                            call["replay_mismatch"] = "specialist payload fingerprint differs from recorded baseline"
                            raise EvaluationReplayMismatch(call["replay_mismatch"])
                        call["replayed"] = True
                        call["baseline_http_status"] = baseline.get("http_status")
                        call["http_status"] = baseline.get("http_status", 599)
                        if baseline.get("ok"):
                            return 200, {"model": baseline.get("model", adapter.model), "choices": [{
                                "finish_reason": "stop", "message": {"content": json.dumps(baseline["output"])} }]}
                        status = baseline.get("http_status")
                        if baseline.get("error_type") == "OllamaTransportError":
                            # Preserve transport semantics instead of fabricating HTTP 599.
                            call["http_status"] = None
                            raise TimeoutError("Replayed baseline transport interruption")
                        if isinstance(status, int) and status >= 400:
                            return status, {}
                        call["replay_mismatch"] = "baseline failure cannot be reconstructed safely"
                        raise EvaluationReplayMismatch(call["replay_mismatch"])
                    status, body = recorder.pacer.transport(*args, call=call)
                    call["http_status"] = status
                    return status, body
                adapter._transport = transport
                started = perf_counter()
                try:
                    value = adapter.chat(**kwargs)
                    call.update(ok=True, prompt_hash=value.prompt_hash, settings_hash=value.settings_hash,
                                output_fingerprint=fingerprint(value.value), output=value.value)
                    return value
                except Exception as error:
                    call["error_type"] = type(error).__name__
                    raise
                finally:
                    adapter._transport = original_transport
                    call["elapsed_ms"] = round((perf_counter() - started) * 1000)
                    recorder.calls.append(call)
                    if recorder.journal:
                        with recorder.journal.open("a") as stream:
                            stream.write(json.dumps({"case_id": recorder.case_id, "arm": recorder.arm, **call}) + "\n")
                    print(json.dumps({"case": recorder.case_id, "arm": recorder.arm,
                        **{key: call[key] for key in ("stage", "model", "ok", "elapsed_ms", "http_status") if key in call}}), flush=True)
        return RecordedAdapter()


class EvaluationReplayMismatch(RuntimeError):
    """A controlled replay cannot safely substitute a non-identical request."""


def seed(sessions, cases):
    project_id, schedule_id = uuid4(), uuid4()
    schedule_path = Path(cases[0].get("schedule_path", ROOT / "data/synthetic/expanded/schedule.csv"))
    with sessions.begin() as db:
        db.add(Project(id=project_id, name=f"Planner evaluation {project_id}", timezone="UTC"))
        db.flush()
        db.add(ScheduleVersion(id=schedule_id, project_id=project_id, version_number=1,
            content_sha256=sha256(schedule_path.read_bytes()).hexdigest(), state="active"))
        db.flush()
        db.get(Project, project_id).active_schedule_version_id = schedule_id
        with schedule_path.open() as source:
            for row in csv.DictReader(source):
                db.add(Activity(schedule_version_id=schedule_id, external_id=row["activity_id"],
                    name=row["activity_name"], wbs=row["wbs_path"], discipline=row["discipline"],
                    work_type=row["work_type"], area=row["area"] or None, asset_tags=row["asset_tags"] or None,
                    aliases=row["aliases"] or None, is_leaf=row["is_leaf"].lower() == "true",
                    measurement_basis=row["measurement_basis"], unit=row["unit"] or None,
                    planned_quantity=Decimal(row["planned_quantity"]) if row["planned_quantity"] else None,
                    planned_start=date.fromisoformat(row["planned_start"]) if row["planned_start"] else None,
                    planned_finish=date.fromisoformat(row["planned_finish"]) if row["planned_finish"] else None))
        for case in cases:
            report = Report(project_id=project_id, content_hash=fingerprint(case["case_id"]),
                report_date=date.fromisoformat(case["report_date"]), report_date_evidence="Synthetic fixture metadata",
                source_label=case["case_id"])
            db.add(report)
            db.flush()
            db.add(Fragment(report_id=report.id, ordinal=1, locator=case["locator"],
                original_text=case["text"], normalised_text=case["text"]))
            case["report_id"] = report.id
    return project_id, schedule_id


def cleanup(sessions, project_id):
    with sessions.begin() as db:
        threads = list(db.scalars(select(AgentRun.thread_id).join(Job, AgentRun.job_id == Job.id).where(Job.project_id == project_id)))
        for thread in threads:
            for table in ("checkpoint_writes", "checkpoints", "checkpoint_blobs"):
                db.execute(text(f"DELETE FROM {table} WHERE thread_id = :thread"), {"thread": thread})
        project = db.get(Project, project_id)
        if project:
            project.active_schedule_version_id = None
            db.flush()
            db.execute(delete(Project).where(Project.id == project_id))


def run_case(sessions, project_id, schedule_id, case, settings, recorder, parent_job_id=None):
    token = uuid4().hex
    with sessions.begin() as db:
        job = Job(project_id=project_id, report_id=case["report_id"], schedule_version_id=schedule_id,
            parent_job_id=parent_job_id, reanalysis_key=str(uuid4()) if parent_job_id else None,
            state="running", stage="parse", attempts=1, lease_token=token,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
            config_snapshot={"provider": "groq", "model": settings.groq_model})
        db.add(job)
        db.flush()
        job_id = job.id
    recorder.calls = []
    started = perf_counter()
    original_settings = runtime.get_settings
    runtime.get_settings = lambda: settings
    ownership = []
    try:
        with observe_ownership(runtime, sessions, job_id, token) as ownership:
            with renewing_lease(sessions, job_id, token) as (beat, lost):
                with sessions() as db:
                    result = runtime.process_job_with_graph(db, db.get(Job, job_id), token=token,
                        session_factory=sessions, database_url=settings.database_url,
                        heartbeat_callback=beat, should_stop=lost)
    except Exception as error:
        result = {"state": "failed", "error_code": getattr(error, "code", "EVALUATION_RUNTIME_FAILED"),
                  "exception_type": type(error).__name__,
                  "failure_location": [f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                      for frame in traceback.extract_tb(error.__traceback__)[-6:]]}
    finally:
        runtime.get_settings = original_settings
    mismatch = next((call.get("replay_mismatch") for call in recorder.calls if call.get("replay_mismatch")), None)
    if mismatch:
        raise EvaluationReplayMismatch(mismatch)
    elapsed = round((perf_counter() - started) * 1000)
    with sessions() as db:
        observations = list(db.scalars(select(Observation).where(Observation.job_id == job_id).order_by(Observation.ordinal)))
        proposals = list(db.scalars(select(Proposal).join(Observation, Proposal.observation_id == Observation.id).where(Observation.job_id == job_id)))
        activities = {activity.id: activity.external_id for activity in db.scalars(select(Activity).where(Activity.schedule_version_id == schedule_id))}
        run = db.scalar(select(AgentRun).where(AgentRun.job_id == job_id))
        ledger = int(db.scalar(select(func.count()).select_from(ProgressEvent).join(Observation, ProgressEvent.observation_id == Observation.id).join(Job, Observation.job_id == Job.id).where(Job.project_id == project_id)))
        row = {"case_id": case["case_id"], "arm": recorder.arm, "family": case["family"],
            "job_id": str(job_id), "state": result["state"], "error_code": result.get("error_code"),
            "exception_type": result.get("exception_type"), "failure_location": result.get("failure_location"),
            "elapsed_ms": elapsed, "ownership_checks": ownership, "observations": [item.fields for item in observations],
            "selected_activity_ids": [activities[p.chosen_activity_id] for p in proposals if p.chosen_activity_id],
            "mapping_states": [p.mapping_state for p in proposals], "review_states": [p.review_state for p in proposals],
            "effects": [p.proposed_effects for p in proposals], "ledger_writes": ledger,
            "calls": list(recorder.calls), "graph_version": run.graph_version if run else None,
            "specialist_execution": "replayed_baseline" if recorder.replay_specialists and recorder.arm in {"v2_super_vl", "v2_deterministic"} else "live",
            "orchestrator_mode": "model_assisted" if settings.orchestrator_model_assisted else "deterministic",
            "replay_calls_remaining": len(recorder.replay_queue) if recorder.replay_specialists and recorder.arm in {"v2_super_vl", "v2_deterministic"} else None,
            "elapsed_ms_comparable": not (recorder.replay_specialists and recorder.arm in {"v2_super_vl", "v2_deterministic"}),
            "root_usage": (run.config_metadata or {}).get("hierarchy_usage") if run else None,
            "task_count": int(db.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.run_id == run.id))) if run else 0}
    before = len(recorder.calls)
    if result["state"] == "ready_for_review":
        with sessions() as db:
            replay = runtime.process_job_with_graph(db, db.get(Job, job_id), token=token,
                session_factory=sessions, database_url=settings.database_url)
        row["terminal_replay_reused"] = replay["state"] == result["state"] and len(recorder.calls) == before
        with sessions() as db:
            count = int(db.scalar(select(func.count()).select_from(Proposal).join(
                Observation, Proposal.observation_id == Observation.id).where(Observation.job_id == job_id)))
        row["terminal_replay_duplicate_free"] = count == len(proposals)
        if not row["terminal_replay_duplicate_free"]:
            raise RuntimeError("Terminal replay created duplicate proposals")
    row["scores"] = score_case(case, row)
    if ledger or any(state != "pending" for state in row["review_states"]):
        raise RuntimeError("Evaluation approval boundary was violated")
    return job_id, row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="postgresql+psycopg://progress:progress@127.0.0.1:5432/progress_test")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--case-ids", nargs="+", default=list(CASE_IDS))
    parser.add_argument("--dataset", choices=("expanded", "seed"), default="expanded")
    parser.add_argument("--arms", nargs="+", choices=("v1_groq", "v2_super_vl"), default=["v1_groq", "v2_super_vl"])
    parser.add_argument("--deterministic-planner", action="store_true",
                        help="Use deterministic v2 orchestration without live planner calls")
    parser.add_argument("--replay-specialists", action="store_true",
                        help="Replay each baseline Groq specialist response for exact candidate payload matches")
    args = parser.parse_args()
    if args.dataset == "seed" and args.case_ids == list(CASE_IDS):
        args.case_ids = list(SEED_CASE_IDS)
    if args.replay_specialists and ("v1_groq" not in args.arms or "v2_super_vl" not in args.arms or
                                    args.arms.index("v1_groq") > args.arms.index("v2_super_vl")):
        raise SystemExit("--replay-specialists requires v1_groq before v2_super_vl")
    if args.deterministic_planner:
        args.arms = ["v2_deterministic" if arm == "v2_super_vl" else arm for arm in args.arms]
    url = make_url(args.database_url)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "progress_test":
        raise SystemExit("Evaluation requires the isolated local progress_test database")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("Use a new output directory to preserve existing evaluation evidence")
    if not args.deterministic_planner:
        with urlopen("https://openrouter.ai/api/v1/models", timeout=20) as response:
            model = next((row for row in json.loads(response.read())["data"] if row["id"] == PLANNER), None)
        if not model or any(float(model.get("pricing", {}).get(key, "-1")) != 0 for key in ("prompt", "completion")):
            raise SystemExit("Planner is missing or not zero-price in the current official catalog")
    settings = get_settings().model_copy(update={"database_url": args.database_url,
        "report_model_timeout_seconds": args.timeout, "llm_provider": "groq",
        "extraction_provider": "groq", "extraction_model": get_settings().groq_model, "extraction_key_slot": 0,
        "selection_provider": "groq", "selection_model": get_settings().groq_model, "selection_key_slot": 0,
        "orchestrator_provider": "openrouter", "orchestrator_model": PLANNER})
    cases = load_cases(args.case_ids, dataset=args.dataset)
    sessions = sessionmaker(create_engine(args.database_url), expire_on_commit=False)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_paths = {"reports": str(ROOT / ("data/synthetic/reports/seed-reports.jsonl" if args.dataset == "seed" else "data/synthetic/expanded/reports.jsonl")),
                    "labels": str(ROOT / ("data/synthetic/labels/seed-labels.jsonl" if args.dataset == "seed" else "data/synthetic/expanded/labels.jsonl")),
                    "schedule": str(ROOT / ("data/synthetic/schedules/demo-utility-01.csv" if args.dataset == "seed" else "data/synthetic/expanded/schedule.csv"))}
    config = {"scope": "synthetic single-fragment reports through full PostgreSQL runtime; no UI or approvals",
        "dataset": args.dataset, "dataset_paths": source_paths,
        "dataset_sha256": {key: sha256(Path(path).read_bytes()).hexdigest() for key, path in source_paths.items()},
        "replay_specialists": args.replay_specialists,
        "quality_comparison": "paired runtime comparison using baseline Groq specialist outputs" if args.replay_specialists else "independent arm executions",
        "latency_comparison": "candidate includes real planner time and replay overhead; not comparable to baseline" if args.replay_specialists else "arm elapsed time includes live model calls",
        "planner": "deterministic" if args.deterministic_planner else PLANNER, "scoring_version": SCORING_VERSION,
        "lease_heartbeat": "worker_primitive_independent_thread", "specialists": settings.groq_model, "groq_key_slot": 0,
        "case_ids": args.case_ids, "arms": args.arms, "timeout_seconds": args.timeout, "transport_retries": 0,
        "label_status": "synthetic_unadjudicated", "started_at": datetime.now(timezone.utc).isoformat(),
        "input_hash": fingerprint([{k: v for k, v in case.items() if k != "label"} for case in cases]),
        "schedule_sha256": sha256(Path(source_paths["schedule"]).read_bytes()).hexdigest()}
    (args.output_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    recorder = Recorder(journal=args.output_dir / "calls.jsonl", replay_specialists=args.replay_specialists)
    original_settings = runtime.get_settings
    original_factory = provider.create_adapter
    project_id = None
    rows = []
    try:
        project_id, schedule_id = seed(sessions, cases)
        provider.create_adapter = recorder.create
        for case in cases:
            parent = None
            for arm in args.arms:
                recorder.case_id, recorder.arm = case["case_id"], arm
                if args.replay_specialists and arm in {"v2_super_vl", "v2_deterministic"}:
                    recorder.replay_queue = [call.copy() for call in recorder.baseline_queues.get(case["case_id"], [])]
                enabled = arm in {"v2_super_vl", "v2_deterministic"}
                actual_settings = settings.model_copy(update={"agent_hierarchy_enabled": enabled,
                                                             "orchestrator_model_assisted": enabled and not args.deterministic_planner})
                job_id, row = run_case(sessions, project_id, schedule_id, case, actual_settings, recorder, parent)
                if args.replay_specialists and arm == "v1_groq":
                    recorder.baseline_queues[case["case_id"]] = [call.copy() for call in recorder.calls if call["stage"] != "planner"]
                if args.replay_specialists and arm in {"v2_super_vl", "v2_deterministic"} and row["replay_calls_remaining"]:
                    raise EvaluationReplayMismatch(f"{case['case_id']}: {row['replay_calls_remaining']} baseline specialist calls were not consumed")
                parent = parent or job_id
                rows.append(row)
                with (args.output_dir / "predictions.jsonl").open("a") as output:
                    output.write(json.dumps(row, default=str) + "\n")
                (args.output_dir / "summary.json").write_text(json.dumps(summarize(rows), indent=2) + "\n")
                print(json.dumps({"case": case["case_id"], "arm": arm, "state": row["state"], "elapsed_ms": row["elapsed_ms"], "scores": row["scores"]}), flush=True)
    finally:
        runtime.get_settings = original_settings
        provider.create_adapter = original_factory
        if project_id:
            cleanup(sessions, project_id)
            (args.output_dir / "cleanup.json").write_text(json.dumps({"synthetic_project_removed": True}) + "\n")
    print(json.dumps(summarize(rows)), flush=True)


if __name__ == "__main__":
    main()
