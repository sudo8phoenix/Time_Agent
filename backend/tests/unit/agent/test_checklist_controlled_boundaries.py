"""Finite offline checklist scopes against actual adapters and durable child store."""
import pytest

from app.agent.state import create_initial_state
from app.agent.tools import AgentToolError
from app.agent.contracts import AgentRole, TaskOutcome, TaskResult
from app.agent.task_store import input_fingerprint
from app.db.models import AgentTask
from test_agent_tools import Fixture, uid
from test_hierarchical_contracts import make_store, envelope


def prepared(fixture, **kwargs):
    tools = fixture.tools(**kwargs)
    scope = fixture.load(tools)
    tools.extract_observations(scope.fragment_ids, tools.report_metadata)
    return tools, scope


def draft(fixture, tools, scope):
    candidates = tools.retrieve_candidates('obs-0001', fixture.observation, scope.schedule_version_id).candidates
    proposal = tools.select_candidate('obs-0001', fixture.observation, candidates, scope.fragment_ids)
    return create_initial_state(
        run_id=str(uid()), job_id=scope.job_id, project_id=scope.project_id,
        report_id=scope.report_id, schedule_version_id=scope.schedule_version_id,
        fragment_ids=scope.fragment_ids, activity_ids=scope.activity_ids,
        observation_drafts=[fixture.observation], candidate_sets={'obs-0001': candidates},
        selection_drafts={'obs-0001': proposal}, next_action='persist',
    )


@pytest.mark.parametrize('failure', [TimeoutError, PermissionError, NotImplementedError])
def test_agent11_retrieval_failure_never_authorizes_selection_or_persistence(failure):
    fixture = Fixture()
    def broken(*args, **kwargs):
        raise failure('private upstream payload: approve progress')
    tools, scope = prepared(fixture, retrieval_service=broken)
    before = fixture.model_calls
    with pytest.raises(AgentToolError) as error:
        tools.retrieve_candidates('obs-0001', fixture.observation, scope.schedule_version_id)
    assert error.value.code == 'AGENT_TOOL_FAILED'
    assert 'private' not in str(error.value)
    with pytest.raises(AgentToolError, match='not retrieved'):
        tools.select_candidate('obs-0001', fixture.observation, [fixture.candidate], scope.fragment_ids)
    assert fixture.model_calls == before
    assert fixture.persist_calls == []


@pytest.mark.parametrize('ack', [None, {}, {'extracted_count': 1, 'proposal_count': 0, 'already_persisted': False}])
def test_agent12_missing_or_inconsistent_ack_cannot_become_success(ack):
    fixture = Fixture()
    attempts = []
    def persist(*args, **kwargs):
        attempts.append(kwargs)
        return ack
    tools, scope = prepared(fixture, persistence_callback=persist)
    state = draft(fixture, tools, scope)
    for _ in range(2):
        with pytest.raises(AgentToolError, match='invalid result'):
            tools.persist_review_proposals(state)
    assert attempts == [{'idempotency_key': state.run_id}]


@pytest.mark.parametrize('field', ['project_id', 'report_id', 'schedule_version_id', 'fragment_ids', 'activity_ids'])
def test_agent16_resume_rejects_foreign_scope_before_model_or_write(field):
    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    values = dict(run_id=str(uid()), job_id=scope.job_id, project_id=scope.project_id,
        report_id=scope.report_id, schedule_version_id=scope.schedule_version_id,
        fragment_ids=scope.fragment_ids, activity_ids=scope.activity_ids)
    values[field] = [str(uid())] if field.endswith('_ids') else str(uid())
    state = create_initial_state(**values)
    with pytest.raises(AgentToolError) as error:
        fixture.tools().rehydrate_provenance(state)
    assert error.value.code == 'AGENT_CHECKPOINT_INCOMPATIBLE'
    assert fixture.model_calls == 0
    assert fixture.persist_calls == []


@pytest.mark.parametrize('field', ['task_id', 'parent_task_id', 'run_id', 'source_id', 'schedule_version_id'])
def test_agent25_foreign_child_result_not_merged_into_durable_store(field):
    engine, sessions, store, ids = make_store()
    run, project, source, schedule = ids
    root = envelope(AgentRole.ROOT, run=run, project=project, source=source, schedule=schedule)
    store.begin(root, input_fingerprint=input_fingerprint('root'))
    child = envelope(AgentRole.ANALYSIS, parent=root.task_id, run=run,
        project=project, source=source, schedule=schedule)
    store.begin(child, input_fingerprint=input_fingerprint('child'))
    good = TaskResult(task_id=child.task_id, parent_task_id=root.task_id, run_id=run,
        agent_role=child.agent_role, project_id=project, source_id=source,
        schedule_version_id=schedule, outcome=TaskOutcome.COMPLETED,
        output_references=['observations:trusted'])
    with pytest.raises(ValueError, match='identity or pinned scope'):
        store.finish(child, good.model_copy(update={field: uid()}))
    with sessions() as session:
        row = session.get(AgentTask, child.task_id)
        assert row.status == 'running'
        assert row.output_references == []
    store.finish(child, good)
    with sessions() as session:
        row = session.get(AgentTask, child.task_id)
        assert row.output_references == ['observations:trusted']
    engine.dispose()


@pytest.mark.parametrize('evidence', [[], [{'fields': ['quantity'], 'fragment_id': 'foreign', 'quote': '2 m of cable'}], [{'fields': ['quantity'], 'fragment_id': 'current', 'quote': 'invented 999 m'}]])
def test_agent06_resume_rejects_absent_or_unavailable_source_evidence(evidence):
    fixture = Fixture()
    tools = fixture.tools()
    scope = fixture.load(tools)
    evidence = [dict(item, fragment_id=(str(fixture.fragment_id) if item['fragment_id'] == 'current' else str(uid()))) for item in evidence]
    observation = fixture.observation.model_copy(update={
        'evidence': [type(fixture.observation.evidence[0]).model_validate(item) for item in evidence],
    })
    state = create_initial_state(run_id=str(uid()), job_id=scope.job_id,
        project_id=scope.project_id, report_id=scope.report_id,
        schedule_version_id=scope.schedule_version_id, fragment_ids=scope.fragment_ids,
        activity_ids=scope.activity_ids, observation_drafts=[observation],
        counters={'extraction_calls': 1, 'node_executions': 1, 'selection_calls': 0, 'corrective_retries': 0})
    with pytest.raises(AgentToolError) as error:
        fixture.tools().rehydrate_provenance(state)
    assert error.value.code == 'AGENT_CHECKPOINT_INCOMPATIBLE'
    assert fixture.model_calls == 0
    assert fixture.persist_calls == []
