# Checkpoint serialization hardening

Production graph runs now assign an explicit `JsonPlusSerializer` to the
`PostgresSaver` before reading or writing checkpoints. It disables pickle
fallback and permits LangGraph's built-in safe types plus an exact allowlist of
the historical agent state, schema models, and enums. It does not permit
arbitrary modules, dynamic proposal classes, or wildcard matching. The same
exact types are allowed for legacy JSON constructor envelopes so previously
written typed state can be resumed; unknown constructors remain inert data.

New graph input is `AgentState.model_dump(mode="json")`, and validated node
updates are projected from the merged state's JSON dump. Thus newly written
checkpoints carry ordinary JSON values rather than application model or enum
objects. The injected checkpointer path remains untouched, and saver DDL
continues to belong to migrations/deployment. The existing strict-msgpack
environment default is not relied upon to establish this policy.

Focused unit validation covers safe built-ins, the historical `ModelMetadata`
JSON constructor, and an unknown constructor with a no-construction assertion.
Runtime integration tests should run against the prepared `progress_test`
database to verify the Postgres saver can resume the existing recovery seed.
