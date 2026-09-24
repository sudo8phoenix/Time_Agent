# W-07-PIPELINE handoff

Implemented `process_job(db, job, *, model_call=None, extraction_call=None, selection_call=None, retrieve_call=None, **kwargs)` in `backend/app/jobs/pipeline.py`.

It reads persisted fragments and the job's pinned schedule version, persists observations and pending proposals atomically, preserves evidence and source fragment IDs, stores extraction metadata, handles no-fragment jobs safely, and returns persisted counts on retry. It does not create progress events, mutate activity state, or approve proposals.

Validation: Added PostgreSQL integration coverage for no fragments, traceable happy path, idempotent retry, and failure rollback (4 tests in the worker pipeline module). The suite previously reported 12 passing tests; current environment cannot connect to PostgreSQL (`127.0.0.1:5432`, operation not permitted), so `make test-integration` could not be rerun here.

No contract changes.
