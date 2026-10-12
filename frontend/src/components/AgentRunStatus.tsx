import { useEffect, useRef, useState } from "react";
import {
  isTerminalAgentRun,
  parseAgentRunStatus,
  type AgentRunStatus as AgentRunStatusData,
  type RequestApi,
} from "../api/agentRuns";
import "../agent-run-status.css";

const endpointTerminalJobStates = new Set(["ready_for_review", "failed", "stale", "needs_transcription", "cancelled"]);
const notFoundRetryLimit = 5;
const pollIntervalMs = 2000;

function safeHttpStatus(error: unknown): number | null {
  if (!error || typeof error !== "object" || !("status" in error)) return null;
  const status = (error as { status?: unknown }).status;
  return typeof status === "number" ? status : null;
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${milliseconds} ms`;
  return `${(milliseconds / 1000).toFixed(milliseconds >= 10_000 ? 0 : 1)} s`;
}

function stepStateLabel(state: string): string {
  if (state === "succeeded") return "Complete";
  if (state === "running") return "In progress";
  if (state === "failed") return "Needs attention";
  return "Skipped";
}

export function AgentRunStatus({ jobId, jobState, runAvailable, enabled = true, requestApi }: { jobId: string; jobState: string; runAvailable: boolean; enabled?: boolean; requestApi: RequestApi }) {
  const [run, setRun] = useState<AgentRunStatusData | null>(null);
  const [loading, setLoading] = useState(true);
  const [waitingForRun, setWaitingForRun] = useState(false);
  const [notAvailable, setNotAvailable] = useState(false);
  const [connectionIssue, setConnectionIssue] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const previousJobId = useRef(jobId);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    let missingRunResponses = 0;
    const jobChanged = previousJobId.current !== jobId;
    previousJobId.current = jobId;
    if (jobChanged) {
      setRun(null);
      setLoading(true);
      setWaitingForRun(false);
      setNotAvailable(false);
      setConnectionIssue(false);
    }

    if (!enabled || (!runAvailable && endpointTerminalJobStates.has(jobState))) {
      setRun(null);
      setLoading(false);
      setWaitingForRun(false);
      setNotAvailable(false);
      setConnectionIssue(false);
      return () => { active = false; };
    }

    if (!runAvailable) {
      setRun(null);
      setLoading(false);
      setWaitingForRun(true);
      setNotAvailable(false);
      setConnectionIssue(false);
      return () => { active = false; };
    }

    const schedule = (callback: () => void) => {
      if (!active) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(callback, pollIntervalMs);
    };

    const load = async () => {
      if (!active) return;
      controller = new AbortController();
      try {
        const response = await requestApi<unknown>(`/jobs/${encodeURIComponent(jobId)}/agent-run`, { signal: controller.signal });
        if (!active) return;
        const parsed = parseAgentRunStatus(response);
        if (!parsed || parsed.job_id !== jobId) {
          setRun(null);
          setNotAvailable(true);
          setWaitingForRun(false);
          setConnectionIssue(false);
          setLoading(false);
          return;
        }
        setRun(parsed);
        setWaitingForRun(false);
        setNotAvailable(false);
          setConnectionIssue(false);
        setLoading(false);
        if (!isTerminalAgentRun(parsed.state)) schedule(() => void load());
      } catch (error) {
        if (!active || controller?.signal.aborted) return;
        const status = safeHttpStatus(error);
        if (status === 404) {
          missingRunResponses += 1;
          if (missingRunResponses <= notFoundRetryLimit) {
            setWaitingForRun(true);
            setConnectionIssue(false);
            setLoading(false);
            schedule(() => void load());
            return;
          }
          setWaitingForRun(false);
          setNotAvailable(true);
          setLoading(false);
          return;
        }
        setConnectionIssue(true);
        setWaitingForRun(false);
        setLoading(false);
        if (!endpointTerminalJobStates.has(jobState)) schedule(() => void load());
      }
    };

    const online = () => {
      if (timer) clearTimeout(timer);
      setRefresh(value => value + 1);
    };
    const offline = () => setConnectionIssue(true);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    void load();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
      controller?.abort();
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, [jobId, jobState, runAvailable, enabled, requestApi, refresh]);

  if (!enabled || (!runAvailable && endpointTerminalJobStates.has(jobState))) return null;

  const retry = () => setRefresh(value => value + 1);
  return <section className="agent-run-status" aria-labelledby="agent-run-status-heading">
    <div className="agent-run-status__heading">
      <div>
        <p className="eyebrow">ANALYSIS DETAILS</p>
        <h3 id="agent-run-status-heading">Agent run</h3>
      </div>
      {run && <span className={`agent-run-status__badge agent-run-status__badge--${run.state}`}>
        {run.state === "ready_for_review" ? "Ready for review" : run.state === "running" || run.state === "created" ? "In progress" : run.state === "failed" ? "Failed" : run.state === "stale" ? "Stale" : "Cancelled"}
      </span>}
    </div>

    {loading && <p className="agent-run-status__message" role="status">Loading agent status…</p>}
    {!loading && waitingForRun && <p className="agent-run-status__message" role="status">Waiting for agent status…</p>}
    {!loading && notAvailable && <div className="agent-run-status__message" role="status"><p>Agent run details are not available right now.</p><button className="secondary" type="button" onClick={retry}>Check again</button></div>}
    {!loading && connectionIssue && <div className="agent-run-status__message" role="status"><p>Connection interrupted. Agent status will be checked again.</p><button className="secondary" type="button" onClick={retry}>Check again</button></div>}

    {run && <>
      <p className="agent-run-status__stage" role="status">{run.current_stage || (run.state === "running" || run.state === "created" ? "Analysis in progress" : run.state === "ready_for_review" ? "Ready for review" : run.state === "failed" ? "Failed" : run.state === "stale" ? "Stale" : "Cancelled")}</p>
      {run.state === "failed" && <p className="agent-run-status__terminal-copy">The analysis could not complete. Review the job status and retry if available.</p>}
      {run.state === "stale" && <p className="agent-run-status__terminal-copy">The project schedule changed during analysis. This run did not update progress.</p>}
      {run.state === "cancelled" && <p className="agent-run-status__terminal-copy">This analysis was cancelled.</p>}
      <dl className="agent-run-status__counters" aria-label="Agent run counts">
        <div><dt>Steps run</dt><dd>{run.counters.node_executions}</dd></div>
        <div><dt>Extraction calls</dt><dd>{run.counters.extraction_calls}</dd></div>
        <div><dt>Selection calls</dt><dd>{run.counters.selection_calls}</dd></div>
        <div><dt>Correction retries</dt><dd>{run.counters.corrective_retries}</dd></div>
      </dl>
      {run.steps.length > 0 && <ol className="agent-run-status__steps" aria-label="Agent stages">
        {run.steps.map(step => <li className={`agent-run-status__step agent-run-status__step--${step.state}`} key={step.ordinal}>
          <span className="agent-run-status__step-label">{step.label}</span>
          <span className="agent-run-status__step-state">{stepStateLabel(step.state)}</span>
          <span className="agent-run-status__step-meta">Attempt {step.attempt}{step.duration_ms === null ? "" : ` · ${formatDuration(step.duration_ms)}`}</span>
        </li>)}
      </ol>}
    </>}
  </section>;
}
