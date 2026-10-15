# Multi-agent implementation handoff

Prepared 15 October 2026. Start implementation from this document and `docs/multi-agent-architecture.md`.

## User-approved direction

Convert the current flat report pipeline into a multi-level agent hierarchy. The architecture plan was reviewed and accepted in conversation. The user now wants implementation in a new chat. This handoff and the architecture document are planning artifacts; no multi-agent runtime has been implemented yet.

Hierarchy:

```text
Project orchestrator
├── Intake supervisor
│   └── Clarification agent
├── Analysis supervisor
│   ├── Observation extraction agent
│   ├── Schedule matching agent
│   │   └── Activity selection agent
│   └── Evidence review agent
└── Review preparation supervisor
    ├── Deterministic effect calculation and validation
    └── Idempotent proposal persistence → existing human approval
```

Agents require explicit contracts, scoped context/tools, bounded delegation, and traceable parent/child tasks. Do not merely rename the existing graph nodes. Keep deterministic operations as tools. Keep human approval as the boundary for progress ledger writes.

## Implementation-agent delegation authorized by the user

The user explicitly permits spawning **GPT-6 Luna agents with low reasoning** to help implement this work. When supported by the available tool, use `model="gpt-6-luna"`, `reasoning_effort="low"`, and `fork_turns="none"`. Give each agent a self-contained task, relevant file paths, acceptance criteria, and a non-overlapping edit scope.

The primary agent remains responsible for architecture, task coordination, reviewing every delegated change, integration, testing, and the final outcome. Delegate bounded tasks such as isolated schema tests, fixture preparation, documentation, or a narrowly specified adapter. Do not delegate unresolved architecture decisions or accept an agent's success report without checking its diff and relevant tests. Avoid conflicting edits in the shared workspace. These are development assistants; this permission does not configure the application's runtime models.

## Repository and existing work

Repository: `/Users/cyrilsabugeorge/Documents/python_project/site-progress-agent`.

The parent workspace also contains `progress-agent-plan`, a historical design/planning directory, and a small separate `backend` directory. Implement in `site-progress-agent`.

At handoff, Git already reports modifications to `.env.example`, `README.md`, runtime, schedule decision, conversation service, jobs service, settings, and selection tests. Untracked files include Groq/provider adapters and tests, evaluation scripts/results, schedule data, and operator notes. Inspect `git status` and diffs at the start. Preserve existing changes; do not reset or overwrite them.

Relevant implementation:

- `backend/app/agent/graph.py`: current fixed report graph.
- `backend/app/agent/nodes.py`: extraction, retrieval, selection, repair, validation, persistence.
- `backend/app/agent/runtime.py`: leases, checkpoint execution, resume, terminal state, domain persistence.
- `backend/app/agent/state.py`: strict JSON state, `report-analysis-v1`, `agent-state-v1`.
- `backend/app/agent/policy.py`: routing, stage labels, retry and node budgets.
- `backend/app/agent/tools.py`: existing tool/domain interfaces.
- `backend/app/agent/telemetry.py`: durable sanitized trace and checkpoint reconciliation.
- `backend/app/conversation/service.py`: separate conversation extraction/matching/clarification path.
- `backend/app/llm/provider.py`, `groq.py`, `ollama.py`: existing provider interface and adapters.
- `backend/app/settings.py`: typed environment configuration.
- `backend/app/db/models.py`, `backend/migrations/versions/`: storage and migrations.
- `backend/tests/unit/agent/`, `backend/tests/integration/agent/`: existing runtime coverage.

## Credentials and model decisions

The `.env` file was checked without printing credentials. It is Git-ignored. It contains **four distinct nonempty credentials**:

- `GROQ_API_KEY`: original key.
- `GROQ_API_KEY_1`: additional key.
- `GROQ_API_KEY_2`: additional key.
- `OPENROUTER_API_KEY`: OpenRouter key.

The user referred to three newly provided keys; those are in addition to the original Groq key. Do not print, commit, or copy their values into docs, tests, command output, or prompts.

Current code recognizes only the original Groq key. The settings provider enum currently allows `ollama` and `groq`; OpenRouter and additional Groq key selection are not implemented. `OPENROUTER_MODEL` was absent at inspection. Credentials have not been live-tested in this session.

The initial architecture proposed deterministic orchestration. The later conversation selected **NVIDIA Nemotron 3 Ultra (free)** as the first candidate for model-assisted orchestrator decisions. Incorporate it as a bounded planner: it proposes registered supervisor/task actions, while Python validates the proposal, enforces scope/budgets, and executes transitions. Deterministic continuation should remain available for fixed workflow stages. Never give the model unrestricted tools, arbitrary agent creation, or approval authority.

Before pinning the model, verify its exact current free model ID, availability, structured-output/tool support, and provider behavior using OpenRouter's current official catalog/documentation. Do not infer a free ID from the paid model slug. If it is unavailable, implement the deterministic path and report the model configuration issue; do not silently choose a paid model or random free router.

