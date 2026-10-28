import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  CalendarRange,
  FileInput,
  Inbox,
  ChartNoAxesCombined,
  History,
  Upload,
  LogOut,
  Sun,
  Moon,
  ChevronDown,
  Layers3,
} from "lucide-react";
const destinations = [
  ["overview", "Overview", LayoutDashboard],
  ["schedule", "Schedule", CalendarRange],
  ["intake", "Report intake", FileInput],
  ["queue", "Review queue", Inbox],
  ["progress", "Approved progress", ChartNoAxesCombined],
  ["history", "Job history", History],
  ["scheduleImport", "Import schedule", Upload],
] as const;
export type WorkspaceView = (typeof destinations)[number][0] | "job" | "review";
export function WorkspaceNav({
  view,
  reviewer,
  disabled,
  onNavigate,
  username,
  onSignOut,
}: {
  view: string;
  reviewer: boolean;
  disabled: boolean;
  onNavigate: (view: WorkspaceView) => void;
  username: string;
  onSignOut: () => void;
}) {
  const [dark, setDark] = useState(() => {
    try {
      return localStorage.getItem("time-agent-theme") === "dark";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try {
      localStorage.setItem("time-agent-theme", dark ? "dark" : "light");
    } catch {
      /* The appearance still works without storage. */
    }
  }, [dark]);
  return (
    <aside className="navigation-rail">
      <a
        className="product-brand"
        href="#"
        onClick={(e) => {
          e.preventDefault();
          onNavigate("overview");
        }}
      >
        <span className="product-symbol">
          <Layers3 size={22} />
        </span>
        <span>
          time<span className="brand-light">agent</span>
          <small>PROJECT WORKSPACE</small>
        </span>
      </a>
      <div className="rail-label">WORKSPACE</div>
      <nav aria-label="Workspace">
        {destinations
          .filter(
            ([id]) =>
              reviewer || ["overview", "schedule", "progress"].includes(id),
          )
          .map(([id, label, Icon]) => (
            <button
              key={id}
              aria-label={label}
              title={label}
              disabled={disabled}
              aria-current={
                view === id ||
                (id === "intake" && ["job", "review"].includes(view))
                  ? "page"
                  : undefined
              }
              onClick={() => onNavigate(id)}
            >
              <Icon size={18} />
              <span>{label}</span>
              {id === "schedule" && <span className="nav-dot" />}
            </button>
          ))}
      </nav>
      <div className="rail-note">
        <span className="live-dot" /> Evidence-led progress
        <p>Every accepted update has a source and a reviewer.</p>
      </div>
      <div className="rail-footer">
        <button
          className="theme-control"
          onClick={() => setDark(!dark)}
          aria-label={dark ? "Use light theme" : "Use dark theme"}
        >
          {dark ? <Sun size={17} /> : <Moon size={17} />}
          <span>{dark ? "Light appearance" : "Dark appearance"}</span>
        </button>
        <div className="user-row">
          <span className="user-avatar">
            {username.slice(0, 2).toUpperCase()}
          </span>
          <span>
            {username}
            <small>{reviewer ? "Project reviewer" : "Project viewer"}</small>
          </span>
          <button
            aria-label="Sign out"
            title="Sign out"
            disabled={disabled}
            onClick={onSignOut}
          >
            <LogOut size={17} />
          </button>
        </div>
      </div>
    </aside>
  );
}
type Project = {
  id: string;
  name: string;
  timezone: string;
  active_schedule_version_id: string | null;
};
export function WorkspaceBar({
  project,
  projects,
  disabled,
  onProject,
  fixture,
}: {
  project: Project | null;
  projects: Project[];
  disabled: boolean;
  onProject: (p: Project) => void;
  fixture: boolean;
}) {
  return (
    <header className="workspace-bar">
      <div className="project-switch">
        <span className="project-monogram">
          {project?.name.slice(0, 1) || "P"}
        </span>
        <div>
          <span className="bar-caption">CURRENT PROJECT</span>
          {projects.length > 1 ? (
            <select
              aria-label="Active project"
              disabled={disabled}
              value={project?.id || ""}
              onChange={(e) => {
                const p = projects.find((p) => p.id === e.target.value);
                if (p) onProject(p);
              }}
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          ) : (
            <strong>{project?.name || "Select a project"}</strong>
          )}
        </div>
        <ChevronDown size={14} />
      </div>
      <div className="bar-status">
        {fixture && <span className="fixture-label">Development fixture</span>}
        <span className="live-dot" />
        <span>
          {project?.active_schedule_version_id
            ? "Active schedule"
            : "Schedule setup"}
          <small>{project?.timezone || "Project workspace"}</small>
        </span>
      </div>
    </header>
  );
}
