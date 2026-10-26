# Recorded generation settings — 26 October 2026

Scope: current repository adapter wire behavior, not a claim that any remote
model currently supports every provider parameter. MODEL-01/02 live capability
checks remain required. Source hashes and actual wire payloads belong in every
experiment. Temperature zero reduces variation but does not guarantee identical
outputs; repeated trials remain necessary.

| Adapter | Default temperature | Effective output/context | Reasoning settings actually sent |
|---|---|---|---|
| Groq application adapter | 0.0, trusted `temperature` override | `num_predict` defaults to 8112 and becomes max_completion_tokens, capped at 8112; num_ctx is not sent | `reasoning_effort=low` for names starting `openai/gpt-oss-`; absent for other models. A settings reasoning_effort value does not override this. |
| OpenRouter application adapter | 0.0; trusted override validated from 0 through 2 | num_predict becomes max_tokens, capped at 1536; num_ctx is not sent | No explicit reasoning parameter sent. It does not implement a reasoning-effort override. |
| Gonka application adapter | Same bounded JSON contract as OpenRouter | num_predict becomes max_tokens, capped at 4096 (default 1536); num_ctx is not sent | No explicit reasoning parameter sent. The 26 October [role comparison](gonka-role-comparison.md) records one incomplete MiniMax planner response. |
| Ollama application adapter | 0.0; trusted options map | num_ctx=8192 and num_predict=1536, each capped at that bound | Top-level think=False by default; a trusted constructor can set True or None (omit). Additional trusted settings pass through the options map; remote support must be verified separately. |
| Repeated development harness | Frozen per-arm temperature/settings in prepared plan | Plan pins output tokens, wire schema, request deadline and strict flag; this is a separately controlled request path | Frozen reasoning_effort (low by default) can be explicitly set in the preregistered harness. Do not attribute those experimental settings to application adapters. |

Application adapter construction selects zero retries. Local standalone adapter
constructors permit at most one retry where configured, which is not an automatic
application fallback. Compact shortlist/selection requests explicitly set
num_predict=768 and temperature=0. Default extraction and noncompact selection use adapter defaults. The bounded
V2 planner explicitly requests num_predict=128. The four-model matrix extraction
explicitly requests 4096. No seed or determinism guarantee is recorded.

Injected-transport tests in `test_recorded_generation_settings.py` inspect actual
payloads for the application defaults and reasoning switches without inference.
Existing repeated-plan/runtime tests pin experiment settings. SPEC-15 is complete
for this current source's settings inventory; choosing budgets from measured
valid response sizes (SPEC-14), caching (SPEC-16), capability support, reasoning
ablations and model quality remain open.

---

[Documentation index](README.md) · [Project overview](../README.md)

The Groq application adapter uses strict structured output for GPT-OSS 20B/120B and Qwen 3.8 27B
when the schema contains only closed objects. Provider schemas require every
declared field, normalize nullable enum unions, and omit bounds and formats
unsupported by constrained decoding. The original schema and application models
continue to validate responses locally. Other models and open-ended map schemas
retain best-effort output. Response diagnostics distinguish truncation, invalid
JSON, schema mismatch, refusal, and invalid response envelopes without recording
raw model output.

HTTP rejections retain numeric status counts and an allowlisted provider error
code in saved provider metrics. Raw provider error messages and failed generations
are never saved or exposed. Planner calls use the same durable tool diagnostics;
Groq completion finish reasons are allowlisted. HTTP rejections are categorized as
`MODEL_REQUEST_FAILED`, while invalid successful responses retain their specific
output categories. Extraction and selection failure categories reach the terminal
job error instead of being reduced to `AGENT_TOOL_FAILED`.

Strict Qwen support follows the current [Groq supported-model list](https://console.groq.com/docs/structured-outputs).

Daily-token/request rejections use `MODEL_QUOTA_EXHAUSTED` and retain only quota
kind and numeric limit/used/requested values. The job failure stage reflects the
failing operation rather than always reporting persistence. No quota counters or
existing run checkpoints are reset.

Groq HTTP 400 with the allowlisted `json_validate_failed` code is a generated-output
schema failure, not a network timeout. Extraction and selection use their existing
single corrective graph attempt to request a fresh generation. Both attempts are
charged and journaled separately; persistent rejection stops at the existing retry
limit. Generic HTTP 400, authentication failures, rate limits, and daily quota errors
do not enter this retry path. No malformed output is salvaged, and the original
schema, evidence validation, deadlines, and budgets remain in force.

Gonka strips only a complete JSON code fence before local schema validation;
prose, partial fences and truncated completions are not salvaged. The
[four-model comparison](FOUR_MODEL_ROLE_COMPARISON.md) preserves the initial
DeepSeek planner failures and the independent updated-adapter retest. A larger
adapter cap does not override the planner’s explicit 128-token budget.
