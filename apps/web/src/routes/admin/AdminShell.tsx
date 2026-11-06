import type { ReactNode } from "react";
import { NavLink, Navigate, Outlet } from "react-router-dom";
import clsx from "clsx";
import { useAuth } from "@/features/auth/AuthContext";

const sections = [
  { to: "/admin", label: "Overview", end: true },
  { to: "/admin/catalog", label: "Apps & Dependencies" },
  { to: "/admin/servicenow", label: "ServiceNow & CMDB" },
  { to: "/admin/notifications", label: "Notifications" },
  { to: "/admin/users", label: "Users & Permissions" },
  { to: "/admin/jobs", label: "Jobs & Delivery" },
  { to: "/admin/audit", label: "Audit" },
];

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="py-16 text-center text-sm text-ink-500">Checking administrator access…</div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (!user.roles.includes("platform_administrator")) {
    return (
      <div className="mh-panel mx-auto max-w-lg p-8 text-center">
        <h1 className="font-display text-2xl font-semibold text-ink-950">Administration</h1>
        <p className="mt-3 text-sm text-ink-600">
          This workspace requires the <code>platform_administrator</code> role. API authorization
          enforces the same rule — navigation alone is not a security boundary.
        </p>
        <NavLink to="/" className="mh-btn mt-6 inline-flex">
          Back to dashboard
        </NavLink>
      </div>
    );
  }
  return children;
}

export function AdminShell() {
  return (
    <RequireAdmin>
      <div className="space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
              Enterprise
            </p>
            <h1 className="font-display text-3xl font-semibold text-ink-950">Administration</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-600">
              Catalog, integrations, notifications, permissions, jobs, and audit — secured by API
              role checks. Secrets stay in environment / OpenShift; this UI never edits them.
            </p>
          </div>
        </header>
        <nav
          className="flex flex-wrap gap-1 rounded-xl border border-ink-200/80 bg-white/80 p-1.5 shadow-sm"
          aria-label="Administration"
        >
          {sections.map((s) => (
            <NavLink
              key={s.to}
              to={s.to}
              end={s.end}
              className={({ isActive }) =>
                clsx(
                  "rounded-lg px-3 py-2 text-sm font-medium transition",
                  isActive
                    ? "bg-ink-900 text-white shadow-sm"
                    : "text-ink-700 hover:bg-ink-100",
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
