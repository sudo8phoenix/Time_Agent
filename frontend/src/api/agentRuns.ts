export const publicAgentStages = [
  "Loading context",
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

export type AgentRunStatus = {
  id: string;
  job_id: string;
  state: AgentRunState;
  current_stage: PublicAgentStage | null;
  counters: {
    node_executions: number;
    extraction_calls: number;
    selection_calls: number;
    corrective_retries: number;
  };
  steps: AgentRunStep[];
};

const stageSet = new Set<string>(publicAgentStages);
const runStates = new Set<AgentRunState>(["created", "running", "ready_for_review", "failed", "stale", "cancelled"]);
const stepStates = new Set<AgentStepState>(["running", "succeeded", "failed", "skipped"]);

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
  return {
    id: value.id,
    job_id: value.job_id,
    state: value.state as AgentRunState,
    current_stage: currentStage,
    counters: {
      node_executions: rawCounters.node_executions as number,
      extraction_calls: rawCounters.extraction_calls as number,
      selection_calls: rawCounters.selection_calls as number,
      corrective_retries: rawCounters.corrective_retries as number,
    },
    steps,
  };
}

export function isTerminalAgentRun(state: AgentRunState): boolean {
  return state !== "created" && state !== "running";
}
