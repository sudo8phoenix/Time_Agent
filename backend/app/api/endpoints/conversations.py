"""Project-scoped text conversation endpoints."""
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...conversation.service import QUESTIONS, add_turn, analyze, confirm, payload
from ...agent.schedule_decision import AgentDecisionError
from ...llm.extract import ExtractionError
from ...llm.ollama import OllamaError
from ...db.models import Activity, Conversation, Project, User
from ...db.session import get_session
from ...schemas.conversation import (ConversationDecision, ConversationEdit,
                                     ConversationMessage, ConversationView)
from ...schemas.observation import Observation
from ...progress.effects import build_effects
from ..dependencies import current_user, project_access, require_csrf

router = APIRouter(prefix="/projects/{project_id}/conversations", tags=["conversations"])


def _conversation(db: Session, project: Project, conversation_id: UUID, user: User,
                  *, lock: bool = False) -> Conversation:
    query = select(Conversation).where(Conversation.id == conversation_id,
                                       Conversation.project_id == project.id,
                                       Conversation.creator_id == user.id)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "Conversation not found")
    return row


def _revision(row: Conversation, expected: int):
    if row.revision != expected:
        raise HTTPException(409, detail={"code": "STALE_CONVERSATION", "revision": row.revision})
    if row.status != "draft":
        raise HTTPException(409, detail={"code": "CONVERSATION_ALREADY_SUBMITTED"})


@router.get("")
def list_conversations(project: Project = Depends(project_access),
                       user: User = Depends(current_user), db: Session = Depends(get_session)):
    rows = db.scalars(select(Conversation).where(Conversation.project_id == project.id,
                                                 Conversation.creator_id == user.id)
                      .order_by(Conversation.created_at.desc()).limit(30)).all()
    return {"items": [payload(db, row) for row in rows]}


@router.post("", response_model=ConversationView, status_code=201)
def create_conversation(project: Project = Depends(project_access),
                        user: User = Depends(require_csrf), db: Session = Depends(get_session)):
    if not project.active_schedule_version_id:
        raise HTTPException(409, detail={"code": "PROJECT_HAS_NO_ACTIVE_SCHEDULE"})
    row = Conversation(project_id=project.id, creator_id=user.id,
                       schedule_version_id=project.active_schedule_version_id,
                       revision=0, status="draft", draft={})
    db.add(row)
    db.flush()
    return payload(db, row)


@router.get("/{conversation_id}", response_model=ConversationView)
def get_conversation(conversation_id: UUID, project: Project = Depends(project_access),
                     user: User = Depends(current_user), db: Session = Depends(get_session)):
    return payload(db, _conversation(db, project, conversation_id, user))


@router.post("/{conversation_id}/messages", response_model=ConversationView)
def message(conversation_id: UUID, body: ConversationMessage,
            project: Project = Depends(project_access), user: User = Depends(require_csrf),
            db: Session = Depends(get_session)):
    row = _conversation(db, project, conversation_id, user, lock=True)
    _revision(row, body.expected_revision)
    if project.active_schedule_version_id != row.schedule_version_id:
        raise HTTPException(409, detail={"code": "STALE_SCHEDULE"})
    add_turn(db, row, "user", body.text, user.id)
    draft = dict(row.draft or {})
    if body.report_date:
        draft["report_date"] = body.report_date.isoformat()
        row.draft = draft
    try:
        analyze(db, row)
    except (OllamaError, ExtractionError, AgentDecisionError, ValueError):
        # Keep the turn so an outage does not erase the user's text. Retry analysis later.
        row.pending_question = "retry"
        add_turn(db, row, "assistant", QUESTIONS["retry"])
        row.status = "draft"
        row.revision += 1
        db.flush()
        return payload(db, row)
    if row.pending_question:
        add_turn(db, row, "assistant", QUESTIONS[row.pending_question])
    row.revision += 1
    db.flush()
    return payload(db, row)


@router.post("/{conversation_id}/retry", response_model=ConversationView)
def retry(conversation_id: UUID, body: ConversationDecision,
          project: Project = Depends(project_access), user: User = Depends(require_csrf),
          db: Session = Depends(get_session)):
    row = _conversation(db, project, conversation_id, user, lock=True)
    _revision(row, body.expected_revision)
    if project.active_schedule_version_id != row.schedule_version_id:
        raise HTTPException(409, detail={"code": "STALE_SCHEDULE"})
    try:
        analyze(db, row)
    except (OllamaError, ExtractionError, AgentDecisionError, ValueError):
        row.pending_question = "retry"
    if row.pending_question:
        add_turn(db, row, "assistant", QUESTIONS[row.pending_question])
    row.revision += 1
    db.flush()
    return payload(db, row)


