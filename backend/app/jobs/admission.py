"""Keep reports queued during known provider cooldowns without spending attempts."""
from datetime import datetime, timezone
import math

from sqlalchemy import select

from ..db.models import AgentRun, HostedProviderAdmission
from ..llm.account_scopes import resolve_scope
from ..settings import get_settings


def report_admission_ready(db, job, *, settings=None, now=None):
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    run = db.scalar(select(AgentRun).where(AgentRun.job_id == job.id))
    metadata = run.config_metadata if run else {}
    snapshot = job.config_snapshot or {}
    baseline = snapshot.get("provider") or settings.llm_provider
    roles = (metadata or {}).get("roles")
    if roles:
        assignments = [(role, item["provider"], item.get("key_slot", 0))
                       for role, item in roles.items()]
        model_assisted = metadata.get("model_assisted", False)
    else:
        assignments = [(role, getattr(settings, f"{role}_provider", None) or baseline,
                        getattr(settings, f"{role}_key_slot", 0))
                       for role in ("orchestrator", "extraction", "selection")]
        model_assisted = settings.agent_hierarchy_enabled and settings.orchestrator_model_assisted
    scopes = set()
    for role, provider, slot in assignments:
        if role == "orchestrator" and not model_assisted:
            continue
        if provider == "groq":
            # Never multiply quota by key. Use the same verified scope policy as
            # the transport, including pinned policy for a retained run.
            if metadata and "groq_account_scopes_enabled" in metadata:
                settings = settings.model_copy(update={
                    "groq_account_scopes_enabled": metadata["groq_account_scopes_enabled"]})
            scopes.add(resolve_scope(settings, slot) or "groq")
        elif provider == "openrouter":
            scopes.add(provider)
    if not scopes:
        return True
    for row in db.scalars(select(HostedProviderAdmission).where(
            HostedProviderAdmission.provider.in_(scopes))):
        state = row.state or {}
        for field in ("cooldown", "request_reset"):
            value = state.get(field, 0)
            if field == "request_reset" and state.get("remaining_requests") != 0:
                continue
            if isinstance(value, (int, float)) and math.isfinite(value) and value > now.timestamp():
                return False
    return True
