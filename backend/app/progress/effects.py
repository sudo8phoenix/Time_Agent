"""Shared typed effect construction for legacy and graph workers."""
from typing import Any
from app.schemas.events import LifecycleEffect


def build_effects(observation: Any) -> dict[str, Any]:
    event = getattr(observation.event_type, "value", observation.event_type)
    if event in {"actual_start", "actual_finish"}:
        effects = observation.lifecycle_effects
        if len(effects) != 1 or effects[0].kind.value != event:
            return {}  # unresolved assertions remain review/clarification work
        effect: LifecycleEffect = effects[0]
        return {"event_type": event, "scope": effect.scope.value,
                "endpoint": effect.endpoint.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in effect.evidence],
                "effective_date": effect.endpoint.local_date.isoformat(),
                "source_version_id": str(effect.source_version_id) if effect.source_version_id else None,
                "observation_id": str(effect.observation_id) if effect.observation_id else None,
                "proposal_id": str(effect.proposal_id) if effect.proposal_id else None,
                "subactivity_key": effect.subactivity_key,
                "scheduled_parent_id": str(effect.scheduled_parent_id) if effect.scheduled_parent_id else None}
    if event == "blocker":
        return {"event_type": "blocker", "blocker": observation.blocker or observation.summary,
                "blocker_category": "other",
                "effective_date": observation.work_date.isoformat() if observation.work_date else None,
                "evidence": [item.model_dump(mode="json") for item in observation.evidence]}
    if event != "actual_progress":
        return {}
    result: dict[str, Any] = {"event_type": event,
                              "quantity_semantics": getattr(observation.quantity_kind, "value", observation.quantity_kind)}
    if observation.quantity is not None:
        result["quantity"] = str(observation.quantity)
    if observation.unit is not None:
        result["unit"] = getattr(observation.unit, "value", observation.unit)
    if observation.reported_percent is not None:
        result["reported_percent"] = str(observation.reported_percent)
    if observation.work_date is not None:
        result["effective_date"] = observation.work_date.isoformat()
    return result
