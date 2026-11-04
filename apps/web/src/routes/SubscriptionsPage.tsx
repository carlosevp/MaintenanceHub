import { FormEvent, useEffect, useState } from "react";
import { api } from "@/api/client";

type Sub = {
  id: string;
  destination_type: string;
  destination: string;
  bridge_channel_key?: string | null;
  is_active: boolean;
  reminders: Array<{ id: string; offset_minutes: number }>;
  targets: Array<{ id: string; target_type: string; target_id: string }>;
};

type App = { id: string; name: string; key: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem("mh_token");
  const headers = new Headers(init?.headers || {});
  if (init?.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) throw new Error(await res.text());
  if (res.status === 204) return undefined as T;
  return res.json();
}

export function SubscriptionsPage() {
  const [subs, setSubs] = useState<Sub[]>([]);
  const [apps, setApps] = useState<App[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [appId, setAppId] = useState("");
  const [destType, setDestType] = useState("email_address");
  const [destination, setDestination] = useState("");
  const [channelKey, setChannelKey] = useState("ops-demo");
  const [testResult, setTestResult] = useState<string | null>(null);
  const [icsUrl, setIcsUrl] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [s, a] = await Promise.all([
        request<Sub[]>("/api/v1/subscriptions"),
        api.applications(),
      ]);
      setSubs(s);
      setApps(a);
      if (!appId && a[0]) setAppId(a[0].id);
      if (!destination) {
        const me = await api.me();
        setDestination(me.email);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await request("/api/v1/subscriptions", {
        method: "POST",
        body: JSON.stringify({
          destination_type: destType,
          destination,
          bridge_channel_key: destType === "teams_bridge_channel" ? channelKey : null,
          targets: [{ target_type: "application", target_id: appId }],
          reminders: [{ offset_minutes: -1440 }, { offset_minutes: -60 }],
        }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function testNotify() {
    setTestResult(null);
    try {
      const body = await request<{
        status: string;
        channel: string;
        subject: string;
        note: string;
        provider_message_id?: string;
      }>("/api/v1/notifications/test", {
        method: "POST",
        body: JSON.stringify({
          template_key: "event.created",
          destination_type: destType,
          destination,
          bridge_channel_key: channelKey,
        }),
      });
      setTestResult(
        `${body.note} → ${body.status} via ${body.channel}; subject=${body.subject}; id=${body.provider_message_id}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
    }
  }

  async function createIcs() {
    try {
      const body = await request<{ token: string; feed_url: string }>("/api/v1/calendar-tokens", {
        method: "POST",
        body: JSON.stringify({ scopes: ["favorites", "subscriptions"], label: "Outlook" }),
      });
      setIcsUrl(body.feed_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ICS token failed");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-semibold text-ink-950">Subscriptions & calendar</h1>
        <p className="mt-1 text-sm text-ink-600">
          Email SMTP (or log sink) and <strong>Teams via email bridge</strong> — no Teams APIs or
          webhooks. Digests are optional (digest_mode on subscription).
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="mh-panel p-5">
          <h2 className="font-display text-xl font-semibold">Your subscriptions</h2>
          {subs.length === 0 ? (
            <p className="mt-3 text-sm text-ink-500">None yet.</p>
          ) : (
            <ul className="mt-3 divide-y divide-ink-100">
              {subs.map((s) => (
                <li key={s.id} className="py-3 text-sm">
                  <div className="font-semibold">
                    {s.destination_type === "teams_bridge_channel"
                      ? "Teams via email bridge"
                      : "Email"}{" "}
                    → {s.destination}
                  </div>
                  {s.bridge_channel_key && (
                    <div className="text-ink-500">channel key: {s.bridge_channel_key}</div>
                  )}
                  <div className="text-ink-500">
                    reminders:{" "}
                    {s.reminders.map((r) => `${r.offset_minutes}m`).join(", ") || "none"}
                  </div>
                  <div className="text-ink-500">
                    targets: {s.targets.map((t) => `${t.target_type}:${t.target_id.slice(0, 8)}`).join(", ")}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="mh-panel p-5">
          <h2 className="font-display text-xl font-semibold">Create subscription</h2>
          <form className="mt-4 space-y-3" onSubmit={onCreate}>
            <div>
              <label className="mh-label">Application</label>
              <select className="mh-input" value={appId} onChange={(e) => setAppId(e.target.value)}>
                {apps.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mh-label">Destination type</label>
              <select
                className="mh-input"
                value={destType}
                onChange={(e) => setDestType(e.target.value)}
              >
                <option value="email_address">Email address</option>
                <option value="teams_bridge_channel">Teams via email bridge</option>
              </select>
            </div>
            <div>
              <label className="mh-label">Destination</label>
              <input
                className="mh-input"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                required
              />
            </div>
            {destType === "teams_bridge_channel" && (
              <div>
                <label className="mh-label">Bridge channel key (subject routing)</label>
                <input
                  className="mh-input"
                  value={channelKey}
                  onChange={(e) => setChannelKey(e.target.value)}
                  required
                />
              </div>
            )}
            <p className="text-xs text-ink-500">Default reminders: −24h and −1h before start.</p>
            <div className="flex flex-wrap gap-2">
              <button className="mh-btn" type="submit">
                Subscribe
              </button>
              <button className="mh-btn-ghost" type="button" onClick={() => void testNotify()}>
                Preview/test send
              </button>
            </div>
          </form>
          {testResult && (
            <p className="mt-3 rounded-md border border-ink-200 bg-ink-50 px-3 py-2 text-xs text-ink-700">
              {testResult}
            </p>
          )}
        </section>
      </div>

      <section className="mh-panel p-5">
        <h2 className="font-display text-xl font-semibold">ICS calendar feed</h2>
        <p className="mt-1 text-sm text-ink-600">
          Personalized Outlook-compatible feed scoped to favorites and subscriptions. Token is shown
          once; revoke anytime.
        </p>
        <button type="button" className="mh-btn mt-3" onClick={() => void createIcs()}>
          Create ICS token
        </button>
        {icsUrl && (
          <p className="mt-3 break-all rounded-md border border-accent/20 bg-accent-soft px-3 py-2 text-xs">
            Feed URL (copy now): {icsUrl}
          </p>
        )}
      </section>
    </div>
  );
}
