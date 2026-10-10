"""Strict, invocation-local adapters for the existing report services."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator
from sqlalchemy import select

from ..db.models import Activity, Fragment, Job, Project, Report, ScheduleVersion
from ..llm.extract import ExtractionError, FragmentInput, deduplicate_results, extract_fragments
from .schedule_decision import AgentDecisionError, select_activity as default_selection_service, shortlist_activities as default_retrieval_service
from ..schemas.common import StrictModel
from ..schemas.matching import Candidate, Proposal
from ..schemas.observation import Observation
from .context import AgentRuntimeContext
from .state import AgentState, AgentWarning, MAX_CANDIDATES, MAX_OBSERVATIONS, ModelMetadata, ValidationErrorRecord, observation_keys


class AgentToolError(RuntimeError):
    """Stable, safe tool failure; never carries service exception text."""

    def __init__(self, code: str, safe_message: str, *, stage: str | None = None, retryable: bool = False):
        self.code = code
        self.safe_message = safe_message
        self._stage = stage
        self._retryable = retryable
        super().__init__(safe_message)

    @property
    def stage(self) -> str | None:
        return self._stage

    @property
    def retryable(self) -> bool:
        return self._retryable


class _ToolModel(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReportMetadata(_ToolModel):
    report_date: date | None
    report_date_trusted: StrictBool


class JobContextResult(_ToolModel):
    job_id: StrictStr
    project_id: StrictStr
    report_id: StrictStr
    schedule_version_id: StrictStr
    fragment_ids: list[StrictStr]
    activity_ids: list[StrictStr]

    @field_validator("job_id", "project_id", "report_id", "schedule_version_id")
    @classmethod
    def identity_is_canonical(cls, value: str) -> str:
        return _canonical(value)

    @field_validator("fragment_ids", "activity_ids")
    @classmethod
    def ids_are_canonical_and_unique(cls, values: list[str]) -> list[str]:
        for value in values:
            _canonical(value)
        if len(values) != len(set(values)):
            raise ValueError("IDs must be ordered and unique")
        return values


class ExtractionToolResult(_ToolModel):
    observations: list[Observation] = Field(max_length=MAX_OBSERVATIONS)
    model_metadata: ModelMetadata
    errors: list[ValidationErrorRecord]
    warnings: list[AgentWarning]


class RetrievalToolResult(_ToolModel):
    candidates: list[Candidate] = Field(max_length=MAX_CANDIDATES)
    warnings: list[AgentWarning]


class ValidationToolResult(_ToolModel):
    valid: StrictBool
    errors: list[ValidationErrorRecord]
    warnings: list[AgentWarning]


class PersistenceResult(_ToolModel):
    extracted_count: StrictInt = Field(ge=0)
    proposal_count: StrictInt = Field(ge=0)
    already_persisted: StrictBool


def _canonical(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AgentToolError("AGENT_TOOL_FAILED", "Invalid scoped identifier.") from exc
    if str(parsed) != value:
        raise AgentToolError("AGENT_TOOL_FAILED", "Invalid scoped identifier.")
    return value


def _safe_call(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except AgentToolError:
        raise
    except Exception as exc:
        # Keep the one stable ownership failure recognizable, without forwarding
        # arbitrary exception strings from a service.
        if str(exc) == "JOB_LEASE_LOST":
            raise AgentToolError("JOB_LEASE_LOST", "The job lease is no longer valid.") from None
        raise AgentToolError("AGENT_TOOL_FAILED", "The requested agent operation failed safely.") from None


class AgentTools:
    """One private server scope and bounded call budgets for one graph run."""

    def __init__(
        self,
        context: AgentRuntimeContext,
        *,
        extraction_service: Callable[..., Any] = extract_fragments,
        retrieval_service: Callable[..., Any] = default_retrieval_service,
        selection_service: Callable[..., Any] = default_selection_service,
        persistence_callback: Callable[..., Any],
    ) -> None:
        self._context = context
        self._extract = extraction_service
        self._retrieve = retrieval_service
        self._select = selection_service
        self._persist = persistence_callback
        self._scope: JobContextResult | None = None
        self._fragments: dict[str, Any] = {}
        self._activities: dict[str, Any] = {}
        self._report: Any = None
        self._extraction_calls = 0
        self._selection_calls: dict[str, int] = {}
        self._returned_candidates: dict[str, dict[str, Candidate]] = {}
        self._observations: dict[str, Observation] = {}
        self._model_metadata = ModelMetadata()
        self._persistence_called = False
        self._persistence_result: PersistenceResult | None = None
        self._persistence_error: AgentToolError | None = None

    def _require_scope(self) -> JobContextResult:
        if self._scope is None:
            raise AgentToolError("AGENT_TOOL_FAILED", "Job context has not been loaded.")
        return self._scope

    def rehydrate_provenance(self, state: AgentState) -> None:
        """Rebuild invocation-only provenance from a validated checkpoint.

        Checkpoints intentionally contain only strict JSON state.  Database
        rows are reloaded under the current lease, then the observation and
        candidate membership maps used by the typed tools are reconstructed
        from that accepted state.  No checkpoint value can widen the current
        job/report/schedule scope.
        """
        try:
            restored = state if isinstance(state, AgentState) else AgentState.model_validate(state)
        except ValidationError:
            raise AgentToolError(
                "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved graph state is incompatible."
            ) from None

        scope = self.load_job_context(restored.job_id)
        if (
            restored.project_id != scope.project_id
            or restored.report_id != scope.report_id
            or restored.schedule_version_id != scope.schedule_version_id
            or (restored.fragment_ids and restored.fragment_ids != scope.fragment_ids)
            or (restored.activity_ids and restored.activity_ids != scope.activity_ids)
        ):
            raise AgentToolError(
                "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved graph scope is incompatible."
            )

        keys = observation_keys(len(restored.observation_drafts))
        if restored.observation_drafts and restored.counters.extraction_calls == 0:
            raise AgentToolError(
                "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved extraction counters are incompatible."
            )
        if restored.candidate_sets and not restored.observation_drafts:
            raise AgentToolError(
                "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved candidate provenance is incompatible."
            )
        if restored.selection_drafts and (
            set(restored.selection_drafts) != set(restored.candidate_sets)
            or restored.counters.selection_calls < len(keys)
        ):
            raise AgentToolError(
                "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved selection counters are incompatible."
            )
        for observation in restored.observation_drafts:
            if not observation.evidence:
                raise AgentToolError(
                    "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved evidence provenance is incompatible."
                )
            for evidence in observation.evidence:
                fragment = self._fragments.get(evidence.fragment_id)
                if fragment is None or evidence.quote not in fragment.text:
                    raise AgentToolError(
                        "AGENT_CHECKPOINT_INCOMPATIBLE",
                        "The saved evidence provenance is incompatible.",
                    )
            if (
                observation.date_basis.value == "relative_resolved"
                and not self._report.report_date_trusted
            ):
                raise AgentToolError(
                    "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved date provenance is incompatible."
                )
        self._observations = {
            key: observation
            for key, observation in zip(keys, restored.observation_drafts, strict=True)
        }
        returned: dict[str, dict[str, Candidate]] = {}
        for key, candidates in restored.candidate_sets.items():
            by_id: dict[str, Candidate] = {}
            for candidate in candidates:
                candidate_id = str(candidate.candidate_id)
                activity = self._activities.get(candidate_id)
                if (
                    activity is None
                    or str(activity.schedule_version_id) != scope.schedule_version_id
                    or not activity.is_leaf
                    or candidate_id in by_id
                    or candidate.external_id != activity.external_id
                    or candidate.activity_name != activity.name
                    or candidate.area != activity.area
                    or candidate.work_type.value != activity.work_type
                    or candidate.is_leaf != activity.is_leaf
                ):
                    raise AgentToolError(
                        "AGENT_CHECKPOINT_INCOMPATIBLE",
                        "The saved candidate provenance is incompatible.",
                    )
                by_id[candidate_id] = candidate
            returned[key] = by_id
        self._returned_candidates = returned

        self._extraction_calls = restored.counters.extraction_calls
        self._model_metadata = restored.model_metadata.model_copy(deep=True)
        self._selection_calls = {}
        remaining = restored.counters.selection_calls
        # Selection increments the public counter in stable observation order.
        # Reconstruct at most the two frozen passes without treating empty
        # candidate abstentions as model calls.
        for _pass in range(2):
            for key in keys:
                if remaining <= 0:
                    break
                remaining -= 1
                if self._returned_candidates.get(key):
                    self._selection_calls[key] = self._selection_calls.get(key, 0) + 1
        if remaining:
            raise AgentToolError(
                "AGENT_CHECKPOINT_INCOMPATIBLE", "The saved model-call counters are incompatible."
            )

        if restored.selection_drafts:
            validation = self.validate_proposal_drafts(restored)
            if not validation.valid:
                raise AgentToolError(
                    "AGENT_CHECKPOINT_INCOMPATIBLE",
                    "The saved proposal provenance is incompatible.",
                )

    @property
    def report_metadata(self) -> ReportMetadata:
        """Return fresh, strict metadata derived only from the loaded report row."""
        self._require_scope()
        if self._report is None:
            raise AgentToolError("AGENT_TOOL_FAILED", "Job context has not been loaded.")
        return ReportMetadata(
            report_date=self._report.report_date,
            report_date_trusted=self._report.report_date_trusted,
        )

    @property
    def model_metadata(self) -> ModelMetadata:
        """Return only sanitized model and prompt revision metadata."""
        return self._model_metadata.model_copy(deep=True)

    def _check_lease_schedule(self, db: Any, job: Any, project: Any) -> None:
        now = self._context.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        expires = job.lease_expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if (job.state != "running" or job.lease_token != self._context.lease_token
                or expires is None or expires <= now):
            raise AgentToolError("JOB_LEASE_LOST", "The job lease is no longer valid.")
        if project.active_schedule_version_id != job.schedule_version_id:
            raise AgentToolError("SCHEDULE_VERSION_STALE", "The project schedule changed during this run.")

    def load_job_context(self, job_id: str) -> JobContextResult:
        job_key = _canonical(job_id)
        try:
            manager = self._context.session_factory()
            with manager as db:
                job = db.get(Job, UUID(job_key))
                if job is None:
                    raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be loaded.")
                project = db.get(Project, job.project_id)
                report = db.get(Report, job.report_id)
                schedule = db.get(ScheduleVersion, job.schedule_version_id)
                if project is None or report is None or schedule is None:
                    raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be loaded.")
                self._check_lease_schedule(db, job, project)
                if (str(job.id) != job_key or report.project_id != job.project_id
                        or schedule.project_id != job.project_id):
                    raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be loaded.")
                fragment_rows = list(db.scalars(select(Fragment).where(
                    Fragment.report_id == job.report_id
                ).order_by(Fragment.ordinal, Fragment.id)))
                activity_rows = list(db.scalars(select(Activity).where(
                    Activity.schedule_version_id == job.schedule_version_id,
                    Activity.is_leaf.is_(True),
                ).order_by(Activity.id)))
                if any(row.report_id != job.report_id for row in fragment_rows) or any(
                    row.schedule_version_id != job.schedule_version_id or not row.is_leaf for row in activity_rows
                ):
                    raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be loaded.")
                result = JobContextResult(
                    job_id=str(job.id), project_id=str(job.project_id), report_id=str(job.report_id),
                    schedule_version_id=str(job.schedule_version_id),
                    fragment_ids=[str(row.id) for row in fragment_rows],
                    activity_ids=[str(row.id) for row in activity_rows],
                )
                # Detach plain values so no session or lazy database state leaks
                # into the invocation's retained scope.
                self._fragments = {str(row.id): SimpleNamespace(
                    id=row.id, locator=row.locator,
                    text=row.normalised_text or row.original_text, ordinal=row.ordinal,
                    report_id=row.report_id,
                ) for row in fragment_rows}
                from .project_aliases import with_project_aliases
                activity_rows = with_project_aliases(db, job.project_id, activity_rows)
                self._activities = {str(row.id): SimpleNamespace(**{
                    name: getattr(row, name) for name in (
                        "id", "schedule_version_id", "external_id", "name", "wbs", "discipline",
                        "work_type", "area", "asset_tags", "aliases", "is_leaf",
                    )
                }) for row in activity_rows}
                self._report = SimpleNamespace(
                    report_date=report.report_date,
                    report_date_trusted=bool(report.report_date and report.report_date_evidence),
                )
                self._scope = result
                return result
        except AgentToolError:
            raise
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be loaded.") from None

    def _validate_identity(self, value: str, expected: str) -> None:
        if _canonical(value) != expected:
            raise AgentToolError("AGENT_TOOL_FAILED", "Supplied data is outside the loaded job scope.")

    def extract_observations(self, fragment_ids: list[str], report_metadata: ReportMetadata) -> ExtractionToolResult:
        scope = self._require_scope()
        if self._extraction_calls >= 2:
            raise AgentToolError("AGENT_REPAIR_LIMIT", "Extraction call budget exhausted.")
        try:
            metadata = ReportMetadata.model_validate(report_metadata)
            ids = [_canonical(value) for value in fragment_ids]
        except (ValidationError, AgentToolError):
            raise AgentToolError("AGENT_TOOL_FAILED", "Invalid extraction input.") from None
        if ids != scope.fragment_ids:
            raise AgentToolError("AGENT_TOOL_FAILED", "Fragments are outside the loaded report scope.")
        expected_date = self._report.report_date if self._report else None
        expected_trust = bool(self._report and self._report.report_date_trusted)
        if metadata.report_date != expected_date or metadata.report_date_trusted != expected_trust:
            raise AgentToolError("AGENT_TOOL_FAILED", "Report metadata does not match the loaded report.")
        inputs = [FragmentInput(
            fragment_id=key, locator=self._fragments[key].locator,
            text=self._fragments[key].text, ordinal=self._fragments[key].ordinal,
        ) for key in ids]
        self._extraction_calls += 1
        try:
            results = self._extract(
                inputs, self._context.model_callable,
                report_date=metadata.report_date, report_date_trusted=metadata.report_date_trusted,
            )
        except ExtractionError:
            raise AgentToolError("AGENT_TOOL_FAILED", "Extraction output failed validation.", stage="extraction", retryable=True) from None
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "The requested agent operation failed safely.") from None
        try:
            observations = list(deduplicate_results(results))
            if len(observations) > MAX_OBSERVATIONS:
                raise AgentToolError("AGENT_OBSERVATION_LIMIT", "Report exceeds the 200 observation limit.", stage="extraction", retryable=True)
            valid: list[Observation] = []
            warnings: list[AgentWarning] = []
            for value in observations:
                obs = value if isinstance(value, Observation) else Observation.model_validate(value)
                for evidence in obs.evidence:
                    fragment = self._fragments.get(evidence.fragment_id)
                    if evidence.fragment_id not in ids or fragment is None or evidence.quote not in fragment.text:
                        raise AgentToolError("AGENT_TOOL_FAILED", "Extraction evidence is outside the supplied fragments.", stage="extraction", retryable=True)
                if obs.date_basis.value == "relative_resolved" and not metadata.report_date_trusted:
                    raise AgentToolError("AGENT_TOOL_FAILED", "Relative dates require a trusted report date.", stage="extraction", retryable=True)
                valid.append(obs)
            model_metadata = ModelMetadata()
            errors: list[ValidationErrorRecord] = []
            for result in results:
                info = getattr(result, "metadata", None)
                if info is not None:
                    model_metadata = ModelMetadata(
                        model_tag=getattr(info, "model", None), model_digest=getattr(info, "model_digest", None),
                        extraction_prompt_version=getattr(info, "prompt_version", None),
                        extraction_prompt_hash=getattr(info, "prompt_hash", None),
                        settings_hash=getattr(info, "settings_hash", None),
                    )
                if getattr(result, "errors", ()):
                    warnings.append(AgentWarning(code="EXTRACTION_ITEMS_REJECTED", message="Some unsupported extraction items were rejected."))
            self._model_metadata = model_metadata
            self._observations = {key: value for key, value in zip(observation_keys(len(valid)), valid, strict=True)}
            return ExtractionToolResult(observations=valid, model_metadata=model_metadata, errors=errors, warnings=warnings)
        except AgentToolError:
            raise
        except ValidationError:
            raise AgentToolError("AGENT_TOOL_FAILED", "Extraction output failed validation.", stage="extraction", retryable=True) from None
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "Extraction output failed validation.", stage="extraction", retryable=True) from None

    def retrieve_candidates(self, observation_key: str, observation: Observation, schedule_version_id: str) -> RetrievalToolResult:
        scope = self._require_scope()
        self._validate_identity(schedule_version_id, scope.schedule_version_id)
        keys = observation_keys(MAX_OBSERVATIONS)
        if observation_key not in keys or not observation_key.startswith("obs-"):
            raise AgentToolError("AGENT_TOOL_FAILED", "Invalid observation key.")
        try:
            obs = observation if isinstance(observation, Observation) else Observation.model_validate(observation)
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "Invalid observation.") from None
        if self._observations.get(observation_key) != obs:
            raise AgentToolError("AGENT_TOOL_FAILED", "Observation does not match the extracted report data.")
        try:
            if self._retrieve is default_retrieval_service:
                raw = self._retrieve(obs, scope.schedule_version_id, list(self._activities.values()),
                                     model_call=self._context.model_callable)
            else:
                raw = self._retrieve(obs, scope.schedule_version_id, list(self._activities.values()))
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "Schedule decision failed safely.") from None
        warnings = []
        try:
            rows = list(raw.candidates if hasattr(raw, "candidates") else raw)
            if len(rows) > MAX_CANDIDATES:
                raise AgentToolError("AGENT_TOOL_FAILED", "Retrieval returned more than eight candidates.")
            candidates: list[Candidate] = []
            seen: set[str] = set()
            for item in rows:
                candidate = Candidate.model_validate(item.model_dump() if hasattr(item, "model_dump") else {
                    "candidate_id": getattr(item, "candidate_id", getattr(item, "id", None)),
                    "external_id": getattr(item, "external_id", None),
                    "activity_name": getattr(item, "activity_name", getattr(item, "name", None)),
                    "area": getattr(item, "area", None), "work_type": getattr(item, "work_type", "unknown"),
                    "is_leaf": getattr(item, "is_leaf", True),
                    "retrieval_rank": getattr(item, "retrieval_rank", getattr(item, "lexical_rank", None)),
                    "retrieval_score": getattr(item, "retrieval_score", getattr(item, "rrf_score", None)),
                })
                key = str(candidate.candidate_id)
                if key in seen or key not in self._activities or not candidate.is_leaf:
                    raise AgentToolError("AGENT_TOOL_FAILED", "Retrieval returned an unknown or unsafe candidate.")
                if str(self._activities[key].schedule_version_id) != scope.schedule_version_id:
                    raise AgentToolError("AGENT_TOOL_FAILED", "Retrieval returned an out-of-scope candidate.")
                seen.add(key)
                candidates.append(candidate)
            self._returned_candidates[observation_key] = {str(item.candidate_id): item for item in candidates}
            return RetrievalToolResult(candidates=candidates, warnings=warnings)
        except AgentToolError:
            raise
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "Retrieval output failed validation.") from None

    def select_candidate(self, observation_key: str, observation: Observation, candidates: list[Candidate], fragment_ids: list[str]) -> Proposal:
        scope = self._require_scope()
        if observation_key not in self._returned_candidates:
            raise AgentToolError("AGENT_TOOL_FAILED", "Candidates were not retrieved for this observation.")
        try:
            obs = observation if isinstance(observation, Observation) else Observation.model_validate(observation)
            ids = [_canonical(value) for value in fragment_ids]
            supplied = [item if isinstance(item, Candidate) else Candidate.model_validate(item) for item in candidates]
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "Invalid selection input.") from None
        if self._observations.get(observation_key) != obs:
            raise AgentToolError("AGENT_TOOL_FAILED", "Observation does not match the extracted report data.")
        if not ids or len(ids) != len(set(ids)) or any(value not in self._fragments for value in ids):
            raise AgentToolError("AGENT_TOOL_FAILED", "Evidence fragments are outside the loaded report scope.")
        known = self._returned_candidates[observation_key]
        if len(supplied) > MAX_CANDIDATES or len({str(item.candidate_id) for item in supplied}) != len(supplied):
            raise AgentToolError("AGENT_TOOL_FAILED", "Invalid candidate set.")
        if any(str(item.candidate_id) not in known or item != known[str(item.candidate_id)] for item in supplied):
            raise AgentToolError("AGENT_TOOL_FAILED", "Candidates were not returned by retrieval for this observation.")
        if not supplied:
            try:
                proposal = self._select(obs, supplied, {key: self._fragments[key].text for key in ids}, model_call=None)
            except AgentDecisionError:
                raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True) from None
            except Exception:
                raise AgentToolError("AGENT_TOOL_FAILED", "The requested agent operation failed safely.") from None
            try:
                result = proposal if isinstance(proposal, Proposal) else Proposal.model_validate(proposal)
                if result.candidate_id is not None or result.proposed_effects or result.mapping_state.value != "unmatched":
                    raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True)
                if any(value not in ids for value in result.evidence_fragment_ids):
                    raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True)
                return result
            except AgentToolError:
                raise
            except ValidationError:
                raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True) from None
            except Exception:
                raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True) from None
        attempts = self._selection_calls.get(observation_key, 0)
        if attempts >= 2:
            raise AgentToolError("AGENT_REPAIR_LIMIT", "Selection call budget exhausted.")
        self._selection_calls[observation_key] = attempts + 1
        def selection_model(**call_kwargs: Any) -> Any:
            value = self._context.model_callable(**call_kwargs)
            if hasattr(value, "value"):
                self._model_metadata = self._model_metadata.model_copy(update={
                    "model_tag": getattr(value, "model", None) or self._model_metadata.model_tag,
                    "model_digest": (
                        getattr(value, "model_digest", None) or self._model_metadata.model_digest
                    ),
                    "selection_prompt_version": "agent-schedule-v1",
                    "selection_prompt_hash": getattr(value, "prompt_hash", None),
                    "settings_hash": (
                        getattr(value, "settings_hash", None) or self._model_metadata.settings_hash
                    ),
                })
            return value.value if hasattr(value, "value") else value
        try:
            proposal = self._select(
                obs, supplied, {key: self._fragments[key].text for key in ids},
                model_call=selection_model, project_id=scope.project_id,
            )
        except AgentDecisionError:
            raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True) from None
        except ValidationError:
            raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True) from None
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "The requested agent operation failed safely.") from None
        try:
            result = proposal if isinstance(proposal, Proposal) else Proposal.model_validate(proposal)
            if any(key not in ids for key in result.evidence_fragment_ids):
                raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True)
            if result.candidate_id is not None and str(result.candidate_id) not in known:
                raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True)
            if any(str(item.candidate_id) not in known or known[str(item.candidate_id)] != item for item in result.candidates):
                raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True)
            if result.proposed_effects:
                raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True)
            return result
        except AgentToolError:
            raise
        except ValidationError:
            raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True) from None
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "Selection output failed validation.", stage="selection", retryable=True) from None

    def validate_proposal_drafts(self, state: AgentState) -> ValidationToolResult:
        def invalid(stage: str, retryable: bool, message: str) -> ValidationToolResult:
            return ValidationToolResult(valid=False, errors=[ValidationErrorRecord(
                stage=stage, code="AGENT_TOOL_FAILED" if stage != "state" else "AGENT_STATE_INVALID",
                message=message, retryable=retryable,
            )], warnings=[])

        try:
            if isinstance(state, AgentState):
                payload = state.model_dump(mode="python", warnings=False)
            elif isinstance(state, dict):
                payload = dict(state)
            else:
                return invalid("state", False, "Agent state is malformed.")
            selection_payload = payload.get("selection_drafts")
            state_payload = dict(payload)
            state_payload["selection_drafts"] = {}
            base_state = AgentState.model_validate(state_payload)
            if not isinstance(selection_payload, dict):
                return invalid("selection", True, "Selection output is malformed.")
            if set(selection_payload) != set(observation_keys(len(base_state.observation_drafts))):
                return invalid("state", False, "Agent state keys are inconsistent.")
            try:
                state = AgentState.model_validate({**state_payload, "selection_drafts": selection_payload})
            except ValidationError:
                return invalid("selection", True, "Selection output is malformed.")
            state = state if isinstance(state, AgentState) else base_state
        except Exception:
            return invalid("state", False, "Agent state is malformed.")
        try:
            scope = self._require_scope()
            if (state.job_id != scope.job_id or state.project_id != scope.project_id
                    or state.report_id != scope.report_id or state.schedule_version_id != scope.schedule_version_id
                    or state.fragment_ids != scope.fragment_ids or state.activity_ids != scope.activity_ids):
                return invalid("state", False, "Agent state is outside the loaded job scope.")
            expected = set(observation_keys(len(state.observation_drafts)))
            if len(state.observation_drafts) > MAX_OBSERVATIONS or set(state.candidate_sets) != expected or set(state.selection_drafts) != expected:
                return invalid("state", False, "Agent state keys are inconsistent.")
            for observation in state.observation_drafts:
                if not observation.evidence or any(item.fragment_id not in state.fragment_ids for item in observation.evidence):
                    return invalid("extraction", False, "Observation evidence is outside the loaded report scope.")
            if any(self._observations.get(key) != observation for key, observation in zip(observation_keys(len(state.observation_drafts)), state.observation_drafts, strict=True)):
                return invalid("extraction", False, "Observation drafts differ from extracted report data.")
            for key, proposal in state.selection_drafts.items():
                returned = self._returned_candidates.get(key, {})
                candidate_ids = {str(item.candidate_id) for item in state.candidate_sets[key]}
                if any(str(item.candidate_id) not in returned or returned[str(item.candidate_id)] != item for item in state.candidate_sets[key]):
                    return invalid("retrieval", False, "Candidate provenance does not match retained retrieval results.")
                if any(str(item.candidate_id) not in candidate_ids or item not in state.candidate_sets[key] for item in proposal.candidates):
                    return invalid("selection", True, "Selection output contains an unsupported candidate.")
                if proposal.candidate_id is not None and str(proposal.candidate_id) not in candidate_ids:
                    return invalid("selection", True, "Selection output chose a candidate outside the retrieved set.")
                if any(item not in state.fragment_ids for item in proposal.evidence_fragment_ids):
                    return invalid("selection", True, "Selection evidence is outside the loaded report scope.")
                if proposal.candidate_id is not None and not proposal.evidence_fragment_ids:
                    return invalid("selection", True, "Selected proposal has no supporting evidence.")
                if proposal.proposed_effects:
                    return invalid("selection", True, "Selection output contains unsupported proposed effects.")
            return ValidationToolResult(valid=True, errors=[], warnings=[])
        except Exception:
            return invalid("state", False, "Agent state failed safety validation.")

    def persist_review_proposals(self, state: AgentState) -> PersistenceResult:
        if self._persistence_result is not None:
            return self._persistence_result
        if self._persistence_error is not None:
            raise self._persistence_error
        if self._persistence_called:
            raise AgentToolError("AGENT_TOOL_FAILED", "Persistence has already been attempted.")
        validation = self.validate_proposal_drafts(state)
        if not validation.valid:
            raise AgentToolError("AGENT_TOOL_FAILED", "Proposal drafts failed safety validation.")
        scope = self._require_scope()
        try:
            with self._context.session_factory() as db:
                job = db.get(Job, UUID(scope.job_id))
                project = db.get(Project, UUID(scope.project_id))
                if job is None or project is None:
                    raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be revalidated.")
                self._check_lease_schedule(db, job, project)
                if (str(job.project_id) != scope.project_id or str(job.report_id) != scope.report_id
                        or str(job.schedule_version_id) != scope.schedule_version_id):
                    raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be revalidated.")
        except AgentToolError:
            raise
        except Exception:
            raise AgentToolError("AGENT_TOOL_FAILED", "The job context could not be revalidated.") from None
        self._persistence_called = True
        try:
            result = _safe_call(self._persist, state, idempotency_key=state.run_id)
        except AgentToolError as error:
            self._persistence_error = error
            raise
        try:
            validated = PersistenceResult.model_validate(result)
            if (validated.extracted_count != len(state.observation_drafts)
                    or validated.proposal_count != len(state.selection_drafts)):
                raise ValueError("persistence counts do not match validated input")
            self._persistence_result = validated
            return validated
        except Exception:
            self._persistence_error = AgentToolError("AGENT_TOOL_FAILED", "Persistence returned an invalid result.")
            raise self._persistence_error from None


__all__ = [
    "AgentToolError", "AgentTools", "JobContextResult", "ReportMetadata", "ExtractionToolResult",
    "RetrievalToolResult", "ValidationToolResult", "PersistenceResult",
]
