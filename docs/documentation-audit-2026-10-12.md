# Documentation reconciliation — 12 October 2026

The repository's Markdown documentation, current runtime instructions, release/task
status, evaluation evidence links and generated API contract were reviewed against
the application source and saved measurements. Current guides are listed in the
[documentation index](README.md). Dated implementation/verification records retain
their historical evidence and have supersession pointers where runtime behavior changed.

## Findings and updates

| Finding | Correction |
|---|---|
| Main guides omitted completed Gemma quality measurements | README, release, task state, E02/E03 and the V2 checklist now reference all 60 cases, five false matches and the scope limits |
| Runbook described embedding/lexical candidate retrieval | Replaced with the current model-led shortlist and selection path in `agent/schedule_decision.py` |
| Dated handoffs could be read as current legacy/rollback instructions | Added explicit historical/runtime supersession notices and current guide links |
| Graph-only handoff still promised later test totals | Linked the recorded 233 unit / 124 integration / 44 browser / 11 final regression results |
| API contract omitted current agent-run status route | Regenerated OpenAPI from `app.main.app`; all 50 path entries now match the application |
| V2 checklist described both processors and old current test counts | Updated graph-only operation and current recorded counts; independent acceptance stays unchecked |
| V2 checklist linked an absent original TODO | Identified that source as historical and absent instead of publishing broken links |
| Results-only push left evidence links and scoring commands unavailable on GitHub | Identified runners, raw captures and combined evidence as local-only; replaced GitHub links to unpublished artifacts with local path references |
| Evaluation smoke digest contained a transcription suffix error | Corrected it to the digest in the saved smoke record |
| Existing held-out assignments could be confused with frozen release splits | Added the distinction to split, calibration and target documentation |

## Verified measurements and limits

The combined compact benchmark uses original batches 1–4 and post-restart reruns
of batches 5–6 with unchanged model/runtime/prompt/settings. All 60 cases returned
outputs. Matchable activity choice is 44/45, all-selection precision 44/49, stated
quantity accuracy 36/36 and unmatched safe abstention 10/15. Five unmatched inputs
received unsupported activity selections. Batch six's ten repeated outputs were
unchanged. See [results](../evaluation/RESULTS.md) for units, missing-value formatting,
event conventions, timing, source-locator corrections and individual errors.

These are real model calls on existing synthetic inputs using a compact prompt
with the full schedule. They do not measure actual shortlist Recall@8, atomic F1,
complete graph-runtime accuracy or UI-to-export timing. Independent human review,
reviewed split freeze, calibration, target agreement, complete unseen evaluation
and the owner sample package remain pending. Draft targets were not retuned.

## Checks performed in this reconciliation

- Reviewed 86 Markdown files, including the current guides, dated handoffs, V2 checklist and archived preliminary results; local Markdown link targets resolve. Links in the documentation-only publication are additionally checked against files included in Git.
- Generated `docs/api-contract.json` directly from the application OpenAPI and checked exact equality, including its 50 path entries. No running API or database was needed.
- Validated the nine captured retry/combined artifact SHA-256 entries against the saved provenance record.
- Rescored all 60 saved combined cases with split and exact case-identity validation; no model requests or database writes were needed.
- Existing `backend/tests/unit/test_evaluation_metrics.py`: 13 passed.
- Ruff checks for the three locally retained evaluation runners/scorer passed; `git diff --check` passed.

The application regression counts above are prior recorded checks, not newly rerun
full application tests. This documentation-only reconciliation leaves synthetic evaluation tooling/evidence
in the original local workspace; it does not change application
behavior or declare a release gate passed.
