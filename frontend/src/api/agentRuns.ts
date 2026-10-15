export const publicAgentStages = [
  "Loading context",
  "Analyzing report",
  "Extracting observations",
  "Validating evidence",
  "Retrieving schedule candidates",
  "Selecting supported matches",
  "Validating proposals",
  "Saving for review",
  "Ready for review",
  "Failed",
  "Stale",
] as const;

export type PublicAgentStage = (typeof publicAgentStages)[number];
export type AgentRunState = "created" | "running" | "ready_for_review" | "failed" | "stale" | "cancelled";
export type AgentStepState = "running" | "succeeded" | "failed" | "skipped";
export type RequestApi = <T>(path: string, init?: RequestInit, retry?: boolean) => Promise<T>;

export type AgentRunStep = {
  ordinal: number;
  label: PublicAgentStage;
  state: AgentStepState;
  attempt: number;
  duration_ms: number | null;
};

export type AgentTask = {
  id: string;
  parent_task_id: string | null;
  role: "root" | "intake" | "analysis" | "review" | "clarification" | "extraction" | "matching" | "evidence" | "selection";
  status: AgentStepState;
  attempt: number;
  outcome: "completed" | "needs_clarification" | "retryable_failure" | "failed" | "stale" | "unresolved" | null;
};

export type AgentHierarchyUsage = {
  delegations: number;
  supervisor_transitions: number;
  model_calls: number;
  tool_calls: number;
};

export type AgentRunStatus = {
  id: string;
  job_id: string;
  graph_version: "report-analysis-v1" | "report-analysis-v2" | "unrecognized" | null;
  state: AgentRunState;
  current_stage: PublicAgentStage | null;
  counters: {
    node_executions: number;
    extraction_calls: number;
    selection_calls: number;
    corrective_retries: number;
  };
  steps: AgentRunStep[];
  tasks: AgentTask[];
  hierarchy_usage: AgentHierarchyUsage | null;
};

const stageSet = new Set<string>(publicAgentStages);
const runStates = new Set<AgentRunState>(["created", "running", "ready_for_review", "failed", "stale", "cancelled"]);
const stepStates = new Set<AgentStepState>(["running", "succeeded", "failed", "skipped"]);
const taskRoles = new Set<AgentTask["role"]>(["root", "intake", "analysis", "review", "clarification", "extraction", "matching", "evidence", "selection"]);
const taskOutcomes = new Set<NonNullable<AgentTask["outcome"]>>(["completed", "needs_clarification", "retryable_failure", "failed", "stale", "unresolved"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function boundedInteger(value: unknown, max: number, min = 0): value is number {
  return Number.isInteger(value) && (value as number) >= min && (value as number) <= max;
}

/** Parse only fields the public UI is allowed to display. */
export function parseAgentRunStatus(value: unknown): AgentRunStatus | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.job_id !== "string") return null;
  if (typeof value.state !== "string" || !runStates.has(value.state as AgentRunState)) return null;
  const rawCounters = value.counters;
  if (!isRecord(rawCounters)
    || !boundedInteger(rawCounters.node_executions, 16)
    || !boundedInteger(rawCounters.extraction_calls, 2)
    || !boundedInteger(rawCounters.selection_calls, 400)
    || !boundedInteger(rawCounters.corrective_retries, 2)) return null;

  const current = value.current_stage;
  const currentStage = current === null ? null : typeof current === "string" && stageSet.has(current) ? current as PublicAgentStage : null;
  const rawSteps = value.steps;
  if (!Array.isArray(rawSteps) || rawSteps.length > 16) return null;
  const steps: AgentRunStep[] = [];
  const ordinals = new Set<number>();
  for (const raw of rawSteps) {
    if (!isRecord(raw) || !boundedInteger(raw.ordinal, 16, 1) || ordinals.has(raw.ordinal as number)) return null;
    ordinals.add(raw.ordinal as number);
    if (typeof raw.label !== "string" || !stageSet.has(raw.label)) continue;
    if (typeof raw.state !== "string" || !stepStates.has(raw.state as AgentStepState)) return null;
    if (!boundedInteger(raw.attempt, 16, 1)) return null;
    const duration = raw.duration_ms;
    if (duration !== null && !boundedInteger(duration, 86_400_000)) return null;
    if (raw.state === "running" && duration !== null) return null;
    steps.push({ ordinal: raw.ordinal as number, label: raw.label as PublicAgentStage, state: raw.state as AgentStepState, attempt: raw.attempt as number, duration_ms: duration as number | null });
  }
  steps.sort((a, b) => a.ordinal - b.ordinal);
  const graphVersion = value.graph_version === undefined ? null : value.graph_version;
  if (graphVersion !== null && graphVersion !== "report-analysis-v1" && graphVersion !== "report-analysis-v2" && graphVersion !== "unrecognized") return null;
  const rawTasks = value.tasks === undefined ? [] : value.tasks;
  if (!Array.isArray(rawTasks) || rawTasks.length > 1301) return null;
  const tasks: AgentTask[] = [];
  for (const raw of rawTasks) {
    if (!isRecord(raw) || typeof raw.id !== "string" || !taskRoles.has(raw.role as AgentTask["role"])) return null;
    if (raw.parent_task_id !== null && typeof raw.parent_task_id !== "string") return null;
    if (typeof raw.status !== "string" || !stepStates.has(raw.status as AgentStepState)) return null;
    if (!boundedInteger(raw.attempt, 100, 1)) return null;
    const outcome = raw.outcome;
    if (outcome !== null && (typeof outcome !== "string" || !taskOutcomes.has(outcome as NonNullable<AgentTask["outcome"]>))) return null;
    tasks.push({ id: raw.id, parent_task_id: raw.parent_task_id as string | null,
      role: raw.role as AgentTask["role"], status: raw.status as AgentStepState,
      attempt: raw.attempt as number, outcome: outcome as AgentTask["outcome"] });
  }
  let hierarchyUsage: AgentHierarchyUsage | null = null;
  if (value.hierarchy_usage !== undefined && value.hierarchy_usage !== null) {
    const raw = value.hierarchy_usage;
    if (isRecord(raw) && boundedInteger(raw.delegations, 1300)
      && boundedInteger(raw.supervisor_transitions, 12)
      && boundedInteger(raw.model_calls, 806) && boundedInteger(raw.tool_calls, 1010)) {
      hierarchyUsage = { delegations: raw.delegations, supervisor_transitions: raw.supervisor_transitions,
        model_calls: raw.model_calls, tool_calls: raw.tool_calls };
    }
  }
  return {
    id: value.id,
    job_id: value.job_id,
    graph_version: graphVersion,
    state: value.state as AgentRunState,
    current_stage: currentStage,
    counters: {
      node_executions: rawCounters.node_executions as number,
      extraction_calls: rawCounters.extraction_calls as number,
      selection_calls: rawCounters.selection_calls as number,
      corrective_retries: rawCounters.corrective_retries as number,
    },
    steps,
    tasks,
    hierarchy_usage: hierarchyUsage,
  };
}

export function isTerminalAgentRun(state: AgentRunState): boolean {
  return state !== "created" && state !== "running";
}
