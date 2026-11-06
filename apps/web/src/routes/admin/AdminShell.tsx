import type { ReactNode } from "react";
import { NavLink, Navigate, Outlet } from "react-router-dom";
import clsx from "clsx";
import { useAuth } from "@/features/auth/AuthContext";
import { useExperience } from "@/features/experience/ExperienceContext";

const sections = [
  { to: "/admin", label: "Overview", end: true, capability: "admin_workspace" },
  { to: "/admin/catalog", label: "Apps & dependencies", capability: "admin_workspace" },
  { to: "/admin/servicenow", label: "Integrations & import", capability: "servicenow" },
  { to: "/admin/notifications", label: "Notifications", capability: "notification_admin" },
  { to: "/admin/users", label: "Users & permissions", capability: "admin_users" },
  { to: "/admin/jobs", label: "Jobs & delivery", capability: "admin_workspace" },
  { to: "/admin/audit", label: "Audit", capability: "admin_workspace" },
];

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="py-16 text-center text-sm text-ink-muted">Checking administrator access…</div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!user.roles.includes("platform_administrator")) {
    return (
      <div className="mh-panel mx-auto max-w-lg p-8 text-center">
        <h1 className="font-display text-2xl font-semibold text-ink">Administration</h1>
        <p className="mt-3 text-sm text-ink-muted">
          This workspace requires the <code>platform_administrator</code> role. API authorization
          enforces the same rule — navigation alone is not a security boundary.
        </p>
        <NavLink to="/" className="mh-btn mt-6 inline-flex">
          Back to Overview
        </NavLink>
      </div>
    );
  }
  return children;
}

export function AdminShell() {
  const { can } = useExperience();
  const visible = sections.filter((s) => can(s.capability));

  return (
    <RequireAdmin>
      <div className="space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="mh-eyebrow">Admin · separated from consumer nav</p>
            <h1 className="font-display text-3xl font-semibold text-ink">Administration</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-muted">
              Catalog, integrations, notifications, permissions, jobs, and audit — secured by API
              role checks. Secrets stay in environment / OpenShift; this UI never edits them.
            </p>
          </div>
        </header>
        <nav
          className="flex flex-wrap gap-1 rounded-xl border border-ink-200 bg-surface/80 p-1.5"
          aria-label="Administration"
        >
          {visible.map((s) => (
            <NavLink
              key={s.to}
              to={s.to}
              end={s.end}
              className={({ isActive }) =>
                clsx(
                  "rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive ? "bg-ink text-accent-fg shadow-sm" : "text-ink-muted hover:bg-accent-soft",
                )
              }
            >
              {s.label}
            </NavLink>
          ))}
        </nav>
        <Outlet />
      </div>
    </RequireAdmin>
  );
}
