# Deterministic scoring and escalation contract

Audited 21 October 2026, batch twenty. Owner: Codex under the implementation
request. This is AI-assisted engineering review of known-answer controls; it is
not independent adjudication of construction reports or release acceptance.

## Alignment before field scoring

| Scorer | Event identity and ordering | Limits and failure behavior |
|---|---|---|
| `metrics.atomic_extraction` | Case-scoped multiset of explicit nonempty EVENT_FIELDS; event type plus one discriminating attribute required | Full signatures are exact, including annotated field inventory. Reordering changes nothing; duplicates retain multiplicity. Incomplete identity withholds precision/recall/F1; counts describe only alignable events. Failed predictions supply no successful events. |
| `score_paired_pilot.event_scores` and repeated development | Multiset of event type, work date and area | Coarse event diagnostic only: cannot establish asset/quantity/evidence correctness. `fields_exact` is the complete selected-field gate. Failed normalized payloads earn no event credit, including empty expected outputs. |
| `score_paired_pilot.fields_exact` | Multiset of whole selected-field tuples: event type, work date, area, quantity, unit, quantity kind; asset tags/date basis/summary/evidence when explicitly annotated | Repeated types align as whole tuples. No per-field mixing across events. Asset-tag order is irrelevant but duplicates/leading zeros are retained. Decimal quantity normalization is explicit. Missing and JSON null differ. Mixed optional annotation inventories raise. Unannotated fields are outside this score. |
| `score_frozen_acceptance` | Event type within the case; each frozen reference permits at most one event of each type | Repeated expected types raise rather than use row order. Multiple predictions of one type cannot supply a unique field match. Initial successful extraction and ready normalized proposals are scored separately. Missing fields never match explicit nulls. |
| `development_contract.score_case` | One complete explicitly enumerated alternative at a time, through `fields_exact` | Alternatives must have the same field inventory. No cross-alternative cherry-picking; semantic evidence support remains unmeasured. |

These are exact alignment contracts, not semantic similarity algorithms. A
correctly paraphrased summary can fail a verbatim summary label. Coarse event
agreement cannot substitute for critical-field correctness. New event identities
or acceptable alternatives require new versioned labels/scorers and separate
rescores; frozen historical evidence stays unchanged.

## Known-answer review and deterministic boundaries

The batch-twenty closure matrix uses explicit independently calculated expected
counts: one exact event/ID gives TP=1/FP=0/FN=0 and selected precision=1; changing
only the ID to INVENTED gives selected precision=0; dropping the event gives
TP=0/FN=1; duplicating it gives TP=1/FP=1. String "null" cannot match a null
quantity. Failed/cancelled/conflicting-status saved outputs retain their scheduled
case and earn zero normalized event/field credit. A successful explicit empty
observation list can pass an empty reference; a failed or absent list cannot.
Paired duplicate scheduled cases are rejected instead of multiplying support.

`test_scorer_closure_matrix.py` exercises public general, paired, repeated and
frozen scorer paths. Existing evaluation/frozen/paired/annotation suites verify
unmatched false positives, known wrong IDs, omissions, extra events, nulls,
permutations, repeated types and sealed/missing captures. Exact enum/date/quantity
and nested-schema validity use the Pydantic domain models and local wire-schema
validator. `test_extraction.py` checks literal quote containment, fragment
membership and locator repair without inventing quotes. Durable conversation,
review, agent and outbox integration checks use database state and receiver
acknowledgements for writes/approvals/delivery; scorer prose is not evidence of a
side effect.

SCORE-01/02/03/04 are complete for the repository's documented deterministic
contracts and finite known-answer matrix. This does not establish correct gold
labels, semantic entailment, all future scorer correctness or representative
model quality. Domain and data checks remain separate open requirements.

## Judge policy (SCORE-05)

Use deterministic checks for identities, exact fields, enum/schema validity,
evidence containment and durable effects. Reserve any future LLM judge for
semantic support, equivalent paraphrases or qualitative usefulness that those
checks cannot settle. A judge cannot override hard safety gates, repair gold
labels, count a failed output as abstention or establish a durable effect.
There is currently no enabled LLM judge in this evaluation pipeline. Before
introducing one, complete SCORE-06/07/08: reviewed domain labels, identity blinding,
order/style controls, versioned prompts and measured agreement, with critical
disagreements adjudicated. This policy completes SCORE-05 only.

## Bounded escalation outcomes (MODEL-08)

| Observation | Permitted outcome | Bound and authority |
|---|---|---|
| Valid extraction and supported supplied candidate/evidence | Retain validated result as a pending proposal | It is available for human review, not approval or delivery. |
| Decisive identity/date/context absent | Deterministic conversation clarification, or ambiguous/unmatched proposal with missing information | Wait for a new immutable turn; never invent a fact, ID or write. Empty candidate set abstains without calling selection. |
| Plausible alternatives or unresolved field/evidence conflict | Leave for review | No silent auto-selection, reviewer impersonation or automatic model promotion. |
| Inconsistent mapping state/candidate | At most one consistency repair, then validate or stop | Two selection calls maximum; unknown IDs/evidence and invalid outputs fail. |
| Missing tool, invalid configuration, safety/integrity failure, unsupported response, exhausted deadline/budget | Stop with retained failure/checkpoint | No alternate credential/model/provider selected by failure. |
| Transient transport/admission/429 | Existing durable retry policy within original attempt/call/deadline/configuration | Cooldown releases ownership; daily quota/configuration/invalid output stops. No transport-level retry in application-created adapters. |

The planner may only confirm its single server-supplied legal supervisor action.
It cannot add a tool, escalate approval authority or choose a new model. Existing
retrieval contract, planner, hierarchy and durable retry tests verify these finite
outcomes; deployment/model quality remains unassessed.
