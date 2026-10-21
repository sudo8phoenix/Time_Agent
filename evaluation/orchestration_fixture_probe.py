"""Reproducible, offline routing/call-accounting benchmark using real graph/tool code.

Fixture model answers are deterministic. Results measure graph behavior and local
execution overhead, never provider/model quality or production latency.
"""
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from app.agent.graph import build_report_analysis_graph
from app.agent.hierarchy import HierarchyExecution, build_hierarchical_report_graph
from app.agent.runtime import FRAMEWORK_VERSION
from app.agent.state import create_initial_state, create_hierarchical_state, parse_agent_state
from app.db.models import AgentRun, AgentTask

CONFIGURATIONS = ('flat', 'hierarchy', 'hierarchy_planner', 'hierarchy_invalid_planner')
WORKLOADS = {'simple': 0, 'one_selection_repair': 1, 'selection_repair_exhausted': 2}


class MeasuredTools:
    METHODS = {'load_job_context', 'extract_observations', 'retrieve_candidates',
               'select_candidate', 'validate_proposal_drafts', 'persist_review_proposals'}

    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.calls = []

    def __getattr__(self, name):
        value = getattr(self.wrapped, name)
        if name not in self.METHODS:
            return value
        def measured(*args, **kwargs):
            started = perf_counter()
            result = {'tool': name, 'failed': False}
            try:
                return value(*args, **kwargs)
            except Exception:
                result['failed'] = True
                raise
            finally:
                result['elapsed_ms'] = (perf_counter() - started) * 1000
                self.calls.append(result)
        return measured


