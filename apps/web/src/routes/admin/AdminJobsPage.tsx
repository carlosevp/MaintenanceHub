import { useEffect, useState } from "react";
import { api, ApiError } from "@/api/client";

type Job = {
  id: string;
  job_type: string;
  status: string;
  attempt_count: number;
  last_error?: string | null;
  idempotency_key?: string | null;
  run_at?: string | null;
  created_at?: string | null;
};

type Delivery = {
  id: string;
  idempotency_key: string;
  channel: string;
  destination: string;
  subject?: string | null;
  status: string;
  event_id?: string | null;
  attempt_count: number;
  last_error?: string | null;
  created_at?: string | null;
};

export function AdminJobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [jobStatus, setJobStatus] = useState("");
  const [delStatus, setDelStatus] = useState("");
  const [dest, setDest] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function reload() {
    const jp = new URLSearchParams();
    if (jobStatus) jp.set("status", jobStatus);
    const dp = new URLSearchParams();
    if (delStatus) dp.set("status", delStatus);
    if (dest) dp.set("destination", dest);
    const [j, d] = await Promise.all([api.adminJobs(jp), api.adminDeliveries(dp)]);
    setJobs(j);
    setDeliveries(d);
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof ApiError ? e.detail : "Load failed"));
  }, []);

  async function retry(id: string) {
    if (!window.confirm("Retry this failed/dead job? Already-sent deliveries are refused.")) return;
    try {
      await api.adminRetryJob(id);
      setMsg(`Job ${id} requeued.`);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Retry failed");
    }
  }

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}
      {msg && <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">{msg}</div>}

      <section className="mh-panel p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-semibold">Jobs</h2>
            <p className="text-sm text-ink-600">
              Safe retry for failed/dead only. Notify jobs refuse retry when delivery already sent
              (idempotency).
            </p>
          </div>
          <div className="flex gap-2">
            <select className="mh-input w-40" value={jobStatus} onChange={(e) => setJobStatus(e.target.value)}>
              <option value="">All statuses</option>
              <option value="queued">queued</option>
              <option value="leased">leased</option>
              <option value="succeeded">succeeded</option>
              <option value="failed">failed</option>
              <option value="dead">dead</option>
            </select>
            <button type="button" className="mh-btn-ghost" onClick={() => void reload()}>
              Refresh
            </button>
          </div>
        </div>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {jobs.length === 0 && <li className="py-4 text-ink-500">No jobs.</li>}
          {jobs.map((j) => (
            <li key={j.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div>
                <div className="font-medium">
                  {j.job_type} · <span className="text-ink-500">{j.status}</span>
                </div>
                <div className="text-xs text-ink-500">
                  attempts {j.attempt_count}
                  {j.idempotency_key ? ` · ${j.idempotency_key}` : ""}
                  {j.run_at ? ` · run ${j.run_at}` : ""}
                </div>
                {j.last_error && <div className="mt-1 text-xs text-red-700">{j.last_error}</div>}
              </div>
              {(j.status === "failed" || j.status === "dead") && (
                <button type="button" className="mh-btn-ghost text-xs" onClick={() => void retry(j.id)}>
                  Retry
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="mh-panel p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-semibold">Notification deliveries</h2>
            <p className="text-sm text-ink-600">Filter by status and destination. History is append-oriented.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <select className="mh-input w-36" value={delStatus} onChange={(e) => setDelStatus(e.target.value)}>
              <option value="">All</option>
              <option value="pending">pending</option>
              <option value="sent">sent</option>
              <option value="failed">failed</option>
              <option value="dead">dead</option>
            </select>
            <input
              className="mh-input w-48"
              placeholder="Destination contains…"
              value={dest}
              onChange={(e) => setDest(e.target.value)}
            />
            <button type="button" className="mh-btn-ghost" onClick={() => void reload()}>
              Filter
            </button>
          </div>
        </div>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {deliveries.length === 0 && <li className="py-4 text-ink-500">No deliveries.</li>}
          {deliveries.map((d) => (
            <li key={d.id} className="py-3">
              <div className="font-medium">
                {d.destination} · {d.status} · {d.channel}
              </div>
              <div className="text-xs text-ink-500">
                {d.subject || "(no subject)"} · attempts {d.attempt_count}
                {d.event_id ? ` · event ${d.event_id}` : ""}
              </div>
              {d.last_error && <div className="mt-1 text-xs text-red-700">{d.last_error}</div>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
