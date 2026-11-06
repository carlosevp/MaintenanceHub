import { useEffect, useMemo, useState } from "react";
import {
  addDays,
  addMonths,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  parseISO,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { Link } from "react-router-dom";
import { api, type Application, type CalendarEvent } from "@/api/client";
import { PrimaryStatusBadge } from "@/components/StatusBadge";
import { fmtRange } from "@/lib/format";
import clsx from "clsx";

type View = "day" | "week" | "month" | "agenda";

function cleanTitle(title: string) {
  return title.replace("[DEMO] ", "");
}

function eventId(e: CalendarEvent) {
  return e.id.split("@")[0];
}

export function CalendarPage() {
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(new Date());
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [appFilter, setAppFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showIcsHelp, setShowIcsHelp] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const today = new Date();

  const range = useMemo(() => {
    if (view === "day") {
      const start = new Date(anchor);
      start.setHours(0, 0, 0, 0);
      return { from: start, to: addDays(start, 1) };
    }
    if (view === "week") {
      const from = startOfWeek(anchor, { weekStartsOn: 1 });
      return { from, to: endOfWeek(anchor, { weekStartsOn: 1 }) };
    }
    if (view === "agenda") {
      const from = new Date(anchor);
      from.setHours(0, 0, 0, 0);
      return { from, to: addDays(from, 14) };
    }
    const from = startOfWeek(startOfMonth(anchor), { weekStartsOn: 1 });
    const to = endOfWeek(endOfMonth(anchor), { weekStartsOn: 1 });
    return { from, to };
  }, [view, anchor]);

  useEffect(() => {
    void api.applications().then(setApps).catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          view: view === "agenda" ? "agenda" : view,
          from: range.from.toISOString(),
          to: range.to.toISOString(),
        });
        if (appFilter) params.set("application_id", appFilter);
        if (kindFilter) params.set("kind", kindFilter);
        if (favoritesOnly) params.set("favorites_only", "true");
        const data = await api.calendar(params);
        if (!cancelled) setEvents(data);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [view, range, appFilter, kindFilter, favoritesOnly]);

  const days: Date[] = [];
  for (let d = range.from; d <= range.to; d = addDays(d, 1)) {
    days.push(d);
    if (view === "day") break;
  }

  function shift(dir: -1 | 1) {
    if (view === "day") setAnchor((a) => addDays(a, dir));
    else if (view === "week" || view === "agenda")
      setAnchor((a) => addDays(a, dir * (view === "agenda" ? 14 : 7)));
    else setAnchor((a) => addMonths(a, dir));
  }

  const agendaEvents = useMemo(
    () => [...events].sort((a, b) => a.starts_at.localeCompare(b.starts_at)),
    [events],
  );

  const selected = events.find((e) => e.id === selectedId) || null;

  return (
    <div className="space-y-5 md:space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-xl">
          <p className="mh-eyebrow">Calendar</p>
          <h1 className="font-display text-3xl font-semibold text-ink">Schedule</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Confirmed work is never inferred from a window alone. Times shown in{" "}
            <span className="font-medium text-ink">{tz}</span>.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Calendar view">
          {(["day", "week", "month", "agenda"] as View[]).map((v) => (
            <button
              key={v}
              type="button"
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-semibold capitalize focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
                view === v ? "bg-ink text-accent-fg" : "bg-surface-raised text-ink-muted ring-1 ring-ink-200",
              )}
              aria-pressed={view === v}
              onClick={() => setView(v)}
            >
              {v}
            </button>
          ))}
          <button type="button" className="mh-btn-ghost" onClick={() => shift(-1)} aria-label="Previous">
            Prev
          </button>
          <button
            type="button"
            className="mh-btn"
            onClick={() => setAnchor(new Date())}
          >
            Today
          </button>
          <button type="button" className="mh-btn-ghost" onClick={() => shift(1)} aria-label="Next">
            Next
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div className="min-w-[10rem] flex-1 sm:max-w-xs">
          <label className="mh-label" htmlFor="cal-app">
            Application
          </label>
          <select
            id="cal-app"
            className="mh-input"
            value={appFilter}
            onChange={(e) => setAppFilter(e.target.value)}
          >
            <option value="">All apps</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {cleanTitle(a.name)}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[8rem]">
          <label className="mh-label" htmlFor="cal-kind">
            Type
          </label>
          <select
            id="cal-kind"
            className="mh-input"
            value={kindFilter}
            onChange={(e) => setKindFilter(e.target.value)}
          >
            <option value="">All</option>
            <option value="planned_maintenance">Planned</option>
            <option value="manual_outage">Outage</option>
          </select>
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm font-medium text-ink">
          <input
            type="checkbox"
            checked={favoritesOnly}
            onChange={(e) => setFavoritesOnly(e.target.checked)}
          />
          My apps only
        </label>
        <button
          type="button"
          className="pb-2 text-sm font-medium text-accent underline"
          onClick={() => setShowIcsHelp((v) => !v)}
          aria-expanded={showIcsHelp}
        >
          Subscribe via ICS
        </button>
      </div>

      {showIcsHelp && (
        <p className="rounded-md border border-ink-200 bg-accent-soft px-3 py-2 text-sm text-ink-muted">
          Calendar feeds refresh when your client polls — not push realtime. Create a token under{" "}
          <Link to="/alerts" className="font-medium text-accent underline">
            My Alerts
          </Link>
          .
        </p>
      )}

      <p className="text-sm font-medium text-ink">
        {format(range.from, "MMM d, yyyy")}
        {view !== "day" ? ` – ${format(range.to, "MMM d, yyyy")}` : ""}
      </p>

      {loading && <p className="text-sm text-ink-muted">Loading calendar…</p>}
      {error && (
        <p
          className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="min-w-0">
          {!loading && view === "agenda" && (
            <ol className="mh-panel divide-y divide-ink-200">
              {agendaEvents.length === 0 && (
                <li className="p-5 text-sm text-ink-muted">No events in this agenda window.</li>
              )}
              {agendaEvents.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    className="flex w-full flex-wrap items-start justify-between gap-3 px-4 py-3 text-left hover:bg-accent-soft/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
                    onClick={() => setSelectedId(e.id)}
                  >
                    <div className="min-w-0">
                      <div className="text-xs text-ink-muted">
                        {fmtRange(e.starts_at, e.ends_at, e.timezone)}
                      </div>
                      <div className="truncate font-medium text-ink">{cleanTitle(e.title)}</div>
                    </div>
                    <PrimaryStatusBadge status={e.status} kind={e.kind} />
                  </button>
                </li>
              ))}
            </ol>
          )}

          {!loading && view === "month" && (
            <div className="mh-panel overflow-hidden">
              <div className="grid grid-cols-7 border-b border-ink-200 bg-surface text-center text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
                  <div key={d} className="px-1 py-2 sm:px-2">
                    {d}
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-7">
                {days.map((day) => {
                  const dayEvents = events.filter((e) => {
                    const s = parseISO(e.starts_at);
                    const en = parseISO(e.ends_at);
                    return s <= endOfDay(day) && en >= startOfDay(day);
                  });
                  const isToday = isSameDay(day, today);
                  return (
                    <div
                      key={day.toISOString()}
                      className={clsx(
                        "min-h-[4.5rem] border-b border-r border-ink-200 p-1.5 sm:min-h-[6.5rem] sm:p-2",
                        !isSameMonth(day, anchor) && "bg-canvas/60 text-ink-faint",
                        isToday && "bg-accent-soft/50",
                      )}
                    >
                      <div
                        className={clsx(
                          "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold",
                          isToday && "bg-ink text-accent-fg",
                        )}
                      >
                        {format(day, "d")}
                      </div>
                      <ul className="mt-1 space-y-0.5">
                        {dayEvents.slice(0, 2).map((e) => (
                          <li key={e.id}>
                            <button
                              type="button"
                              onClick={() => setSelectedId(e.id)}
                              className={clsx(
                                "block w-full truncate rounded px-1 py-0.5 text-left text-[10px] font-medium sm:text-[11px]",
                                e.kind === "manual_outage"
                                  ? "bg-danger-soft text-danger"
                                  : e.approval_state === "approved_window"
                                    ? "bg-surface-raised text-ink-muted ring-1 ring-ink-200"
                                    : "bg-accent-soft text-ink",
                              )}
                            >
                              {cleanTitle(e.title)}
                            </button>
                          </li>
                        ))}
                        {dayEvents.length > 2 && (
                          <li className="px-1 text-[10px] text-ink-muted">+{dayEvents.length - 2}</li>
                        )}
                      </ul>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {!loading && (view === "day" || view === "week") && (
            <div className="space-y-3">
              {days.map((day) => {
                const dayEvents = events.filter((e) => {
                  const s = parseISO(e.starts_at);
                  const en = parseISO(e.ends_at);
                  return s <= endOfDay(day) && en >= startOfDay(day);
                });
                const isToday = isSameDay(day, today);
                return (
                  <section
                    key={day.toISOString()}
                    className={clsx("mh-panel p-4", isToday && "ring-1 ring-accent/40")}
                  >
                    <h2 className="font-display text-lg font-semibold text-ink">
                      {format(day, "EEEE, MMM d")}
                      {isToday && (
                        <span className="ml-2 text-xs font-sans font-semibold uppercase tracking-wide text-accent">
                          Today
                        </span>
                      )}
                    </h2>
                    {dayEvents.length === 0 ? (
                      <p className="mt-2 text-sm text-ink-muted">No events this day.</p>
                    ) : (
                      <ul className="mt-3 divide-y divide-ink-200">
                        {dayEvents.map((e) => (
                          <li key={e.id}>
                            <button
                              type="button"
                              className="flex w-full flex-wrap items-center justify-between gap-2 py-3 text-left hover:bg-accent-soft/40"
                              onClick={() => setSelectedId(e.id)}
                            >
                              <span className="min-w-0 truncate font-medium text-ink">
                                {cleanTitle(e.title)}
                              </span>
                              <PrimaryStatusBadge status={e.status} kind={e.kind} />
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                );
              })}
            </div>
          )}
        </div>

        {/* Details panel */}
        <aside
          className="mh-panel h-fit p-4 lg:sticky lg:top-4"
          aria-label="Event details"
        >
          {selected ? (
            <div className="space-y-3">
              <PrimaryStatusBadge
                status={selected.status}
                kind={selected.kind}
                showExplanation
              />
              <h2 className="font-display text-xl font-semibold leading-snug text-ink">
                {cleanTitle(selected.title)}
              </h2>
              <p className="text-sm text-ink-muted">
                {fmtRange(selected.starts_at, selected.ends_at, selected.timezone)}
              </p>
              <div className="flex flex-col gap-2 pt-1">
                <Link to={`/events/${eventId(selected)}`} className="mh-btn text-center">
                  Open details
                </Link>
                <Link
                  to={`/status/events/${eventId(selected)}`}
                  className="mh-btn-ghost text-center text-sm"
                >
                  Shareable status
                </Link>
                <button
                  type="button"
                  className="text-sm text-ink-muted underline"
                  onClick={() => setSelectedId(null)}
                >
                  Clear selection
                </button>
              </div>
            </div>
          ) : (
            <p className="text-sm text-ink-muted">
              Select an event to see status, timing, and links. Approved windows are planned — not
              outages.
            </p>
          )}
        </aside>
      </div>
    </div>
  );
}

function startOfDay(d: Date) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function endOfDay(d: Date) {
  const x = new Date(d);
  x.setHours(23, 59, 59, 999);
  return x;
}
