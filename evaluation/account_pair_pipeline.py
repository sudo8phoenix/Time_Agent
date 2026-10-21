"""Real graph comparison under the original batch-32 cumulative ceiling.

Retains all synthetic PostgreSQL projects/jobs/checkpoints. Never approves work.
"""

from copy import deepcopy
import argparse
import json
from pathlib import Path
import time

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Project
from app.llm import provider
from app.settings import get_settings
from evaluation.account_pair_study import Study, SMALL, LARGE, digest, write, append
from evaluation.assembled_development import full_case_score
from evaluation.deployment_rehearsal import _validate_target, _ensure_migrated
from evaluation.report_planner_eval import run_case, seed
from evaluation.repeated_development import ExperimentStop

ARMS = ["deterministic", "one_account", "two_accounts"]


def prepare(parent_prepared, parent_live, output):
    parent_prepared, parent_live, output = map(Path, (parent_prepared, parent_live, output))
    original = json.loads((parent_prepared / "plan.json").read_text())
    seals = json.loads((parent_live / "capture-manifest.json").read_text())
    for name, expected in seals.items():
        if Path(name).name != name:
            raise ExperimentStop("Unsafe retained capture path")
        if digest(parent_live / name) != expected:
            raise ExperimentStop("Retained capture changed")
    if not {"config.json", "summary.json"}.issubset(seals):
        raise ExperimentStop("Incomplete parent seal")
    config = json.loads((parent_live / "config.json").read_text())
    if config.get("plan_sha256") != digest(parent_prepared / "plan.json"):
        raise ExperimentStop("Parent plan changed")
    retained = json.loads((parent_live / "summary.json").read_text())
    if retained.get("stopped") is not False:
        raise ExperimentStop("Parent study stopped; no automatic continuation")
    output.mkdir(parents=True, exist_ok=False)
    source = Path("evaluation/fixtures/paired-development-v2/inputs.json")
    inputs = [
        r
        for r in json.loads(source.read_text())
        if r["case_id"] in {"DEV-20261020-01", "DEV-20261020-08"}
    ]
    write(output / "cases.json", inputs)
    labels = {
        "DEV-20261020-01": dict(
            expected_activity_ids=["EXC-CEDAR"],
            expected_mapping_state="suggested",
            expected_event_type="actual_progress",
            expected_quantity="5",
            expected_quantity_kind="delta",
            expected_unit="m3",
            expected_area="Zone Cedar",
            expected_asset_tags=["TR-030"],
        ),
        "DEV-20261020-08": dict(
            expected_activity_ids=[],
            expected_mapping_state="ambiguous",
            expected_event_type="actual_progress",
            expected_quantity="2",
            expected_quantity_kind="delta",
            expected_unit="m3",
            expected_area=None,
            expected_asset_tags=[],
        ),
    }
    write(output / "labels.json", labels)
    (output / "schedule.csv").write_text(
        "activity_id,activity_name,wbs_path,discipline,work_type,area,asset_tags,is_leaf,measurement_basis,planned_quantity,unit,planned_start,planned_finish,aliases\nEXC-CEDAR,Excavation Zone Cedar TR-030,1.1,civil,excavation,Zone Cedar,TR-030,true,quantity_ratio,100,m3,2026-10-01,2026-11-30,excavation\nEXC-OAK,Excavation Zone Oak TR-021,1.2,civil,excavation,Zone Oak,TR-021,true,quantity_ratio,100,m3,2026-10-01,2026-11-30,excavation\n"
    )
    deadline = (parent_prepared / "plan.json").stat().st_mtime + original["budget"]["wall_seconds"]
    limits = deepcopy(original["budget"])
    for key, used in [
        ("calls", "reserved_calls"),
        ("reserved_tokens", "reserved_tokens"),
        ("list_price_usd", "reserved_list_price_usd"),
    ]:
        limits[key] -= retained[used]
    limits["wall_seconds"] = max(1, int(deadline - time.time()))
    plan = dict(
        original,
        budget=limits,
        absolute_deadline=deadline,
        retained_budget=retained,
        parent_capture=str(parent_live),
        parent_manifest_sha256=digest(parent_live / "capture-manifest.json"),
        arms=ARMS,
        comparison="Actual v2 graph: deterministic vs 120B assistance; one-account vs fixed key1/key2. Same worker/model/prompt/schedule for all arms; provider-wide admission retained.",
        schedule=[
            dict(case_id=r["case_id"], arm=arm)
            for i, r in enumerate(inputs)
            for arm in (ARMS if i % 2 == 0 else list(reversed(ARMS)))
        ],
        source_sha256={**original["source_sha256"], str(Path(__file__)): digest(__file__)},
        file_sha256={
            name: digest(output / name) for name in ("cases.json", "labels.json", "schedule.csv")
        },
    )
    write(output / "plan.json", plan)
    return plan


