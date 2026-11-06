import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";

/**
 * Demo embed page for the MaintenanceHub banner package.
 * Uses the same public DTO as @maintenancehub/banner (no internal notes).
 */

type Msg = {
  id: string;
  kind: string;
  title: string;
  status: string;
  starts_at: string;
  ends_at: string;
  expected_impact?: string | null;
  approval_state: string;
};

export function BannerDemoPage() {
  const [appKey, setAppKey] = useState("payments-gateway");
  const [envKey, setEnvKey] = useState("PROD");
  const [token, setToken] = useState(localStorage.getItem("mh_token") || "");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState<string>("");

  async function load(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    try {
      const params = new URLSearchParams({ application_key: appKey });
      if (envKey) params.set("environment_key", envKey);
      const headers: HeadersInit = {};
      if (token.trim()) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/v1/public/banner?${params}`, { headers });
      if (!res.ok) throw new Error(await res.text());
      const data = (await res.json()) as Msg[];
      setMessages(data);
      setRaw(JSON.stringify(data, null, 2));
      if (JSON.stringify(data).includes("description") || JSON.stringify(data).includes("timeline")) {
        setError("Unexpected internal fields in public DTO");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← Dashboard
      </Link>
      <div className="mh-panel p-6">
        <h1 className="font-display text-3xl font-semibold">Banner embed demo</h1>
        <p className="mt-2 text-sm text-ink-600">
          Preview of <code>@maintenancehub/banner</code> against{" "}
          <code>/api/v1/public/banner</code>. Auth is optional for the public DTO — do{" "}
          <strong>not</strong> paste long-lived service <code>client_secret</code> values into
          browsers. Optional Bearer is for demos only. This is communication only — not monitoring.
        </p>
        <form className="mt-4 space-y-3" onSubmit={(e) => void load(e)}>
          <div>
            <label className="mh-label">Application key</label>
            <input className="mh-input" value={appKey} onChange={(e) => setAppKey(e.target.value)} />
          </div>
          <div>
            <label className="mh-label">Environment key (optional)</label>
            <input className="mh-input" value={envKey} onChange={(e) => setEnvKey(e.target.value)} />
          </div>
          <div>
            <label className="mh-label">Bearer token (optional)</label>
            <input className="mh-input" value={token} onChange={(e) => setToken(e.target.value)} />
          </div>
          <button className="mh-btn" type="submit">
            Fetch banner messages
          </button>
        </form>
        {error && (
          <p className="mt-3 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}
      </div>

      <aside
        className="rounded-lg border border-teal-700/30 bg-teal-50 p-4"
        role="region"
        aria-label="Maintenance and outage communications"
      >
        <p className="text-xs font-bold uppercase tracking-wide text-teal-800">
          MaintenanceHub notices
        </p>
        {messages.length === 0 ? (
          <p className="mt-2 text-sm text-ink-500">No active/upcoming confirmed messages.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {messages.map((m) => (
              <li key={m.id} className="rounded border border-teal-200 bg-white px-3 py-2 text-sm">
                <span className="mr-2 text-xs font-bold uppercase text-teal-800">
                  {m.kind === "manual_outage" ? "Outage" : "Maintenance"}
                </span>
                <span className="mr-2 text-xs font-bold uppercase text-ink-500">
                  {m.status.replaceAll("_", " ")}
                </span>
                <strong className="block">{m.title}</strong>
                <span className="text-xs text-ink-600">
                  {m.starts_at} → {m.ends_at}
                </span>
                {m.expected_impact && (
                  <span className="block text-xs text-ink-600">Impact: {m.expected_impact}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </aside>

      {raw && (
        <pre className="mh-panel overflow-x-auto p-4 text-xs text-ink-700">{raw}</pre>
      )}
    </div>
  );
}
