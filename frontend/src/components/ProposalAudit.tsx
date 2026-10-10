import { useState } from "react";
export type ProposalProvenance = {
  capture_status: string;
  intake?: Record<string, unknown>;
  confidence: Record<string, { score: number | null; method: string; version: string | null; validation_status: string }>;
  source: Record<string, string | null>;
  original_fields: Record<string, unknown>;
  original_selection: Record<string, unknown>;
  model_metadata: Record<string, unknown>;
  validation: Record<string, unknown>;
};
export type ProposalHistory = {
  scope: string;
  decisions: { id: string; action: string; actor_id: string; timestamp: string | null; reason: string | null; before: unknown; after: unknown }[];
  proposals: unknown[];
  events: unknown[];
};
export function ProposalAudit({ provenance, history, onRefresh, disabled }: { provenance?: ProposalProvenance; history?: ProposalHistory; onRefresh?: () => Promise<void>; disabled?: boolean }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  return <section className="proposal-audit" aria-label="Confidence and decision history">
    <h3>Confidence and provenance</h3>
    <p className="helper">Confidence helps prioritize review. Every update requires authorized acceptance.</p>
    {provenance ? <>
      <dl>{["extraction", "linking"].map(stage => {
        const estimate = provenance.confidence[stage];
        return <div key={stage}><dt>{stage === "extraction" ? "Extraction confidence" : "Linking confidence"}</dt>
          <dd>{estimate?.score == null ? "Unavailable" : estimate.score} · {estimate?.validation_status || "unavailable"}</dd></div>;
      })}</dl>
      {provenance.capture_status !== "recorded" && <p className="helper">This older proposal has incomplete recorded metadata.</p>}
      {provenance.source.original_url && <a href={provenance.source.original_url} target="_blank" rel="noreferrer">Open immutable original source</a>}
      {provenance.intake?.quality === "human_transcribed" && <p className="helper">Human transcription · transcriber {String(provenance.intake.transcriber_id)} · {String(provenance.intake.transcribed_at)}. Evidence retains original page numbers.</p>}
      <details><summary>Original extraction, link decision and source</summary>
        <pre>{JSON.stringify({ source: provenance.source, intake: provenance.intake, original_fields: provenance.original_fields,
          original_selection: provenance.original_selection, confidence: provenance.confidence,
          validation: provenance.validation, model_metadata: provenance.model_metadata }, null, 2)}</pre>
      </details>
    </> : <p className="helper">Confidence metadata unavailable.</p>}
    {onRefresh && <button className="secondary" disabled={disabled || loading} onClick={async () => {
      setLoading(true); setError("");
      try { await onRefresh(); } catch { setError("Could not refresh decision history. Try again."); }
      finally { setLoading(false); }
    }}>{loading ? "Refreshing history…" : "Refresh decision history"}</button>}
    {error && <p role="alert">{error}</p>}
    <details><summary>Decision history for this report</summary>
      {history?.decisions.length ? <ol>{history.decisions.map(decision => <li key={decision.id}>
        <strong>{decision.action.replaceAll("_", " ")}</strong> · {decision.timestamp ? new Date(decision.timestamp).toLocaleString() : "Time unavailable"}
        <p>Actor: {decision.actor_id}</p>{decision.reason && <p>{decision.reason}</p>}
        <details><summary>Before and after</summary><pre>{JSON.stringify({ before: decision.before, after: decision.after }, null, 2)}</pre></details>
      </li>)}</ol> : <p className="helper">No recorded decisions yet.</p>}
      {history && <details><summary>All proposal revisions and accepted events</summary>
        <pre>{JSON.stringify({ proposals: history.proposals, events: history.events }, null, 2)}</pre>
      </details>}
    </details>
  </section>;
}
