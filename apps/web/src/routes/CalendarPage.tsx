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
import { api, type CalendarEvent } from "@/api/client";
import { KindBadge, StatusBadge } from "@/components/StatusBadge";
import clsx from "clsx";

type View = "day" | "week" | "month";

export function CalendarPage() {
  const [view, setView] = useState<View>("month");
  const [anchor, setAnchor] = useState(new Date());
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    const from = startOfWeek(startOfMonth(anchor), { weekStartsOn: 1 });
    const to = endOfWeek(endOfMonth(anchor), { weekStartsOn: 1 });
    return { from, to };
  }, [view, anchor]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          view,
          from: range.from.toISOString(),
          to: range.to.toISOString(),
        });
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
  }, [view, range]);

  const days: Date[] = [];
  for (let d = range.from; d <= range.to; d = addDays(d, 1)) {
    days.push(d);
    if (view === "day") break;
  }

  function shift(dir: -1 | 1) {
    if (view === "day") setAnchor((a) => addDays(a, dir));
    else if (view === "week") setAnchor((a) => addDays(a, dir * 7));
    else setAnchor((a) => addMonths(a, dir));
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold text-ink-950">Maintenance calendar</h1>
          <p className="mt-1 text-sm text-ink-600">
            Day, week, and month views with recurring occurrence expansion (IANA TZ / DST-aware).
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(["day", "week", "month"] as View[]).map((v) => (
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

      {!loading && view !== "month" && (
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
