"""Two-turn text start becomes a review proposal without changing activity state."""
import re
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.conversation.service import add_turn, analyze, confirm, payload
from app.db.base import Base
from app.db.models import (Activity, ActivityState, Conversation, Job, ProgressEvent,
                           Project, ProjectMembership, Proposal, ScheduleVersion, User)
from app.api.endpoints.review import ApprovalRequest, approve
from app.api.endpoints.conversations import edit
from app.schemas.conversation import ConversationEdit
from datetime import time


def test_missing_date_then_confirmed_start_stays_pending_review():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(username="supervisor", password_hash="unused", role="viewer")
        reviewer = User(username="reviewer", password_hash="unused", role="reviewer")
        project = Project(name="Developer fixture", timezone="Asia/Kolkata")
        schedule = ScheduleVersion(project=project, version_number=1, content_sha256=uuid4().hex, state="active")
        activity = Activity(schedule_version=schedule, external_id="EX-F01", name="Excavation F-01",
                            wbs="1", discipline="civil", work_type="excavation", area="F-01",
                            asset_tags="F-01", is_leaf=True, measurement_basis="unsupported",
                            planned_quantity=None, unit=None)
        db.add_all([user, reviewer, project, schedule, activity])
        db.flush()
        db.add(ProjectMembership(project_id=project.id, user_id=reviewer.id))
        project.active_schedule_version_id = schedule.id
        db.add(ActivityState(activity=activity, revision=0, completed_quantity=Decimal(0)))
        conversation = Conversation(project_id=project.id, creator_id=user.id,
                                    schedule_version_id=schedule.id, revision=0, draft={})
        db.add(conversation)
        db.flush()
        add_turn(db, conversation, "user", "Started excavation at F-01 at 08:30", user.id)
        analyze(db, conversation, model_call=lambda **_: (_ for _ in ()).throw(AssertionError("date must be asked first")))
        assert conversation.pending_question == "date"
        assert conversation.draft.get("events") is None
        add_turn(db, conversation, "user", "2026-10-09", user.id)
        observed = []

        def model_call(**kwargs):
            system = kwargs["system"]
            if "Extract" in system or "atomic" in system.lower():
                fragment_id = re.search(r"\[([a-f0-9-]{36}) \|", kwargs["user"]).group(1)
                observed.append(fragment_id)
                quote = "Started excavation at F-01 at 08:30"
                return {"observations": [{
                    "discipline": "civil", "work_type": "excavation", "event_type": "actual_start",
                    "observed_status": "in_progress", "area": "F-01", "asset_tags": ["F-01"],
                    "explicit_activity_id": None, "work_date": "2026-10-09", "date_basis": "report_context",
                    "quantity": None, "quantity_kind": "none", "unit": None, "raw_unit": None,
                    "reported_percent": None, "actual_start": None, "actual_finish": None,
                    "blocker": None, "summary": quote,
                    "evidence": [{"fields": ["event_type"], "fragment_id": fragment_id, "quote": quote}],
                    "warnings": [], "lifecycle_effects": [{"kind": "actual_start", "scope": "whole_activity",
                        "endpoint": {"local_date": "2026-10-09", "local_time": "08:30:00", "precision": "minute",
                                     "basis": "report_context", "raw_expression": "at 08:30"},
                        "evidence": [{"fields": ["endpoint"], "fragment_id": fragment_id, "quote": quote}]}],
                }]}
            raise AssertionError("exact quoted area should skip model schedule decisions")

        analyze(db, conversation, model_call=model_call)
        assert conversation.pending_question is None
        assert len(payload(db, conversation)["events"]) == 1
        assert payload(db, conversation)["events"][0]["selection"]["reason_codes"] == ["EXACT_AREA_WORK_TYPE"]
        corrected = edit(conversation.id, ConversationEdit(expected_revision=0, event_index=0,
                         local_date=date(2026, 10, 9), local_time=time(8, 35), scope="whole_activity"),
                         project, user, db)
        assert corrected["events"][0]["effect"]["endpoint"]["local_time"] == "08:35:00"
        assert corrected["events"][0]["observation"]["lifecycle_effects"][0]["evidence"][-1]["quote"].startswith("Correction to event 1")
        date_only = edit(conversation.id, ConversationEdit(expected_revision=1, event_index=0,
                         date_only=True, scope="subactivity", subactivity_key="north trench"),
                         project, user, db)
        assert date_only["events"][0]["effect"]["endpoint"]["precision"] == "date"
        assert date_only["events"][0]["effect"]["scope"] == "subactivity"
        corrected = edit(conversation.id, ConversationEdit(expected_revision=2, event_index=0,
                         local_time=time(8, 35), scope="whole_activity"), project, user, db)
        assert corrected["events"][0]["effect"]["subactivity_key"] is None
        assert corrected["events"][0]["effect"]["endpoint"]["precision"] == "minute"
        confirm(db, conversation, user, None)
        db.flush()
        assert conversation.status == "pending_review"
        assert db.get(Job, conversation.job_id).state == "ready_for_review"
        proposal = db.scalar(select(Proposal).where(Proposal.project_id == project.id))
        assert proposal.review_state == "pending"
        assert proposal.proposed_effects["endpoint"]["precision"] == "minute"
        assert proposal.proposed_effects["endpoint"]["local_time"] == "08:35:00"
        assert db.get(ActivityState, activity.id).actual_start is None
        assert db.scalar(select(ProgressEvent)) is None
        approve(proposal.id, ApprovalRequest(expected_proposal_revision=1,
                expected_activity_revision=0, idempotency_key="conversation-start"), reviewer, db)
        db.flush()
        assert db.get(ActivityState, activity.id).actual_start == date(2026, 10, 9)
        assert payload(db, conversation)["status"] == "accepted"
