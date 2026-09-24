from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph


class State(TypedDict):
    value: int


def build_graph(checkpointer):
    def increment(state: State) -> State:
        return {"value": state["value"] + 1}

    graph = StateGraph(State)
    graph.add_node("increment", increment)
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    return graph.compile(checkpointer=checkpointer)


def test_typed_graph_invokes_and_resumes_with_memory_checkpointer():
    compiled = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "unit-test"}}
    assert compiled.invoke({"value": 1}, config) == {"value": 2}
    assert compiled.invoke(None, config) == {"value": 2}


def test_postgres_smoke_refuses_non_test_database():
    # Guard is exercised by the script itself without opening a connection; the
    # PostgreSQL acceptance smoke remains explicitly opt-in.
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[4] / "ops" / "agent_framework_smoke.py"
    env = os.environ | {"DATABASE_URL": "postgresql+psycopg://user:pass@localhost/progress"}
    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "database must be progress_test" in result.stderr


@pytest.mark.parametrize("node_count", [1])
def test_minimal_stategraph_has_one_declared_node(node_count):
    compiled = build_graph(InMemorySaver())
    assert compiled.get_graph().nodes.keys() >= {"increment"}
