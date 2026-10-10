import { FormEvent, useEffect, useState } from "react";

type Project = { id: string; name: string; active_schedule_version_id: string | null };
type Candidate = { candidate_id: string; activity_name: string; external_id: string; area: string | null };
type Card = {
  observation: { summary: string; event_type: string; evidence: { quote: string; fragment_id: string }[] };
  effect: { event_type?: string; scope?: string; subactivity_key?: string | null; endpoint?: { local_date: string; local_time: string | null; precision: string; timezone: string | null } };
  selection: { candidates: Candidate[]; mapping_state: string; explanation: string };
  activity_id: string | null;
};
type Conversation = {
  id: string; revision: number; status: string; pending_question: string | null; question: string | null;
  turns: { ordinal: number; role: string; text: string }[]; events: Card[];
  job_id: string | null; proposal_ids: string[];
};
type Request = (path: string, init?: RequestInit) => Promise<any>;

function EventCorrection({ card, index, busy, onSave }: { card: Card; index: number; busy: boolean; onSave: (body: object) => void }) {
  const [date, setDate] = useState(card.effect.endpoint?.local_date || "");
  const [time, setTime] = useState(card.effect.endpoint?.local_time?.slice(0, 5) || "");
  const [scope, setScope] = useState(card.effect.scope || "whole_activity");
  const [part, setPart] = useState(card.effect.subactivity_key || "");
  const [dateOnly, setDateOnly] = useState(false);
  useEffect(() => { setDate(card.effect.endpoint?.local_date || ""); setTime(card.effect.endpoint?.local_time?.slice(0, 5) || ""); setScope(card.effect.scope || "whole_activity"); setPart(card.effect.subactivity_key || ""); setDateOnly(false); }, [card]);
  const save = (event: FormEvent) => { event.preventDefault(); onSave({ event_index: index, local_date: date || null, local_time: dateOnly ? null : time || null, date_only: dateOnly, scope, subactivity_key: scope === "subactivity" ? part.trim() || null : null }); };
  return <form className="time-event-edit" onSubmit={save}><strong>Correct event details</strong><div className="time-event-edit-fields">
    <label>Date<input type="date" value={date} onChange={event => setDate(event.target.value)} required disabled={busy} /></label>
    <label>Time (optional)<input type="time" value={time} onChange={event => { setTime(event.target.value); setDateOnly(false); }} disabled={busy || dateOnly} /></label>
    <label>Scope<select value={scope} onChange={event => setScope(event.target.value)} disabled={busy}><option value="whole_activity">Whole activity</option><option value="subactivity">Named part</option></select></label>
    {scope === "subactivity" && <label>Part name<input value={part} onChange={event => setPart(event.target.value)} required maxLength={200} disabled={busy} /></label>}
  </div><label className="time-event-check"><input type="checkbox" checked={dateOnly} onChange={event => { setDateOnly(event.target.checked); if (event.target.checked) setTime(""); }} disabled={busy} /> Date only; time unknown</label><button className="secondary" disabled={busy || !date || (scope === "subactivity" && !part.trim())}>Save correction</button></form>;
}

