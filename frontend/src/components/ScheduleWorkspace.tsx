import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  CalendarRange,
  Search,
  ListFilter,
  ChevronRight,
  ChevronLeft,
  CheckCheck,
  Inbox,
  Layers3,
  Upload,
  FileInput,
} from "lucide-react";
import { Tabs } from "@base-ui/react/tabs";
import type { WorkspaceView } from "./WorkspaceNav";
type Item = {
  activity_id: string;
  external_id: string;
  name: string;
  wbs: string;
  planned_start?: string | null;
  planned_finish?: string | null;
  actual_start?: string | null;
  actual_finish?: string | null;
  physical_percent: string | null;
  completed_quantity: string;
  planned_quantity: string | null;
  unit: string | null;
  approved_event_count: number;
  lifecycle_status?: string | null;
};
type Data = {
  schedule_version: number;
  counts: {
    activities: number;
    approved_events: number;
    pending_review: number;
  };
  items: Item[];
  notice: string;
};
type Project = {
  id: string;
  name: string;
  active_schedule_version_id: string | null;
};
const dateLabel = (v: string | null | undefined) =>
  v
    ? new Date(v + "T00:00:00Z").toLocaleDateString(undefined, {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      })
    : "—";
export function ScheduleWorkspace({
  project,
  overview,
  request,
  fixture,
  canReview,
  onNavigate,
}: {
  project: Project | null;
  overview: boolean;
  request: <T>(path: string) => Promise<T>;
  fixture?: Data;
  canReview: boolean;
  onNavigate: (v: WorkspaceView) => void;
}) {
  const [data, setData] = useState<Data | null>(null),
    [error, setError] = useState(""),
    [reload, setReload] = useState(0),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [mode, setMode] = useState("timeline"),
    [collapsed, setCollapsed] = useState<Set<string>>(new Set()),
    [page, setPage] = useState(0),
    [windowDays, setWindowDays] = useState(0),
    [dateOffset, setDateOffset] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    if (fixture) {
      setData(fixture);
      return;
    }
    if (!project?.active_schedule_version_id) return;
    request<Data>(`/projects/${project.id}/progress`)
      .then((d) => {
        if (active) setData(d);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [project?.id, project?.active_schedule_version_id, reload]);
  const filtered = useMemo(
    () =>
      data?.items.filter(
        (i) =>
          (i.name + " " + i.external_id + " " + i.wbs)
            .toLowerCase()
            .includes(query.toLowerCase()) &&
          (filter === "all" ||
            (filter === "accepted" && i.approved_event_count > 0) ||
            (filter === "unreported" && i.approved_event_count === 0)),
      ) || [],
    [data, query, filter],
  );
  const dates = (data?.items || [])
    .flatMap((i) => [i.planned_start, i.planned_finish])
    .filter((d): d is string => !!d)
    .map((d) => Date.parse(d));
  const baselineStart = dates.reduce((a, b) => Math.min(a, b), Infinity),
    baselineEnd = dates.reduce((a, b) => Math.max(a, b), -Infinity);
  const start = dates.length
      ? baselineStart + dateOffset * windowDays * 86400000
      : 0,
    end = dates.length
      ? windowDays
        ? start + windowDays * 86400000
        : baselineEnd
      : 0,
    span = Math.max(end - start, 86400000);
  const groups = [
    ...new Set(filtered.map((i) => i.wbs || "Ungrouped activities")),
  ];
  const visible = filtered.slice(page * 50, (page + 1) * 50);
  const toggle = (key: string) =>
    setCollapsed((old) => {
      const next = new Set(old);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  return (
    <>
      <div className="workspace-breadcrumb">
        Workspace <ChevronRight size={12} />
        {overview ? "Project overview" : "Schedule workspace"}
      </div>
      <section className="page-intro">
        <div>
          <p className="eyebrow">
            {overview ? "A CLEAR VIEW OF THE WORK" : "THE PLAN, IN PERSPECTIVE"}
          </p>
          <h1>
            {overview ? "Project overview" : "Schedule workspace"}
            <span className="heading-dot">.</span>
          </h1>
          <p>
            {overview
              ? "Your schedule, field evidence, and accepted progress. Connected."
              : "Explore the active schedule. Trace every activity back to the plan."}
          </p>
        </div>
        {canReview && (
          <button
            className="primary"
            onClick={() => onNavigate(overview ? "intake" : "scheduleImport")}
          >
            {overview ? <FileInput size={16} /> : <Upload size={16} />}
            {overview ? "New field report" : "Import schedule"}
          </button>
        )}
      </section>
      {error ? (
        <section className="panel" role="alert">
          <h2>Could not load this schedule</h2>
          <p>{error}</p>
          <button className="secondary" onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </section>
      ) : !data && project?.active_schedule_version_id ? (
        <div
          className="workspace-skeleton"
          role="status"
          aria-label="Loading schedule"
        >
          <div />
          <div />
          <div />
        </div>
      ) : !data ? (
        <section className="setup-empty panel">
          <CalendarRange size={36} />
          <p className="eyebrow">A STRONG START</p>
          <h2>
            {project
              ? "Bring your project plan into focus."
              : "Your next project starts here."}
          </h2>
          <p>
            Import a schedule, verify its mapping, then explicitly activate the
            version your team will work from.
          </p>
          {canReview && (
            <button
              className="primary"
              onClick={() => onNavigate("scheduleImport")}
            >
              Set up your schedule <ArrowUpRight size={16} />
            </button>
          )}
        </section>
      ) : (
        <>
          {overview && (
            <div className="overview-metrics">
              {[
                [
                  Layers3,
                  "Scheduled activities",
                  data.counts.activities,
                  "In the active version",
                ],
                [
                  CheckCheck,
                  "Accepted events",
                  data.counts.approved_events,
                  "Source-backed updates",
                ],
                [
                  Inbox,
                  "Awaiting review",
                  data.counts.pending_review,
                  "Proposals, not accepted progress",
                ],
              ].map(([Icon, label, value, caption], index) => {
                const Glyph = Icon as typeof Layers3;
                return (
                  <div className="overview-metric" key={String(label)}>
                    <span className={"metric-icon tone-" + index}>
                      <Glyph size={19} />
                    </span>
                    <span className="metric-label">{String(label)}</span>
                    <strong>{String(value).padStart(2, "0")}</strong>
                    <small>{String(caption)}</small>
                  </div>
                );
              })}
            </div>
          )}
          {overview && canReview && (
            <button
              className="review-invitation"
              onClick={() => onNavigate("queue")}
            >
              <span className="invitation-icon">
                <Inbox size={20} />
              </span>
              <span>
                <strong>
                  {data.counts.pending_review
                    ? "Evidence is ready for your attention."
                    : "Keep the field and the plan connected."}
                </strong>
                <small>
                  {data.counts.pending_review
                    ? `${data.counts.pending_review} pending proposals · Review before progress changes.`
                    : "Submit field reports to build a traceable record of work."}
                </small>
              </span>
              <span className="invitation-action">
                Open review queue <ArrowUpRight size={17} />
              </span>
            </button>
          )}
          <section className="schedule-surface">
            <div className="schedule-title">
              <div>
                <p className="eyebrow">
                  ACTIVE SCHEDULE{" "}
                  <span className="version-chip">V{data.schedule_version}</span>
                </p>
                <h2>{overview ? "The work ahead" : "Activity register"}</h2>
              </div>
              <Tabs.Root
                value={mode}
                onValueChange={(v) => setMode(String(v))}
                className="glass-tabs"
              >
                <Tabs.List activateOnFocus aria-label="Schedule view">
                  <Tabs.Tab value="timeline">
                    <CalendarRange size={15} /> Timeline
                  </Tabs.Tab>
                  <Tabs.Tab value="table">
                    <ListFilter size={15} /> Table
                  </Tabs.Tab>
                  <Tabs.Indicator className="glass-tab-indicator" />
                </Tabs.List>
              </Tabs.Root>
            </div>
            <div className="schedule-tools">
              <label className="search-field">
                <Search size={16} />
                <input
                  aria-label="Search schedule"
                  placeholder="Search activities or WBS…"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(0);
                  }}
                />
              </label>
              <select
                aria-label="Filter activities"
                value={filter}
                onChange={(e) => {
                  setFilter(e.target.value);
                  setPage(0);
                }}
              >
                <option value="all">All activities</option>
                <option value="accepted">With accepted updates</option>
                <option value="unreported">No accepted updates</option>
              </select>
              <span className="schedule-range">
                {dates.length
                  ? `${dateLabel(new Date(start).toISOString().slice(0, 10))} — ${dateLabel(new Date(end).toISOString().slice(0, 10))}`
                  : "Planned dates unavailable"}
              </span>
            </div>
            {mode === "timeline" && dates.length > 0 && (
              <div className="timeline-navigation">
                <div>
                  <button
                    aria-label="Previous date window"
                    disabled={!windowDays || dateOffset <= 0}
                    onClick={() => setDateOffset((n) => n - 1)}
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span aria-live="polite">
                    {dateLabel(new Date(start).toISOString().slice(0, 10))} —{" "}
                    {dateLabel(new Date(end).toISOString().slice(0, 10))}
                  </span>
                  <button
                    aria-label="Next date window"
                    disabled={!windowDays || end >= baselineEnd}
                    onClick={() => setDateOffset((n) => n + 1)}
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
                <select
                  aria-label="Timeline scale"
                  value={windowDays}
                  onChange={(e) => {
                    setWindowDays(Number(e.target.value));
                    setDateOffset(0);
                  }}
                >
                  <option value={0}>Fit schedule</option>
                  <option value={30}>30 days</option>
                  <option value={90}>90 days</option>
                </select>
              </div>
            )}
            <p className="schedule-scroll-hint">
              Scroll horizontally to explore the full schedule →
            </p>
            <div
              className="schedule-scroll"
              tabIndex={0}
              role="region"
              aria-label="Scrollable activity schedule"
            >
              <table
                role="table"
                aria-label="Schedule activities"
                className={"activity-table " + mode}
              >
                <thead>
                  <tr>
                    <th scope="col">Activity / work breakdown</th>
                    {mode === "table" ? (
                      <>
                        <th scope="col">Planned start</th>
                        <th scope="col">Planned finish</th>
                        <th scope="col">Accepted quantity</th>
                        <th scope="col">Physical progress</th>
                      </>
                    ) : (
                      <th scope="col" className="timeline-column">
                        <div className="timeline-scale">
                          {[0, 0.25, 0.5, 0.75, 1].map((n) => (
                            <span key={n}>
                              {dates.length
                                ? new Date(start + span * n).toLocaleDateString(
                                    undefined,
                                    { month: "short", day: "numeric", timeZone: "UTC" },
                                  )
                                : "—"}
                            </span>
                          ))}
                        </div>
                      </th>
                    )}
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {groups
                    .filter((g) =>
                      visible.some(
                        (i) => (i.wbs || "Ungrouped activities") === g,
                      ),
                    )
                    .map((g) => (
                      <Group
                        key={g}
                        group={g}
                        collapsed={collapsed.has(g)}
                        toggle={() => toggle(g)}
                        items={visible.filter(
                          (i) => (i.wbs || "Ungrouped activities") === g,
                        )}
                        mode={mode}
                        start={start}
                        span={span}
                      />
                    ))}
                </tbody>
              </table>
            </div>
            {!filtered.length && (
              <div className="table-empty">
                {data.items.length
                  ? "No activities match your filters."
                  : "No activities are available in this version."}
              </div>
            )}
            <footer className="schedule-footer">
              <span>
                {filtered.length} activities{" "}
                <span className="footer-separator">·</span>{" "}
                <span className="legend-dot" /> Imported baseline
              </span>
              <span>Read-only schedule</span>
              {filtered.length > 50 && (
                <div>
                  <button
                    aria-label="Previous activities"
                    disabled={!page}
                    onClick={() => setPage((n) => n - 1)}
                  >
                    <ChevronLeft size={16} />
                  </button>{" "}
                  {page + 1} / {Math.ceil(filtered.length / 50)}{" "}
                  <button
                    aria-label="Next activities"
                    disabled={(page + 1) * 50 >= filtered.length}
                    onClick={() => setPage((n) => n + 1)}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              )}
            </footer>
          </section>
          <p className="data-footnote">
            {data.notice}{" "}
            {mode === "timeline"
              ? "Bars show imported planned dates; undated activities remain visible."
              : ""}
          </p>
          {overview && (
            <div className="overview-bottom">
              <div>
                <span className="live-dot" /> Version {data.schedule_version} ·
                Active project schedule
              </div>
              <button
                className="text-button"
                onClick={() => onNavigate("progress")}
              >
                Explore approved progress <ArrowUpRight size={14} />
              </button>
            </div>
          )}
        </>
      )}
    </>
  );
}
function Group({
  group,
  collapsed,
  toggle,
  items,
  mode,
  start,
  span,
}: {
  group: string;
  collapsed: boolean;
  toggle: () => void;
  items: Item[];
  mode: string;
  start: number;
  span: number;
}) {
  return (
    <>
      <tr className="wbs-row">
        <th colSpan={mode === "table" ? 6 : 3}>
          <button onClick={toggle} aria-expanded={!collapsed}>
            <ChevronRight
              size={14}
              style={{ transform: collapsed ? "" : "rotate(90deg)" }}
            />
            {group}
            <span>{items.length}</span>
          </button>
        </th>
      </tr>
      {!collapsed &&
        items.map((item) => (
          <tr key={item.activity_id}>
            <td>
              <span className="activity-id">{item.external_id}</span>
              <strong>{item.name}</strong>
            </td>
            {mode === "table" ? (
              <>
                <td>{dateLabel(item.planned_start)}</td>
                <td>{dateLabel(item.planned_finish)}</td>
                <td>
                  {item.completed_quantity} / {item.planned_quantity ?? "—"}{" "}
                  {item.unit}
                </td>
                <td>
                  {item.physical_percent === null
                    ? "Not measured"
                    : `${item.physical_percent}%`}
                </td>
              </>
            ) : (
              <td className="timeline-cell">
                {item.planned_start && item.planned_finish ? (
                  Date.parse(item.planned_finish) >= start &&
                  Date.parse(item.planned_start) <= start + span ? (
                    <div
                      className="gantt-bar"
                      title={`${item.name}: ${dateLabel(item.planned_start)} — ${dateLabel(item.planned_finish)}`}
                      style={{
                        left: `${Math.max(0, (Date.parse(item.planned_start) - start) / span) * 96}%`,
                        width: `${Math.max(1.5, ((Math.min(start + span, Date.parse(item.planned_finish)) - Math.max(start, Date.parse(item.planned_start))) / span) * 96)}%`,
                      }}
                    >
                      <span />
                    </div>
                  ) : (
                    <span className="undated">Outside this date window</span>
                  )
                ) : (
                  <span className="undated">No planned date range</span>
                )}
              </td>
            )}
            <td>
              <span
                className={
                  "activity-status " +
                  (item.approved_event_count ? "accepted" : "neutral")
                }
              >
                <span />
                {item.lifecycle_status?.replaceAll("_", " ") ||
                  (item.approved_event_count
                    ? "Updates accepted"
                    : "No updates")}
              </span>
            </td>
          </tr>
        ))}
    </>
  );
}
