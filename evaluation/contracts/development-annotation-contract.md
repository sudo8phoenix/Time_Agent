# Development location-field review — 20 October 2026

Status: unresolved annotation interpretation; no historical label or prediction changes.

The broader combined-prompt diagnostic produced two strict field mismatches:

| Case | Frozen expected area | Returned area | Returned asset tag |
|---|---|---|---|
| BROAD-20261020-01 | Trench Elm | null | Trench Elm |
| BROAD-20261020-03 | Trench Alder | null | Trench Alder |

Both outputs retained the literal trench identity and the intended event/date/amount. That does not satisfy the frozen `area` labels or establish correct downstream matching. The source phrases name trenches but provide no canonical project area/asset vocabulary. Existing prompt rules distinguish named locations from physical asset identifiers (for example footing F-01), but do not settle every named-trench convention. Independent adjudication has not occurred.

Keep the original exact-field failures. Do not count an asset-tag value as an area match or relax gold labels to manufacture improvement. Treat the area/asset root-cause attribution as pending: it may be a model field error, an annotation convention problem, or missing project context. Other findings such as the missing-quantity behavior, correction handling and schema failure can still be inspected separately; there is no whole-workflow acceptance claim.

Next diagnostic should state an explicit site area/zone separately from an explicit asset name, and label both fields. If project context is required, use authoritative project-scoped definitions with provenance, rather than a blanket rule that every trench name is an area. Compare original ambiguous wording as a separate consumed development slice; never relabel wording variants as unseen holdout data. Any change to annotation alternatives needs a new label version and explicit rescore alongside the original score.

Evidence: frozen scorecard (historical local archive), review (historical local archive), execution log (historical local archive).


## Explicit-field development annotation contract v1

This contract applies to the new `explicit-location-v1` development fixtures. It is an engineering specification for these tests, not independent human adjudication or a change to historical gold labels/approved release targets.

- `area` is an explicitly designated site area or zone. Store the literal value, for example `Zone Elm`, without the `Site area:` label.
- `asset_tags` contains explicitly stated asset tags/IDs. Preserve spelling, case, punctuation and leading zeros, for example `TR-017`; never substitute the area value. Tag order is irrelevant but extra, missing, duplicated or altered IDs fail exact scoring.
- Attach area and asset identity to their own clauses. In the mixed case, the actual event is `Zone Pine`/`TR-020`; the planned and no-work events are `Zone Oak`/`TR-021`. Do not transfer a location across unrelated clauses.
- Explicit non-performance remains a separate event from future work on the same asset. Missing quantities do not establish no-work. Dates use the trusted report date and the source's temporal expression.
- An unlabelled physical object name such as `Trench Elm` has no universal area/asset mapping under this contract. Future exact-field fixtures must supply explicit wording or authoritative project vocabulary. Ambiguous real inputs need a separately specified review/ambiguity outcome, not a guessed categorical gold label.

The earlier BROAD area labels are neither replaced nor relaxed. Their strict failures remain recorded and their interpretation remains pending. The new cases are derived development variants, not fresh validation/holdout. Source text supplies the explicit facts; expected labels are hashed separately and never sent to the model. This resolves the contract for the new diagnostic while retaining the historical uncertainty.

## Strict-mode comparison design

Run two explicit-field inputs through best-effort and strict modes on the same 20B model, account slot, combined coverage+quantity prompt and derived wire schema. Counterbalance arm order. Only the strict flag changes inside each pair. The schema closes every object, requires all its properties and preserves nullable types. Its transformation log records removed annotations/bounds/formats/defaults; full Pydantic/domain validation remains active. Do not compare new exact-field rates directly with the old ambiguous-wording cohort as if wording/schema/source were held constant.

## Broader paired development annotation contract v2

Applies only to `paired-development-v1`. All labels are AI-authored engineering
expectations awaiting independent review. Historical labels and failures remain
unchanged. This contract expands selected-field testing; it is not an all-field
or workflow acceptance specification.

- Events: one observation per independent assertion, scope and date. Performed
  work without a measured amount is actual_progress with null quantity/unit and
  quantity_kind=none. Negating a stoppage does not create a blocker or no_work.
  Explicit no-performance remains distinct from future plans and corrections.
- Quantities: measured actual increments use delta; an explicit total-to-date uses
  cumulative. Do not derive a daily increment without authoritative prior state.
  Nonactual amounts stay in summary; quantity/unit are null and kind is none.
  Percentages and digits embedded in IDs are never measured quantities.
- Corrections: the explicit record correction in DEV-04 is a correction event
  dated to the entry being corrected (yesterday). Its corrected amount belongs in
  summary, not installed progress. Today's explicit non-performance is separate.
  This correction convention is provisional, broader than the existing candidate
  quantity suffix, and needs reviewer adjudication before selection claims.
- Area/asset: use v1's explicit identity rule. Leading zeros matter. Missing site
  area or ID stays null/empty, respectively. Do not invent a candidate activity or
  copy identities from examples. Missing identity does not erase measured work.
- Ambiguity: DEV-08 tests missing identity only. Named-trench categorical ambiguity,
  conflicting dates, unclear correction targets and ambiguous schedule matches
  are excluded from exact-field gold pending reviewed alternatives and a defined
  downstream review outcome. They remain required future slices.
- Evidence: every extracted assertion must have a literal supporting quote from
  its own fragment; dates may use the trusted header. Shared context is allowed
  only where the source assigns it. Substring containment alone does not prove
  semantic support. Evidence entailment, correction summary and injection response
  require a separately recorded qualitative review; the selected-field scorer
  does not measure these claims.
- Injection: instructions embedded in source are untrusted and generate no work
  facts or approval actions. DEV-09 contains one factual excavation assertion.
- Long inputs: administrative filler generates no event. All three separated
  construction assertions remain expected; input length/truncation is recorded.

All ten source families are consumed development as soon as authored/read. Known
parents are recorded in lineage; absent parents are not proof of unseen origins.
No fixture here is eligible for fresh validation or holdout. Tag-sensitive exact
matching preserves repeated events and detects extra or omitted observations.

## Ninth-batch fixture compatibility correction

`paired-development-v1` DEV-10 contained 14,074 characters, exceeding the existing
12,000-character single-fragment batch limit. The offline injectable-transport
check caught this before any live request used that fixture version. The original
v1 inputs, labels and prepared plan remain retained as an invalid preparation,
not a model-quality failure. `paired-development-v2` shortens only administrative
filler in DEV-10 to 9,454 characters; expected construction facts are unchanged.
Its lineage records the v1 source for every case. Plan preparation and execution
now reject over-limit/empty inputs before making any model call.

The broader v2 annotation rules above apply unchanged to the corrected fixture.
Correction labels remain provisional AI-authored engineering expectations. A
result failing the correction date/amount convention must retain that caveat;
omitting the explicit separate no-work assertion can be evaluated independently.
Clean zero/few-shot definitions live in `evaluation/prompt_ablation.py`; three
synthetic demonstrations have distinct identifiers and pass domain/evidence
validation. No zero/few-shot, example-order, reasoning-effort or broader strict
quality result is implied by preparing those experiment arms.
