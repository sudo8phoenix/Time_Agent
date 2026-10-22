# Model-comparison checklist — 22 October 2026

This maintained public checklist records the latest study dispositions. The full dated execution checklist remains local: its corrected inventory has **269 requirements, 231 checked and 38 open**. Qwen evaluation is uniquely MODEL-11; lifecycle/deprecation keeps MODEL-10. No new whole-requirement closure or production acceptance is claimed by this publication.

## Completed bounded study work

- [x] Freeze exact models, role/key assignments, source inputs, schema/settings and budgets before inference.
- [x] Run all-20B, 120B/20B, Qwen/20B and all-Qwen on the same two consumed synthetic reports with both key assignments.
- [x] Separate HTTP/schema validity from scoped facts/mapping and complete workflow success.
- [x] Preserve all 18 attempts, including original network/HTTP503 failures and bounded same-key recovery.
- [x] Verify pending review, zero study ledger writes and duplicate-free successful terminal replay.
- [x] Rescore persisted outcomes, verify exact prompts, separate known cost from unknown failed-request usage and retain conservative reservations.
- [x] Record zero/few-shot, fixed/dynamic examples, instruction/quantity/coverage ablations, strict output, reasoning effort, repair and critic results with their original denominators.
- [x] Publish sanitized evidence, an offline rescorer and the complete report; keep raw transport/source archives local.

## Still open

- [ ] MODEL-05: Select a configuration on representative reviewed reports and frozen quality/security/readiness gates.
- [ ] MODEL-11: Resolve full Qwen selection-schema compatibility, then re-evaluate broader worker correctness and robustness.
- [ ] Compare explicit full-object selection examples, supported strict schemas and Qwen reasoning modes in separate frozen arms.
- [ ] Repeat full-graph no-work, correction, future-work, lifecycle, unreadable, unmatched and injected-input cases.
- [ ] Establish independent human gold, genuinely fresh validation/holdout and complete exposure accounting.
- [ ] Meet the 120-second report-readiness target under production-equivalent admission/load and verify complete product flows.
- [ ] Make an explicit production candidate/release decision; active assignments remain unchanged.

All-20B is a cost-focused development baseline on these cases, not an established universal quality winner. Earlier 20B injection/negation errors remain relevant. All-Qwen passed 2/4 and has a current selection-contract limitation.

[Complete comparison](MODEL_AND_PROMPT_COMPARISON_REPORT.md) · [Quality summary](MODEL_QUALITY_SUMMARY.md) · [Published evidence](../evaluation/fixtures/model-comparison-2026-10-22/README.md) · [Inventory record](../evaluation/fixtures/model-comparison-2026-10-22/checklist-inventory.json).
