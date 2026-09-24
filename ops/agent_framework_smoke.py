"""Compatibility smoke for the frozen LangGraph/PostgresSaver candidate pair.

Run only with DATABASE_URL set to the isolated progress_test database. This is
an operator smoke, not application startup: setup() performs package DDL.
"""
from __future__ import annotations

import os
import platform
import sys
from importlib.metadata import version
from typing import TypedDict
from urllib.parse import urlparse

import psycopg

# Checkpoints can contain only the smoke's primitive typed state; deny dynamic
# msgpack object imports before LangGraph initializes its serializer.
os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from psycopg.conninfo import conninfo_to_dict


class SmokeState(TypedDict):
    value: int


def make_graph(checkpointer):
    def increment(state: SmokeState) -> SmokeState:
        return {"value": state["value"] + 1}

    builder = StateGraph(SmokeState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile(checkpointer=checkpointer)


def check_memory() -> None:
    graph = make_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "w31-memory"}}
    first = graph.invoke({"value": 40}, config)
    resumed = graph.invoke(None, config)
    assert first == {"value": 41}
    assert resumed == first
    print(f"memory compile/invoke/checkpoint-resume: PASS ({first})")


def main() -> int:
    raw_url = os.environ.get("DATABASE_URL", "")
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"postgresql+psycopg", "postgresql"}:
        raise SystemExit("DATABASE_URL must use PostgreSQL with psycopg")
    db_name = parsed.path.lstrip("/")
    if db_name != "progress_test":
        raise SystemExit("refusing PostgresSaver.setup(): database must be progress_test")

    print(f"Python: {platform.python_version()} ({sys.implementation.name})")
    print(f"langgraph: {version('langgraph')}")
    print(f"langgraph-checkpoint-postgres: {version('langgraph-checkpoint-postgres')}")
    print(f"psycopg: {version('psycopg')}")
    check_memory()

    # SQLAlchemy's driver-qualified URL is translated to libpq conninfo without
    # printing credentials. A direct sync psycopg connection matches run_once's
    # synchronous worker flow; do not share this connection across threads.
    conninfo = conninfo_to_dict(raw_url.replace("postgresql+psycopg://", "postgresql://", 1))
    with psycopg.connect(**conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), version()")
            database, pg_version = cur.fetchone()
            assert database == "progress_test"
            print(f"PostgreSQL: {pg_version.split(',')[0]}")

    saver = PostgresSaver.from_conn_string(
        raw_url.replace("postgresql+psycopg://", "postgresql://", 1)
    )
    with saver as checkpointer:
        checkpointer.setup()
        graph = make_graph(checkpointer)
        thread_id = "w31-compatibility-smoke"
        config = {"configurable": {"thread_id": thread_id}}
        first = graph.invoke({"value": 40}, config)
        resumed = graph.invoke(None, config)
        assert first == {"value": 41}
        assert resumed == first
        print(f"Postgres compile/invoke/checkpoint-resume: PASS ({first})")
        # Delete only this smoke's thread ID. Child rows are scoped through their
        # package key and are safe to remove after the checkpoint rows.
        with checkpointer.conn.cursor() as cur:
            cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s", (thread_id,))
            cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s", (thread_id,))
            cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
        checkpointer.conn.commit()

    print("PostgresSaver.setup(): PASS; tables: checkpoint_migrations, checkpoints, checkpoint_blobs, checkpoint_writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
