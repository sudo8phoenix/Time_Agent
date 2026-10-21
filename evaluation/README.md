# Evaluation tools

Use [testing and measured quality](../docs/TESTING_AND_QUALITY.md) for completed
checks, model results, incidents and open acceptance gates. This directory holds
runners/scorers and small reproducible fixtures. Generated results belong under
`evaluation/results/`, which is ignored. Historical archives remain local.

## Software checks and live studies

Unit and integration tests use deterministic or injected models. Live evaluation
consumes provider quota and is a separate operation. Read a runner's help before
use from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m evaluation.frozen_acceptance --help
PYTHONPATH=backend .venv/bin/python -m evaluation.score_frozen_acceptance --help
```

| Module | Purpose |
|---|---|
| `extraction_quality`, `delivery_matching` | Component extraction/matching studies |
| `frozen_acceptance`, `score_frozen_acceptance` | Real worker capture and separate sealed offline scoring |
| `account_pair_study`, `account_pair_pipeline` | Bounded account/model component and V2 graph comparisons |
| `study_controls`, `experiment_controls` | Prerequisites, source identity, budgets and study integrity |
| `sealed_measurements` | Offline accounting from sealed captures, including failures and unknown usage |
| `calibrate` | Offline confidence study; does not install a runtime policy |
| `mixed_workload` | Bounded report/conversation rehearsal in an isolated local database |
| `full_approval_delivery_latency` | Browser approval through durable commit and HTTP MOCK delivery |
| `release_gate_review` | Fail-closed numerical review; never grants release approval |

Other diagnostic modules remain available for specific development contracts.
Historical audit utilities can require local archived inputs; these are not a
prerequisite for running the application or its standard regression suite.

## Study rules

1. Freeze source, dependencies, input groups, labels, model/prompt settings and
   call/token/time/spend budgets before inference. Verify provider/account limits.
2. Use a new output directory and an explicitly isolated database. Preserve
   original failures, reservations and consumed budgets; never reset a stopped run.
3. Keep labels out of inference. Seal initial responses and normalized proposals
   before offline scoring. Unknown usage/cache/spend stays unknown.
4. Treat exposed inputs as consumed. Do not tune on a holdout or relabel an old
   development comparison as fresh acceptance. AI review is not independent human review.
5. Require representative quality, safety and sustained-workload evidence before
   an explicit release decision. The application remains a local prototype.

## Contracts and fixtures

[contracts/](contracts/) contains the owner-approved numeric targets, evaluation
units, scoring/safety/split contracts, calibration policy, development annotation
conventions and historical data-review context used by tooling. These are
technical inputs, not release certificates. Dates and historical exposure labels
inside them remain part of the original contracts.

[fixtures/](fixtures/) contains public/synthetic test inputs and labels.
[Regression fixture provenance](fixtures/regression/README.md) explains the small
sealed captures kept for offline tests. Full run logs, screenshots and source
snapshots are intentionally excluded from Git. They remain local without being
required by a fresh checkout.
