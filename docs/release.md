# Local prototype release evidence — 10 October 2026

This working tree implements the public/synthetic construction-progress prototype. It is not an independently validated release or owner-package acceptance. The completed implementation and remaining acceptance gates are recorded here; versioned task handoffs provide the supporting implementation evidence.

## Source and runtime

Base commit: `a174963ab1654e48e909d9aac3713897da7f1db9`. Verification includes uncommitted changes and untracked implementation files; the base commit alone cannot reproduce this state. No new commit was created. The release evidence manifest records SHA-256 for application, migration, test, operations, evaluation and frontend sources. Record a new immutable commit before packaging a release.

Python 3.12.14; Node 26.0.0; npm 11.12.1; OpenJDK 25.0.1; PostgreSQL container 16.6. Python pins are in `pyproject.toml`/`uv.lock`; frontend pins are in `frontend/package-lock.json`. Lock hashes:

- `uv.lock`: `d9fc6a58f24fbf75fb9d99e5bed28e410ee3a9cde0e6ec9f0b306c3ca45269ce`
- `frontend/package-lock.json`: `438ccc28d5cbe697e5b8757c2569f8849f4204a8bea766c435601ca4e98ee96f`

Default execution remains `legacy`; graph rollout stays gated. Migration head is `0014_audited_reanalysis`. Only isolated test/recovery databases were migrated for these checks. Applying migrations to the application database remains a deployment action.

No model was called in this verification. Fixture models were injected for deterministic pipeline checks; browser fixture tests intercept API responses. The earlier Gemma connection/extraction smoke in [evaluation/RESULTS.md](../evaluation/RESULTS.md) is historical compatibility evidence, not E02 unseen workflow evidence. Server-side configuration controls the endpoint and model. Reanalysis records a requested configuration snapshot and the actual pipeline provenance separately; it does not permit browser-supplied configuration overrides.

## Tested behavior

Quantity-free actual starts/finishes retain date/time precision, scope and source evidence. Authorized reviewers accept proposals; conversations alone do not authorize changes. Corrections/retractions preserve history and recompute current state. Report mapping and PDF transcription preserve original cell/page attribution. History/export separates event values from current state, and duration queries disclose unavailable calendar/labour inputs.

Explicit reanalysis creates a linked job with actor, reason, pinned schedule and configuration. Ordinary duplicate submission returns the original base job. Cross-run repeat application of accepted source work is blocked; accepted work changes through the existing correction workflow. Backup manifests verify row-content hashes for jobs, lifecycle state/events, observations/proposals/audit, graph records, conversations and outbox, plus original-file hashes.

The connector and receiver are labelled **MOCK PMIS — prototype**. Automatic outbox delivery, read-back, retry and correction ordering have fixture coverage. This is not a production PMIS integration.

## Fresh verification

211 unit tests, 102 isolated PostgreSQL integration tests and 33 browser fixtures passed. Final counts and command results are recorded in [E01–E03 verification](validation/e01-e03-verification-2026-10-10.json). Native smoke parsed all six required inputs, including XER, P6 XML, MSPDI and real MPP, and rejected the malformed XML fixture. Frontend type checking, production build and contract assertions passed.

A fresh source database `progress_recovery_e01_20261010` was migrated and seeded with explicitly synthetic data using `ops/seed_e01_recovery.py`. `ops/backup.py` created `/private/tmp/e01-recovery-20261010/backup-v2`; `ops/restore_verify.py` restored it into the new `progress_restore_e01_20261010` database and `/private/tmp/e01-recovery-20261010/restored-uploads`. Verification passed for two accepted events, one immutable original, three jobs, one graph operational record, one conversation/turn and one pending outbox record; state/event/lineage/payload content hashes matched. The restored pending outbox then delivered in one attempt to a separate loopback HTTP receiver, whose read-back matched revision 2 and 08:30 minute precision. The receiver's separate storage is outside this application-database backup. Temporary artifacts and both databases were left separate for inspection.

## Remaining acceptance gates

- D04 independent event-label review/adjudication and D05 reviewed, frozen leakage-aware splits.
- A02 calibrated thresholds from reviewed validation inputs; no fabricated threshold or confidence probability.
- E02 real unseen UI → live model → shortlist/match → reviewer acceptance → internal update → mock read-back → export capture, with agreed quality/latency targets and all failures included. [Proposed targets](evaluation-targets-draft.md) await agreement; they are not achieved results.
- Owner sample package remains `not_received`. Register/hash it when supplied, review mappings and calendar/timezone semantics, and repeat project-specific validation. Cambridge/GT10 and synthetic reports do not replace it.
- Commit the verified tree, freeze exact model digest/config and release artifacts, and rehearse on the intended laptop/network setup before a release claim.

E03 documentation reconciliation is implemented; its full release gate remains pending E02 and the independent data gates. Public/synthetic fixture verification must be reported separately from owner-package and live-model validation.
