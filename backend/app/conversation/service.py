"""Draft lifecycle conversation analysis and reviewer-queue handoff."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.schedule_decision import candidate_for_activity, shortlist_activities, select_activity, has_location_conflict
from ..db.models import (Activity, Conversation, ConversationTurn, Fragment, Job,
                         Observation as StoredObservation, Project, Proposal, Report, User)
from ..llm.extract import FragmentInput, extract_fragments, deduplicate_results
from ..llm.ollama import OllamaChatAdapter
from ..progress.effects import build_effects
from ..schemas.observation import Observation
from ..schemas.matching import Proposal as SelectionProposal
from ..settings import get_settings


QUESTIONS = {
    "date": "What date did this work happen? A time is optional.",
    "location": "Which scheduled activity or location does this refer to?",
    "scope": "What exactly finished: the whole scheduled activity or a named part?",
    "work": "What work started or finished? Please include the activity or location.",
    "retry": "The analysis is temporarily unavailable. Retry when the model is ready.",
}


def turns(db: Session, conversation: Conversation) -> list[ConversationTurn]:
    return list(db.scalars(select(ConversationTurn).where(
        ConversationTurn.conversation_id == conversation.id).order_by(ConversationTurn.ordinal)))


def add_turn(db: Session, conversation: Conversation, role: str, text: str, actor_id=None):
    row = ConversationTurn(conversation_id=conversation.id,
                           ordinal=len(turns(db, conversation)) + 1,
                           role=role, text=text, actor_id=actor_id)
    db.add(row)
    db.flush()
    return row


def _model_call():
    settings = get_settings()
    adapter = OllamaChatAdapter(settings.ollama_base_url, settings.ollama_model,
                                timeout=settings.conversation_model_timeout_seconds, max_retries=0,
                                bearer_token=settings.ollama_api_key.get_secret_value() if settings.ollama_api_key else None)
    return adapter.chat


def _date_from_answer(text: str) -> date | None:
    answer = text.strip().replace(",", "")
    for pattern in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(answer, pattern).date()
        except ValueError:
            continue
    return None


def _has_complete_date(text: str) -> bool:
    month = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    return bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", text) or
                re.search(rf"\b\d{{1,2}}\s+{month}\s+\d{{4}}\b", text, re.I) or
                re.search(rf"\b{month}\s+\d{{1,2}},?\s+\d{{4}}\b", text, re.I))


def _exact_selection(observation: Observation, candidates: list, fragment_map: dict[str, str]):
    """Accept one shortlisted row when its area and work type match quoted evidence."""
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if not candidate.area or has_location_conflict(candidate):
        return None
    area = candidate.area.strip().casefold()
    if observation.area and observation.area.strip().casefold() != area:
        return None
    if candidate.work_type != observation.work_type:
        return None
    pattern = rf"(?<![a-z0-9]){re.escape(area)}(?![a-z0-9])"
    evidence_ids = [item.fragment_id for item in observation.evidence
                    if item.fragment_id in fragment_map and
                    re.search(pattern, item.quote.casefold()) and
                    re.search(pattern, fragment_map[item.fragment_id].casefold())]
    if not evidence_ids:
        return None
    return SelectionProposal.model_validate({
        "candidate_id": candidate.candidate_id, "mapping_state": "suggested",
        "match_strength": "review", "evidence_fragment_ids": list(dict.fromkeys(evidence_ids)),
        "reason_codes": ["EXACT_AREA_WORK_TYPE"],
        "explanation": "The quoted area and work type match the only shortlisted activity.",
        "missing_information": [], "candidates": candidates,
        "review_state": "pending", "proposed_effects": {},
    })


def _quoted_exact_candidates(observation: Observation, activities: list[Activity], fragment_map: dict[str, str]):
    """Return one schedule row only when its area is named in validated event evidence."""
    matches = []
    for activity in activities:
        if not activity.area or activity.work_type != observation.work_type.value:
            continue
        candidate = candidate_for_activity(activity)
        if _exact_selection(observation, [candidate], fragment_map):
            matches.append(candidate)
    return matches if len(matches) == 1 else None


def analyze(db: Session, conversation: Conversation, *, model_call=None) -> None:
    """Recompute draft cards from immutable user turns. Failed model calls leave turns retryable."""
    history = [row for row in turns(db, conversation) if row.role == "user"]
    draft = dict(conversation.draft or {})
    report_date = date.fromisoformat(draft["report_date"]) if draft.get("report_date") else None
    if conversation.pending_question == "date" and history and not report_date:
        answer = _date_from_answer(history[-1].text)
        if answer:
            report_date = answer
            draft["report_date"] = answer.isoformat()
        else:
            conversation.draft = draft
            return
    source = [row for row in history if _date_from_answer(row.text) is None]
    if not source:
        conversation.pending_question = "work"
        conversation.draft = draft
        return
    text = " ".join(row.text for row in source)
    lifecycle_verb = re.search(r"\b(started|finished|completed|began)\b", text, re.I)
    nonactual_prefix = re.search(r"\b(?:not|never|didn.t|will|would|plan(?:ned)? to|scheduled to)\b.{0,25}\b(?:start|finish|complete|begin|started|finished|completed|began)\b", text, re.I)
    if not report_date and lifecycle_verb and not nonactual_prefix and not _has_complete_date(text):
        conversation.pending_question = "date"
        conversation.draft = draft
        return
    fragments = [FragmentInput(str(row.id), f"Conversation turn {row.ordinal}", row.text, row.ordinal)
                 for row in history]
    raw_call = model_call or _model_call()
    call_trace = []
    def call(**kwargs):
        from ..confidence.provenance import call_metadata
        response = raw_call(**kwargs)
        call_trace.append(call_metadata(kwargs, response))
        return response
    results = extract_fragments(fragments, call, report_date=report_date,
                                report_date_trusted=bool(report_date))
    draft["extraction_metadata"] = [vars(result.metadata) for result in results]
    draft["extraction_errors"] = [error for result in results for error in result.errors]
    all_observations = deduplicate_results(results)
    observations = [item for item in all_observations
                    if item.event_type.value in {"actual_start", "actual_finish"}]
    if not observations:
        conversation.pending_question = None if all_observations else "work" if report_date else "date"
        draft["events"] = []
        conversation.draft = draft
        return
    activities = list(db.scalars(select(Activity).where(
        Activity.schedule_version_id == conversation.schedule_version_id,
        Activity.is_leaf.is_(True))))
    from ..agent.project_aliases import with_project_aliases
    activities = with_project_aliases(db, conversation.project_id, activities)
    cards = []
    fragment_map = {item.fragment_id: item.text for item in fragments}
    for observation in observations:
        effect = build_effects(observation)
        if observation.event_type.value in {"actual_start", "actual_finish"} and not effect:
            conversation.pending_question = ("scope" if observation.event_type.value == "actual_finish" and
                                             (report_date or observation.work_date) else "date")
            conversation.draft = draft
            return
        candidates = (_quoted_exact_candidates(observation, activities, fragment_map) or
                      shortlist_activities(observation, conversation.schedule_version_id,
                                           activities, model_call=call))
        decision = (_exact_selection(observation, candidates, fragment_map) or
                    select_activity(observation, candidates, fragment_map, model_call=call))
        cards.append({
            "observation": observation.model_dump(mode="json"),
            "effect": effect,
            "selection": decision.model_dump(mode="json"),
            "activity_id": str(decision.candidate_id) if decision.candidate_id else None,
        })
    draft["model_calls"] = call_trace
    draft["events"] = cards
    conversation.draft = draft
    scope_answered = history[-1].text.strip().casefold() in {"whole activity", "the whole activity", "whole scheduled activity", "the whole scheduled activity"}
    unclear_scope = not scope_answered and any(card["observation"]["event_type"] == "actual_finish" and
                        card["effect"].get("scope") == "whole_activity" and
                        any(re.search(r"\b(?:part of|portion of|section of|partial(?:ly)?)\b", item["quote"], re.I)
                            for item in card["observation"]["evidence"])
                        for card in cards)
    if any(card["selection"]["mapping_state"] != "suggested" for card in cards):
        conversation.pending_question = "location"
    elif unclear_scope:
        conversation.pending_question = "scope"
    elif any(card["effect"].get("scope") == "subactivity" and
             not card["effect"].get("subactivity_key") for card in cards):
        conversation.pending_question = "scope"
    else:
        conversation.pending_question = None


def payload(db: Session, conversation: Conversation) -> dict:
    cards = (conversation.draft or {}).get("events", [])
    proposal_ids = []
    if conversation.job_id:
        proposals = db.scalars(select(Proposal).join(
            StoredObservation, Proposal.observation_id == StoredObservation.id
        ).where(StoredObservation.job_id == conversation.job_id)
            .order_by(Proposal.observation_id, Proposal.revision.desc())).all()
        latest = {}
        for proposal in proposals:
            latest.setdefault(proposal.observation_id, proposal)
        proposal_ids = [proposal.id for proposal in latest.values()]
    status = conversation.status
    if proposal_ids:
        states = [proposal.review_state for proposal in latest.values()]
        if states and all(state == "approved" for state in states):
            status = "accepted"
        elif any(state == "pending" for state in states):
            status = "pending_review"
        else:
            status = "reviewed"
    return {
        "id": conversation.id, "project_id": conversation.project_id,
        "schedule_version_id": conversation.schedule_version_id,
        "revision": conversation.revision, "status": status,
        "pending_question": conversation.pending_question,
        "question": QUESTIONS.get(conversation.pending_question),
        "events": cards,
        "turns": [{"ordinal": row.ordinal, "role": row.role, "text": row.text} for row in turns(db, conversation)],
        "job_id": conversation.job_id, "proposal_ids": proposal_ids,
    }


def confirm(db: Session, conversation: Conversation, user: User, indexes: list[int] | None):
    cards = (conversation.draft or {}).get("events", [])
    selected = list(range(len(cards))) if indexes is None else indexes
    if not cards or not selected or len(set(selected)) != len(selected) or any(i < 0 or i >= len(cards) for i in selected):
        raise HTTPException(422, detail={"code": "CONVERSATION_EVENTS_INVALID"})
    if conversation.pending_question:
        raise HTTPException(409, detail={"code": "CONVERSATION_CLARIFICATION_REQUIRED"})
    project = db.get(Project, conversation.project_id)
    if not project or project.active_schedule_version_id != conversation.schedule_version_id:
        raise HTTPException(409, detail={"code": "STALE_SCHEDULE"})
    for index in selected:
        card = cards[index]
        activity = db.get(Activity, UUID(card["activity_id"])) if card.get("activity_id") else None
        if not activity or activity.schedule_version_id != conversation.schedule_version_id or not activity.is_leaf:
            raise HTTPException(422, detail={"code": "ACTIVITY_OUTSIDE_PINNED_SCHEDULE"})
        if not card.get("effect"):
            raise HTTPException(422, detail={"code": "CONVERSATION_EVENT_INCOMPLETE"})
    source_turns = [row for row in turns(db, conversation) if row.role == "user"]
    source_text = "\n".join(row.text for row in source_turns)
    report = Report(project_id=conversation.project_id, report_date=date.fromisoformat(conversation.draft["report_date"]) if conversation.draft.get("report_date") else None,
                    report_date_evidence="Conversation user answer" if conversation.draft.get("report_date") else None,
                    source_label="Confirmed text conversation", source_revision=str(conversation.revision),
                    content_hash=hashlib.sha256((str(conversation.id) + source_text).encode()).hexdigest())
    db.add(report)
    db.flush()
    job = Job(project_id=conversation.project_id, report_id=report.id,
              schedule_version_id=conversation.schedule_version_id,
              state="ready_for_review", stage="persist", extracted_count=len(selected),
              proposal_count=len(selected), prompt_version="conversation-v1")
    db.add(job)
    db.flush()
    for row in source_turns:
        db.add(Fragment(id=row.id, report_id=report.id, ordinal=row.ordinal,
                        locator=f"Conversation turn {row.ordinal}", original_text=row.text,
                        normalised_text=row.text))
    db.flush()
    for index in selected:
        card = cards[index]
        observation = Observation.model_validate(card["observation"])
        evidence = [item.model_dump(mode="json") for item in observation.evidence]
        source_id = UUID(evidence[0]["fragment_id"])
        stored = StoredObservation(job_id=job.id, fragment_id=source_id, ordinal=index + 1,
                                   fields=card["observation"],
                                   field_evidence={"evidence": evidence, "selection": card["selection"]})
        from ..confidence.provenance import capture
        stored.field_evidence = {**stored.field_evidence, "provenance": capture(
            stored.fields, card["selection"], metadata={"prompt_version": job.prompt_version,
            "capture_mode": "confirmed_conversation", "model_version": job.model_version,
            "conversation_id": str(conversation.id), "confirmed_by": str(user.id),
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "selection_prompt_version": "conversation-exact-or-agent-schedule-v1",
            "model_calls": conversation.draft.get("model_calls", []),
            "extraction_batches": conversation.draft.get("extraction_metadata", []),
            "extraction_errors": conversation.draft.get("extraction_errors", [])})}
        db.add(stored)
        db.flush()
        decision = card["selection"]
        db.add(Proposal(observation_id=stored.id, project_id=conversation.project_id,
                        chosen_activity_id=UUID(card["activity_id"]),
                        candidates=decision["candidates"], mapping_state=decision["mapping_state"],
                        match_strength=decision["match_strength"], review_state="pending",
                        warnings=observation.warnings, proposed_effects=card["effect"]))
    conversation.job_id = job.id
    conversation.status = "pending_review"
    conversation.revision += 1
    db.flush()
