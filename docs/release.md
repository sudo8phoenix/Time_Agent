# Local release status

Status date: 23 September 2026. This is a local release candidate, not a hosted or model-evaluated release.

Agent-framework note, 24 September 2026: W-31–W-36 are accepted. The repository now has strict sanitized trace records, migration `0008_agent_runs`, the fixed 11-node graph, migration-owned PostgreSQL checkpoints, lease-aware durable provenance resume, idempotent persistence/finalization, sanitized telemetry and exact terminal checkpoint pruning. The application still defaults to the legacy pipeline. W-37–W-39 status visibility, frontend display, parity/security/backup/rollback and a real private-Ollama graph smoke remain pending.

## Verified

- Unit suite: 150 passed.
- Isolated PostgreSQL integration suite: 49 passed, including persisted worker embeddings and ten durable graph-runtime cases.
- Four native formats pass bounded parsing and authenticated preview → mapping → staging → activation → retrieval flows, including a real MPP fixture.
- Production frontend build and source-contract checks pass.
- Human approval safety, concurrent approval, corrections, source evidence, rollback, safe CSV export, backup and separate-database restore are covered.
- The API serves the production frontend locally and keeps unknown `/api/*` routes as JSON 404 responses.
- Private remote-Ollama configuration is server-side, endpoint-restricted, bounded, and has a fail-fast readiness command.

## Open release gates

- Friend-hosted Ollama readiness, exact model digest, latency and live extraction/selection evaluation.
- Human review of the W-03 and W-29 label worksheets.
- Browser walkthrough of login, import, report processing, review/correction/approval, progress history and CSV export.
- Demo rehearsal on the actual two-laptop Tailscale network.
- Public-host checks are deferred by user decision.

Do not present fixture-only retrieval, injected-model tests, synthetic labels, or parser fixtures as live model accuracy. Do not claim W-03/W-29 as reviewed until the review sheets are signed off.

## Release procedure

1. Follow [local-run.md](local-run.md) and record `make doctor` output.
2. Record the exact Ollama tag, digest, runtime version, quantization, configuration and test-machine details.
3. Complete the label review sheets; preserve corrections and regenerate any derived held-out manifest.
4. Run the full unit, integration, native smoke, frontend build and contract checks.
5. Run the real-model evaluation and save predictions separately from reference labels.
6. Perform the browser walkthrough and record observed failures rather than silently bypassing them.
7. Stop intake/worker, create a backup, and verify it into a new database.
8. Rehearse model outage, duplicate submission, unauthorized access and restart recovery.
9. Update `evaluation/RESULTS.md`, both task boards and this file with measured evidence.
