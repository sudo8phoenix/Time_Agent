# Stage specification v1

Defined 21 October 2026 by Codex under the checklist implementation request.
This closes definition requirements SPEC-01/04/05/07/09. It is a versioned
specification and executable compatibility example set, not proof of model
compliance, a new default prompt, independent adjudication or release acceptance.
Existing prompt versions, raw outputs and labels remain unchanged. Future prompt
candidates must cite this contract and undergo the revalidation policy.

The [authority inventory](model-call-authority-inventory.md) lists reachable
application calls. This document supplies the previously missing common
specification. Historical replay prompts can differ; record their versions and
score those differences rather than silently replacing their instructions.

## Stage tasks, inputs, outputs and abstention (SPEC-01)

| Stage | Available inputs and task | Permitted output and no-result behavior |
|---|---|---|
| Parse/transcribe | Original supported document, parser result and source locators; preserve source text | Ordered source fragments or explicit parse/transcription error. Unreadable content needs human transcription; it is never invented text or successful no-event extraction. |
| Extract | Source fragments and IDs; separately trusted report date/trust flag; produce atomic report observations | `ObservationBatch` only. Supported physical assertions require exact source evidence. `observations: []` is successful abstention only when readable input has no supported facts; refusal, timeout, invalid output and unreadable input are failures, not empty successes. No schedule values or labels are extraction facts. |
| Shortlist | Observation/evidence and permitted rows from the pinned project/schedule; discover plausible identities | Unique supplied candidate IDs within the bounded limit, or `candidate_ids: []`. An empty result has one bounded reconsideration; invented IDs fail. Retrieval grants no write or approval authority. |
| Select | Observation, legal candidates and report fragment map; select a supported identity | Typed `Proposal`: `suggested` requires a supplied ID and legal report evidence; `unmatched` and `ambiguous` require JSON null ID. Ambiguous requires at least two candidates; absence of a source measurement alone does not make activity identity ambiguous. No candidates yields deterministic unmatched without a model call. Invalid outputs receive at most the existing bounded consistency repair and then fail. |
| Optional supervisor | Trusted `legal_actions` containing the single allowed next action; confirm the graph transition | `SupervisorDecision` with exactly that action. No free-form abstention field exists; invalid/unavailable output stops the stage. The supervisor cannot invent tools or bypass the state machine. |
| Review/approval | Persisted source, observations, candidates, proposal/version and authorized reviewer action | Pending, rejected or explicitly approved durable review state. A model explanation is never approval. Unresolved material facts require clarification/review. |
| Internal update/MOCK delivery | Approved current proposal, idempotency identity and durable outbox | Persisted update and receipt/acknowledgement, or pending/failed delivery. No model stage may assert success in place of durable evidence. |

The last two are deterministic application stages, not additional model calls.
Typed parse/model failures remain visible separately from valid abstention.

## Missing, unreadable, conflicting and not-applicable values (SPEC-04)

| Condition | Representation and required action |
|---|---|
| Missing scalar fact | JSON `null` for nullable area, explicit activity ID, date, quantity, unit, raw unit, percentage, endpoint or blocker. Never the strings `"null"`, `"unknown"` or `"N/A"`. |
| Missing classification | The schema's `unknown` enum, where available. Never null for required enum fields. |
| Absent tags/effects/warnings | `[]`; evidence is different: each supported observation requires at least one legal exact source quote. Required summary remains nonempty. |
| No measured amount | `quantity: null`, `unit: null`, `raw_unit: null`, `quantity_kind: none`. This does not turn performed work into no-work. |
| Unreadable content | Parse/transcription-needed error or review state; no fabricated observation, amount or evidence. An unreadable report is not a completed empty batch. |
| Conflicting assertions | Preserve assertions and quotes, record the conflict in warnings/summary and require review. For conflicting work dates, raw output may use `date_basis: conflicting`; the existing normalizer sets the usable date to null, basis to unknown, removes endpoint effects and appends a clarification warning. Preserve raw versus normalized evidence separately. |
| Not applicable | Use the same absent scalar/array representation permitted by the schema; explain applicability in summary/warnings if relevant. The observation schema has no universal distinct missing/unreadable/not-applicable sentinel. Do not add an undeclared enum or pretend JSON null identifies the reason. |

The adapters' compatibility normalization of placeholder strings is a recorded
repair, not raw schema compliance. Schema validity alone cannot prove that a
model chose the correct absence reason. No observation may be created solely to
encode an error when there is no supported physical assertion.

## Event definitions and examples (SPEC-05)

Examples are in [the consumed specification fixtures](../evaluation/fixtures/stage-specification-v1/cases.json).
They contain complete schema-valid outputs, not just a single selected field.

