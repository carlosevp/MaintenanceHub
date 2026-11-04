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

function EventRow({ event }: { event: MaintenanceEvent }) {
  return (
    <li className="animate-rise border-b border-ink-100 py-4 last:border-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Link
            to={`/events/${event.id}`}
            className="font-semibold text-ink-950 hover:text-accent-strong hover:underline"
          >
            {event.title}
          </Link>
          <p className="mt-1 text-sm text-ink-600">{fmtRange(event.starts_at, event.ends_at)}</p>
          {event.expected_impact && (
            <p className="mt-1 text-sm text-ink-700">
              <span className="font-medium">Impact:</span> {event.expected_impact}
            </p>
          )}
          {(event.status === "in_progress" ||
            event.status === "extended" ||
            event.status === "verifying") && (
            <p className="mt-1 text-sm font-medium text-warn">{untilBack(event.ends_at)}</p>
          )}
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
}: {
  title: string;
  subtitle: string;
  count: number;
  items: MaintenanceEvent[];
  empty: string;
}) {
  return (
    <section className="mh-panel p-5">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-xl font-semibold text-ink-950">{title}</h2>
          <p className="text-sm text-ink-500">{subtitle}</p>
        </div>
        <span
          className="rounded-full bg-ink-100 px-2.5 py-1 text-xs font-semibold text-ink-700"
          aria-label={`${count} items`}
        >
          {count}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="mt-6 text-sm text-ink-500">{empty}</p>
      ) : (
        <ul className="mt-2">{items.map((e) => <EventRow key={e.id} event={e} />)}</ul>
      )}
    </section>
  );
}

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [appFilter, setAppFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (appFilter) p.set("application_id", appFilter);
    if (kindFilter) p.set("kind", kindFilter);
    if (favoritesOnly) p.set("favorites_only", "true");
    return p;
  }, [appFilter, kindFilter, favoritesOnly]);

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

  return (
    <div className="space-y-6">
      <div className="animate-rise">
        <h1 className="font-display text-3xl font-semibold text-ink-950">
          What is down, scheduled, and when will it be back?
        </h1>
        <p className="mt-2 max-w-3xl text-ink-600">
          Status is communicated by people — MaintenanceHub does not probe or monitor applications.
        </p>
      </div>

      <div className="mh-panel flex flex-wrap items-end gap-3 p-4">
        <div className="min-w-[12rem] flex-1">
          <label className="mh-label" htmlFor="app-filter">
            Application
          </label>
          <select
            id="app-filter"
            className="mh-input"
            value={appFilter}
            onChange={(e) => setAppFilter(e.target.value)}
          >
            <option value="">All applications</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[10rem]">
          <label className="mh-label" htmlFor="kind-filter">
            Kind
          </label>
          <select
            id="kind-filter"
            className="mh-input"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
          >
            <option value="">All kinds</option>
            <option value="planned_maintenance">Planned maintenance</option>
            <option value="manual_outage">Manual outage</option>
          </select>
        </div>
        <label className="mb-2 flex items-center gap-2 text-sm font-medium text-ink-700">
          <input
            type="checkbox"
            checked={favoritesOnly}
            onChange={(e) => setFavoritesOnly(e.target.checked)}
          />
          Favorites only
        </label>
        <Link to="/events/new?kind=manual_outage" className="mh-btn-ghost mb-0.5">
          Report outage
        </Link>
        <Link to="/events/new" className="mh-btn mb-0.5">
          Publish maintenance
        </Link>
      </div>

      {apps.length > 0 && (
        <div className="flex flex-wrap gap-2" aria-label="Favorite applications">
          {apps.map((a) => {
            const fav = favorites.includes(a.id);
            return (
              <button
                key={a.id}
                type="button"
                className={
                  fav
                    ? "rounded-full border border-accent bg-accent-soft px-3 py-1 text-xs font-semibold text-accent-strong"
                    : "rounded-full border border-ink-200 bg-white px-3 py-1 text-xs font-medium text-ink-600 hover:bg-ink-50"
                }
                aria-pressed={fav}
                onClick={() => void toggleFavorite(a.id)}
              >
                {fav ? "★" : "☆"} {a.name.replace("[DEMO] ", "")}
              </button>
            );
          })}
        </div>
      )}

      {loading && <p className="text-sm text-ink-500">Loading dashboard…</p>}
      {error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}

      {summary && !loading && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Section
            title="Currently impacting"
            subtitle="In progress, extended, or verifying right now"
            count={summary.current.count}
            items={summary.current.items}
            empty="Nothing is currently in an active maintenance or outage window."
          />
          <Section
            title="Active outages"
            subtitle="Manually reported — distinct from planned work"
            count={summary.outages.count}
            items={summary.outages.items}
            empty="No open manual outages."
          />
          <Section
            title="Upcoming"
            subtitle="Confirmed or approved windows still scheduled"
            count={summary.upcoming.count}
            items={summary.upcoming.items}
            empty="No upcoming maintenance in this filter."
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
    </div>
  );
}
