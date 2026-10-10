from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Time,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
    UniqueConstraint,
    Index,
    func,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    active_schedule_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("schedule_versions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    schedule_versions: Mapped[list["ScheduleVersion"]] = relationship(
        back_populates="project", foreign_keys="ScheduleVersion.project_id"
    )
    memberships: Mapped[list["ProjectMembership"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ScheduleVersion(Base):
    __tablename__ = "schedule_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version_number"),
        UniqueConstraint("project_id", "content_sha256"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    source_file_id: Mapped[UUID | None] = mapped_column(nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="staged")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    project: Mapped[Project] = relationship(
        back_populates="schedule_versions", foreign_keys=[project_id]
    )
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="schedule_version", cascade="all, delete-orphan"
    )


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (UniqueConstraint("schedule_version_id", "external_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    schedule_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="CASCADE")
    )
    external_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(500))
    wbs: Mapped[str] = mapped_column(String(500))
    discipline: Mapped[str] = mapped_column(String(40))
    work_type: Mapped[str] = mapped_column(String(60))
    area: Mapped[str | None] = mapped_column(String(200))
    asset_tags: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[str | None] = mapped_column(Text)
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=True)
    measurement_basis: Mapped[str] = mapped_column(String(30))
    planned_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(20))
    baseline_date: Mapped[date | None] = mapped_column(Date)
    baseline_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_finish: Mapped[date | None] = mapped_column(Date)
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_finish: Mapped[date | None] = mapped_column(Date)
    schedule_version: Mapped[ScheduleVersion] = relationship(back_populates="activities")
    state: Mapped["ActivityState | None"] = relationship(
        back_populates="activity", uselist=False, cascade="all, delete-orphan"
    )


class ActivityEmbedding(Base):
    """A locally generated activity vector for one immutable model revision."""

    __tablename__ = "activity_embeddings"
    activity_id: Mapped[UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    model_revision: Mapped[str] = mapped_column(String(255), primary_key=True)
    composed_text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ActivityState(Base):
    __tablename__ = "activity_states"
    activity_id: Mapped[UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    completed_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    physical_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    observed_status: Mapped[str] = mapped_column(String(30), default="not_started")
    actual_start: Mapped[date | None] = mapped_column(Date)
    actual_finish: Mapped[date | None] = mapped_column(Date)
    last_observed_date: Mapped[date | None] = mapped_column(Date)
    actual_start_time: Mapped[time | None] = mapped_column(Time)
    actual_finish_time: Mapped[time | None] = mapped_column(Time)
    actual_start_precision: Mapped[str | None] = mapped_column(String(10))
    actual_finish_precision: Mapped[str | None] = mapped_column(String(10))
    lifecycle_status: Mapped[str | None] = mapped_column(String(30))
    lifecycle_source_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("schedule_versions.id"))
    lifecycle_start_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("progress_events.id"))
    lifecycle_finish_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("progress_events.id"))
    activity: Mapped[Activity] = relationship(back_populates="state")


