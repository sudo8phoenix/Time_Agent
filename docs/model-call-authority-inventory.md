# Model-call and authority inventory — 20 October 2026

Scope: every backend application model-call entry point found by repository
search for adapter construction, chat, injected model_call and system/user
request assembly. Evaluation-only scripts are separate experiments. Runtime
configuration is read from Settings and persisted job/run metadata, never from
report instructions. No private reasoning is requested or used as authority.

| Entry point / prompt | Reachability and version | Inputs and task | Output / abstention | Authority and observability | Generation settings |
|---|---|---|---|---|---|
| llm/extract.py:extract_batch → prompts/extraction_v1.py:get_extraction_prompt | Report tools, linear graph, hierarchy extraction specialist, conversation analysis. Default extraction-v12; explicit v9–v20 retained for replay. v17/v18 reuse v15 text; v20 reuses v19 text with matching wire change | Trusted report-date header plus canonical fragment headers and source bodies; extract atomic observations only | ObservationBatch schema with typed fields/evidence/effects. v14+ explicitly permits empty observations when no physical facts; prior versions rely on schema and fail/clarification flow. Unknown facts stay null; dates can warn | System message separate from user source; source treated as untrusted. Quotes and fragment IDs validated. ExtractionResult metadata records prompt/settings hashes, runtime/model and errors | Caller settings or temperature=0; provider defaults below |
| agent/schedule_decision.py:shortlist_activities → nested choose → _decision_call | Report and conversation matching, same shared production function. Unnamed source-versioned prompt; compact_context and short_ids are pinned runtime alternatives | Observation/evidence plus pinned schedule rows; shortlist plausible activity identities. Optional blocker/delivery suffix; bounded empty reconsideration | candidate_ids only, supplied enum, maximum limit, unique IDs. Empty list is explicit abstention. Invalid IDs/duplicate/malformed return raises AgentDecisionError | Report/schedule text explicitly data; schedule does not prove work, discovery is not approval. Source facts preserved under wire-ID transformation. Calls tracked through report telemetry or conversation call_trace | Standard provider defaults; compact mode temperature=0,num_predict=768 |
| agent/schedule_decision.py:select_activity → _decision_call | Report and conversation selection, including hierarchical specialists. Unnamed source-versioned prompt; compact/short-ID flags and blocker/delivery suffixes | Observation, legal Candidate list, exact report fragment map; choose supported activity identity | candidate_id plus mapping_state, evidence IDs, reason codes, explanation and missing_information. suggested requires supplied ID/evidence; ambiguous/unmatched require null. Empty candidates deterministically unmatched without a call. One bounded consistency repair | Explicit data-not-instructions rule. Typed machine decision is separate from free text. No approval/write operation. Fragment ID legality, candidate membership and mapping consistency checked; Proposal review_state=pending | Standard defaults; compact mode temperature=0,num_predict=768, explanation ≤2 sentences instructed |
| agent/hierarchy.py:validated_decision | Only report-analysis-v2 when agent_hierarchy_enabled and orchestrator_model_assisted. runtime.py constructs planner via agent/planner.py | Trusted user object containing only legal_actions=[expected]; confirm the single permitted next supervisor. No report/tool/retrieval text supplied | Strict SupervisorDecision: action enum intake/analysis/review; action must equal expected. Invalid/mismatched output fails closed, no model abstention enum | Cannot add tools, writes, approvals or override graph transitions. Reservations/errors/selected role persist in hierarchy state/tasks; no reasoning field | Provider defaults; supported assignments constrained by create_planner |

The only application request assemblers are these four logical stages. The
extract_batch positional model_call fallback is the same extraction request for
injectable adapter compatibility, not a separate role. _decision_call is a wire
ID wrapper, not an independent decision. Agent tools/specialists delegate to
these shared functions; confidence/provenance.py records metadata, it does not
call a model. Conversation prompts are not an independent conversational agent:
conversation/service.py analyzes immutable user turns with the same extractor,
filters to start/finish assertions, asks deterministic date/scope/work questions,
and uses the same shortlist/selector. Confirmation hands off to review.

Agent nodes/policy and conditional routers are deterministic. The hierarchy's
intake/analysis/matching/selection/evidence/review names do not each represent a
new prompt. Shadow execution denies persistence through scoped tools. No model
controls approval or delivery endpoints. Planner creation supports only explicit
allowlisted OpenRouter models or Groq GPT-OSS 120B; invalid configuration fails.

Provider roles are orchestrator/extraction/selection in llm/provider.py. Defaults
are Settings.llm_provider=ollama, ollama_model=qwen3.5:4b; Groq model default
openai/gpt-oss-20b; OpenRouter requires an explicit model. Hierarchy defaults off,
model assistance defaults off, execution mode graph. Report/conversation timeouts
are 360/300 seconds by default. Durable metadata pins effective configuration;
legacy replay remains reachable and is not silently rewritten here.

Adapters serialize system and user separately. Ollama defaults temperature=0,
num_ctx=8192,num_predict=1536 and think=False. Groq defaults temperature=0,
output cap 1536 and low reasoning effort for supported GPT-OSS models. OpenRouter
defaults temperature=0, output cap 1536; it appends schema JSON to the system
message. No adapter grants a model tools or approval authority. All use zero
transport retries. Settings hashes and prompt/model identity are retained;
model-internal reasoning is neither a machine decision nor a review approval.

Missing specification gaps remain explicit: older extraction replay prompts do
not consistently state an empty-output abstention rule; correction event/date
semantics are not settled; unreadable/conflicting/not-applicable states and
schedule-derived unit provenance lack one uniform all-stage instruction contract.
No legacy prompt text or effective historical replay hash changed in this audit.

## Common specification follow-up — 21 October, batch twenty-two

[Stage specification v1](stage-specification-v1.md) now defines the common
stage task/abstention, absence/conflict, event, provenance and precedence rules
identified as gaps above. Thirteen consumed examples and nineteen compatibility
checks exercise the actual schemas/extraction/matching. The original audit and
legacy prompt text/hashes remain unchanged: this definition does not establish
uniform model compliance, independently settle old labels or promote a prompt.
