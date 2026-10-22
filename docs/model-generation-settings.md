# Recorded generation settings — 21 October 2026

Scope: current repository adapter wire behavior, not a claim that any remote
model currently supports every provider parameter. MODEL-01/02 live capability
checks remain required. Source hashes and actual wire payloads belong in every
experiment. Temperature zero reduces variation but does not guarantee identical
outputs; repeated trials remain necessary.

| Adapter | Default temperature | Effective output/context | Reasoning settings actually sent |
|---|---|---|---|
| Groq application adapter | 0.0, trusted `temperature` override | `num_predict` becomes max_completion_tokens, capped at 1536; num_ctx is not sent | `reasoning_effort=low` for names starting `openai/gpt-oss-`; absent for other models. A settings reasoning_effort value does not override this. |
| OpenRouter application adapter | 0.0; trusted override validated from 0 through 2 | num_predict becomes max_tokens, capped at 1536; num_ctx is not sent | No explicit reasoning parameter sent. It does not implement a reasoning-effort override. |
| Ollama application adapter | 0.0; trusted options map | num_ctx=8192 and num_predict=1536, each capped at that bound | Top-level think=False by default; a trusted constructor can set True or None (omit). Additional trusted settings pass through the options map; remote support must be verified separately. |
| Repeated development harness | Frozen per-arm temperature/settings in prepared plan | Plan pins output tokens, wire schema, request deadline and strict flag; this is a separately controlled request path | Frozen reasoning_effort (low by default) can be explicitly set in the preregistered harness. Do not attribute those experimental settings to application adapters. |

Application adapter construction selects zero retries. Local standalone adapter
constructors permit at most one retry where configured, which is not an automatic
application fallback. Compact shortlist/selection requests explicitly set
num_predict=768 and temperature=0. Default extraction, noncompact selection and
planner use adapter defaults. No seed or determinism guarantee is recorded.

Injected-transport tests in `test_recorded_generation_settings.py` inspect actual
payloads for the application defaults and reasoning switches without inference.
Existing repeated-plan/runtime tests pin experiment settings. SPEC-15 is complete
for this current source's settings inventory; choosing budgets from measured
valid response sizes (SPEC-14), caching (SPEC-16), capability support, reasoning
ablations and model quality remain open.

---

[Documentation index](README.md) · [Project overview](../README.md)
