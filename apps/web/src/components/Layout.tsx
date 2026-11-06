import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import { useExperience } from "@/features/experience/ExperienceContext";
import { getTheme, toggleTheme } from "@/lib/theme";
import clsx from "clsx";

export function Layout() {
  const { user, logout } = useAuth();
  const { can, label: profileLabel } = useExperience();
  const [theme, setThemeState] = useState(getTheme());
  const isPublisher =
    user?.roles.some((r) =>
      ["publisher", "application_owner", "platform_administrator"].includes(r),
    ) ?? false;
  const isAdmin = user?.roles.includes("platform_administrator") ?? false;
  const showAdmin = isAdmin && can("admin_workspace");

  const primary = [
    { to: "/", label: "Overview", end: true },
    { to: "/calendar", label: "Calendar", end: false },
    { to: "/alerts", label: "My Alerts", end: false },
  ];

  return (
    <div className="min-h-screen">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-sm focus:text-accent-fg"
      >
        Skip to main content
      </a>
      <header className="border-b border-ink-200/80 bg-surface/80 backdrop-blur-md">
        <div className="mh-shell flex flex-wrap items-center justify-between gap-3 py-3.5">
          <div className="flex items-baseline gap-3">
            <NavLink to="/" className="font-display text-2xl font-semibold tracking-tight text-ink">
              MaintenanceHub
            </NavLink>
            <span className="hidden text-[10px] font-semibold uppercase tracking-[0.18em] text-ink-faint sm:inline">
              {profileLabel}
            </span>
          </div>

          <nav className="order-3 flex w-full flex-wrap items-center gap-1 sm:order-none sm:w-auto" aria-label="Primary">
            {primary.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    isActive ? "bg-ink text-accent-fg" : "text-ink-muted hover:bg-accent-soft hover:text-ink",
                  )
                }
              >
                {l.label}
              </NavLink>
            ))}
            {can("catalog_browse") && (
              <NavLink
                to="/catalog"
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                    isActive ? "bg-ink text-accent-fg" : "text-ink-muted hover:bg-accent-soft hover:text-ink",
                  )
                }
              >
                Apps
              </NavLink>
            )}
            {showAdmin && (
              <NavLink
                to="/admin"
                className={({ isActive }) =>
                  clsx(
                    "rounded-md px-3 py-1.5 text-sm font-medium transition",
                    isActive
                      ? "bg-ink text-accent-fg"
                      : "border border-ink-200 text-ink-muted hover:bg-accent-soft",
                  )
                }
              >
                Admin
              </NavLink>
            )}
          </nav>

          <div className="flex items-center gap-2">
            {isPublisher && (
              <Link to="/events/new?quick=1" className="mh-btn whitespace-nowrap">
                Schedule maintenance
              </Link>
            )}
            <button
              type="button"
              className="mh-btn-ghost px-2.5"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              onClick={() => setThemeState(toggleTheme())}
            >
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            <div className="hidden text-right leading-tight sm:block">
              <div className="text-sm font-medium text-ink">{user?.display_name}</div>
              <div className="text-[11px] text-ink-faint">{user?.roles.join(", ")}</div>
            </div>
            <button type="button" className="mh-btn-ghost" onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main id="main-content" className="mh-shell py-8" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="mh-shell border-t border-ink-200/60 py-6 text-xs text-ink-faint">
        <div className="flex flex-wrap gap-4">
          <Link to="/about" className="hover:text-ink">
            About & limitations
          </Link>
          {can("banner_embed") && (
            <Link to="/banner-demo" className="hover:text-ink">
              Banner embed
            </Link>
          )}
          <span>Communication platform — not monitoring</span>
        </div>
      </footer>
    </div>
  );
}
