import { useEffect, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { PrimaryStatusBadge } from "@/components/StatusBadge";
import { fmtRange } from "@/lib/format";

type StatusEvent = {
  id: string;
  title: string;
  kind: string;
  status: string;
  approval_state: string;
  starts_at: string | null;
  ends_at: string | null;
  timezone?: string;
  expected_impact?: string | null;
  phase?: string;
};

export function StatusApplicationPage() {
  const { applicationKey, environmentKey } = useParams();
  const [params] = useSearchParams();
  const envKey = environmentKey || params.get("environment_key") || undefined;
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!applicationKey) return;
    let cancelled = false;
    (async () => {
      try {
        const body = await api.statusApplication(applicationKey, envKey);
        if (!cancelled) setData(body);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load status");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applicationKey, envKey]);

  if (error) {
    return (
      <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
        {error}
      </p>
    );
  }
  if (!data) return <p className="text-sm text-ink-500">Loading status…</p>;

  const app = data.application as { key: string; name: string };
  const env = data.environment as { key: string; name: string } | null;
  const active = (data.active as StatusEvent[]) || [];
  const upcoming = (data.upcoming_confirmed as StatusEvent[]) || [];
  const approved = (data.approved_window_not_confirmed as StatusEvent[]) || [];

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">Shareable status</p>
      <h1 className="font-display text-3xl font-semibold text-ink-950">
        {app.name}
        {env ? ` · ${env.key}` : ""}
      </h1>
      <p className="text-sm text-ink-600">{String(data.note || "")}</p>
      <p className="text-xs text-ink-500">
        Path: <code>{String(data.share_path)}</code> · as of {String(data.as_of)}
      </p>

      <StatusSection title="Active (confirmed executing)" items={active} empty="No active confirmed communications." />
      <StatusSection
        title="Upcoming confirmed"
        items={upcoming}
        empty="No upcoming confirmed communications."
      />
      <StatusSection
        title="Approved window (not confirmed)"
        items={approved}
        empty="No approved-only windows."
        muted
      />

      <p className="text-xs text-ink-500">{String(data.ics_note || "")}</p>
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← My Applications
      </Link>
    </div>
  );
}

export function StatusEventPage() {
  const { eventId } = useParams();
  const location = useLocation();
  const scheduled = location.pathname.includes("/status/scheduled/");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!eventId) return;
    let cancelled = false;
    (async () => {
      try {
        const body = scheduled
          ? await api.statusScheduled(eventId)
          : await api.statusEvent(eventId);
        if (!cancelled) setData(body);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load status");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [eventId, scheduled]);

  if (error) {
    return (
      <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
        {error}
      </p>
    );
  }
  if (!data) return <p className="text-sm text-ink-500">Loading status…</p>;

  const starts = data.starts_at as string | null;
  const ends = data.ends_at as string | null;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">Event status</p>
      <h1 className="font-display text-3xl font-semibold text-ink-950">{String(data.title)}</h1>
      <div className="flex flex-wrap gap-2">
        <PrimaryStatusBadge
          status={String(data.status)}
          approvalState={String(data.approval_state || "")}
          kind={String(data.kind)}
          showExplanation
        />
      </div>
      {starts && ends && (
        <p className="text-sm text-ink-700">
          Scheduled: {fmtRange(starts, ends)} · {String(data.timezone || "UTC")}
        </p>
      )}
      {data.expected_impact ? (
        <p className="text-sm text-ink-600">Expected impact: {String(data.expected_impact)}</p>
      ) : null}
      <p className="text-sm text-ink-600">{String(data.note || "")}</p>
      <p className="text-xs text-ink-500">
        Share path: <code>{String(data.share_path)}</code>
      </p>
      <div className="flex flex-wrap gap-3 text-sm">
        <Link to={`/events/${eventId}`} className="font-medium text-accent hover:underline">
          Full event detail
        </Link>
        <Link to="/" className="font-medium text-accent hover:underline">
          ← My Applications
        </Link>
      </div>
    </div>
  );
}

function StatusSection({
  title,
  items,
  empty,
  muted,
}: {
  title: string;
  items: StatusEvent[];
  empty: string;
  muted?: boolean;
}) {
  return (
    <section className={`mh-panel p-5 ${muted ? "opacity-80" : ""}`}>
      <h2 className="font-display text-xl font-semibold">{title}</h2>
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-ink-500">{empty}</p>
      ) : (
        <ul className="mt-3 divide-y divide-ink-100">
          {items.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div>
                <Link to={`/status/events/${e.id}`} className="font-medium hover:underline">
                  {e.title}
                </Link>
                {e.starts_at && e.ends_at && (
                  <div className="text-xs text-ink-500">
                    {fmtRange(e.starts_at, e.ends_at)}
                  </div>
                )}
              </div>
              <PrimaryStatusBadge status={e.status} kind={e.kind} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
