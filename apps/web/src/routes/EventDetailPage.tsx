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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!id) return;
    setError(null);
    try {
      const [e, t] = await Promise.all([api.event(id), api.timeline(id)]);
      setEvent(e);
      setTimeline(t);
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
        </div>
        <h1 className="mt-3 font-display text-3xl font-semibold text-ink-950">{event.title}</h1>
        <p className="mt-2 text-sm text-ink-600">{fmtRange(event.starts_at, event.ends_at)}</p>
        {event.description && <p className="mt-4 text-ink-800">{event.description}</p>}
        {event.expected_impact && (
          <p className="mt-2 text-sm">
            <span className="font-semibold">Expected impact:</span> {event.expected_impact}
          </p>
        )}
        {event.is_recurring && (
          <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Recurrence flagged — RRULE expansion is incomplete (M3b). See docs/LIMITATIONS.md.
          </p>
        )}

        {error && (
          <p className="mt-4 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}

        {canWrite && (
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
                onClick={() => void run(() => api.cancel(event.id, "Cancelled from UI"))}
              >
                Cancel
              </button>
            )}
          </div>
        )}
      </div>

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