| Event | Meaning and example | Measurement/endpoint rule |
|---|---|---|
| `actual_progress` | Performed work: “Excavated 5 m3 …”; unmeasured work is also performed work | Source-stated measured increment is delta; explicit total-to-date is cumulative. Missing amount stays null. Percentages never become measured quantity. |
| `planned_work` | Future intention: “Excavation of 8 m3 is planned tomorrow” | Planned amount remains in summary, not installed quantity. |
| `material_delivery` | Arrival: “Six pipe spools arrived today” | Arrival does not establish installation; amount remains in summary under this extraction contract. |
| `blocker` | Affirmative constraint: “Excavation is blocked by standing water” | Store the constraint in blocker/summary; no installed quantity. “Not blocked” is not a positive blocker. |
| `correction` | Earlier record amended: “8 m3 should read 6 m3” | Preserve old/new amounts and target information in summary/evidence; null progress quantity. Never book the difference or corrected total as new work automatically. |
| `actual_start` | Explicit whole-activity start assertion with supported date | Matching start lifecycle effect, date precision preserved; no quantity/percentage. A partial subtask start must retain its scope. |
| `actual_finish` | Explicit whole-activity finish assertion with supported date | Matching finish effect, no quantity/percentage. “5 of 10 completed” alone is not whole-activity finish. |
| `no_work` | Explicit non-performance: “No excavation occurred today” | No measured progress; does not erase a separate future plan or past correction. |

`inspection` remains the schema's inspection assertion type; it does not imply
installation or whole-activity completion. Unsupported event classification uses
`unknown` and review, rather than assigning a more specific physical event.
These definitions do not resolve the historical named-trench area/asset dispute
or independently adjudicate old correction labels.

## Observed, schedule and derived facts (SPEC-07)

The immutable source text/locator and raw model output are the observation
record. `raw_unit` is a literal source expression; normalized `unit` may represent
an explicit source synonym (for example cubic metres → m3), with evidence.
`raw_unit: null` cannot mean “the schedule stated m3.”

Schedule candidate unit, planned quantity/date, aliases and identity live in
candidate context. They help matching but never establish reported performance,
measured quantity, source unit or actual endpoint. The executable matching check
supplies a schedule with m3/100 while the source has no measurement; shortlist
and selection preserve source quantity/unit/raw_unit as null.

Derived values must remain explicitly labelled outside source fields: for
example a separately recorded conversion or reviewer-proposed unit must carry
origin, input identity, rule/version, authorization and review status. The
current observation schema has no generic derived-value provenance field; do
not squeeze a schedule-derived value into `raw_unit` or an exact source quote.
Unsupported derivation stays unavailable and requires review. This specification
does not add a schedule-default unit path or claim every legacy model obeys it.

Raw and normalized values are separately scored; a documented repair is not
proof that the raw answer was right. Exact quote containment is necessary but
does not establish semantic attribution to the correct event.

## Correction, time and location precedence (SPEC-09)

1. Source and authorized metadata outrank examples, schedule plans and the wall
   clock for report facts. Instructions embedded in any source are untrusted.
2. An explicit clause date belongs to that clause. Resolve yesterday/tomorrow
   only from a trusted report-date anchor and mark `relative_resolved`; no anchor
   means null/unknown and clarification. `report_context` requires the date to
   equal the trusted report date. Never invent midnight or timezone.
3. Incompatible date assertions do not acquire precedence merely because one
   appeared last. Preserve both and clear usable dates/effects for review, as
   specified above. Trusted metadata is an anchor, not permission to discard
   contradictory source evidence.
4. Explicit corrections supersede the identified earlier record only through
   authorized versioned correction/review logic. They never suppress a separate
   today's no-work or tomorrow's plan. Preserve target record, original/corrected
   amounts and all stated dates. Where whether `work_date` denotes corrected
   work date or correction act date is unresolved, keep the alternatives coherent
   and require adjudication; do not select dates field by field to improve a
   score. The new unclear-target example uses null/unknown and a warning. Old
   proposed alternatives and their provisional labels remain unchanged.
5. Explicit clause area/asset/date takes precedence over an applicable heading.
   Share a heading only with assertions within its actual scope. A trailing
   destination or a later independent clause never supplies the earlier event's
   location. Preserve leading zeros and spelling of identities.
6. Distinct scopes, dates or assertion types remain separate observations. The
   `SPEC-SCOPES` example retains today's Zone East/TR-001 work and tomorrow's
   Zone West/TR-002 plan. Evidence must belong to its own fragment and event.

These rules define safe review behavior when interpretation is unresolved;
independent semantic adjudication and representative model tests remain required
under DATA-06/07, QUAL and NEXT-01. Definition completion is not those tests.
