import { useEffect, useState } from "react";
import { ExecutionHistory } from "./ExecutionHistory";
type Snapshot = {
  project_id: string;
  schedule_version: number;
  items: { activity_id: string; external_id: string; name: string }[];
};
export function AuditWorkspace({
  projectId,
  request,
  fixture,
}: {
  projectId: string | null;
  request: <T>(path: string) => Promise<T>;
  fixture?: Snapshot;
}) {
  const [data, setData] = useState<Snapshot | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    if (fixture) {
      setData(fixture);
      return;
    }
    if (!projectId) return;
    request<Snapshot>(`/projects/${projectId}/progress`)
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [projectId, request, reload]);
  if (!projectId)
    return (
      <section className="panel">
        <p>Select a project to inspect its accepted history.</p>
      </section>
    );
  if (error)
    return (
      <section className="panel" role="alert">
        <p>{error}</p>
        <button className="secondary" onClick={() => setReload((n) => n + 1)}>
          Retry audit history
        </button>
      </section>
    );
  if (!data)
    return (
      <section className="panel" role="status">
        Loading the active schedule’s audit context…
      </section>
    );
  if (fixture)
    return (
      <section className="panel">
        <h2>Accepted updates and audit</h2>
        <p className="helper">
          Development fixture mode. Open Approved progress to inspect the
          synthetic event. Full history filters require an API-backed workspace.
        </p>
      </section>
    );
  return (
    <ExecutionHistory
      key={data.project_id + data.schedule_version}
      projectId={data.project_id}
      version={data.schedule_version}
      activities={data.items}
      request={request}
    />
  );
}
