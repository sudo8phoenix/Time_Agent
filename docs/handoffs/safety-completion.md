# Safety acceptance completion

Completed the remaining W-04/W-06/W-13 safety acceptance work.

## Changes

- Added PostgreSQL-backed session lifecycle and project isolation acceptance: expired and revoked session cookies return 401, project listings only include memberships, and a foreign project request returns 403.
- Session cookies now set `Secure` when `environment=production`; local development keeps HTTP test flows usable.
- Approval now requires a selected `suggested` mapping with no unresolved warnings, and the selected activity must belong to the schedule version pinned to the originating job.
- Reviewers can resolve specific proposal warnings through `field_changes.resolve_warnings`; resolutions must match existing warning text, and the revision still requires a reason. Other unsupported `field_changes` keys are rejected.
- Added a controlled two-session PostgreSQL approval race. The second transaction waits behind the first proposal lock and receives the same committed response for the same idempotency key; one event and one revision are stored.
- Added correction acceptance confirming the old event remains immutable, the new event points to it through `supersedes_event_id`, and recomputation uses the corrected value.
- Added a PostgreSQL uniqueness-conflict intake test proving the stored original file is removed and the failed transaction leaves no report row.

## Verification

Command: `.venv/bin/pytest backend/tests/integration/test_security_acceptance.py backend/tests/integration/test_review_concurrency.py backend/tests/integration/test_report_recovery.py -q`

Result: **8 passed**, with one pre-existing Starlette `BlockingPortal` deprecation warning.

The tests use rollback-isolated fixtures except for the real two-connection race, which commits only uniquely named rows and deletes its exact project fixture in teardown. One earlier teardown attempt left a single generated fixture; it was removed by its exact schedule ID and cascading project ID before the clean rerun.
