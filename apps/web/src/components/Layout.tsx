import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import clsx from "clsx";

const baseLinks = [
  { to: "/", label: "Dashboard" },
  { to: "/calendar", label: "Calendar" },
  { to: "/catalog", label: "Catalog" },
  { to: "/subscriptions", label: "Subscriptions" },
  { to: "/banner-demo", label: "Banner" },
  { to: "/events/new", label: "Publish" },
  { to: "/about", label: "About" },
];

export function Layout() {
  const { user, logout } = useAuth();
  const isAdmin = user?.roles.includes("platform_administrator");
  const links = isAdmin
    ? [...baseLinks.slice(0, -1), { to: "/admin", label: "Admin" }, baseLinks[baseLinks.length - 1]]
    : baseLinks;

  return (
    <div className="min-h-screen">
      <header className="border-b border-ink-200/70 bg-white/70 backdrop-blur">
        <div className="mh-shell flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex items-baseline gap-3">
            <NavLink to="/" className="font-display text-2xl font-semibold tracking-tight text-ink-950">
              MaintenanceHub
            </NavLink>
            <span className="hidden text-xs font-medium uppercase tracking-[0.16em] text-ink-400 sm:inline">
              Outage communication
            </span>
          </div>
          <nav className="flex flex-wrap items-center gap-1" aria-label="Primary">
            {links.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.to === "/"}
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition",
                    isActive
                      ? "bg-ink-900 text-white"
                      : "text-ink-700 hover:bg-ink-100",
                  )
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
          <div className="flex items-center gap-3 text-sm">
            <div className="text-right leading-tight">
              <div className="font-medium text-ink-900">{user?.display_name}</div>
              <div className="text-xs text-ink-500">{user?.roles.join(", ")}</div>
            </div>
            <button type="button" className="mh-btn-ghost" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mh-shell py-8">
        <Outlet />
      </main>
    </div>
  );
}
