import { useEffect, useState } from "react";

type Request = <T>(path: string) => Promise<T>;
type Event = { event_id: string; activity_id: string; activity_external_id: string; activity_name: string; discipline: string; work_type: string; wbs: string; status: string; correction_status: string; event_type: string; work_date: string | null; scope: string | null; blocker: string | null; blocker_category: string | null; accepted_values: Record<string, unknown>; latest_activity_state: Record<string, unknown> | null; source_locator: string | null; provenance: { source?: { original_url?: string } }; evidence: { quote: string; locator?: string }[]; confidence: unknown; decisions: unknown };
type Page = { items: Event[]; total: number; next_offset: number | null };
type Duration = { activity_id: string; activity_external_id: string; work_type: string; elapsed: { status: string; basis: string; reason: string | null; elapsed_seconds: number | null; elapsed_min_seconds: number | null; elapsed_max_seconds: number | null; date_span_days: number | null; uncertainty: string | null }; calendar_working: { reason: string }; labour_productivity: { reason: string } };

export function ExecutionHistory({ projectId, version, request, activities }: { projectId: string; version: number; request: Request; activities: { activity_id: string; external_id: string; name: string }[] }) {
  const [activity, setActivity] = useState(""), [discipline, setDiscipline] = useState(""), [workType, setWorkType] = useState("");
  const [from, setFrom] = useState(""), [to, setTo] = useState(""), [blocker, setBlocker] = useState(""), [status, setStatus] = useState(""), [correction, setCorrection] = useState("");
  const [query, setQuery] = useState(""), [offset, setOffset] = useState(0), [data, setData] = useState<Page | null>(null), [error, setError] = useState(""), [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [causes, setCauses] = useState<{ category: string; count: number }[] | null>(null);
  const [durations, setDurations] = useState<{ items: Duration[]; next_offset: number | null } | null>(null), [durationOffset, setDurationOffset] = useState(0);
  const base = `/projects/${projectId}`;
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(""); setData(null);
    request<Page>(`${base}/history?version=${version}&limit=25&offset=${offset}${query}`)
      .then(value => { if (!cancelled) setData(value); })
      .catch(reason => { if (!cancelled) setError(reason.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [base, version, offset, query, request, reload]);
  useEffect(() => {
    let cancelled = false;
    setCauses(null);
    request<{ items: { category: string; count: number }[] }>(`${base}/blockers?version=${version}`)
      .then(value => { if (!cancelled) setCauses(value.items); }).catch(reason => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [base, version, request, reload]);
  useEffect(() => {
    let cancelled = false;
    setDurations(null);
    const work = new URLSearchParams(query).get("work_type");
    request<{ items: Duration[]; next_offset: number | null }>(`${base}/durations?version=${version}&limit=25&offset=${durationOffset}${work ? `&work_type=${encodeURIComponent(work)}` : ""}`)
      .then(value => { if (!cancelled) setDurations(value); }).catch(reason => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [base, version, query, durationOffset, request, reload]);
  function apply() {
    const params = new URLSearchParams();
    for (const [key, value] of [["activity_id", activity], ["discipline", discipline], ["work_type", workType], ["date_from", from], ["date_to", to], ["blocker", blocker], ["status", status], ["correction_status", correction]]) if (value) params.set(key, value);
    setOffset(0); setDurationOffset(0); setQuery(params.size ? "&" + params.toString() : "");
  }
  return <section className="panel execution-history" aria-label="Execution history">
    <h2>Execution history</h2><p className="helper">Accepted values describe the event at approval. Latest activity state is shown separately. Superseded and retracted records remain available.</p>
    <form className="history-filters" onSubmit={event => { event.preventDefault(); apply(); }}>
      <label>Activity<select value={activity} onChange={e => setActivity(e.target.value)}><option value="">All activities</option>{activities.map(item => <option key={item.activity_id} value={item.activity_id}>{item.external_id} · {item.name}</option>)}</select></label>
      <label>Discipline<input value={discipline} onChange={e => setDiscipline(e.target.value)} /></label>
      <label>Work type<input value={workType} onChange={e => setWorkType(e.target.value)} /></label>
      <label>From work date<input type="date" value={from} onChange={e => setFrom(e.target.value)} /></label>
      <label>To work date<input type="date" value={to} onChange={e => setTo(e.target.value)} /></label>
      <label>Blocker category<select value={blocker} onChange={e => setBlocker(e.target.value)}><option value="">All events</option><option value="any">Any blocker</option>{["access", "design", "equipment", "inspection", "labour", "material", "safety", "weather", "other"].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Event status<select value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{["active", "superseded", "retracted", "retraction"].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Correction status<select value={correction} onChange={e => setCorrection(e.target.value)}><option value="">All records</option>{["original", "correction", "retraction"].map(value => <option key={value}>{value}</option>)}</select></label>
      <button className="secondary" type="submit" disabled={loading}>Apply history filters</button>
    </form>
    <p><a href={`/api/v1${base}/exports/approved.json?version=${version}`}>Export event JSON</a> · <a href={`/api/v1${base}/exports/approved.csv?version=${version}&active_only=true`}>Export active events CSV</a></p>
    <h3>Recurring blocker causes</h3><p className="helper">Counts include active reviewer-accepted events; corrections replace the earlier cause.</p>
    {causes === null ? <p role="status">{error ? "Blocker summary unavailable." : "Loading blocker summary…"}</p> : causes.length ? <ul>{causes.map(cause => <li key={cause.category}><button className="text-button" onClick={() => { setActivity(""); setDiscipline(""); setWorkType(""); setFrom(""); setTo(""); setCorrection(""); setBlocker(cause.category); setStatus("active"); setOffset(0); setDurationOffset(0); setQuery(`&blocker=${encodeURIComponent(cause.category)}&active_only=true`); }}>{cause.category}: {cause.count} · View evidence</button></li>)}</ul> : <p>No active reviewed blockers.</p>}
    <button className="secondary" onClick={() => setReload(value => value + 1)}>Refresh execution history</button>
    {error && <p role="alert" className="form-error">{error}</p>}
    {loading ? <p role="status">Loading execution history…</p> : data && <><p>{data.total} matching events</p>{!data.items.length && <p>No events match these filters.</p>}{data.items.map(event => <article className="execution-event" key={event.event_id}>
      <h3>{event.activity_external_id} · {event.activity_name}</h3><p>{event.event_type.replaceAll("_", " ")} · {event.work_date || "Date unavailable"} · {event.status} · {event.correction_status}</p>
      <p>{event.discipline} / {event.work_type} · {event.wbs} · {event.scope || "Scope not specified"}</p>
      {event.blocker && <p>Blocker: {event.blocker} ({event.blocker_category})</p>}
      {event.evidence?.map((source, index) => <figure key={index}><blockquote>{source.quote}</blockquote><figcaption>{source.locator || event.source_locator}</figcaption></figure>)}
      {event.provenance?.source?.original_url && <a href={event.provenance.source.original_url} target="_blank" rel="noreferrer">Open original evidence</a>}
      <details><summary>Accepted event values</summary><pre>{JSON.stringify(event.accepted_values, null, 2)}</pre></details>
      <details><summary>Latest activity state</summary><pre>{JSON.stringify(event.latest_activity_state, null, 2)}</pre></details>
      <details><summary>Confidence, source and decisions</summary><pre>{JSON.stringify({ confidence: event.confidence, provenance: event.provenance, decisions: event.decisions }, null, 2)}</pre></details>
    </article>)}<div className="pagination"><button className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous history page</button><span>Page {Math.floor(offset / 25) + 1}</span><button className="secondary" disabled={data.next_offset === null} onClick={() => { if (data.next_offset !== null) setOffset(data.next_offset); }}>Next history page</button></div></>}
    <h3>Actual duration by work type</h3><p className="helper">The applied work type filter also controls this list. Clock duration does not establish crew labour or continuous productive work.</p>
    {!durations ? <p role="status">{error ? "Duration results unavailable." : "Loading durations…"}</p> : <>{durations.items.map(item => <div className="execution-event" key={item.activity_id}><strong>{item.activity_external_id} · {item.work_type}</strong><p>{item.elapsed.basis.replaceAll("_", " ")}: {item.elapsed.elapsed_seconds != null ? `${item.elapsed.elapsed_seconds / 3600} hours (range ${Number(item.elapsed.elapsed_min_seconds) / 3600}–${Number(item.elapsed.elapsed_max_seconds) / 3600})` : item.elapsed.basis === "date_span" ? `${item.elapsed.date_span_days} days between reported dates; clock hours unknown` : `Unavailable: ${item.elapsed.reason?.replaceAll("_", " ")}`}</p><p>Calendar working time: unavailable — {item.calendar_working.reason.replaceAll("_", " ")}</p><p>Crew-hour productivity: unavailable — {item.labour_productivity.reason.replaceAll("_", " ")}</p></div>)}<div className="pagination"><button className="secondary" disabled={!durationOffset} onClick={() => setDurationOffset(Math.max(0, durationOffset - 25))}>Previous durations page</button><button className="secondary" disabled={durations.next_offset === null} onClick={() => { if (durations.next_offset !== null) setDurationOffset(durations.next_offset); }}>Next durations page</button></div></>}
  </section>;
}
