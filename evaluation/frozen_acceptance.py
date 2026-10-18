"""Capture fresh prototype reports through the real worker, without reading labels.

Only local progress_rehearsal_* databases are allowed. Fixtures and checkpoints
are retained. This command never accepts a proposal or starts an API server.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import monotonic

from sqlalchemy import func, select

from app.agent import runtime
from app.db.models import Activity, AgentRun, AgentStep, AgentToolCall, Job, Observation, ProgressEvent, Proposal
from app.db.session import engine, session_factory as sessions
from app.jobs.service import enqueue_job, heartbeat
from app.jobs.worker import run_once
from app.llm import provider
from app.prompts.extraction_v1 import get_extraction_prompt
from app.settings import get_settings
from evaluation.deployment_rehearsal import _ensure_migrated, _validate_target
from evaluation.report_planner_eval import seed
from evaluation.live_pacing import wait_before_case


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def load_inputs(path, manifest_path, split):
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("status") != "frozen_inputs_and_ai_labels" or manifest["hashes"].get(path.name) != digest(path):
        raise ValueError("Inputs must match a frozen input manifest")
    seen_cases, seen_groups = set(), set()
    for inventory in manifest["splits"].values():
        cases = [r["case_id"] for r in inventory]
        groups = {r["group_id"] for r in inventory}
        if len(cases) != len(set(cases)) or seen_cases.intersection(cases) or seen_groups.intersection(groups):
            raise ValueError("Cross-split case/group leakage")
        seen_cases.update(cases)
        seen_groups.update(groups)
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    def check(value):
        if isinstance(value, dict):
            if any(key.startswith("expected") or key in {"labels", "gold", "targets", "confidence"} for key in value):
                raise ValueError("Capture inputs must contain no expected labels")
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(rows)
    if len({r["case_id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate input case")
    selected = [r for r in rows if r["split"] == split]
    expected = {r["case_id"]: r["group_id"] for r in manifest["splits"][split]}
    if {r["case_id"]: r["group_id"] for r in selected} != expected or not 1 <= len(selected) <= 8:
        raise ValueError("Capture must cover exactly 1–8 frozen cases in the selected split")
    return selected


def capture(inputs, manifest, output, split, prompt_version, *, batch_size=5):
    if not 1 <= batch_size <= 5:
        raise ValueError('Use groups of at most five live cases')
    settings = get_settings()
    _validate_target(settings.database_url)
    if settings.agent_hierarchy_enabled or settings.orchestrator_model_assisted or settings.llm_provider != "groq":
        raise ValueError("This capture requires explicit Groq baseline with rollout flags off")
    if settings.report_model_timeout_seconds > 90:
        raise ValueError("Use a bounded report timeout at most 90 seconds")
    _ensure_migrated(engine)
    rows = load_inputs(inputs, manifest, split)
    version, prompt = get_extraction_prompt(prompt_version)
    if output.exists():
        raise ValueError("Use a new evidence directory")
    with sessions() as db:
        if db.scalar(select(func.count()).select_from(Job).where(Job.state.in_(("running", "queued")))):
            raise ValueError("Inspect pending rehearsal work before capture")
    output.mkdir(parents=True)
    source_paths = [Path("backend/app/agent/runtime.py"), Path("backend/app/agent/schedule_decision.py"),
        Path("backend/app/llm/extract.py"), Path("backend/app/llm/hosted.py"),
        Path("backend/app/prompts/extraction_v1.py"), Path('evaluation/live_pacing.py'), Path(__file__)]
    _write(output / "config.json", {
        "started_at": datetime.now(timezone.utc).isoformat(), "split": split,
        "inputs_sha256": digest(inputs), "manifest_sha256": digest(manifest),
        "provider": "groq", "model": settings.groq_model, "key_slot": 0,
        "prompt_version": version, "prompt_sha256": sha256(prompt.encode()).hexdigest(),
        "timeout_seconds": settings.report_model_timeout_seconds,
        "rollout_flags": False, "source_sha256": {str(p): digest(p) for p in source_paths},
        "labels_read_by_capture": False, "automatic_acceptance": False,
        "scope": "Sequential real worker baseline; synthetic narrative reports; no UI/approval/connector timing",
        "batch_size": batch_size, "batch_pause_seconds": 60,
        "readiness_excludes_recorded_pre_submission_pacing": True,
    })
    # Seed input-only projects; expected labels are never opened in this command.
    schedule_dir = output / "schedules"
    schedule_dir.mkdir()
    fixtures = {}
    for group in sorted({r["group_id"] for r in rows}):
        group_rows = [r for r in rows if r["group_id"] == group]
        activities = group_rows[0]["activities"]
        if any(row["activities"] != activities for row in group_rows):
            raise ValueError("A group must pin one schedule snapshot")
        path = schedule_dir / f"{group}.csv"
        with path.open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(activities[0]))
            writer.writeheader()
            writer.writerows(activities)
        cases = [{"case_id": r["case_id"], "report_date": r["report_date"], "text": r["text"],
            "locator": "synthetic:1", "schedule_path": str(path)} for r in group_rows]
        project_id, schedule_id = seed(sessions, cases)
        for case in cases:
            fixtures[case["case_id"]] = (project_id, schedule_id, case["report_id"])
    _write(output / "fixtures.json", fixtures)
    original_factory = provider.create_adapter
    active_case = None
    def factory(*args, **kwargs):
        adapter = original_factory(*args, **kwargs)
        class Recorded:
            def chat(self, **call):
                properties = call.get("schema", {}).get("properties", {})
                stage = "extraction" if "observations" in properties else "retrieval" if "candidate_ids" in properties else "selection"
                result = {"case_id": active_case, "stage": stage, "ok": False}
                if isinstance(call.get("user"), dict) and "observation" in call["user"]:
                    result["observation"] = call["user"]["observation"]
                try:
                    value = adapter.chat(**call)
                    result.update(ok=True, value=value.value, model=value.model,
                        prompt_hash=value.prompt_hash, settings_hash=value.settings_hash)
                    return value
                except Exception as error:
                    result["error_type"] = type(error).__name__
                    raise
                finally:
                    with (output / "calls.jsonl").open("a") as stream:
                        stream.write(json.dumps(result) + "\n")
        return Recorded()
    provider.create_adapter = factory
    try:
        for index, row in enumerate(rows):
            active_case = row["case_id"]
            wait_before_case(output, active_case, index, batch_size=batch_size)
            project_id, schedule_id, report_id = fixtures[active_case]
            started = monotonic()
            with sessions.begin() as db:
                from app.db.models import Project, Report
                job, existed = enqueue_job(db, db.get(Project, project_id), db.get(Report, report_id))
                assert not existed
                job.config_snapshot = {"provider": "groq", "model": settings.groq_model,
                    "extraction_prompt_version": version}
                job_id = job.id
            def pipeline(db, job, *, token, should_stop, heartbeat_callback):
                assert job.id == job_id, "Unexpected claim; stop and inspect the rehearsal database"
                return runtime.process_job_with_graph(db, job, token=token, session_factory=sessions,
                    database_url=settings.database_url, should_stop=should_stop,
                    heartbeat_callback=heartbeat_callback)
            def beat(job, token):
                with sessions.begin() as db:
                    return heartbeat(db, job.id, token)
            with sessions() as db:
                run_once(db, pipeline, heartbeat_callback=beat,
                    should_stop=lambda: monotonic() - started > 360)
            with sessions() as db:
                job = db.get(Job, job_id)
                run = db.scalar(select(AgentRun).where(AgentRun.job_id == job_id))
                activity_ids = {str(a.id): a.external_id for a in db.scalars(select(Activity).where(Activity.schedule_version_id == schedule_id))}
                observations = list(db.scalars(select(Observation).where(Observation.job_id == job_id).order_by(Observation.ordinal)))
                events = []
                for observation in observations:
                    proposal = db.scalar(select(Proposal).where(Proposal.observation_id == observation.id))
                    candidates = [activity_ids.get(str(c.get("candidate_id"))) for c in (proposal.candidates if proposal else [])]
                    events.append({"fields": observation.fields, "selected_activity": activity_ids.get(str(proposal.chosen_activity_id)) if proposal else None,
                        "candidate_ids": candidates, "mapping_state": proposal.mapping_state if proposal else None,
                        "effects": proposal.proposed_effects if proposal else {}, "review_state": proposal.review_state if proposal else None})
                tools = [dict(r) for r in db.execute(select(AgentToolCall.tool_name, AgentToolCall.state,
                    AgentToolCall.error_code, AgentToolCall.sanitized_output_summary, AgentToolCall.duration_ms)
                    .join(AgentStep, AgentToolCall.step_id == AgentStep.id).where(AgentStep.run_id == run.id)).mappings()] if run else []
                ledger = db.scalar(select(func.count()).select_from(ProgressEvent).join(Observation,
                    Observation.id == ProgressEvent.observation_id).join(Job, Job.id == Observation.job_id).where(Job.project_id == project_id))
                assert ledger == 0, "Capture must never write approved progress"
                prediction = {"case_id": active_case, "group_id": row["group_id"], "job_id": str(job_id),
                    "state": job.state, "error_code": job.error_code, "elapsed_seconds": round(monotonic()-started, 3),
                    "events": events, "tools": tools, "approved_progress_events": ledger,
                    "activity_external_ids": activity_ids}
            with (output / "predictions.jsonl").open("a") as stream:
                stream.write(json.dumps(prediction) + "\n")
            print(json.dumps({k: prediction[k] for k in ("case_id", "state", "error_code", "elapsed_seconds")}), flush=True)
            if prediction["state"] in {"running", "queued"}:
                raise RuntimeError("Nonterminal job retained; inspect before resuming")
    finally:
        provider.create_adapter = original_factory
        _write(output / "capture-manifest.json", {"sealed_at": datetime.now(timezone.utc).isoformat(),
            "labels_read": False, "hashes": {p.name: digest(p) for p in output.iterdir() if p.is_file()}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "holdout"), required=True)
    parser.add_argument("--prompt-version", required=True)
    parser.add_argument("--batch-size", type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    capture(args.inputs, args.manifest, args.output_dir, args.split, args.prompt_version,
        batch_size=args.batch_size)


if __name__ == "__main__":
    main()
