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
import { KindBadge, StatusBadge } from "@/components/StatusBadge";
import clsx from "clsx";

type View = "day" | "week" | "month" | "agenda";

export function CalendarPage() {
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(new Date());
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [appFilter, setAppFilter] = useState("");
  const [kindFilter, setKindFilter] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;

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
    else if (view === "week" || view === "agenda") setAnchor((a) => addDays(a, dir * (view === "agenda" ? 14 : 7)));
    else setAnchor((a) => addMonths(a, dir));
  }

  const agendaEvents = useMemo(
    () => [...events].sort((a, b) => a.starts_at.localeCompare(b.starts_at)),
    [events],
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mh-eyebrow">Calendar</p>
          <h1 className="font-display text-3xl font-semibold text-ink">Schedule</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Day, week, month, and agenda. Same rules as Overview: confirmed work is never inferred
            from a window alone. Browser TZ: <code className="text-ink">{tz}</code>.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(["day", "week", "month", "agenda"] as View[]).map((v) => (
            <button
              key={v}
              type="button"
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-semibold capitalize",
                view === v ? "bg-ink-900 text-white" : "bg-white text-ink-700 ring-1 ring-ink-200",
              )}
              aria-pressed={view === v}
              onClick={() => setView(v)}
            >
              {v}
            </button>
          ))}
          <button type="button" className="mh-btn-ghost" onClick={() => shift(-1)}>
            Prev
          </button>
          <button type="button" className="mh-btn-ghost" onClick={() => setAnchor(new Date())}>
            Today
          </button>
          <button type="button" className="mh-btn-ghost" onClick={() => shift(1)}>
            Next
          </button>
        </div>
      </div>

      <div className="mh-panel flex flex-wrap items-end gap-3 p-4">
        <div className="min-w-[12rem]">
          <label className="mh-label" htmlFor="cal-app">
            Application
          </label>
          <select
            id="cal-app"
            className="mh-input"
            value={appFilter}
            onChange={(e) => setAppFilter(e.target.value)}
          >
            <option value="">All</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-[10rem]">
          <label className="mh-label" htmlFor="cal-kind">
            Kind
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
        <label className="mb-2 flex items-center gap-2 text-sm font-medium text-ink-700">
          <input
            type="checkbox"
            checked={favoritesOnly}
            onChange={(e) => setFavoritesOnly(e.target.checked)}
          />
          Favorites only
        </label>
        <p className="mb-2 text-xs text-ink-500">
          ICS feeds refresh on client poll — not push realtime. Create tokens under Subscriptions.
        </p>
      </div>

      <p className="text-sm font-medium text-ink-700">
        {format(range.from, "MMM d, yyyy")}
        {view !== "day" ? ` – ${format(range.to, "MMM d, yyyy")}` : ""}
      </p>

      {loading && <p className="text-sm text-ink-500">Loading calendar…</p>}
      {error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}

      {!loading && view === "agenda" && (
        <ol className="mh-panel divide-y divide-ink-100">
          {agendaEvents.length === 0 && (
            <li className="p-6 text-sm text-ink-500">No events in this agenda window.</li>
          )}
          {agendaEvents.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  {format(parseISO(e.starts_at), "EEE MMM d · HH:mm")} ({e.timezone})
                </div>
                <Link
                  to={`/events/${e.id.split("@")[0]}`}
                  className="font-medium text-ink-950 hover:underline"
                >
                  {e.title}
                </Link>
                <div className="mt-1 text-xs">
                  <Link to={`/status/events/${e.id.split("@")[0]}`} className="text-accent underline">
                    Status page
                  </Link>
                </div>
              </div>
              <div className="flex gap-2">
                <KindBadge kind={e.kind} />
                <StatusBadge status={e.status} />
              </div>
            </li>
          ))}
        </ol>
      )}

      {!loading && view === "month" && (
        <div className="mh-panel overflow-hidden">
          <div className="grid grid-cols-7 border-b border-ink-100 bg-ink-50 text-center text-xs font-semibold uppercase tracking-wide text-ink-500">
            {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => (
              <div key={d} className="px-2 py-2">
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
              return (
                <div
                  key={day.toISOString()}
                  className={clsx(
                    "min-h-[7.5rem] border-b border-r border-ink-100 p-2",
                    !isSameMonth(day, anchor) && "bg-ink-50/50 text-ink-400",
                    isSameDay(day, new Date()) && "bg-accent-soft/40",
                  )}
                >
                  <div className="text-xs font-semibold">{format(day, "d")}</div>
                  <ul className="mt-1 space-y-1">
                    {dayEvents.slice(0, 3).map((e) => (
                      <li key={e.id}>
                        <Link
                          to={`/events/${e.id.split("@")[0]}`}
                          className={clsx(
                            "block truncate rounded px-1 py-0.5 text-[11px] font-medium",
                            e.kind === "manual_outage"
                              ? "bg-danger-soft text-danger"
                              : "bg-ink-100 text-ink-800",
                          )}
                        >
                          {e.title.replace("[DEMO] ", "")}
                        </Link>
                      </li>
                    ))}
                    {dayEvents.length > 3 && (
                      <li className="text-[11px] text-ink-500">+{dayEvents.length - 3} more</li>
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
            return (
              <section key={day.toISOString()} className="mh-panel p-4">
                <h2 className="font-display text-lg font-semibold">
                  {format(day, "EEEE, MMM d")}
                </h2>
                {dayEvents.length === 0 ? (
                  <p className="mt-2 text-sm text-ink-500">No events this day.</p>
                ) : (
                  <ul className="mt-3 space-y-3">
                    {dayEvents.map((e) => (
                      <li key={e.id} className="flex flex-wrap items-center justify-between gap-2">
                        <Link
                          to={`/events/${e.id.split("@")[0]}`}
                          className="font-medium hover:underline"
                        >
                          {e.title}
                        </Link>
                        <div className="flex gap-2">
                          <KindBadge kind={e.kind} />
                          <StatusBadge status={e.status} />
                        </div>
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