@router.post("/{conversation_id}/edit", response_model=ConversationView)
def edit(conversation_id: UUID, body: ConversationEdit,
         project: Project = Depends(project_access), user: User = Depends(require_csrf),
         db: Session = Depends(get_session)):
    row = _conversation(db, project, conversation_id, user, lock=True)
    _revision(row, body.expected_revision)
    draft = dict(row.draft or {})
    cards = list(draft.get("events", []))
    if body.event_index >= len(cards):
        raise HTTPException(422, detail={"code": "CONVERSATION_EVENT_INVALID"})
    if not any((body.activity_id, body.local_date, body.local_time, body.date_only, body.scope, body.subactivity_key)):
        raise HTTPException(422, detail={"code": "CONVERSATION_EDIT_EMPTY"})
    if body.date_only and body.local_time:
        raise HTTPException(422, detail={"code": "TIME_CONFLICT"})
    card = dict(cards[body.event_index])
    changes = []
    if body.activity_id is not None:
        activity = db.get(Activity, body.activity_id)
        if not activity or activity.schedule_version_id != row.schedule_version_id or not activity.is_leaf:
            raise HTTPException(422, detail={"code": "ACTIVITY_OUTSIDE_PINNED_SCHEDULE"})
        if str(activity.id) not in {str(candidate.get("candidate_id")) for candidate in card["selection"].get("candidates", [])}:
            raise HTTPException(422, detail={"code": "ACTIVITY_OUTSIDE_CANDIDATES"})
        card["activity_id"] = str(activity.id)
        card["selection"] = {**card["selection"], "mapping_state": "suggested", "match_strength": "review"}
        changes.append(f"scheduled activity {activity.external_id}")
    if body.local_date or body.local_time or body.date_only or body.scope or body.subactivity_key:
        observation = dict(card["observation"])
        effects = list(observation.get("lifecycle_effects") or [])
        if len(effects) != 1:
            raise HTTPException(422, detail={"code": "CONVERSATION_EVENT_INCOMPLETE"})
        effect = dict(effects[0])
        endpoint = dict(effect["endpoint"])
        fields = []
        if body.local_date:
            endpoint["local_date"] = body.local_date.isoformat()
            endpoint["basis"] = "supervisor_correction"
            endpoint["normalized_instant"] = None
            observation["work_date"] = body.local_date.isoformat()
            observation["date_basis"] = "explicit"
            if observation.get("actual_start"):
                observation["actual_start"] = body.local_date.isoformat()
            if observation.get("actual_finish"):
                observation["actual_finish"] = body.local_date.isoformat()
            fields.append("endpoint")
            changes.append(f"date {body.local_date.isoformat()}")
        if body.local_time:
            if body.local_time.tzinfo or body.local_time.microsecond:
                raise HTTPException(422, detail={"code": "INVALID_LOCAL_TIME"})
            endpoint["local_time"] = body.local_time.isoformat()
            endpoint["precision"] = "second" if body.local_time.second else "minute"
            endpoint["basis"] = "supervisor_correction"
            endpoint["normalized_instant"] = None
            fields.append("endpoint")
            changes.append(f"time {body.local_time.isoformat(timespec='seconds')}")
        if body.date_only:
            endpoint["local_time"] = None
            endpoint["precision"] = "date"
            endpoint["basis"] = "supervisor_correction"
            endpoint["normalized_instant"] = None
            fields.append("endpoint")
            changes.append("date only (no known time)")
        if body.scope:
            effect["scope"] = body.scope
            card["scope_confirmed"] = True
            fields.append("scope")
            changes.append(f"scope {body.scope}")
        if body.subactivity_key:
            if effect["scope"] != "subactivity":
                raise HTTPException(422, detail={"code": "SUBACTIVITY_SCOPE_REQUIRED"})
            effect["subactivity_key"] = body.subactivity_key.strip()
            fields.append("subactivity_key")
            changes.append(f"part {body.subactivity_key.strip()}")
        if effect["scope"] == "subactivity" and not effect.get("subactivity_key"):
            raise HTTPException(422, detail={"code": "SUBACTIVITY_KEY_REQUIRED"})
        if effect["scope"] == "whole_activity":
            effect["subactivity_key"] = None
        quote = f"Correction to event {body.event_index + 1}: " + ", ".join(changes)
        correction = add_turn(db, row, "user", quote, user.id)
        evidence = {"fields": sorted(set(fields)), "fragment_id": str(correction.id), "quote": quote}
        endpoint["raw_expression"] = quote
        effect["endpoint"] = endpoint
        effect["evidence"] = [*effect["evidence"], evidence]
        observation["lifecycle_effects"] = [effect]
        observation["evidence"] = [*observation["evidence"], evidence]
        validated = Observation.model_validate(observation)
        card["observation"] = validated.model_dump(mode="json")
        card["effect"] = build_effects(validated)
    cards[body.event_index] = card
    draft["events"] = cards
    row.draft = draft
    row.pending_question = ("location" if any(not item.get("activity_id") for item in cards)
                            else "scope" if any((item["effect"].get("scope") == "subactivity" and not item["effect"].get("subactivity_key")) or
                                                (item["observation"]["event_type"] == "actual_finish" and
                                                 item["effect"].get("scope") == "whole_activity" and
                                                 not item.get("scope_confirmed") and
                                                 any(re.search(r"\b(?:part of|portion of|section of|partial(?:ly)?)\b", evidence["quote"], re.I)
                                                     for evidence in item["observation"]["evidence"])) for item in cards)
                            else None)
    row.revision += 1
    db.flush()
    return payload(db, row)


@router.post("/{conversation_id}/confirm", response_model=ConversationView)
def confirm_conversation(conversation_id: UUID, body: ConversationDecision,
                         project: Project = Depends(project_access), user: User = Depends(require_csrf),
                         db: Session = Depends(get_session)):
    row = _conversation(db, project, conversation_id, user, lock=True)
    _revision(row, body.expected_revision)
    confirm(db, row, user, body.event_indexes)
    return payload(db, row)


@router.post("/{conversation_id}/cancel", response_model=ConversationView)
def cancel(conversation_id: UUID, body: ConversationDecision,
           project: Project = Depends(project_access), user: User = Depends(require_csrf),
           db: Session = Depends(get_session)):
    row = _conversation(db, project, conversation_id, user, lock=True)
    _revision(row, body.expected_revision)
    row.status = "cancelled"
    row.revision += 1
    db.flush()
    return payload(db, row)
