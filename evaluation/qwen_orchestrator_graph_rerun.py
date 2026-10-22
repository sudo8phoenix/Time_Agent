"""Isolated actual V2 graph challenger comparison; no approvals or active config edits."""

import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from app.settings import get_settings
from app.db.models import Project, AgentRun, Job, ProgressEvent
from app.llm import provider
from app.llm.hosted import request
from evaluation.account_pair_study import digest, write, append
from evaluation.repeated_development import TrialBudget, ExperimentStop
from evaluation.report_planner_eval import seed, run_case
from evaluation.assembled_development import full_case_score
from evaluation.deployment_rehearsal import _validate_target, _ensure_migrated

ROOT = Path(
    "evaluation/results/prompting-checklist-2026-10-20/qwen-orchestrator-graph-2026-10-22-rerun"
)
QWEN = "qwen/qwen3.8-27b"
CONTROL = "openai/gpt-oss-120b"
WORKER = "openai/gpt-oss-20b"


class Recorder:
    replay_specialists = False
    replay_queue = ()

    def __init__(self, settings, plan):
        self.settings = settings
        self.plan = plan
        self.factory = provider.create_adapter
        self.calls = []
        self.next_at = {1: 0, 2: 0}
        self.stopped = False
        self.stop_reason = None
        self.arm = self.case_id = None
        self.budget = TrialBudget(plan["budget"], {"input": 0.8, "output": 4})
        self.plan_hash = digest(ROOT / "plan.json")

    def create(self, settings, **options):
        role = options["role"]
        slot = getattr(settings, f"{role}_key_slot")
        adapter = self.factory(settings, **options)
        expected = self.model if role == "orchestrator" else WORKER
        if adapter.model != expected:
            raise ExperimentStop("Role assignment mismatch")
        parent = self
        original = adapter._transport

        class Recorded:
            def chat(self, **kwargs):
                props = kwargs["schema"].get("properties", {})
                stage = (
                    "planner"
                    if role == "orchestrator"
                    else "extraction"
                    if "observations" in props
                    else "retrieval"
                    if "candidate_ids" in props
                    else "selection"
                )
                call = dict(role=role, stage=stage, slot=slot, model=adapter.model, ok=False)

                def transport(method, url, payload, timeout, headers):
                    if parent.stopped:
                        raise ExperimentStop("Study stopped")
                    if digest(ROOT / "plan.json") != parent.plan_hash:
                        raise ExperimentStop("Plan drift")
                    for name, expected_hash in parent.plan["source_sha256"].items():
                        if digest(name) != expected_hash:
                            raise ExperimentStop("Source drift")
                    key = getattr(parent.settings, f"groq_api_key_{slot}").get_secret_value()
                    if headers.get("Authorization") != "Bearer " + key:
                        raise ExperimentStop("Key mismatch")
                    allowed = parent.budget.reserve(payload)
                    reserve = (
                        len(json.dumps(payload, ensure_ascii=False).encode())
                        + 1024
                        + payload["max_completion_tokens"]
                    )
                    append(
                        ROOT / "reservations.jsonl",
                        dict(
                            case=parent.case_id,
                            arm=parent.arm,
                            slot=slot,
                            payload=payload,
                            **parent.budget.snapshot(),
                        ),
                    )
                    while time.monotonic() < parent.next_at[slot]:
                        time.sleep(min(1, parent.next_at[slot] - time.monotonic()))
                    left = parent.plan["budget"]["wall_seconds"] - (
                        time.monotonic() - parent.budget.started
                    )
                    if left <= 1:
                        raise ExperimentStop("Wall ceiling")
                    parent.next_at[slot] = time.monotonic() + max(60 / 22, 60 * reserve / 6000)
                    began = time.monotonic()
                    row = dict(
                        case=parent.case_id,
                        arm=parent.arm,
                        slot=slot,
                        role=role,
                        stage=stage,
                        requested_model=payload["model"],
                    )
                    try:
                        status, body = request(
                            "groq", method, url, payload, min(timeout, allowed, left), headers
                        )
                        row.update(
                            status=status, returned_model=body.get("model"), usage=body.get("usage")
                        )
                        if status == 200:
                            choice = body["choices"][0]
                            row.update(
                                content=choice["message"].get("content"),
                                finish_reason=choice.get("finish_reason"),
                            )
                        if status != 200 or body.get("model") != payload["model"]:
                            raise ExperimentStop("HTTP/model identity stop")
                        return status, body
                    except BaseException as error:
                        row["error_type"] = type(error).__name__
                        parent.stopped = True
                        parent.stop_reason = type(error).__name__
                        raise
                    finally:
                        row["seconds"] = time.monotonic() - began
                        append(ROOT / "http-calls.jsonl", row)

                adapter._transport = transport
                tick = time.monotonic()
                try:
                    value = adapter.chat(**kwargs)
                    call.update(ok=True, output=value.value)
                    return value
                except Exception as error:
                    call["error_type"] = type(error).__name__
                    if isinstance(error, ExperimentStop):
                        parent.stopped = True
                        parent.stop_reason = type(error).__name__
                    raise
                finally:
                    adapter._transport = original
                    call["elapsed_ms"] = round(1000 * (time.monotonic() - tick))
                    parent.calls.append(call)
                    print(
                        json.dumps(
                            dict(
                                case=parent.case_id,
                                arm=parent.arm,
                                **{k: call[k] for k in ("stage", "model", "slot", "ok")},
                            )
                        ),
                        flush=True,
                    )

        return Recorded()


