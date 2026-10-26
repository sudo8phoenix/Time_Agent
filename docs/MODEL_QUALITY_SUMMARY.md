# Model quality summary

26 October follow-up: [Four-model role comparison](FOUR_MODEL_ROLE_COMPARISON.md) records the saved role matrix and
updated-adapter DeepSeek planner retest. It is a single-report contract rehearsal,
not 64 durable graph runs or a replacement for repeated workflow evaluation.
DeepSeek and GPT-OSS 120B selectors each scored 30/30 identities across extractor
outputs; Qwen and GPT-OSS 20B each scored 29/30. The compactness-first ranking
therefore does not mean DeepSeek lacks a role advantage.

Updated 22 October 2026. The [complete model and prompting report](MODEL_AND_PROMPT_COMPARISON_REPORT.md) is the consolidated reference; [exact prompts](MODEL_PROMPT_CATALOG.md) are retained separately.

**All GPT-OSS 20B is the strongest cost-focused baseline among the configurations that completed every planned report correctly in this test.** It matches the 4/4 scoped outcomes of both mixed configurations at the lowest listed token rates. **All-Qwen passed 2/4** and failed the full selection schema on both unambiguous cases. This changes the practical interpretation of the earlier simplified Qwen worker wins: Qwen is a promising component challenger, but its current full worker configuration needs compatibility work. Observed lowest known latest-cohort spend among fully passing configurations: **All 20B**, $0.00265643 for four comparisons; this small descriptive cost result is not a billing guarantee.

| Configuration | Exact planned reports | Key1 / key2 exact | All report attempts | Median completed report time | Known latest-cohort cost | Below 120s |
|---|---:|---:|---:|---:|---:|---:|
| All 20B | 4/4 | 2/2 / 2/2 | 4 | 324.594s (4 completed) | $0.00265643 | 0/4 |
| 120B + 20B | 4/4 | 2/2 / 2/2 | 4 | 324.918s (4 completed) | $0.00303638 | 0/4 |
| Qwen + 20B | 4/4 | 2/2 / 2/2 | 5 | 304.375s (4 completed) | $0.00311070 | 0/4 |
| All Qwen | 2/4 | 1/2 / 1/2 | 5 | 333.109s (2 completed) | $0.01913840 | 0/4 |

Costs cover the latest result for each of four planned comparisons, including failures. Earlier failed/recovery attempts remain in separate total-window accounting. All-Qwen timing includes only its two ambiguity successes. These are known list-price estimates, not complete billing or an equal completed-report timing population.

These are two consumed synthetic reports repeated across key assignments. Qwen's all-role failures are at the full selection schema, not a failed supervisor decision. Both ambiguous all-Qwen reports passed. The original HTTP503 and bounded same-key rerun remain retained. Earlier mixed Qwen/20B owner-attributed network failure also remains separate. Active model assignments are unchanged.

## Earlier projected worker tests

Qwen extraction 12/12 versus 20B 10/12; Qwen selection 8/8 successful outputs versus 20B 6/8, plus retained HTTP503; supervisor-only Qwen/120B 6/6 each. These simplified schemas did not establish full worker integration. Earlier 20B selection followed injected source instructions on both keys; the latest two-case graph test does not close that safety requirement.

## Prompting evidence

On a six-case projected task, fixed and training-only dynamic examples both reached 6/6; plain 20B was 3/6, tailored rules 4/6 and plain 120B 6/6. On a different eight-case full-schema metric, three demonstrations improved 1/8 to 3/8 but did not reach acceptance. Medium reasoning, one feedback repair and bounded consistency/critic trials showed no general quality gain. Strict-mode compatibility remains schema-dependent. The full report preserves denominators, prompt settings, evidence links and limitations.

No production release or best overall semantic model is established. All configuration decisions require broader reviewed data, security/abstention testing, fresh validation/holdout and readiness checks. See the [checklist](MODEL_COMPARISON_CHECKLIST.md) and [execution history](../evaluation/fixtures/model-comparison-2026-10-22/README.md).

---

[Documentation index](README.md) · [Project overview](../README.md)
