# Troubleshooting

| Symptom | Check | Next action |
|---|---|---|
| Database connection/missing table | PostgreSQL availability, `DATABASE_URL`, migration version | Start the intended DB; apply migrations before workers |
| Native schedule reader unavailable | Java installation and Python/MPXJ dependencies | Follow bootstrap; run `make native-smoke` with public fixtures |
| No active schedule | Project active version and import state | Validate/stage, then explicitly activate the reviewed schedule |
| Report waits for transcription | PDF page text and transcription markers | Supply reviewed page text; no OCR is installed |
| XLSX mapping rejected | Sheet/header signature and mapping revision | Preview again and confirm a new mapping |
| Job queued without progress | Worker process, leases, queue age, provider admission | Start the correctly configured worker; inspect job/run state |
| Provider timeout/rate limit | Configured model, account scope, remaining budget | Honor limits; do not reset consumed deadlines to force retries |
| Resume rejects source drift | Pinned build/dependency/schema identity | Follow durable configuration contract; preserve the original run |
| 401 after sign-in | Cookie, expiry and HTTPS | Sign in again; use HTTPS when production Secure cookies are enabled |
| 403 on write | Membership, reviewer role and CSRF token | Refresh `/auth/me`; send session cookie and `X-CSRF-Token` |
| 409 on approval | Proposal/activity revisions and schedule version | Reload and review current state before resubmitting |
| Old browser interface | Frontend build and serving directory | Run `make build-web`; verify `FRONTEND_DIST` |
| PMIS delivery backlog | Connector process, older failed revisions and receiver | Inspect receipt/error; repair the underlying issue before retry |
| Integration test touches wrong DB | URL configured before application imports | Stop and use isolated `progress_test` or `progress_rehearsal_*` |

## Collect a useful report

Record the code revision, platform, safe settings, project/job IDs, timestamps,
error code, stage and minimal synthetic reproduction. Include test commands and
results. Remove keys, cookies, passwords and private report text. Preserve original
failure artifacts locally rather than rewriting them after retries.

Start with `make doctor` and `ops/runtime_status.py`; liveness alone does not
verify the database, worker, model or delivery. See [observability](OBSERVABILITY.md),
[recovery](local-run.md) and [security reporting](SECURITY.md).

---

[Documentation index](README.md) · [Project overview](../README.md)
