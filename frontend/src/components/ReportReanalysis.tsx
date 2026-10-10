import { FormEvent, useRef, useState } from "react";

export function ReportReanalysis({ projectId, reportId, jobId, parentJobId, reason: priorReason, request, onSubmitted, onBusy }: {
  projectId: string; reportId: string; jobId: string; parentJobId?: string; reason?: string;
  request: <T>(path: string, init?: RequestInit) => Promise<T>;
  onSubmitted: (value: Record<string, unknown>) => void; onBusy: (value: boolean) => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(crypto.randomUUID());
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !reason.trim()) return;
    setBusy(true); onBusy(true); setError("");
    try {
      const result = await request<Record<string, unknown>>(`/projects/${projectId}/reports/${reportId}/reanalysis`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason.trim(), idempotency_key: key.current }),
      });
      onSubmitted({ ...result, project_id: projectId, report_id: reportId });
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Reanalysis could not start."); }
    finally { setBusy(false); onBusy(false); }
  }
  return <section className="panel">
    <h2>Report reanalysis</h2>
    {parentJobId && <p className="helper">Previous run: <code>{parentJobId}</code>{priorReason ? ` · ${priorReason}` : ""}</p>}
    <p className="helper">Create a linked run using the current worker configuration. Previous evidence and decisions stay in history. Accepted work requires a correction before it can change.</p>
    <form onSubmit={submit} data-dirty={Boolean(reason.trim())}>
      <label htmlFor={`reanalysis-${jobId}`}>Reason for reanalysis</label>
      <textarea id={`reanalysis-${jobId}`} required maxLength={2000} rows={3} value={reason} disabled={busy}
        onChange={event => { setReason(event.target.value); key.current = crypto.randomUUID(); }} />
      {error && <p role="alert" className="form-error">{error}</p>}
      <button className="secondary" disabled={busy || !reason.trim()}>{busy ? "Starting reanalysis…" : "Create reanalysis run"}</button>
    </form>
  </section>;
}
