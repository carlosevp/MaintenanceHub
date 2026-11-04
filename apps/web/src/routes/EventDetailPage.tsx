import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type MaintenanceEvent, type TimelineEntry } from "@/api/client";
import { ApprovalBadge, KindBadge, StatusBadge } from "@/components/StatusBadge";
import { fmtRange, fmtWhen } from "@/lib/format";
import { useAuth } from "@/features/auth/AuthContext";

export function EventDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const canWrite =
    user?.roles.some((r) =>
      ["publisher", "application_owner", "platform_administrator"].includes(r),
    ) ?? false;

  const [event, setEvent] = useState<MaintenanceEvent | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [occurrences, setOccurrences] = useState<
    Array<{
      occurrence_id: string;
      original_starts_at: string;
      starts_at: string;
      ends_at: string;
      cancelled: boolean;
      is_exception: boolean;
    }>
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editScope, setEditScope] = useState<"this" | "this_and_future" | "all">("this");

  async function load() {
    if (!id) return;
    setError(null);
    try {
      const [e, t] = await Promise.all([api.event(id), api.timeline(id)]);
      setEvent(e);
      setTimeline(t);
      if (e.is_recurring) {
        const from = new Date().toISOString();
        const to = new Date(Date.now() + 90 * 86400000).toISOString();
        const occ = await api.eventOccurrences(e.id, from, to);
        setOccurrences(occ);
      } else {
        setOccurrences([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }

  useEffect(() => {
    void load();
  }, [id]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (!event && !error) return <p className="text-sm text-ink-500">Loading event…</p>;
  if (!event) {
    return (
      <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
        {error}
      </p>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← Dashboard
      </Link>
      <div className="mh-panel animate-rise p-6">
        <div className="flex flex-wrap gap-2">
          <KindBadge kind={event.kind} />
          <StatusBadge status={event.status} />
          <ApprovalBadge state={event.approval_state} />
          {event.is_recurring && (
            <span className="rounded-md bg-teal-100 px-2 py-0.5 text-xs font-bold uppercase text-teal-900">
              Recurring
            </span>
          )}
        </div>
        <h1 className="mt-3 font-display text-3xl font-semibold text-ink-950">{event.title}</h1>
        <p className="mt-2 text-sm text-ink-600">{fmtRange(event.starts_at, event.ends_at)}</p>
        <p className="mt-1 text-xs text-ink-500">Timezone: {event.timezone}</p>
        {event.description && <p className="mt-4 text-ink-800">{event.description}</p>}
        {event.expected_impact && (
          <p className="mt-2 text-sm">
            <span className="font-semibold">Expected impact:</span> {event.expected_impact}
          </p>
        )}
        {event.recurrence && (
          <div className="mt-3 rounded-md border border-teal-200 bg-teal-50 px-3 py-2 text-sm text-teal-950">
            <p className="font-semibold">{event.recurrence.summary}</p>
            <p className="mt-1 font-mono text-xs">{event.recurrence.rrule}</p>
            {event.recurrence.exceptions.length > 0 && (
              <p className="mt-1 text-xs">
                {event.recurrence.exceptions.length} exception
                {event.recurrence.exceptions.length === 1 ? "" : "s"} (skip / reschedule)
              </p>
            )}
          </div>
        )}

        {error && (
          <p className="mt-4 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}

        {canWrite && (
          <div className="mt-6 flex flex-wrap gap-2">
            {event.status === "scheduled" && !event.is_recurring && (
              <button
                type="button"
                className="mh-btn"
                disabled={busy}
                onClick={() => void run(() => api.transition(event.id, { status: "in_progress" }))}
              >
                Start
              </button>
            )}
            {(event.status === "in_progress" || event.status === "extended") && (
              <>
                <button
                  type="button"
                  className="mh-btn"
                  disabled={busy}
                  onClick={() => void run(() => api.transition(event.id, { status: "verifying" }))}
                >
                  Begin verifying
                </button>
                <button
                  type="button"
                  className="mh-btn-ghost"
                  disabled={busy}
                  onClick={() => {
                    const iso = new Date(new Date(event.ends_at).getTime() + 60 * 60 * 1000).toISOString();
                    void run(() => api.extend(event.id, { new_ends_at: iso, note: "Extended +1h" }));
                  }}
                >
                  Extend +1h
                </button>
              </>
            )}
            {event.status === "verifying" && (
              <button
                type="button"
                className="mh-btn"
                disabled={busy}
                onClick={() => void run(() => api.transition(event.id, { status: "completed" }))}
              >
                Complete
              </button>
            )}
            {event.status !== "completed" && event.status !== "cancelled" && (
              <button
                type="button"
                className="mh-btn-ghost"
                disabled={busy}
                onClick={() => {
                  const msg = event.is_recurring
                    ? "Cancel the entire series? (Use occurrence list to skip a single date.)"
                    : "Cancel this event?";
                  if (window.confirm(msg)) {
                    void run(() => api.cancel(event.id, "Cancelled from UI"));
                  }
                }}
              >
                {event.is_recurring ? "Cancel series" : "Cancel"}
              </button>
            )}
          </div>
        )}
      </div>

      {event.is_recurring && (
        <section className="mh-panel p-6">
          <h2 className="font-display text-xl font-semibold">Upcoming occurrences</h2>
          <p className="mt-1 text-sm text-ink-600">
            Skip one date or choose edit scope when rescheduling. Series edits ask whether to change
            this occurrence, this and future, or the entire series.
          </p>
          {canWrite && (
            <div className="mt-3">
              <label className="mh-label">Default edit scope</label>
              <select
                className="mh-input max-w-xs"
                value={editScope}
                onChange={(e) => setEditScope(e.target.value as typeof editScope)}
              >
                <option value="this">This occurrence only</option>
                <option value="this_and_future">This and future</option>
                <option value="all">Entire series</option>
              </select>
            </div>
          )}
          <ul className="mt-4 space-y-2">
            {occurrences.map((o) => (
              <li
                key={o.occurrence_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-ink-100 px-3 py-2 text-sm"
              >
                <div>
                  <p className={o.cancelled ? "line-through text-ink-400" : ""}>
                    {new Date(o.starts_at).toLocaleString()} → {new Date(o.ends_at).toLocaleString()}
                  </p>
                  {o.cancelled && <span className="text-xs font-semibold text-danger">Skipped</span>}
                  {o.is_exception && !o.cancelled && (
                    <span className="text-xs font-semibold text-amber-800">Rescheduled</span>
                  )}
                </div>
                {canWrite && !o.cancelled && (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="mh-btn-ghost text-xs"
                      disabled={busy}
                      onClick={() => {
                        if (
                          window.confirm(
                            `Skip this occurrence only (${new Date(o.original_starts_at).toLocaleString()})?`,
                          )
                        ) {
                          void run(() => api.cancelOccurrence(event.id, o.original_starts_at));
                        }
                      }}
                    >
                      Skip
                    </button>
                    <button
                      type="button"
                      className="mh-btn-ghost text-xs"
                      disabled={busy}
                      onClick={() => {
                        const hours = 2;
                        const newStart = new Date(new Date(o.starts_at).getTime() + 60 * 60 * 1000);
                        const newEnd = new Date(newStart.getTime() + hours * 60 * 60 * 1000);
                        const label =
                          editScope === "this"
                            ? "this occurrence only"
                            : editScope === "this_and_future"
                              ? "this and future occurrences"
                              : "the entire series";
                        if (
                          window.confirm(
                            `Reschedule ${label} by +1h starting ${newStart.toLocaleString()}?`,
                          )
                        ) {
                          void run(() =>
                            api.seriesEdit(event.id, {
                              scope: editScope,
                              original_starts_at: o.original_starts_at,
                              starts_at: newStart.toISOString(),
                              ends_at: newEnd.toISOString(),
                            }),
                          );
                        }
                      }}
                    >
                      Reschedule +1h
                    </button>
                  </div>
                )}
              </li>
            ))}
            {occurrences.length === 0 && (
              <li className="text-sm text-ink-500">No occurrences in the next 90 days.</li>
            )}
          </ul>
        </section>
      )}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Timeline</h2>
        <ol className="mt-4 space-y-3">
          {timeline.map((t) => (
            <li key={t.id} className="border-l-2 border-ink-200 pl-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                {t.entry_type.replaceAll("_", " ")} · {fmtWhen(t.at)}
              </p>
              <pre className="mt-1 overflow-x-auto text-xs text-ink-700">
                {JSON.stringify(t.payload, null, 2)}
              </pre>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
