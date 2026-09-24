# W-10 embedding persistence follow-up

- Added the PostgreSQL migration `0007_activity_embeddings` and the `ActivityEmbedding` ORM model.  A row is uniquely identified by `(activity_id, model_revision)` and records the composed-description SHA-256 plus a JSON array of finite local vector values.
- `ensure_activity_embeddings` reuses a row only when both the model revision and composed text hash match.  It regenerates stale vectors without deleting prior model revisions.
- The worker uses a transaction savepoint to populate/reuse vectors once for its pinned schedule snapshot, then passes them to hybrid retrieval.  Query embeddings are still generated locally; activity descriptions are not re-embedded per observation.  Any local embedding failure rolls back that optional savepoint and continues with the existing lexical ranker.
- No embedding package, weights, network service, or Ollama host was used.  The local model loader remains `local_files_only=True`.

Verification: `.venv/bin/pytest backend/tests/unit/test_retrieval.py -q` — `9 passed`.