class PipelineStudy(Study):
    def create(self, settings, **options):
        role = options.get("role")
        adapter = self.factory(settings, **options)
        slot = getattr(settings, f"{role}_key_slot")
        expected_model = LARGE if role == "orchestrator" else SMALL
        if adapter.model != expected_model:
            raise ExperimentStop("Unexpected role model")
        original = adapter._transport
        parent = self

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
                call = dict(stage=stage, role=role, slot=slot, model=adapter.model, ok=False)

                def transport(method, url, payload, timeout, headers):
                    if time.time() >= parent.plan["absolute_deadline"]:
                        raise ExperimentStop("Original wall ceiling")
                    return parent.transport(
                        slot,
                        f"{parent.case_id}:{parent.arm}:{len(parent.calls)}:{stage}",
                        method,
                        url,
                        payload,
                        timeout,
                        headers,
                    )

                adapter._transport = transport
                began = time.monotonic()
                try:
                    result = adapter.chat(**kwargs)
                    call.update(ok=True, output=result.value)
                    return result
                except Exception as error:
                    call["error_type"] = type(error).__name__
                    if isinstance(error, ExperimentStop):
                        parent.stopped = True
                        parent.stop_reason = type(error).__name__
                    raise
                finally:
                    call["elapsed_ms"] = round(1000 * (time.monotonic() - began))
                    parent.calls.append(call)
                    adapter._transport = original

        return Recorded()


def run(prepared, output, database_url):
    _validate_target(database_url)
    study = PipelineStudy(prepared, output)
    retained = study.plan["retained_budget"]
    study.account_usage = {int(k): v for k, v in retained["account_reserved_tokens"].items()}
    parent = Path(study.plan["parent_capture"])
    if digest(parent / "capture-manifest.json") != study.plan["parent_manifest_sha256"]:
        raise ExperimentStop("Parent manifest changed")
    for name, expected in json.loads((parent / "capture-manifest.json").read_text()).items():
        if digest(parent / name) != expected:
            raise ExperimentStop("Retained file changed")
    engine = create_engine(database_url)
    _ensure_migrated(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as db:
        if db.scalar(select(func.count()).select_from(Project)):
            raise ExperimentStop("Fresh database required")
    inputs = json.loads((Path(prepared) / "cases.json").read_text())
    labels = json.loads((Path(prepared) / "labels.json").read_text())
    scopes = {}
    cases = {}
    for arm in ARMS:
        rows = [
            dict(
                **r,
                locator="synthetic:1",
                family="unambiguous" if r["case_id"].endswith("01") else "ambiguous",
                schedule_path=str(Path(prepared) / "schedule.csv"),
                label=labels[r["case_id"]],
            )
            for r in inputs
        ]
        scopes[arm] = seed(sessions, rows)
        cases[arm] = {r["case_id"]: r for r in rows}
    factory = provider.create_adapter
    study.factory = factory
    provider.create_adapter = study.create
    try:
        for trial in study.plan["schedule"]:
            study.arm, study.case_id = trial["arm"], trial["case_id"]
            settings = get_settings().model_copy(
                update=dict(
                    database_url=database_url,
                    agent_hierarchy_enabled=True,
                    orchestrator_model_assisted=study.arm != "deterministic",
                    report_model_timeout_seconds=180,
                    orchestrator_provider="groq",
                    orchestrator_model=LARGE,
                    orchestrator_key_slot=1 if study.arm == "two_accounts" else 2,
                    extraction_provider="groq",
                    extraction_model=SMALL,
                    extraction_key_slot=2,
                    selection_provider="groq",
                    selection_model=SMALL,
                    selection_key_slot=2,
                )
            )
            case = cases[study.arm][study.case_id]
            _, row = run_case(sessions, *scopes[study.arm], case, settings, study)
            row["full_case_score"] = full_case_score(
                row, labels[study.case_id], case["report_date"]
            )
            append(study.output / "reports.jsonl", row)
            print(
                json.dumps(
                    dict(
                        case=study.case_id,
                        arm=study.arm,
                        state=row["state"],
                        calls=len(row["calls"]),
                        scores=row["full_case_score"],
                    )
                ),
                flush=True,
            )
            if row["ledger_writes"] or any(s != "pending" for s in row["review_states"]):
                study.stopped = True
                study.stop_reason = "approval_boundary"
                break
            if study.stopped:
                break
    finally:
        provider.create_adapter = factory
        study.finish()
        engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run"])
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--parent-prepared", type=Path)
    p.add_argument("--parent-live", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--database-url")
    a = p.parse_args()
    if a.action == "prepare":
        prepare(a.parent_prepared, a.parent_live, a.prepared)
    else:
        run(a.prepared, a.output, a.database_url)
