"""Database assembly for the injected extraction and matching pipeline."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Activity, Fragment, Job, Observation as DBObservation, Proposal, Report
from ..llm.extract import FragmentInput, extract_fragments, deduplicate_results
from ..agent.schedule_decision import shortlist_activities, select_activity


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"): return value.model_dump(mode="json")
    if hasattr(value, "__dict__"): return {k: _json(v) for k, v in vars(value).items()}
    return dict(value)

def _json(value: Any) -> Any:
    if hasattr(value, "value"): return value.value
    if hasattr(value, "isoformat"): return value.isoformat()
    if hasattr(value, "__dict__"): return {k: _json(v) for k, v in vars(value).items()}
    if isinstance(value, (list, tuple)): return [_json(v) for v in value]
    if isinstance(value, dict): return {str(k): _json(v) for k, v in value.items()}
    return value


def _effects(obs: Any) -> dict[str, Any]:
    event_value = getattr(obs, "event_type", "")
    event = getattr(event_value, "value", str(event_value))
    quantity = getattr(obs, "quantity", None)
    unit = getattr(obs, "unit", None)
    work_date = getattr(obs, "work_date", None)
    if event.endswith("actual_progress") or event == "actual_progress":
        kind = getattr(obs, "quantity_kind", "unknown")
        out: dict[str, Any] = {
            "event_type": event,
            "quantity_semantics": getattr(kind, "value", kind),
        }
        if quantity is not None: out["quantity"] = str(quantity)
        if unit is not None: out["unit"] = getattr(unit, "value", str(unit))
        reported_percent = getattr(obs, "reported_percent", None)
        if reported_percent is not None: out["reported_percent"] = str(reported_percent)
        if work_date is not None: out["effective_date"] = work_date.isoformat()
        return out
    return {}


def process_job(db: Session, job: Job, *, model_call: Callable[..., Any] | None = None,
                extraction_call: Callable[..., Any] | None = None,
                selection_call: Callable[..., Any] | None = None,
                retrieve_call: Callable[..., Any] | None = None,
                heartbeat_callback: Callable[[Job, str], bool] | None = None,
                lease_token: str | None = None,
                should_stop: Callable[[], bool] | None = None,
                **kwargs: Any) -> dict[str, Any]:
    """Extract, retrieve and persist one job against its pinned schedule snapshot."""
    existing = db.scalar(select(DBObservation).where(DBObservation.job_id == job.id).order_by(DBObservation.id))
    if existing is not None:
        n = db.query(DBObservation).filter(DBObservation.job_id == job.id).count()
        p = db.query(Proposal).join(DBObservation, Proposal.observation_id == DBObservation.id).filter(DBObservation.job_id == job.id).count()
        return {"stage": "persist", "state": "ready_for_review", "extracted_count": n, "proposal_count": p}
    fragments = list(db.scalars(select(Fragment).where(Fragment.report_id == job.report_id).order_by(Fragment.ordinal)))
    if not fragments:
        return {"stage": "persist", "state": "ready_for_review", "extracted_count": 0, "proposal_count": 0}
    activities = list(db.scalars(select(Activity).where(Activity.schedule_version_id == job.schedule_version_id, Activity.is_leaf.is_(True))))
    kwargs.pop("embed", None)
    report = db.get(Report, job.report_id)
    frag_inputs = [FragmentInput(str(f.id), f.locator, f.normalised_text or f.original_text, f.ordinal) for f in fragments]
    # Keep job metadata out of the database transaction until all model calls
    # finish.  Flushing a Job update here locks the lease row; the independent
    # heartbeat session would then block on that lock before it can call the
    # model, deadlocking the worker until the lease expires.
    model_version = job.model_version
    prompt_version = job.prompt_version
    config_version = job.config_version
    if model_call is None and extraction_call is None:
        from ..llm.ollama import OllamaChatAdapter
        from ..settings import get_settings
        config = get_settings()
        adapter = OllamaChatAdapter(
            config.ollama_base_url,
            config.ollama_model,
            bearer_token=(config.ollama_api_key.get_secret_value() if config.ollama_api_key else None),
        )
        model_call = adapter.chat
        model_metadata = adapter.metadata()
        model_version = f"{config.ollama_model}:{model_metadata.get('digest', 'unknown')}"
    else:
        model_metadata = {}

    def checked_model_call(**call_kwargs):
        if should_stop and should_stop():
            from .worker import WorkerShutdown
            raise WorkerShutdown()
        if heartbeat_callback and lease_token and not heartbeat_callback(job, lease_token):
            raise RuntimeError("JOB_LEASE_LOST")
        return model_call(**call_kwargs)

    def selection_model_call(**call_kwargs):
        response = checked_model_call(**call_kwargs)
        return response.value if hasattr(response, "value") else response
    with db.begin_nested():
        if extraction_call is not None:
            results = extraction_call(frag_inputs)
        else:
            if model_call is None: raise ValueError("model_call or extraction_call is required")
            results = extract_fragments(frag_inputs, checked_model_call, report_date=report.report_date if report else None,
                                        report_date_trusted=bool(report and report.report_date and report.report_date_evidence), **kwargs)
        observations = list(deduplicate_results(results)) if results and hasattr(results[0], "observations") else list(results)
        for result in results:
            metadata = getattr(result, "metadata", None)
            if metadata:
                model_version = metadata.model or model_version
                prompt_version = metadata.prompt_version or prompt_version
                config_version = metadata.settings_hash or config_version
        proposal_count = 0
        for index, obs in enumerate(observations):
            fields = _dump(obs)
            evidence = [_dump(e) for e in getattr(obs, "evidence", [])]
            source_ids = {str(e.get("fragment_id")) for e in evidence}
            source = next((f for f in fragments if str(f.id) in source_ids), fragments[0])
            ordinal = source.ordinal * 1000 + index
            row = DBObservation(job_id=job.id, fragment_id=source.id, ordinal=ordinal, fields=fields,
                                field_evidence={"evidence": evidence})
            db.add(row); db.flush()
            retrieved = (retrieve_call(obs, job.schedule_version_id, activities) if retrieve_call else
                         shortlist_activities(obs, job.schedule_version_id, activities,
                                              model_call=checked_model_call))
            candidates = retrieved.candidates if hasattr(retrieved, "candidates") else retrieved
            fragments_map = {str(f.id): f.normalised_text or f.original_text for f in fragments}
            selected = (selection_call(obs, candidates, fragments_map) if selection_call else
                        select_activity(obs, candidates, fragments_map,
                                        model_call=selection_model_call))
            payload = _dump(selected)
            row.field_evidence = {
                "evidence": evidence,
                "selection": {key: payload.get(key) for key in ("explanation", "reason_codes", "missing_information")},
            }
            chosen = payload.get("candidate_id")
            chosen_activity = next((a for a in activities if str(a.id) == str(chosen)), None) if chosen else None
            db.add(Proposal(observation_id=row.id, project_id=job.project_id, chosen_activity_id=chosen_activity.id if chosen_activity else None,
                            candidates=_json(payload.get("candidates", [])), mapping_state=payload.get("mapping_state", "unmatched"),
                            match_strength=payload.get("match_strength", "unresolved"), review_state="pending",
                            warnings=fields.get("warnings", []), proposed_effects=_effects(obs)))
            proposal_count += 1
        job.model_version = model_version
        job.prompt_version = prompt_version
        job.config_version = config_version
        job.extracted_count = len(observations); job.proposal_count = proposal_count
        db.flush()
    return {"stage": "persist", "state": "ready_for_review", "extracted_count": len(observations), "proposal_count": proposal_count}