Groq role/model assignment remains open. Inventory the existing configured model without exposing keys; retain it as the baseline. Make role-to-provider/model/key-slot selection configurable. Multiple agents can share a credential. Additional keys do not imply independent quotas; do not rotate keys to bypass rate limits. Start with explicit role assignment and bounded concurrency rather than automatic key pooling.

## Ordered game plan

### 1. Establish the baseline

Read applicable repository instructions, inspect the dirty worktree, and run relevant existing unit tests. Capture fixture-based report and conversation outputs and failure behavior. Identify unavailable infrastructure separately from code failures. Verify the current pinned dependency APIs before introducing nested graph behavior. No framework replacement is required.

### 2. Prepare provider configuration

Add typed OpenRouter settings and an adapter compatible with the existing injectable `chat` interface and result metadata. Support the three named Groq key slots through explicit trusted role configuration, without changing existing defaults. Add sanitized provider errors, bounded timeouts, and mocked transport tests. Update `.env.example` with placeholders only. Validate model JSON against local schemas even when a provider advertises structured output. Confirm free-model identity before any live smoke test; use synthetic, non-sensitive input for credential checks.

### 3. Define contracts and bounded orchestration

Add role registry, task/result envelopes, scoped specialist inputs, root budget accounting, and validated supervisor decisions. Root identity pins project/source/schedule version. Task identity includes parent, role, observation key where relevant, attempt, and contract version. Return typed outcomes and explicit unresolved results. Cap delegation depth and allowed role transitions. Failed calls and repairs consume root budgets; child spawning must not reset them.

Separate provider transport retries from semantic repairs. Preserve current repair allowances initially. Replace the flat node-limit assumption with measured, explicit limits for supervisor transitions, specialist/model calls, and tool calls.

### 4. Build the report hierarchy first

Implement the root orchestrator, analysis supervisor, extraction specialist, schedule matching supervisor/selection child, evidence checks, and review preparation supervisor. Reuse existing extraction, candidate retrieval, selection, effect calculation, and persistence logic. Intake initially wraps report context loading. Begin sequentially; existing mutable tools, sessions, metadata, and counters need review before concurrent fan-out.

Use deterministic evidence checks first. Add model critique only if evaluation demonstrates value. Keep model-assisted root decisions constrained to legal actions and typed results; unknown actions fail safely or follow an explicitly tested deterministic fallback policy.

### 5. Add durable tasks and versioned runtime

Introduce additive task storage and trace linkage for parent/child identities, attempts, statuses, sanitized errors, output references, and fingerprints. Integrate existing leases and checkpoint reconciliation. Prototype nested subgraph persistence and event streaming using installed package versions.

Create v2 graph/state identities and dispatch by the stored run version. Retain v1 code for already-started checkpoints. A feature flag controls new runs, not the interpretation of existing checkpoints. Root job ownership remains unchanged. Domain persistence stays idempotent across retries and worker restarts.

### 6. Integrate conversations

Reuse specialist contracts from conversation analysis instead of maintaining a second extraction/matching implementation. Preserve immutable user turns, exact-match behavior where valid, clarification semantics, and the review handoff. Persist waiting state without retaining a worker lease. Resume through new user input with pinned identity and invalidation rules.

### 7. Verify and roll out

Test contracts, role scopes, model decision validation, root budget conservation, retry exhaustion, unsupported evidence, ambiguous/no-match outcomes, provider failures, cancellation, lease loss, schedule changes, resume after crashes, and duplicate persistence protection. Use PostgreSQL integration tests for durability. Verify v1/v2 coexistence and rollback behavior.

Compare fixture mapping accuracy, unsupported claims, abstentions, model-call counts, latency, and failure rate against baseline. Shadow execution must use a non-writing persistence adapter. Enable v2 for new jobs only after the end-to-end report flow passes. Rollback should stop creating v2 runs while existing v2 runs remain resumable. Do not deploy or publish as an incidental part of local implementation.

## First deliverable

A working report hierarchy behind a disabled-by-default rollout flag, configurable provider roles, durable child task traces, preserved v1 resume, and passing relevant unit/integration checks. Report exact validation results and infrastructure limitations. Conversation integration follows after the report slice is stable. Continue through the approved migration plan unless a real dependency requires user input; do not claim full completion after only adding contracts or renaming stages.

## Prompt to paste into a new chat

> Implement the hierarchical multi-agent migration in `/Users/cyrilsabugeorge/Documents/python_project/site-progress-agent`. First read `docs/multi-agent-implementation-handoff.md` and `docs/multi-agent-architecture.md`, inspect repository instructions and existing local changes, then follow the ordered plan. Preserve existing work and human approval. The `.env` has one original Groq key, two additional Groq keys, and one OpenRouter key; never expose them. Verify the exact Nemotron 3 Ultra free model ID before configuring model-assisted orchestration. You may spawn GPT-6 Luna low-reasoning development agents for bounded tasks, but you must coordinate them, review their work, integrate changes, and own verification. Begin with the versioned report runtime behind a feature flag, then integrate conversations. Proceed with implementation, not another planning-only response.
