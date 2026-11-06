import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Application,
  type DashboardSummary,
  type MaintenanceEvent,
} from "@/api/client";
import { ApprovalBadge, KindBadge, StatusBadge } from "@/components/StatusBadge";
import { fmtRange, untilBack } from "@/lib/format";
import { useAuth } from "@/features/auth/AuthContext";

function EventRow({ event }: { event: MaintenanceEvent }) {
  const isOutage = event.kind === "manual_outage" || event.status === "extended";
  return (
    <li className="animate-rise border-b border-ink-200 py-4 last:border-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            to={`/events/${event.id}`}
            className="font-semibold text-ink hover:underline"
          >
            {event.title.replace("[DEMO] ", "")}
          </Link>
          <p className="mt-1 text-sm text-ink-muted">{fmtRange(event.starts_at, event.ends_at)}</p>
          {event.expected_impact && (
            <p className="mt-1 text-sm text-ink">
              <span className="font-medium">What’s affected:</span> {event.expected_impact}
            </p>
          )}
          {(event.status === "in_progress" ||
            event.status === "extended" ||
            event.status === "verifying") && (
            <p className={`mt-1 text-sm font-medium ${isOutage ? "text-danger" : "text-warn"}`}>
              {untilBack(event.ends_at)}
            </p>
          )}
          <p className="mt-1 text-xs text-ink-faint">
            <Link to={`/status/events/${event.id}`} className="underline hover:text-accent">
              Shareable status
            </Link>
            {event.approval_state === "approved_window" && (
              <span className="ml-2 text-warn">· planned window (not yet confirmed)</span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <KindBadge kind={event.kind} />
          <StatusBadge status={event.status} />
          <ApprovalBadge state={event.approval_state} />
        </div>
      </div>
    </li>
  );
}

function Section({
  title,
  subtitle,
  count,
  items,
  empty,
  emphasize,
}: {
  title: string;
  subtitle: string;
  count: number;
  items: MaintenanceEvent[];
  empty: string;
  emphasize?: boolean;
}) {
  return (
    <section
      className={`mh-panel p-5 ${emphasize ? "ring-1 ring-danger/30" : ""}`}
      aria-labelledby={`sec-${title}`}
    >
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 id={`sec-${title}`} className="font-display text-xl font-semibold text-ink">
            {title}
          </h2>
          <p className="text-sm text-ink-muted">{subtitle}</p>
        </div>
        <span
          className="rounded-md bg-accent-soft px-2.5 py-1 text-xs font-semibold text-ink"
          aria-label={`${count} items`}
        >
          {count}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="mt-6 text-sm text-ink-faint">{empty}</p>
      ) : (
        <ul className="mt-2">{items.map((e) => <EventRow key={`${e.id}-${e.occurrence_starts_at || ""}`} event={e} />)}</ul>
      )}
    </section>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(true);
  const [showMore, setShowMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (favoritesOnly) p.set("favorites_only", "true");
    if (search.trim()) p.set("q", search.trim());
    return p;
  }, [favoritesOnly, search]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [dash, applicationList, favs] = await Promise.all([
          api.dashboard(params),
          api.applications(),
          api.favorites(),
        ]);
        if (!cancelled) {
          setSummary(dash);
          setApps(applicationList);
          setFavorites(favs.application_ids);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params]);

  async function toggleFavorite(appId: string) {
    const next = favorites.includes(appId)
      ? favorites.filter((id) => id !== appId)
      : [...favorites, appId];
    const saved = await api.putFavorites(next);
    setFavorites(saved.application_ids);
  }

  const nowItems = [
    ...(summary?.current.items ?? []),
    ...(summary?.outages.items ?? []).filter(
      (o) => !(summary?.current.items ?? []).some((c) => c.id === o.id),
    ),
  ];

  return (
    <div className="space-y-6">
      <div className="animate-rise max-w-3xl">
        <p className="mh-eyebrow">Overview</p>
        <h1 className="font-display text-3xl font-semibold text-ink sm:text-4xl">
          What’s happening
        </h1>
        <p className="mt-2 text-ink-muted">
          Active confirmed work and what’s coming for your apps. Status is never guessed from a
          calendar window alone.
        </p>
      </div>

      <div className="mh-panel flex flex-wrap items-end gap-3 p-4">
        <div className="min-w-[14rem] flex-1">
          <label className="mh-label" htmlFor="search">
            Find an outage or window
          </label>
          <input
            id="search"
            className="mh-input"
            placeholder="Search by title or what’s affected…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <label className="mb-2 flex items-center gap-2 text-sm font-medium text-ink">
          <input
            type="checkbox"
            checked={favoritesOnly}
            onChange={(e) => setFavoritesOnly(e.target.checked)}
          />
          My apps only
        </label>
        <Link to="/alerts" className="mh-btn-ghost mb-0.5">
          My Alerts
        </Link>
        <Link to="/calendar" className="mh-btn-ghost mb-0.5">
          Open calendar
        </Link>
      </div>

      <section className="mh-panel p-5" aria-labelledby="my-apps-heading">
        <h2 id="my-apps-heading" className="font-display text-lg font-semibold">
          My apps
        </h2>
        <p className="text-sm text-ink-muted">Star apps to personalize Overview and alerts.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {apps.map((a) => {
            const fav = favorites.includes(a.id);
            return (
              <div key={a.id} className="flex items-center gap-1">
                <button
                  type="button"
                  className={
                    fav
                      ? "rounded-md border border-accent bg-accent-soft px-3 py-1 text-xs font-semibold text-ink"
                      : "rounded-md border border-ink-200 bg-surface-raised px-3 py-1 text-xs font-medium text-ink-muted hover:bg-accent-soft"
                  }
                  aria-pressed={fav}
                  onClick={() => void toggleFavorite(a.id)}
                >
                  {fav ? "★" : "☆"} {a.name.replace("[DEMO] ", "")}
                </button>
                {fav && (
                  <Link
                    to={`/status/apps/${a.key}`}
                    className="rounded-md border border-ink-200 px-2 py-1 text-xs text-ink-muted hover:bg-accent-soft"
                  >
                    Status
                  </Link>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {loading && <p className="text-sm text-ink-muted">Loading overview…</p>}
      {error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}

      {summary && !loading && (
        <>
          <p className="text-xs text-ink-faint">{summary.note || ""}</p>
          <div className="grid gap-4 lg:grid-cols-2">
            <Section
              title="Now"
              subtitle="Confirmed work in progress — including outages"
              count={nowItems.length}
              items={nowItems}
              empty="Nothing active right now for this filter."
              emphasize={nowItems.some((e) => e.kind === "manual_outage")}
            />
            <Section
              title="Coming up"
              subtitle="Confirmed or planned windows still scheduled"
              count={summary.upcoming.count}
              items={summary.upcoming.items}
              empty="No upcoming windows in this filter."
            />
          </div>

          {(summary.extended?.count || summary.cancelled?.count || showMore) && (
            <div className="pt-2">
              <button
                type="button"
                className="text-sm font-medium text-accent underline"
                onClick={() => setShowMore((v) => !v)}
                aria-expanded={showMore}
              >
                {showMore ? "Hide extensions & cancellations" : "Show extensions & cancellations"}
              </button>
            </div>
          )}

          {showMore && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Section
                title="Extensions"
                subtitle="Windows currently marked extended"
                count={summary.extended?.count ?? 0}
                items={summary.extended?.items ?? []}
                empty="No active extensions."
              />
              <Section
                title="Recent cancellations"
                subtitle="Last 14 days"
                count={summary.cancelled?.count ?? 0}
                items={summary.cancelled?.items ?? []}
                empty="No recent cancellations."
              />
              <Section
                title="Recently completed"
                subtitle="Last 14 days"
                count={summary.recent.count}
                items={summary.recent.items}
                empty="No recent completions."
              />
            </div>
          )}
        </>
      )}

      {user?.roles.includes("publisher") && (
        <p className="text-sm text-ink-muted">
          Publishing? Use{" "}
          <Link to="/events/new?quick=1" className="font-medium text-accent underline">
            Schedule maintenance
          </Link>{" "}
          for a minimal flow.
        </p>
      )}
    </div>
  );
}
