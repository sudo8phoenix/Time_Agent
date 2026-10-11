# GT10 live workflow results

Verified 2026-10-11 against the local running app at http://127.0.0.1:8000.
Project: **GT10 five-activity workflow test** (`a57e01e5-9e4b-4bac-a9a9-7596abb996db`), active schedule version 1. The user authorized access for their cyril account.

Activities, WBS and planned dates originate from GT10. Planned and actual quantities and report narratives are explicitly synthetic test data.

| Activity | Planned quantity | Approved cumulative actual | Physical progress | Approved events |
| --- | --- | --- | --- | --- |
| SUP-GF-01 | 1000 kg | 200 kg | 20% | 1 |
| SUP-GF-02 | 20 m3 | 4 m3 | 20% | 1 |
| SUP-GF-03 | 200 m2 | 40 m2 | 20% | 1 |
| SUP-GF-04 | 3000 kg | 600 kg | 20% | 1 |
| SUP-GF-05 | 50 m3 | 10 m3 | 20% | 1 |

Measurement basis is quantity_ratio for each activity. The five reports passed through authenticated API intake, the live gemma4:12b model, worker processing, source/match checks, authorized review, the event ledger, progress calculation, CSV export, and a project-scoped mock PMIS connector. All five deliveries were independently read back from the receiver with matching state and revision.

Safari confirmed the review queue, fifth warning resolution and approval, then the final progress screen: five activities, five approved events, zero pending review, all expected quantities and all five delivery receipts verified. Import and report submission were performed through the app API; the fifth approval was performed through the browser.

Repeating all five report submissions reused their original report/job IDs. Repeating the first four approval requests returned identical responses. Each activity still has exactly one approved event; no quantity was double-counted.

The fifth report's cumulative-quantity warning was resolved with a documented source-supported revision before approval. Actual start/finish dates and lifecycle status were not asserted by these quantity-only reports; the source Not Started status remains. This verifies the quantity workflow, not start/finish or duration processing. Delivery uses the local mock receiver, not an external production PMIS.

Frontend typecheck, contract tests and build passed. Connector integration tests passed (5 tests), including the new project filter that leaves other projects' pending deliveries untouched.

Evidence: [approved CSV](live-approved-export.csv), [progress](live-progress.json), [approvals](live-approvals.json), [receiver readbacks](live-deliveries.json), [duplicate submissions](duplicate-submissions.json), and [source provenance](validation.json).

App, worker and scoped connector were left running for review. In the app, select this project and open **Approved progress**.

## Natural-language percentage report follow-up

The user submitted “slab reinforcement in ground floor is 50% done . date is 19th oct 2026”. Job `9c08f453-476f-45eb-88be-6bcf4b77f758` initially failed because the model also supplied an unsupported unitless quantity of 0.5. Extraction now preserves exact-source percentages and discards this inferred quantity, and its prompt explicitly separates percentage from quantity. Regression tests cover source validation, measured amounts and distinct percentages; 35 extraction/lifecycle/matching/ledger tests passed. Frontend typecheck/build passed, and the intake writing hint was checked in Safari.

The original job was retried with the live model and succeeded: pending proposal `07e09ad5-ac6c-4bef-b838-74400ac38491` matches SUP-GF-04, reports 50%, has date 2026-10-19, and contains no invented quantity. It remains pending for the user. Quantity-based approval still requires measured quantity; percentages are not silently converted to mass/volume. Evidence: [percentage retry](percentage-retry.json).
