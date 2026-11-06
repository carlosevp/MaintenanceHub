import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Application,
  type DashboardSummary,
  type MaintenanceEvent,
} from "@/api/client";
import { PrimaryStatusBadge } from "@/components/StatusBadge";
import { fmtRange, untilBack } from "@/lib/format";
import { useAuth } from "@/features/auth/AuthContext";
import { ScenarioSelector } from "@/components/ScenarioSelector";
import { useExperience } from "@/features/experience/ExperienceContext";
import clsx from "clsx";

const UPCOMING_PREVIEW = 5;

function cleanTitle(title: string) {
  return title.replace("[DEMO] ", "");
}

function EventRow({
  event,
  compact,
}: {
  event: MaintenanceEvent;
  compact?: boolean;
}) {
  const active =
    event.status === "in_progress" ||
    event.status === "extended" ||
    event.status === "verifying";
  const isOutage = event.kind === "manual_outage" || event.status === "extended";

  return (
    <li
      className={clsx(
        "border-b border-ink-200 last:border-0",
        compact ? "py-3" : "py-4",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <Link
              to={`/events/${event.id}`}
              className="truncate font-semibold text-ink hover:underline"
              title={cleanTitle(event.title)}
            >
              {cleanTitle(event.title)}
            </Link>
            <PrimaryStatusBadge
              status={event.status}
              approvalState={event.approval_state}
              kind={event.kind}
            />
          </div>
          <p className="mt-1 truncate text-sm text-ink-muted">
            {fmtRange(event.starts_at, event.ends_at, event.timezone)}
          </p>
          {!compact && event.expected_impact && (
            <p className="mt-1 line-clamp-2 text-sm text-ink">
              <span className="font-medium text-ink-muted">Impact: </span>
              {event.expected_impact}
            </p>
          )}
          {active && (
            <p
              className={clsx(
                "mt-1 text-sm font-medium",
                isOutage ? "text-danger" : "text-warn",
              )}
            >
              {untilBack(event.ends_at)}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const { activeScenario } = useExperience();
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [apps, setApps] = useState<Application[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [showAllUpcoming, setShowAllUpcoming] = useState(false);
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

  const upcomingAll = summary?.upcoming.items ?? [];
  const upcomingVisible = showAllUpcoming
    ? upcomingAll
    : upcomingAll.slice(0, UPCOMING_PREVIEW);
  const upcomingHidden = Math.max(0, upcomingAll.length - UPCOMING_PREVIEW);

  return (
    <div className="space-y-5 md:space-y-6">
      <header className="animate-rise max-w-2xl">
        <p className="mh-eyebrow">Overview</p>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          What’s happening
        </h1>
        <p className="mt-2 text-sm text-ink-muted sm:text-base">
          Active confirmed work, then what’s next. Status is never guessed from a calendar window
          alone.
        </p>
        {activeScenario && (
          <p className="mt-3 rounded-md bg-accent-soft px-3 py-2 text-sm text-ink" role="status">
            Story: <strong>{activeScenario.label}</strong> — {activeScenario.summary}
          </p>
        )}
      </header>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="min-w-0 flex-1 sm:min-w-[16rem]">
          <label className="mh-label" htmlFor="search">
            Search
          </label>
          <input
            id="search"
            className="mh-input"
            placeholder="Title or what’s affected…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {favorites.length > 0 && (
          <label className="flex items-center gap-2 pb-2 text-sm font-medium text-ink">
            <input
              type="checkbox"
              checked={favoritesOnly}
              onChange={(e) => setFavoritesOnly(e.target.checked)}
            />
            My apps only
          </label>
        )}
        <div className="flex gap-2 pb-0.5">
          <Link to="/calendar" className="mh-btn-ghost">
            Calendar
          </Link>
          <Link to="/alerts" className="mh-btn-ghost">
            My Alerts
          </Link>
        </div>
      </div>

      <details className="group text-sm">
        <summary className="cursor-pointer list-none text-ink-muted hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden">
          Manage starred apps
          <span className="ml-2 text-ink-faint">({favorites.length})</span>
        </summary>
        <div className="mt-3 flex flex-wrap gap-2">
          {apps.map((a) => {
            const fav = favorites.includes(a.id);
            return (
              <button
                key={a.id}
                type="button"
                className={
                  fav
                    ? "rounded-md border border-accent bg-accent-soft px-2.5 py-1 text-xs font-semibold text-ink"
                    : "rounded-md border border-ink-200 px-2.5 py-1 text-xs font-medium text-ink-muted hover:bg-accent-soft"
                }
                aria-pressed={fav}
                aria-label={`${fav ? "Unstar" : "Star"} ${cleanTitle(a.name)}`}
                onClick={() => void toggleFavorite(a.id)}
              >
                {fav ? "★" : "☆"} {cleanTitle(a.name)}
              </button>
            );
          })}
        </div>
      </details>

      {loading && <p className="text-sm text-ink-muted">Loading overview…</p>}
      {error && (
        <p
          className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      )}

      {summary && !loading && (
        <div className="space-y-5">
          {/* Compact current strip — not an equal-height twin column */}
          <section
            aria-labelledby="sec-now"
            className={clsx(
              nowItems.length === 0
                ? "rounded-lg border border-dashed border-ink-200 px-4 py-3"
                : "mh-panel px-4 py-3 sm:px-5",
              nowItems.some((e) => e.kind === "manual_outage") && "ring-1 ring-danger/25",
            )}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="sec-now" className="font-display text-lg font-semibold text-ink">
                Happening now
              </h2>
              {nowItems.length > 0 && (
                <span className="text-xs font-medium text-ink-muted">{nowItems.length} active</span>
              )}
            </div>
            {nowItems.length === 0 ? (
              <p className="mt-1 text-sm text-ink-muted">Nothing active right now.</p>
            ) : (
              <ul className="mt-1">
                {nowItems.map((e) => (
                  <EventRow
                    key={`now-${e.id}-${e.occurrence_starts_at || ""}`}
                    event={e}
                    compact
                  />
                ))}
              </ul>
            )}
          </section>

          {/* Full-width upcoming list */}
          <section aria-labelledby="sec-upcoming" className="mh-panel px-4 py-4 sm:px-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <h2 id="sec-upcoming" className="font-display text-xl font-semibold text-ink">
                  Coming up
                </h2>
                <p className="text-sm text-ink-muted">Confirmed or planned windows still scheduled</p>
              </div>
              <Link to="/calendar" className="text-sm font-medium text-accent hover:underline">
                View calendar
              </Link>
            </div>
            {upcomingAll.length === 0 ? (
              <p className="mt-4 text-sm text-ink-muted">No upcoming windows for this filter.</p>
            ) : (
              <>
                <ul className="mt-2">
                  {upcomingVisible.map((e) => (
                    <EventRow
                      key={`up-${e.id}-${e.occurrence_starts_at || ""}`}
                      event={e}
                    />
                  ))}
                </ul>
                {!showAllUpcoming && upcomingHidden > 0 && (
                  <button
                    type="button"
                    className="mt-3 text-sm font-medium text-accent hover:underline"
                    onClick={() => setShowAllUpcoming(true)}
                  >
                    View all {upcomingAll.length} upcoming
                  </button>
                )}
                {showAllUpcoming && upcomingHidden > 0 && (
                  <button
                    type="button"
                    className="mt-3 text-sm font-medium text-ink-muted hover:underline"
                    onClick={() => setShowAllUpcoming(false)}
                  >
                    Show fewer
                  </button>
                )}
              </>
            )}
          </section>

          {(summary.extended?.count || summary.cancelled?.count || summary.recent.count > 0) && (
            <div>
              <button
                type="button"
                className="text-sm font-medium text-ink-muted underline hover:text-ink"
                onClick={() => setShowMore((v) => !v)}
                aria-expanded={showMore}
              >
                {showMore ? "Hide recent history" : "Extensions, cancellations & recent"}
              </button>
              {showMore && (
                <div className="mt-3 space-y-3">
                  {(summary.extended?.items ?? []).map((e) => (
                    <div key={`ex-${e.id}`} className="rounded-md border border-ink-200 px-3 py-2">
                      <EventRow event={e} compact />
                    </div>
                  ))}
                  {(summary.cancelled?.items ?? []).slice(0, 4).map((e) => (
                    <div key={`ca-${e.id}`} className="rounded-md border border-ink-200 px-3 py-2">
                      <EventRow event={e} compact />
                    </div>
                  ))}
                  {summary.recent.items.slice(0, 4).map((e) => (
                    <div key={`re-${e.id}`} className="rounded-md border border-ink-200 px-3 py-2">
                      <EventRow event={e} compact />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {user?.roles.includes("publisher") && (
        <p className="text-sm text-ink-muted">
          Publishing?{" "}
          <Link to="/events/new?quick=1" className="font-medium text-accent underline">
            Schedule maintenance
          </Link>
        </p>
      )}

      <ScenarioSelector />
    </div>
  );
}