class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    memberships: Mapped[list["ProjectMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ProjectMembership(Base):
    """Explicit project scope for provisioned accounts."""

    __tablename__ = "project_memberships"
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    project: Mapped[Project] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped[User] = relationship()


class FileRecord(Base):
    __tablename__ = "files"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    source_kind: Mapped[str] = mapped_column(String(30))
    uploader_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("project_id", "content_hash"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("files.id"))
    report_date: Mapped[date | None] = mapped_column(Date)
    report_date_evidence: Mapped[str | None] = mapped_column(Text)
    source_label: Mapped[str | None] = mapped_column(String(255))
    source_revision: Mapped[str | None] = mapped_column(String(100))
    ingestion_metadata: Mapped[dict | None] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    parsing_warnings: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("uq_jobs_project_report_base", "project_id", "report_id", unique=True,
                            postgresql_where=text("parent_job_id IS NULL")),
                      UniqueConstraint("reanalysis_key", name="uq_jobs_reanalysis_key"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    parent_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    reanalysis_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reanalysis_actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reanalysis_reason: Mapped[str | None] = mapped_column(Text)
    config_snapshot: Mapped[dict | None] = mapped_column(JSON)
    schedule_version_id: Mapped[UUID] = mapped_column(ForeignKey("schedule_versions.id"))
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    stage: Mapped[str | None] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(200))
    config_version: Mapped[str | None] = mapped_column(String(200))
    extracted_count: Mapped[int] = mapped_column(Integer, default=0)
    proposal_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRun(Base):
    """Sanitized operational record for one bounded graph execution."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_agent_runs_job_id"),
        UniqueConstraint("thread_id", name="uq_agent_runs_thread_id"),
        CheckConstraint(
            "state IN ('created', 'running', 'ready_for_review', 'failed', 'stale', "
            "'cancelled')",
            name="ck_agent_runs_state",
        ),
        CheckConstraint(
            "execution_mode IN ('legacy', 'graph')", name="ck_agent_runs_execution_mode"
        ),
        CheckConstraint(
            "state IN ('failed', 'stale', 'cancelled') "
            "OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_agent_runs_error_state",
        ),
        Index("ix_agent_runs_job_id", "job_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    graph_version: Mapped[str] = mapped_column(String(100))
    state_schema_version: Mapped[str] = mapped_column(String(100))
    framework_version: Mapped[str] = mapped_column(String(100))
    thread_id: Mapped[str] = mapped_column(String(255))
    execution_mode: Mapped[str] = mapped_column(String(16), default="graph")
    state: Mapped[str] = mapped_column(String(32), default="created")
    current_node: Mapped[str | None] = mapped_column(String(64))
    counters: Mapped[dict] = mapped_column(JSON, default=dict)
    model_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    config_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(1000))

    job: Mapped[Job] = relationship()
    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentStep.ordinal",
    )


class AgentStep(Base):
    """One sanitized node-attempt trace belonging to an agent run."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_agent_steps_run_ordinal"),
        UniqueConstraint("run_id", "node", "attempt", name="uq_agent_steps_run_node_attempt"),
        CheckConstraint("ordinal >= 1", name="ck_agent_steps_ordinal_positive"),
        CheckConstraint("attempt >= 1", name="ck_agent_steps_attempt_positive"),
        CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')",
            name="ck_agent_steps_state",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_steps_duration_nonnegative"
        ),
        CheckConstraint(
            "state <> 'running' OR (finished_at IS NULL AND duration_ms IS NULL)",
            name="ck_agent_steps_running_unfinished",
        ),
        CheckConstraint(
            "state = 'failed' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_agent_steps_error_state",
        ),
        Index("ix_agent_steps_run_ordinal", "run_id", "ordinal"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="running")
    input_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    sanitized_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(1000))

    run: Mapped[AgentRun] = relationship(back_populates="steps")
    tool_calls: Mapped[list["AgentToolCall"]] = relationship(
        back_populates="step",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AgentToolCall(Base):
    """Sanitized trace for a typed tool invoked within one node attempt."""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        UniqueConstraint("step_id", "tool_name", "attempt", name="uq_agent_tool_calls_attempt"),
        CheckConstraint("attempt >= 1", name="ck_agent_tool_calls_attempt_positive"),
        CheckConstraint(
            "state IN ('running', 'succeeded', 'failed', 'skipped')",
            name="ck_agent_tool_calls_state",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_tool_calls_duration_nonnegative",
        ),
        CheckConstraint(
            "state <> 'running' OR (finished_at IS NULL AND duration_ms IS NULL)",
            name="ck_agent_tool_calls_running_unfinished",
        ),
        CheckConstraint(
            "state = 'failed' OR (error_code IS NULL AND error_message IS NULL)",
            name="ck_agent_tool_calls_error_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    step_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_steps.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="running")
    sanitized_input_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    sanitized_output_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(1000))

    step: Mapped[AgentStep] = relationship(back_populates="tool_calls")


class Fragment(Base):
    __tablename__ = "fragments"
    __table_args__ = (UniqueConstraint("report_id", "ordinal"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str] = mapped_column(String(255))
    original_text: Mapped[str] = mapped_column(Text)
    normalised_text: Mapped[str] = mapped_column(Text)
    normalisation_version: Mapped[str] = mapped_column(String(30), default="v1")
    ocr_status: Mapped[str] = mapped_column(String(30), default="NOT_REQUIRED")


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("job_id", "fragment_id", "ordinal"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    fragment_id: Mapped[UUID | None] = mapped_column(ForeignKey("fragments.id"), nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    field_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Proposal(Base):
    __tablename__ = "proposals"
    __table_args__ = (UniqueConstraint("observation_id", "revision"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    observation_id: Mapped[UUID] = mapped_column(
        ForeignKey("observations.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    chosen_activity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("activities.id"), nullable=True
    )
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    mapping_state: Mapped[str] = mapped_column(String(24), default="suggested")
    match_strength: Mapped[str] = mapped_column(String(24), default="review")
    review_state: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    proposed_effects: Mapped[dict] = mapped_column(JSON, default=dict)
    base_activity_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProgressEvent(Base):
    __tablename__ = "progress_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    activity_id: Mapped[UUID] = mapped_column(
        ForeignKey("activities.id", ondelete="CASCADE"), index=True
    )
    observation_id: Mapped[UUID] = mapped_column(ForeignKey("observations.id"), index=True)
    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"))
    proposal_revision: Mapped[int] = mapped_column(Integer)
    approved_values: Mapped[dict] = mapped_column(JSON, default=dict)
    effect_kind: Mapped[str] = mapped_column(String(32), default="progress")
    effective_date: Mapped[date | None] = mapped_column(Date)
    reviewer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    supersedes_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("progress_events.id"), nullable=True
    )
    source_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    lifecycle_scope: Mapped[str | None] = mapped_column(String(30))
    endpoint_time: Mapped[time | None] = mapped_column(Time)
    endpoint_precision: Mapped[str | None] = mapped_column(String(10))
    endpoint_timezone: Mapped[str | None] = mapped_column(String(64))
    endpoint_basis: Mapped[str | None] = mapped_column(String(40))
    endpoint_raw_expression: Mapped[str | None] = mapped_column(String(500))
    endpoint_instant: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    endpoint_evidence: Mapped[list | None] = mapped_column(JSON)
    source_schedule_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("schedule_versions.id"))
    __table_args__ = (
        Index(
            "uq_progress_events_active_observation",
            "observation_id",
            unique=True,
            postgresql_where=(supersedes_event_id.is_(None)),
        ),
    )


class ScheduleImport(Base):
    __tablename__ = "schedule_imports"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[UUID] = mapped_column(ForeignKey("files.id"), unique=True)
    source_format: Mapped[str] = mapped_column(String(20))
    parser_version: Mapped[str] = mapped_column(String(100))
    selected_source_project_id: Mapped[str | None] = mapped_column(String(255))
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(24), default="needs_mapping")
    error_code: Mapped[str | None] = mapped_column(String(100))
    creator_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_mapping: Mapped[dict | None] = mapped_column(JSON)
    mapped_content_hash: Mapped[str | None] = mapped_column(String(64))
    staged_schedule_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("schedule_versions.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduleSourceMetadata(Base):
    __tablename__ = "schedule_source_metadata"
    schedule_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("schedule_versions.id", ondelete="CASCADE"), primary_key=True
    )
    schedule_import_id: Mapped[UUID] = mapped_column(ForeignKey("schedule_imports.id"), unique=True)
    source_project_id: Mapped[str] = mapped_column(String(255))
    source_file_hash: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(100))
    reviewed_mapping: Mapped[dict] = mapped_column(JSON)
    mapping_hash: Mapped[str] = mapped_column(String(64))
    task_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    wbs: Mapped[list] = mapped_column(JSON, default=list)
    relationships: Mapped[list] = mapped_column(JSON, default=list)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[UUID] = mapped_column()
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("actor_id", "endpoint", "key"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    endpoint: Mapped[str] = mapped_column(String(120))
    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    result_reference: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    creator_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    schedule_version_id: Mapped[UUID] = mapped_column(ForeignKey("schedule_versions.id"))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    draft: Mapped[dict] = mapped_column(JSON, default=dict)
    pending_question: Mapped[str | None] = mapped_column(String(30))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (UniqueConstraint("conversation_id", "ordinal"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IntegrationOutbox(Base):
    __tablename__ = "integration_outbox"
    __table_args__ = (UniqueConstraint("activity_id", "state_revision"),
                      Index("ix_outbox_pending", "status", "next_attempt_at"))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    activity_id: Mapped[UUID] = mapped_column(ForeignKey("activities.id", ondelete="CASCADE"))
    state_revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    receipt: Mapped[dict | None] = mapped_column(JSON)


class ReportMapping(Base):
    __tablename__ = "report_mappings"
    __table_args__ = (UniqueConstraint("project_id", "template", "header_signature", "revision"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    template: Mapped[str] = mapped_column(String(100))
    header_signature: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    spec: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
