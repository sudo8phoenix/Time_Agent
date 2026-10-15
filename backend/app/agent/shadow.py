"""Non-writing comparison of the retained and hierarchical report graphs."""
from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver

from .graph import build_report_analysis_graph
from .hierarchy import build_hierarchical_report_graph
from .state import create_hierarchical_state, parse_agent_state
from .tools import AgentToolError, PersistenceResult


class ShadowTools:
    """Suppress domain persistence even when the supplied tool has a live callback."""

    def __init__(self, tools):
        self._tools = tools

    def __getattr__(self, name):
        if name not in {"load_job_context", "report_metadata", "extract_observations",
                        "retrieve_candidates", "select_candidate", "model_metadata",
                        "validate_proposal_drafts", "rehydrate_provenance"}:
            raise AttributeError(name)
        return getattr(self._tools, name)

    def persist_review_proposals(self, state):
        if not self._tools.validate_proposal_drafts(state).valid:
            raise AgentToolError("AGENT_TOOL_FAILED", "Shadow proposal validation failed.")
        return PersistenceResult(extracted_count=len(state.observation_drafts),
            proposal_count=len(state.selection_drafts), already_persisted=False)


def compare_report(initial, tools_factory):
    """Run with separate ephemeral tools; return quality/call-count and latency deltas.

    Caller provides synthetic or authorized source context. Neither execution
    writes proposals, approval state, progress events, or checkpoints to disk.
    """
    identity = {key: getattr(initial, key) for key in (
        "run_id", "job_id", "project_id", "report_id", "schedule_version_id")}
    results = []
    for builder, state in ((build_report_analysis_graph, initial),
                           (build_hierarchical_report_graph, create_hierarchical_state(**identity))):
        graph = builder(MemorySaver(), ShadowTools(tools_factory()))
        started = perf_counter()
        value = graph.invoke(state.model_dump(mode="json"),
            {"configurable": {"thread_id": str(uuid4())}})
        value = parse_agent_state(value).model_dump(mode="json")
        results.append((value, round((perf_counter() - started) * 1000, 3)))
    legacy, hierarchy = results[0][0], results[1][0]
    return {
        "observations_equal": legacy["observation_drafts"] == hierarchy["observation_drafts"],
        "selections_equal": legacy["selection_drafts"] == hierarchy["selection_drafts"],
        "terminal_equal": legacy["terminal_state"] == hierarchy["terminal_state"],
        "legacy_terminal": legacy["terminal_state"], "hierarchy_terminal": hierarchy["terminal_state"],
        "legacy_counters": legacy["counters"], "hierarchy_counters": hierarchy["counters"],
        "legacy_ms": results[0][1], "hierarchy_ms": results[1][1],
        "writes": 0,
    }
