# Hosted provider capacity and failure policy

Implemented and checked 16 October 2026. Hierarchy and model-assisted rollout flags remain false. This is bounded synthetic/local evidence, not a production saturation or multi-worker capacity certification.

## Runtime policy

Production Groq and OpenRouter transports now use PostgreSQL admission by provider across roles, models, key slots and processes using the same database. One bounded lease reserves each provider; cooldowns, pacing and numeric quota state survive process restarts. Short transactions claim and release reservations; no database transaction spans inference or admission sleeps. A stale process cannot release a replacement lease. External clients and deployments using other databases remain outside this coordinator.

Migration `0018_hosted_admission` is required before starting this source version's hosted transports. It was applied only to `progress_test`, not production. A missing or unavailable coordinator fails closed with `MODEL_CAPACITY_TIMEOUT`; it does not silently switch to process-local admission. Leases expire after two remaining socket-timeout windows plus five seconds for crash recovery. Backup/restore manifests include this private operational table.

Starts retain minimum intervals of 2.1 seconds for Groq and 3.2 seconds for OpenRouter. Groq also spaces estimated request cost against the advertised tokens-per-minute limit. The estimate uses UTF-8 bytes/3 plus reserved completion tokens; it is an approximation, not entitlement or an exact tokenizer. Numeric upstream headers and 429 cooldowns remain authoritative.

Numeric allowlisted headers update remaining-token estimates, reset times, daily request exhaustion and `Retry-After` cooldowns. Queue admission consumes the same timeout budget as network execution: a request that cannot enter within its budget fails safely. Timeouts are finite and bounded to 900 seconds; response bodies are bounded to 2 MiB. Provider error bodies are discarded. Provider credentials, account labels and arbitrary headers are never stored in capacity state or evidence.

The Groq organization is the quota scope, so additional keys are not treated as independent capacity. Its request-limit headers describe daily requests; token-limit headers describe tokens per minute. See [Groq rate limits](https://console.groq.com/docs/rate-limits). The controller deliberately groups all Groq keys together and never rotates them.

Adapters created by the application retain zero transport retries. A 429 becomes a typed retryable `MODEL_RATE_LIMITED` error; a local queue/cooldown timeout becomes `MODEL_CAPACITY_TIMEOUT`; observed daily request exhaustion becomes non-retryable `MODEL_QUOTA_EXHAUSTED`. Durable conversation tasks persist a provider cooldown in `next_attempt_at`, retain the original attempt/call/deadline budgets and release their task lease while waiting. Report runs stop safely and use the existing explicit job retry workflow. Existing semantic repair allowances are separate from these provider failures.

There is no application cross-provider or cross-model fallback. Failures do not select another key, an automatic router, a paid model or a different planner. This fail-closed policy is tested for 429s, timeouts and invalid responses. OpenRouter may route among providers for the same requested model internally; that is distinct from adding fallback models. See [OpenRouter limits](https://openrouter.ai/docs/api/reference/limits) and [model fallbacks](https://openrouter.ai/docs/guides/routing/model-fallbacks).

The default controller's state persists in PostgreSQL. The standalone in-memory gate remains available for deterministic transport tests. Body reads use the remaining request deadline and a 2 MiB limit, including slow trickles; blocked socket operations also have finite timeouts. Operating-system DNS/connect behavior is outside a hard process-kill guarantee. Root/task deadlines remain checked at execution boundaries.

Groq daily request exhaustion clears on its observed reset. OpenRouter epoch-millisecond reset headers are normalized before deriving cooldowns. This fixes a millisecond/second mismatch that could otherwise create an extremely long false cooldown.

## Live evidence

Saved under `evaluation/results/provider-capacity-2026-10-16/`:

| Probe | Result | Duration | Submitted callers | Maximum network concurrency |
| --- | --- | --- | --- | --- |
| Groq `openai/gpt-oss-20b`, original key slot | 8/8 valid responses | 62.784 seconds | 2 | 1 |
| OpenRouter `nvidia/nemotron-3.5-super-vl:free` | 8/8 valid responses | 63.816 seconds | 2 | 1 |

Inference used only the original Groq key. Read-only authentication/model-listing checks returned HTTP 200 for all three configured Groq slots, without exposing their values. Observed Groq headers reported 1,000 requests/day and 8,000 tokens/minute. These values describe this captured account/model observation, not every account or future availability.

The OpenRouter current-key endpoint returned a daily free-model limit of 50, used 38 and remaining 12 before the run. A separate postflight read returned the same counters despite eight successful requests. Accounting freshness/exemptions were not established; unchanged counters must not be interpreted as unlimited quota or proof those calls consume no daily allowance. The catalog verified zero prompt/completion prices and no stated per-request surcharge before inference. No paid fallback was configured or used.

The first capture stopped OpenRouter preflight because the probe initially treated an omitted per-request price as unknown. It made no OpenRouter inference calls. Public catalog inspection showed zero prompt/completion prices and an omitted request surcharge; the corrected OpenRouter-only probe was saved separately. The original stopped capture remains intact.

Production adapter/admission fault tests cover concurrent callers, queue deadlines, token reset and quota exhaustion, cooldowns, release after network errors, response/schema validation, sanitized errors and unchanged key/model/provider identity. PostgreSQL tests verify persisted conversation cooldowns and no automatic daily-quota retry. The live probe did not intentionally exhaust quotas or induce provider outages; those paths use deterministic fault injection.

## Reproduction and remaining gate

```sh
PYTHONPATH=backend .venv/bin/python -m evaluation.provider_capacity \
  --output-dir evaluation/results/NEW_CAPACITY_CAPTURE
```

The CLI permits at most eight calls per selected provider, uses synthetic prompts with 256 output tokens, checks the free model's public catalog, and refuses an existing output directory. It does not change `.env` or either rollout flag.

Shared deployment admission and process-crash recovery are now implemented and fault-tested; before scaling beyond one worker, apply the migration on the intended deployment and measure aggregate workloads there. Before a rollout, measure representative full-report/conversation workloads against agreed latency/failure targets; these small health-check payloads do not certify those workloads. Keep the current fail-closed fallback policy unless an explicit model/provider alternative is selected and separately evaluated.

Final combined regression: 337 unit tests and 165 PostgreSQL integration tests passed after the scoring/date/provider changes. Scoped Ruff and diff checks passed. No rollout flag was enabled and no production migration or deployment was performed.

## Subsequent shared-admission follow-up

The [v11 follow-up record](../evaluation/results/quality-gap-fixes-2026-10-16/FOLLOWUP-v11.md)
supersedes the earlier process-local implementation description. It records
376 unit / 188 integration tests, three-process reservation verification and
explicitly separates live rate limits from coordination correctness. A captured
Groq response imposed a 992-second cooldown even with advertised TPM available;
the specific exhausted quota bucket remains unproven. The latest OpenRouter
preflight reported 49 used / 50 limit / 1 remaining, so the requested two-call
probe performed no inference. Do not treat either provider as ready for sustained
representative workloads on the strength of tiny health checks.