export function TimeChat({ project, request, onReview, canReview, accountId }: { project: Project | null; request: Request; onReview: (jobId: string) => void; canReview: boolean; accountId: string }) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [recent, setRecent] = useState<Conversation[]>([]);
  const [text, setText] = useState("");
  const [reportDate, setReportDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const storageKey = `spa-time-chat:${accountId}:${project?.id || "none"}`;
  useEffect(() => {
    setConversation(null); setLoading(true); setError("");
    if (!project) { setLoading(false); return; }
    let active = true;
    setText(sessionStorage.getItem(storageKey) || "");
    request(`/projects/${project.id}/conversations`).then((result: { items: Conversation[] }) => {
      if (!active) return;
      setRecent(result.items);
      setConversation(result.items.find(item => item.status === "draft") || result.items[0] || null);
    }).catch((reason: Error) => { if (active) setError(reason.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [project?.id, accountId]);
  const perform = async (action: () => Promise<Conversation>) => {
    if (busy) return;
    setBusy(true); setError("");
    try { const next = await action(); setConversation(next); setRecent(items => [next, ...items.filter(item => item.id !== next.id)]); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The conversation could not be updated."); }
    finally { setBusy(false); }
  };
  const start = () => perform(async () => {
    if (!project) throw new Error("Select a project first.");
    const next = await request(`/projects/${project.id}/conversations`, { method: "POST" }) as Conversation;
    setRecent(items => [next, ...items]); return next;
  });
  const send = (event: FormEvent) => { event.preventDefault(); if (!project || !conversation || !text.trim()) return;
    const outgoing = text.trim();
    void perform(async () => {
      const next = await request(`/projects/${project.id}/conversations/${conversation.id}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: outgoing, report_date: reportDate || null, expected_revision: conversation.revision }),
      }) as Conversation;
      setText(""); setReportDate(""); sessionStorage.removeItem(storageKey); return next;
    });
  };
  const decide = (path: string, body: object) => {
    if (!project || !conversation) return;
    void perform(() => request(`/projects/${project.id}/conversations/${conversation.id}/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: conversation.revision, ...body }),
    }) as Promise<Conversation>);
  };
  return <><section className="page-intro"><div><p className="eyebrow">TEXT LOG</p><h1>Log work in conversation</h1><p>Describe what started or finished. Confirm each event before it enters reviewer approval.</p></div></section>
    {!project?.active_schedule_version_id && <p className="prerequisite" role="status">An active schedule is required before logging work.</p>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {loading ? <p role="status">Loading saved conversations…</p> : <div className="time-chat-layout">
      <aside className="panel time-chat-list"><h2>Conversations</h2><button className="secondary" disabled={busy || !project?.active_schedule_version_id} onClick={start}>New conversation</button>
        {recent.length ? <ul>{recent.map(item => <li key={item.id}><button className="quiet-button" aria-current={conversation?.id === item.id ? "true" : undefined} onClick={() => { setConversation(item); setError(""); void request(`/projects/${project?.id}/conversations/${item.id}`).then((fresh: Conversation) => { setConversation(fresh); setRecent(items => items.map(row => row.id === fresh.id ? fresh : row)); }).catch((reason: Error) => setError(reason.message)); }}>{item.turns[0]?.text.slice(0, 55) || "New conversation"}<small>{item.status.replaceAll("_", " ")}</small></button></li>)}</ul> : <p className="muted">No conversations yet.</p>}</aside>
      <section className="panel time-chat-main" aria-label="Conversation">
        {!conversation ? <p>Start a conversation to log an actual start or finish.</p> : <>
          <div className="time-chat-meta"><strong>{conversation.status.replaceAll("_", " ")}</strong><span>Revision {conversation.revision}</span></div>
          <ol className="time-chat-turns" aria-live="polite">{conversation.turns.map(turn => <li className={turn.role === "user" ? "user-turn" : "agent-turn"} key={turn.ordinal}><span>{turn.role === "user" ? "You" : "Assistant"}</span><p>{turn.text}</p></li>)}</ol>
          {conversation.question && conversation.turns[conversation.turns.length - 1]?.text !== conversation.question && <p className="time-chat-question" role="status">{conversation.question}</p>}
          {conversation.events.map((card, index) => <article className="time-event-card" key={index}><div><span className="eyebrow">EVENT {index + 1}</span><strong>{card.observation.event_type.replaceAll("_", " ")}</strong></div><p>{card.observation.summary}</p>
            <dl><dt>When</dt><dd>{card.effect.endpoint ? `${card.effect.endpoint.local_date}${card.effect.endpoint.local_time ? " " + card.effect.endpoint.local_time.slice(0, 5) : ""} · ${card.effect.endpoint.precision} precision` : "Needs review"}</dd><dt>Scope</dt><dd>{card.effect.scope?.replaceAll("_", " ") || "Unspecified"}</dd><dt>Activity</dt><dd>{card.activity_id ? card.selection.candidates.find(candidate => candidate.candidate_id === card.activity_id)?.activity_name || card.activity_id : "Needs clarification"}</dd></dl>
            {card.observation.evidence.map((item, evidenceIndex) => <blockquote key={evidenceIndex}>{item.quote}</blockquote>)}
            {card.selection.candidates.length > 0 && conversation.status === "draft" && <label>Change scheduled activity<select disabled={busy} value={card.activity_id || ""} onChange={event => decide("edit", { event_index: index, activity_id: event.target.value || null })}><option value="">Choose an activity</option>{card.selection.candidates.map(candidate => <option key={candidate.candidate_id} value={candidate.candidate_id}>{candidate.external_id} · {candidate.activity_name}</option>)}</select></label>}
            {conversation.status === "draft" && <EventCorrection key={`${conversation.id}:${conversation.revision}:${index}`} card={card} index={index} busy={busy} onSave={body => decide("edit", body)} />}
          </article>)}
          {conversation.status === "draft" ? <><form className="time-chat-form" onSubmit={send} data-dirty={!!text.trim()}><label>Message<textarea rows={3} value={text} onChange={event => { setText(event.target.value); sessionStorage.setItem(storageKey, event.target.value); }} disabled={busy} placeholder="Started excavation at F-01 at 08:30" /></label><label>Known report date (optional)<input type="date" value={reportDate} onChange={event => setReportDate(event.target.value)} disabled={busy} /></label><button className="primary" disabled={busy || !text.trim()}>{busy ? "Working…" : "Send"}</button></form>
            <div className="time-chat-actions"><button className="secondary" disabled={busy || !!conversation.pending_question || !conversation.events.length} onClick={() => decide("confirm", {})}>Confirm and send for review</button><button className="quiet-button" disabled={busy} onClick={() => decide("retry", {})}>Retry analysis</button><button className="quiet-button" disabled={busy} onClick={() => decide("cancel", {})}>Cancel</button></div></> : <p className="time-chat-status" role="status">{conversation.status === "accepted" ? "Accepted by a reviewer." : conversation.status === "pending_review" ? "Confirmed and awaiting reviewer acceptance." : conversation.status === "cancelled" ? "Conversation cancelled." : "Review decision recorded."} {canReview && conversation.job_id && <button className="text-button" onClick={() => onReview(conversation.job_id!)}>Open review job</button>}</p>}
        </>}
      </section></div>}
  </>;
}
