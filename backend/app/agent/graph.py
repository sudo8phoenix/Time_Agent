"""Assembly of the frozen report-analysis graph and its explicit transitions."""
from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from . import policy as default_policy
from .nodes import _nodes, conditional_routers
from .state import AgentState

NODE_NAMES = (
    "load_context", "extract", "validate_extraction", "repair_extraction", "retrieve",
    "select", "validate_selection", "repair_selection", "persist", "finalize", "record_failure",
)


def build_report_analysis_graph(
    checkpointer: BaseCheckpointSaver[Any] | None,
    tools: Any,
    policy: Any = default_policy,
):
    """Build and compile one fixed graph with the caller's checkpoint saver."""
    nodes = _nodes(tools, policy)
    builder = StateGraph(AgentState)
    for name in NODE_NAMES:
        builder.add_node(name, nodes[name])

    load_route, extraction_route, selection_route, persist_route = conditional_routers(policy)
    builder.add_edge(START, "load_context")
    builder.add_conditional_edges("load_context", load_route, {
        "extract": "extract", "record_failure": "record_failure",
    })
    builder.add_edge("extract", "validate_extraction")
    builder.add_conditional_edges("validate_extraction", extraction_route, {
        "retrieve": "retrieve", "repair_extraction": "repair_extraction",
        "record_failure": "record_failure",
    })
    builder.add_edge("repair_extraction", "validate_extraction")
    builder.add_edge("retrieve", "select")
    builder.add_edge("select", "validate_selection")
    builder.add_conditional_edges("validate_selection", selection_route, {
        "persist": "persist", "repair_selection": "repair_selection",
        "record_failure": "record_failure",
    })
    builder.add_edge("repair_selection", "validate_selection")
    builder.add_conditional_edges("persist", persist_route, {
        "finalize": "finalize", "record_failure": "record_failure",
    })
    builder.add_edge("finalize", END)
    builder.add_edge("record_failure", END)
    return builder.compile(checkpointer=checkpointer)


__all__ = ["NODE_NAMES", "build_report_analysis_graph"]
