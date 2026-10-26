# Provider capacity and account scopes

Groq, OpenRouter and Gonka use database-backed admission shared by roles and processes
using the same PostgreSQL database. Waits and transport fit within finite request
budgets. There are no automatic transport retries or provider/model fallback.
External clients and separate databases are outside this coordinator.

## Owner-reported Groq accounts

Key slots 1 and 2 belong to different accounts, called `key_1` and `key_2`.
For each account, the supplied limits page lists the following limits for both
`openai/gpt-oss-20b` and `openai/gpt-oss-120b`:

| Limit | Per-account reported value |
|---|---:|
| Requests per minute | 30 |
| Requests per day | 1,000 |
| Tokens per minute | 8,000 |
| Tokens per day | 200,000 |

These are owner-provided account observations, not a current entitlement lookup.
Separate input/output and cross-model bucket policies remain unverified.
The first reached limit controls admission. A new key in the same account would
not create an independent quota. Slot 0's account mapping is unknown. The owner
reported no other Groq apps at study setup; this is not continuous monitoring.

## Default policy

`GROQ_ACCOUNT_SCOPES_ENABLED=false` conservatively groups Groq slots together.
This remains the checked-in and last inspected main-database setting. Slow
readiness can reflect quota waiting rather than remote generation alone.
A 75% engineering pacing target is not a guarantee about instantaneous provider
rolling windows; prompt estimates can exceed that target.

## Optional independent scopes

The opt-in implementation maps verified distinct slot-1/slot-2 secrets to
`groq:account-1` and `groq:account-2`. Secret equality is checked in memory; keys
are never persisted as scope names. An unknown credential is rejected. A slot-0
credential equal to a known key resolves to that account's scope.

Activation is an explicit administrative operation through
`app.llm.account_scopes.activate(sessions)`, with workers and in-flight inference
quiesced. It rejects existing ownership/in-flight work, copies legacy usage
conservatively into each account scope, preserves old balances and writes the
`groq:scope-v1` policy marker. Old global workers are fenced after activation;
scoped callers fail before activation. Database locks are short and do not span
inference. Repeated activation and unsafe partial policy states fail closed.

This policy has isolated PostgreSQL regression coverage and has **not** been
activated on the main application database. No production throughput improvement
is claimed. Rollback requires reviewed reconciliation of balances and workers;
do not delete the marker or reset usage. See [testing](TESTING_AND_QUALITY.md).

## Queue admission and Gonka

The report worker checks known Groq/OpenRouter cooldown and exhausted-request
reset state before claiming a queued job. A deferred claim does not acquire a
lease, spend an attempt or start the analysis deadline. The check uses retained
role assignments when available. It does not predict every provider quota, and
the earliest queued job can delay later jobs while its provider is cooling down.

Gonka shares transport admission across roles/processes using the same database,
with a configured 10.5-second interval. The process-local coordinator uses the
same interval. These intervals are engineering pacing, not verified account
entitlements. Gonka is currently absent from the report queue pre-check, so its
waits occur after a claim and consume the request budget. The detailed numeric
provider-metrics collector also currently covers Groq/OpenRouter only; do not
interpret absent Gonka metrics as zero usage or zero wait.

Groq HTTP 400 with `json_validate_failed` is a generation validation failure;
extraction/selection may use the existing single corrective graph attempt. This
is distinct from an automatic transport retry. Generic HTTP rejection, rate
limits and daily quotas do not enter this correction path. Preserve original
attempts, deadlines and provider balances. See [generation settings](model-generation-settings.md).

---

[Documentation index](README.md) · [Project overview](../README.md)
