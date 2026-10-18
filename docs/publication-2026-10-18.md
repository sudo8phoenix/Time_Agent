# Candidate source and evidence publication — 18 October 2026

The owner requested publication of all required project files after the
documentation-only commit `9b55dc1`. This publication includes the remaining
application changes, backend/frontend tests, evaluation and operations tools,
synthetic evaluation inputs/labels, review records, screenshots, source manifests
and saved successful/failed captures referenced by the documentation.

Local `.env` credentials, runtime databases, generated builds/dependencies, logs,
operator notes and imported schedule copies in `data/schedules/` are excluded.
These imported files are local inputs, not application fixtures. Reproducible
application fixtures remain in `data/synthetic/`; public-source import tools and
provenance records remain available. Existing ignore rules protect runtime files;
new rules exclude local schedule copies and operator notes.

Before publication, 455 unit tests and all 201 isolated PostgreSQL integration
tests passed. Frontend TypeScript, production build and contract checks passed.
Ruff passed for changed executable Python; historical captured runner snapshots
were preserved without lint-driven edits. Pending publishable files were checked
against configured credential values and common token/private-key patterns with
no findings across all 551 staged files. Staged diff checking passed with
`cr-at-eol` enabled to recognize the original CSV line endings; captured bytes
were preserved rather than reformatted.

Saved evidence retains its original source hashes, attempts, failures and
limitations. Older records saying source was uncommitted describe their capture
stage; they are not rewritten as if this publication existed then. Candidate
publication is not accepted-release approval: fresh V20 accuracy/readiness, a new
holdout, supported/runtime confidence, sustained capacity and concurrent browser
latency still need evidence. Accepted hash freeze and accepted-source restart
remain pending. See [current status](current-status.md).

This publication starts no inference or deployment, changes no runtime flags and
does not resume retained rehearsal tasks or modify their checkpoints.

## GitHub unit-test portability fix

The first published unit run failed because two schedule adapter tests read
audited datasets from a directory outside the Git repository. Those files existed
on the development machine but were absent on GitHub. The earlier local 455-pass
result did not establish clean-checkout portability.

Both tests now create synthetic XLSX/JSON inputs in pytest temporary directories.
They still verify distinct export/input headers, task and relationship identity,
source locators, unchanged names, raw timestamp/precision/timezone values,
project-scoped Cambridge IDs and preservation of unknown source fields. They do
not claim to validate full public-source row counts or actual dataset accuracy.

Verification copied only Git-tracked files into a fresh temporary checkout with
no `.env` and no sibling datasets. The full unit suite passed with 454 tests and
one pre-existing skip, matching the GitHub environment's optional-test behavior.
The three focused adapter tests and Ruff also passed. No production adapter,
CI skip policy, provider settings or release acceptance gate was changed.