def main():
    settings = get_settings()
    database_url = settings.database_url
    _validate_target(database_url)
    engine = create_engine(database_url)
    _ensure_migrated(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        if db.scalar(select(func.count()).select_from(Project)):
            raise ExperimentStop("Fresh database required")
    ROOT.mkdir(exist_ok=False)
    source = Path("evaluation/fixtures/model-comparison-2026-10-22")
    inputs = json.loads((source / "cases.json").read_text())
    labels = json.loads((source / "labels.json").read_text())
    for name in ("cases.json", "labels.json", "schedule.csv"):
        (ROOT / name).write_bytes((source / name).read_bytes())
    schedule = []
    for i, case in enumerate(inputs):
        arms = [(QWEN, 1), (CONTROL, 1), (CONTROL, 2), (QWEN, 2)]
        if i % 2:
            arms.reverse()
        schedule.extend(
            dict(case_id=case["case_id"], model=model, planner_slot=slot, worker_slot=3 - slot)
            for model, slot in arms
        )
    completed = [
        ("DEV-20261020-01", "qwen/qwen3.8-27b", 1),
        ("DEV-20261020-01", "openai/gpt-oss-120b", 1),
        ("DEV-20261020-01", "openai/gpt-oss-120b", 2),
    ]
    schedule = [
        r for r in schedule if (r["case_id"], r["model"], r["planner_slot"]) not in completed
    ]
    plan = dict(
        owner_rerun="Owner reports network issue from their side and explicitly requests rerun; original failure retained",
        parent_summary={
            "reserved_calls": 20,
            "reserved_tokens": 126346,
            "reserved_list_price_usd": 0.19938080000000005,
            "elapsed_seconds": 1068.757,
            "stopped": True,
            "stop_reason": "URLError",
            "reports": 4,
            "planned_reports": 8,
            "preservation": {"jobs": 4, "runs": 4, "ledger_writes": 0},
            "release_accepted": False,
        },
        parent_manifest_sha256="b968a94ce8f3393f7dea2d8e26c86c5da91899f645f7d43cb19aae8308bc5369",
        scope="Consumed synthetic development; actual V2 graph, pending review only",
        models=[QWEN, CONTROL],
        worker=WORKER,
        schedule=schedule,
        budget=dict(
            calls=76,
            reserved_tokens=873654,
            list_price_usd=0.8006192,
            wall_seconds=2400,
            request_seconds=180,
            output_tokens_per_call=1536,
        ),
        prices_per_million={QWEN: [0.8, 4], CONTROL: [0.15, 0.60], WORKER: [0.075, 0.30]},
        account_mapping={"1": "owner-account-1", "2": "owner-account-2"},
        source_sha256={
            str(p): digest(p)
            for p in sorted(
                set(Path("backend/app").rglob("*.py"))
                | {
                    Path(__file__),
                    Path("evaluation/report_planner_eval.py"),
                    Path("evaluation/assembled_development.py"),
                }
            )
        },
        file_sha256={
            name: digest(ROOT / name) for name in ("cases.json", "labels.json", "schedule.csv")
        },
        pacing="Cold byte-plus-framing reservations, 6000 TPM / 22 RPM per key plus existing provider-wide admission; 120-second report target",
        database_name=database_url.rsplit("/", 1)[-1],
        production_changed=False,
    )
    write(ROOT / "plan.json", plan)
    rec = Recorder(settings, plan)
    reports = []
    scopes = {}
    try:
        catalogs = []
        for slot in (1, 2):
            key = getattr(settings, f"groq_api_key_{slot}").get_secret_value()
            with urlopen(
                Request(
                    "https://api.groq.com/openai/v1/models",
                    headers={
                        "Authorization": "Bearer " + key,
                        "User-Agent": "site-progress-agent/0.1",
                    },
                ),
                timeout=30,
            ) as response:
                ids = [r["id"] for r in json.load(response)["data"]]
                catalogs.append(
                    dict(
                        slot=slot,
                        status=response.status,
                        required_available=all(m in ids for m in (QWEN, CONTROL, WORKER)),
                    )
                )
        write(ROOT / "catalogs.json", catalogs)
        if not all(r["required_available"] for r in catalogs):
            raise ExperimentStop("Catalog unavailable")
        for trial in schedule:
            arm = trial["model"] + ":key" + str(trial["planner_slot"])
            if arm not in scopes:
                cases = [
                    dict(
                        **r,
                        locator="synthetic:1",
                        family="unambiguous" if r["case_id"].endswith("01") else "ambiguous",
                        schedule_path=str(ROOT / "schedule.csv"),
                        label=labels[r["case_id"]],
                    )
                    for r in inputs
                ]
                scopes[arm] = (*seed(sessions, cases), {r["case_id"]: r for r in cases})
            project_id, schedule_id, cases = scopes[arm]
            rec.arm, rec.case_id, rec.model = arm, trial["case_id"], trial["model"]
            pinned = settings.model_copy(
                update=dict(
                    agent_hierarchy_enabled=True,
                    orchestrator_model_assisted=True,
                    report_model_timeout_seconds=180,
                    orchestrator_provider="groq",
                    orchestrator_model=trial["model"],
                    orchestrator_key_slot=trial["planner_slot"],
                    extraction_provider="groq",
                    extraction_model=WORKER,
                    extraction_key_slot=trial["worker_slot"],
                    selection_provider="groq",
                    selection_model=WORKER,
                    selection_key_slot=trial["worker_slot"],
                    llm_max_retries=0,
                )
            )
            provider.create_adapter = rec.create
            _, row = run_case(sessions, project_id, schedule_id, cases[rec.case_id], pinned, rec)
            row["full_case_score"] = full_case_score(
                row, labels[rec.case_id], cases[rec.case_id]["report_date"]
            )
            row["planner_model"] = trial["model"]
            row["planner_slot"] = trial["planner_slot"]
            row["worker_slot"] = trial["worker_slot"]
            append(ROOT / "reports.jsonl", row)
            reports.append(row)
            print(
                json.dumps(
                    dict(
                        case=rec.case_id,
                        arm=arm,
                        state=row["state"],
                        seconds=row["elapsed_ms"] / 1000,
                        score=row["full_case_score"],
                    )
                ),
                flush=True,
            )
            if row["ledger_writes"] or any(s != "pending" for s in row["review_states"]):
                raise ExperimentStop("Approval boundary")
            if rec.stopped:
                break
    except BaseException as error:
        rec.stopped = True
        rec.stop_reason = type(error).__name__
        raise
    finally:
        provider.create_adapter = rec.factory
        with sessions() as db:
            preservation = dict(
                jobs=db.scalar(select(func.count()).select_from(Job)),
                runs=db.scalar(select(func.count()).select_from(AgentRun)),
                ledger_writes=db.scalar(select(func.count()).select_from(ProgressEvent)),
            )
        write(
            ROOT / "summary.json",
            dict(
                **rec.budget.snapshot(),
                stopped=rec.stopped,
                stop_reason=rec.stop_reason,
                reports=len(reports),
                planned_reports=5,
                preservation=preservation,
                release_accepted=False,
            ),
        )
        write(
            ROOT / "capture-manifest.json",
            {p.name: digest(p) for p in ROOT.iterdir() if p.is_file()},
        )
        engine.dispose()


if __name__ == "__main__":
    main()