def run(repetitions=3):
    # The offline probe intentionally reuses the deterministic test fixtures.
    # Resolve them locally so ordinary application imports remain conventional.
    fixture_directory = Path(__file__).resolve().parents[1] / 'backend/tests/unit/agent'
    if str(fixture_directory) not in sys.path:
        sys.path.insert(0, str(fixture_directory))
    from test_agent_tools import Fixture
    from test_agent_graph import FaultingTools

    rows = []
    for workload, selection_failures in WORKLOADS.items():
        for repetition in range(repetitions):
            fixture = Fixture()
            baseline_model = fixture.context.model_callable
            fingerprint = hashlib.sha256(json.dumps({
                'text': 'Installed 2 m of cable.', 'selection_failures': selection_failures,
                'schedule': fixture.candidate.model_dump(mode='json', exclude={'candidate_id'}),
            }, sort_keys=True).encode()).hexdigest()
            try:
                for configuration in CONFIGURATIONS:
                    sessions = sessionmaker(fixture.engine, expire_on_commit=False)
                    with sessions.begin() as db:
                        db.execute(delete(AgentTask))
                        db.execute(delete(AgentRun))
                    fixture.context = replace(fixture.context, model_callable=baseline_model)
                    fixture.model_calls = 0
                    fixture.persist_calls.clear()
                    identity = dict(run_id=str(uuid4()), job_id=str(fixture.job_id),
                        project_id=str(fixture.project_id), report_id=str(fixture.report_id),
                        schedule_version_id=str(fixture.schedule_id))
                    planner_calls = []
                    execution = None
                    if configuration != 'flat':
                        initial = create_hierarchical_state(**identity)
                        sessions = sessionmaker(fixture.engine, expire_on_commit=False)
                        with sessions.begin() as db:
                            db.add(AgentRun(id=UUID(initial.run_id), job_id=fixture.job_id,
                                graph_version='report-analysis-v2', state_schema_version='agent-state-v2',
                                framework_version=FRAMEWORK_VERSION, thread_id=initial.run_id,
                                execution_mode='graph', state='created', counters={}, model_metadata={},
                                prompt_metadata={}, config_metadata={}))
                        def planner(**request):
                            action = request['user']['legal_actions'][0]
                            planner_calls.append(action)
                            return {'action': 'approve' if configuration == 'hierarchy_invalid_planner' else action}
                        execution = HierarchyExecution(sessions, initial, ensure_active=lambda: None,
                            planner=planner if 'planner' in configuration else None)
                        fixture.context = replace(fixture.context, model_callable=execution.model({
                            'extraction': baseline_model, 'selection': baseline_model}))
                    else:
                        initial = create_initial_state(**identity)
                    tools = MeasuredTools(FaultingTools(fixture.tools(), selection_failures=selection_failures))
                    started = perf_counter()
                    graph = (build_report_analysis_graph(MemorySaver(), tools) if execution is None else
                             build_hierarchical_report_graph(MemorySaver(), tools, execution))
                    compilation_ms = (perf_counter() - started) * 1000
                    started = perf_counter()
                    result = graph.invoke(initial.model_dump(mode='json'),
                        {'configurable': {'thread_id': initial.run_id}})
                    elapsed_ms = (perf_counter() - started) * 1000
                    result = parse_agent_state(result).model_dump(mode='json')
                    tasks, usage = [], {}
                    if execution:
                        with sessions() as db:
                            tasks = [{'role': t.agent_role, 'status': t.status} for t in db.scalars(
                                select(AgentTask).where(AgentTask.run_id == UUID(initial.run_id)))]
                            usage = db.get(AgentRun, UUID(initial.run_id)).config_metadata.get('hierarchy_usage', {})
                    rows.append(dict(workload=workload, repetition=repetition, configuration=configuration,
                        drafts={'observations': result['observation_drafts'], 'selections': result['selection_drafts']},
                        task_fingerprint=fingerprint, terminal=result['terminal_state'],
                        success=result['terminal_state'] == 'ready_for_review',
                        plan_valid=not any(e['code'] == 'AGENT_PLANNER_INVALID' for e in result['validation_errors']),
                        planner_calls=len(planner_calls), singleton_action_planner_calls=len(planner_calls),
                        draft_fingerprint=hashlib.sha256(json.dumps({
                            'observations': result['observation_drafts'],
                            'selections': result['selection_drafts'],
                        }, sort_keys=True, default=str).encode()).hexdigest(), specialist_model_calls=fixture.model_calls,
                        total_model_calls=fixture.model_calls + len(planner_calls),
                        persistence_attempts=len(fixture.persist_calls), counters=result['counters'],
                        tools=tools.calls, tool_counts=dict(Counter(c['tool'] for c in tools.calls)),
                        failed_tool_calls=sum(c['failed'] for c in tools.calls), tasks=tasks, durable_usage=usage,
                        elapsed_ms=elapsed_ms, compilation_ms=compilation_ms,
                        observation_count=len(result['observation_drafts']),
                        selection_count=len(result['selection_drafts']),
                        errors=[e['code'] for e in result['validation_errors']],
                        paid_calls=0, queue_wait_ms=None, provider_transport_ms=None))
            finally:
                fixture.engine.dispose()
    return rows


def summarize(rows):
    summary = []
    for configuration in CONFIGURATIONS:
        for workload in WORKLOADS:
            group = [r for r in rows if r['configuration'] == configuration and r['workload'] == workload]
            timings = [r['elapsed_ms'] for r in group]
            successes = sum(r['success'] for r in group)
            summary.append(dict(configuration=configuration, workload=workload, sample_count=len(group),
                successes=successes, failures=len(group)-successes, valid_plans=sum(r['plan_valid'] for r in group),
                model_calls_per_success=(sum(r['total_model_calls'] for r in group)/successes if successes else None),
                model_call_counts=sorted({r['total_model_calls'] for r in group}),
                tool_call_counts=sorted({len(r['tools']) for r in group}),
                corrective_retries=sorted({r['counters']['corrective_retries'] for r in group}),
                measured_normal_call_target=(max(r['total_model_calls'] for r in group) if workload == 'simple' and successes else None),
                singleton_action_planner_calls=sum(r['singleton_action_planner_calls'] for r in group),
                p50_ms=statistics.median(timings), max_ms=max(timings), p95_ms=None,
                p95_status='insufficient sample for stable tail estimate'))
    return summary


if __name__ == '__main__':
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    rows = run()
    (output / 'runs.json').write_text(json.dumps(rows, indent=2) + '\n')
    (output / 'summary.json').write_text(json.dumps(summarize(rows), indent=2) + '\n')
    print(f'{len(rows)} offline graph runs captured')
