# OpenRouter free planner smoke test

Each trial used the existing application adapter and `validated_decision` with a synthetic legal action. Catalog checks confirmed the six exact IDs and zero prompt/completion prices before inference. Runtime settings and credentials were unchanged.

| Exact model ID | Valid actions | Median successful latency | Result |
| --- | --- | --- | --- |
| `nvidia/nemotron-3-super-120b-a12b:free` | 3/3 | 1.428 s | Passed |
| `google/gemma-4-31b-it:free` | 0/1 | — | HTTP 429 |
| `google/gemma-4-26b-a4b-it:free` | 0/1 | — | HTTP 429 |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 3/3 | 3.892 s | Passed |
| `nvidia/nemotron-3.5-lightning:free` | 3/3 | 6.784 s | Passed |
| `nvidia/nemotron-3.5-super-vl:free` | 3/3 | 0.625 s | Passed |

Gemma trials stopped at their first HTTP 429; no credentials were rotated and no retry or paid fallback was used. HTTP 429 does not invalidate the key or demonstrate model quality.

Super VL was fastest in this small sample; Nemotron 3 Super also passed with low latency. This verifies basic planner JSON/transition compatibility only. It does not measure extraction accuracy, schedule matching, adversarial robustness, or sustained availability. Model-assisted orchestration remains disabled, and the production planner allowlist/configuration has not changed.

Reproduce (uses the configured key without printing it):

```sh
.venv/bin/python -m evaluation.openrouter_free_smoke --output /tmp/openrouter-planner.json --phases 3 --timeout 35
```
