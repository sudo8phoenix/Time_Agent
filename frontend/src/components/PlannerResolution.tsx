import { useState } from "react";

type Activity = { id: string; name: string; area: string; external_id: string; wbs: string };
export function PlannerResolution({ proposalId, disabled, search, choose, resolve }: {
  proposalId: string; disabled: boolean;
  search: (query: string, offset: number) => Promise<{ items: Activity[]; total: number }>;
  choose: (activity: Activity) => void;
  resolve: (outcome: string) => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Activity[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (next: number) => {
    setBusy(true); setError("");
    try { const result = await search(query, next); setItems(result.items); setTotal(result.total); setOffset(next); }
    catch (value) { setError(value instanceof Error ? value.message : "Search failed."); }
    finally { setBusy(false); }
  };
  return <fieldset className="planner-resolution" disabled={disabled || busy} key={proposalId}>
    <legend>Planner resolution</legend>
    <label>Search the pinned schedule<input value={query} onChange={e => setQuery(e.target.value)} /></label>
    <button className="secondary" onClick={() => void run(0)}>Search activities</button>
    <p className="helper" role="status">{busy ? "Searching…" : total === null ? "Search by activity ID, terminology, location, discipline or WBS." : `${total} eligible activities found. Select an activity, then save a revision with your reason.`}</p>
    {items.map(item => <button className="secondary" key={item.id} onClick={() => choose(item)}>{item.external_id} · {item.name} · {item.area} · {item.wbs}</button>)}
    {offset > 0 && <button onClick={() => void run(offset - 50)}>Previous results</button>}
    {total !== null && offset + items.length < total && <button onClick={() => void run(offset + 50)}>Next results</button>}
    <button className="secondary" onClick={() => void resolve("request_clarification")}>Request clarification</button>
    <button className="secondary" onClick={() => void resolve("missing_schedule_scope")}>Flag missing schedule scope</button>
    {error && <p className="form-error" role="alert">{error}</p>}
  </fieldset>;
}
