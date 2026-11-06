import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type MaintenanceEvent, type TimelineEntry } from "@/api/client";
import { KindBadge, PrimaryStatusBadge, StatusBadge } from "@/components/StatusBadge";
import { fmtRange, fmtWhen } from "@/lib/format";
import { useAuth } from "@/features/auth/AuthContext";

type OccurrenceRow = {
  occurrence_id: string;
  original_starts_at: string;
  starts_at: string;
  ends_at: string;
  cancelled: boolean;
  is_exception: boolean;
  status: string;
  phase: string;
  has_record?: boolean;
  expected_impact?: string | null;
  description?: string | null;
};

export function EventDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const canWrite =
    user?.roles.some((r) =>
      ["publisher", "application_owner", "platform_administrator"].includes(r),
    ) ?? false;

  const [event, setEvent] = useState<MaintenanceEvent | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [occurrences, setOccurrences] = useState<OccurrenceRow[]>([]);
  const [selectedOrig, setSelectedOrig] = useState<string | null>(null);
  const [occHistory, setOccHistory] = useState<{
    timeline: TimelineEntry[];
    deliveries: Array<{ id: string; idempotency_key: string; status: string; subject?: string | null }>;
  } | null>(null);
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
        const from = new Date(Date.now() - 30 * 86400000).toISOString();
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

  async function loadOccHistory(originalStartsAt: string) {
    if (!id) return;
    setSelectedOrig(originalStartsAt);
    try {
      const h = await api.occurrenceHistory(id, originalStartsAt);
      setOccHistory({ timeline: h.timeline, deliveries: h.deliveries });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load occurrence history");
    }
  }

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      if (selectedOrig) await loadOccHistory(selectedOrig);
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

  function occActions(o: OccurrenceRow) {
    if (!canWrite || o.cancelled || o.status === "cancelled" || o.status === "completed") {
      return null;
    }
    return (
      <div className="flex flex-wrap gap-2">
        {o.status === "scheduled" && (
          <button
            type="button"
            className="mh-btn text-xs"
            disabled={busy}
            onClick={() =>
              void run(() =>
                api.occurrenceTransition(event!.id, {
                  original_starts_at: o.original_starts_at,
                  status: "in_progress",
                  note: "Started occurrence",
                }),
              )
            }
          >
            Start
          </button>
        )}
        {(o.status === "in_progress" || o.status === "extended") && (
          <>
            <button
              type="button"
              className="mh-btn text-xs"
              disabled={busy}
              onClick={() =>
                void run(() =>
                  api.occurrenceTransition(event!.id, {
                    original_starts_at: o.original_starts_at,
                    status: "verifying",
                  }),
                )
              }
            >
              Verifying
            </button>
            <button
              type="button"
              className="mh-btn-ghost text-xs"
              disabled={busy}
              onClick={() => {
                const iso = new Date(new Date(o.ends_at).getTime() + 60 * 60 * 1000).toISOString();
                void run(() =>
                  api.occurrenceExtend(event!.id, {
                    original_starts_at: o.original_starts_at,
                    new_ends_at: iso,
                    note: "Extended +1h",
                  }),
                );
              }}
            >
              Extend +1h
            </button>
          </>
        )}
        {o.status === "verifying" && (
          <button
            type="button"
            className="mh-btn text-xs"
            disabled={busy}
            onClick={() =>
              void run(() =>
                api.occurrenceTransition(event!.id, {
                  original_starts_at: o.original_starts_at,
                  status: "completed",
                }),
              )
            }
          >
            Complete
          </button>
        )}
        <button
          type="button"
          className="mh-btn-ghost text-xs"
          disabled={busy}
          onClick={() => {
            if (
              window.confirm(
                `Cancel this occurrence only (${new Date(o.original_starts_at).toLocaleString()})?`,
              )
            ) {
              void run(() => api.cancelOccurrence(event!.id, o.original_starts_at));
            }
          }}
        >
          Cancel
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
                api.seriesEdit(event!.id, {
                  scope: editScope,
                  original_starts_at: o.original_starts_at,
                  starts_at: newStart.toISOString(),
                  ends_at: newEnd.toISOString(),
                  exception_reconcile:
                    editScope === "all" ? "drop_incompatible_future" : undefined,
                }),
              );
            }
          }}
        >
          Reschedule +1h
        </button>
        <button
          type="button"
          className="mh-btn-ghost text-xs"
          disabled={busy}
          onClick={() => void loadOccHistory(o.original_starts_at)}
        >
          History
        </button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← Dashboard
      </Link>
      <div className="mh-panel animate-rise p-6">
        <div className="flex flex-wrap gap-2">
          <PrimaryStatusBadge
            status={event.status}
            approvalState={event.approval_state}
            kind={event.kind}
            showExplanation
          />
          {event.is_recurring && (
            <span className="rounded-md border border-ink-200 bg-accent-soft px-2 py-0.5 text-xs font-semibold text-ink">
              Recurring series
            </span>
          )}
        </div>
        <h1 className="mt-3 font-display text-3xl font-semibold text-ink">
          {event.title.replace("[DEMO] ", "")}
        </h1>
        <p className="mt-2 text-sm text-ink-muted">
          {fmtRange(event.starts_at, event.ends_at, event.timezone)}
        </p>
        {event.description && <p className="mt-4 text-ink">{event.description}</p>}
        {event.expected_impact && (
          <p className="mt-2 text-sm">
            <span className="font-semibold text-ink-muted">Impact:</span> {event.expected_impact}
          </p>
        )}
        <details className="mt-4 text-sm text-ink-muted">
          <summary className="cursor-pointer list-none underline [&::-webkit-details-marker]:hidden">
            Technical status
          </summary>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <KindBadge kind={event.kind} />
            <StatusBadge status={event.status} />
            <span className="text-xs">
              approval: {event.approval_state} · TZ {event.timezone}
              {event.is_recurring ? " · lifecycle is per occurrence" : ""}
            </span>
          </div>
        </details>
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

        {canWrite && !event.is_recurring && (
          <div className="mt-6 flex flex-wrap gap-2">
            {event.status === "scheduled" && (
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
                  if (window.confirm("Cancel this event?")) {
                    void run(() => api.cancel(event.id, "Cancelled from UI"));
                  }
                }}
              >
                Cancel
              </button>
            )}
          </div>
        )}

        {canWrite && event.is_recurring && event.status !== "completed" && event.status !== "cancelled" && (
          <div className="mt-6">
            <button
              type="button"
              className="mh-btn-ghost"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    "Cancel the entire series? Use occurrence Cancel for a single date.",
                  )
                ) {
                  void run(() => api.cancel(event.id, "Cancelled series from UI"));
                }
              }}
            >
              Cancel series
            </button>
          </div>
        )}
      </div>

      {event.is_recurring && (
        <section className="mh-panel p-6">
          <h2 className="font-display text-xl font-semibold">Occurrences</h2>
          <p className="mt-1 text-sm text-ink-600">
            Each occurrence has its own lifecycle (Scheduled → In progress → Extended →
            Verifying → Completed | Cancelled). Series actions use the scope control;
            Start / Extend / Verifying / Complete / Cancel below affect only that occurrence.
          </p>
          {canWrite && (
            <div className="mt-3">
              <label className="mh-label">Series edit scope (reschedule)</label>
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
          <ul className="mt-4 space-y-3">
            {occurrences.map((o) => (
              <li
                key={o.occurrence_id}
                className="rounded border border-ink-100 px-3 py-3 text-sm"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className={o.cancelled || o.status === "cancelled" ? "line-through text-ink-400" : ""}>
                      {new Date(o.starts_at).toLocaleString()} → {new Date(o.ends_at).toLocaleString()}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-2">
                      <StatusBadge status={o.status} />
                      <span className="text-xs text-ink-500">phase: {o.phase}</span>
                      {o.is_exception && o.status !== "cancelled" && (
                        <span className="text-xs font-semibold text-amber-800">Override</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="mt-2">{occActions(o)}</div>
              </li>
            ))}
            {occurrences.length === 0 && (
              <li className="text-sm text-ink-500">No occurrences in the visible window.</li>
            )}
          </ul>
        </section>
      )}

      {occHistory && selectedOrig && (
        <section className="mh-panel p-6">
          <h2 className="font-display text-xl font-semibold">Occurrence history</h2>
          <p className="mt-1 text-xs text-ink-500">{new Date(selectedOrig).toLocaleString()}</p>
          <h3 className="mt-4 text-sm font-semibold">Change timeline</h3>
          <ol className="mt-2 space-y-2">
            {occHistory.timeline.map((t) => (
              <li key={t.id} className="border-l-2 border-ink-200 pl-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  {t.entry_type.replaceAll("_", " ")} · {fmtWhen(t.at)}
                </p>
                <pre className="mt-1 overflow-x-auto text-xs text-ink-700">
                  {JSON.stringify(t.payload, null, 2)}
                </pre>
              </li>
            ))}
            {occHistory.timeline.length === 0 && (
              <li className="text-sm text-ink-500">No occurrence-scoped timeline yet.</li>
            )}
          </ol>
          <h3 className="mt-4 text-sm font-semibold">Notifications (immutable)</h3>
          <ul className="mt-2 space-y-1 text-xs">
            {occHistory.deliveries.map((d) => (
              <li key={d.id} className="font-mono text-ink-700">
                [{d.status}] {d.subject || d.idempotency_key}
              </li>
            ))}
            {occHistory.deliveries.length === 0 && (
              <li className="text-sm text-ink-500">No deliveries for this occurrence.</li>
            )}
          </ul>
        </section>
      )}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Series timeline</h2>
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
