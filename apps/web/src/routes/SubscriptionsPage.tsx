import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Application, type Environment } from "@/api/client";

type Sub = {
  id: string;
  destination_type: string;
  destination: string;
  bridge_channel_key?: string | null;
  is_active: boolean;
  reminders: Array<{ id: string; offset_minutes: number }>;
  targets: Array<{ id: string; target_type: string; target_id: string }>;
};

type TargetMode = "application" | "app_environment" | "event";

function formatOffset(m: number): string {
  const abs = Math.abs(m);
  if (abs % 1440 === 0) return `${m / 1440}d`;
  if (abs % 60 === 0) return `${m / 60}h`;
  return `${m}m`;
}

export function SubscriptionsPage() {
  const [subs, setSubs] = useState<Sub[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<TargetMode>("app_environment");
  const [appId, setAppId] = useState("");
  const [envIds, setEnvIds] = useState<string[]>([]);
  const [eventId, setEventId] = useState("");
  const [destType, setDestType] = useState("email_address");
  const [destination, setDestination] = useState("");
  const [channelKey, setChannelKey] = useState("ops-demo");
  const [reminderText, setReminderText] = useState("-1440,-60");
  const [testResult, setTestResult] = useState<string | null>(null);
  const [icsUrl, setIcsUrl] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      const [s, a, e] = await Promise.all([
        api.subscriptions() as Promise<Sub[]>,
        api.applications(),
        api.environments(),
      ]);
      setSubs(s);
      setApps(a);
      setEnvs(e);
      if (!appId && a[0]) setAppId(a[0].id);
      if (!envIds.length && e[0]) setEnvIds([e[0].id]);
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

  function parseReminders(): Array<{ offset_minutes: number }> {
    return reminderText
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean)
      .map((x) => ({ offset_minutes: Number(x) }))
      .filter((r) => Number.isFinite(r.offset_minutes));
  }

  function buildTargets(): Array<{ target_type: string; target_id: string }> {
    if (mode === "event") {
      return eventId ? [{ target_type: "event", target_id: eventId.trim() }] : [];
    }
    if (mode === "application") {
      return appId ? [{ target_type: "application", target_id: appId }] : [];
    }
    // app_environment: one target per env with id "appId:envId"
    return envIds
      .filter(Boolean)
      .map((envId) => ({
        target_type: "app_environment",
        target_id: `${appId}:${envId}`,
      }));
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const targets = buildTargets();
    if (!targets.length) {
      setError("Select at least one target");
      return;
    }
    const reminders = parseReminders();
    if (!reminders.length) {
      setError("Add at least one reminder offset");
      return;
    }
    try {
      await api.createSubscription({
        destination_type: destType,
        destination,
        bridge_channel_key: destType === "teams_bridge_channel" ? channelKey : null,
        targets,
        reminders,
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  async function onDelete(id: string) {
    setError(null);
    try {
      await api.deleteSubscription(id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  async function testNotify() {
    setTestResult(null);
    try {
      const token = localStorage.getItem("mh_token");
      const res = await fetch("/api/v1/notifications/test", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          template_key: "event.created",
          destination_type: destType,
          destination,
          bridge_channel_key: channelKey,
          context: {
            title: "Demo maintenance",
            approval_state: "confirmed_scheduled",
            expected_impact: "Brief read-only window",
            detail_url: "/events/demo",
          },
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const body = (await res.json()) as {
        status: string;
        channel: string;
        subject: string;
        note: string;
        provider_message_id?: string;
      };
      setTestResult(
        `${body.note} → ${body.status} via ${body.channel}; subject=${body.subject}; id=${body.provider_message_id}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
    }
  }

  async function createIcs() {
    try {
      const body = await api.createCalendarToken({
        scopes: ["favorites", "subscriptions"],
        label: "Outlook",
      });
      setIcsUrl(body.feed_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ICS token failed");
    }
  }

  function toggleEnv(id: string) {
    setEnvIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-semibold text-ink-950">Subscriptions & calendar</h1>
        <p className="mt-1 text-sm text-ink-600">
          Subscribe to applications, app+environment pairs, or a single event. Matching reuses
          effective confirmed impacts (including downstream). Multiple subscriptions to the same
          destination are deduplicated per delivery — you receive one message per reminder slot.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="mh-panel p-5" aria-labelledby="subs-list">
          <h2 id="subs-list" className="font-display text-xl font-semibold">
            Your subscriptions
          </h2>
          {subs.length === 0 ? (
            <p className="mt-3 text-sm text-ink-500">None yet.</p>
          ) : (
            <ul className="mt-3 divide-y divide-ink-100">
              {subs.map((s) => (
                <li key={s.id} className="flex flex-wrap items-start justify-between gap-2 py-3 text-sm">
                  <div>
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
                      {s.reminders.map((r) => formatOffset(r.offset_minutes)).join(", ") || "none"}
                    </div>
                    <div className="text-ink-500">
                      targets:{" "}
                      {s.targets
                        .map((t) =>
                          t.target_type === "app_environment"
                            ? `app+env ${t.target_id}`
                            : `${t.target_type}:${t.target_id.slice(0, 8)}`,
                        )
                        .join(", ")}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="mh-btn-ghost text-xs"
                    onClick={() => void onDelete(s.id)}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="mh-panel p-5" aria-labelledby="subs-create">
          <h2 id="subs-create" className="font-display text-xl font-semibold">
            Create subscription
          </h2>
          <form className="mt-4 space-y-3" onSubmit={onCreate}>
            <div>
              <label className="mh-label" htmlFor="target-mode">
                Target mode
              </label>
              <select
                id="target-mode"
                className="mh-input"
                value={mode}
                onChange={(e) => setMode(e.target.value as TargetMode)}
              >
                <option value="app_environment">App + environment pair(s)</option>
                <option value="application">Entire application (any env)</option>
                <option value="event">Single event</option>
              </select>
            </div>

            {mode !== "event" && (
              <div>
                <label className="mh-label" htmlFor="sub-app">
                  Application
                </label>
                <select
                  id="sub-app"
                  className="mh-input"
                  value={appId}
                  onChange={(e) => setAppId(e.target.value)}
                >
                  {apps.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>
                {appId && (
                  <p className="mt-1 text-xs">
                    <Link className="text-accent underline" to={`/status/apps/${apps.find((a) => a.id === appId)?.key || ""}`}>
                      Open status page
                    </Link>
                  </p>
                )}
              </div>
            )}

            {mode === "app_environment" && (
              <fieldset>
                <legend className="mh-label">Environments (multi-select)</legend>
                <div className="mt-1 flex flex-wrap gap-3">
                  {envs.map((e) => (
                    <label key={e.id} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={envIds.includes(e.id)}
                        onChange={() => toggleEnv(e.id)}
                      />
                      {e.key}
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

            {mode === "event" && (
              <div>
                <label className="mh-label" htmlFor="sub-event">
                  Event ID
                </label>
                <input
                  id="sub-event"
                  className="mh-input"
                  value={eventId}
                  onChange={(e) => setEventId(e.target.value)}
                  placeholder="Paste maintenance event id"
                  required
                />
              </div>
            )}

            <div>
              <label className="mh-label" htmlFor="dest-type">
                Destination type
              </label>
              <select
                id="dest-type"
                className="mh-input"
                value={destType}
                onChange={(e) => setDestType(e.target.value)}
              >
                <option value="email_address">Email address</option>
                <option value="teams_bridge_channel">Teams via email bridge</option>
              </select>
            </div>
            <div>
              <label className="mh-label" htmlFor="dest">
                Destination
              </label>
              <input
                id="dest"
                className="mh-input"
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                required
              />
            </div>
            {destType === "teams_bridge_channel" && (
              <div>
                <label className="mh-label" htmlFor="bridge">
                  Bridge channel key (subject routing)
                </label>
                <input
                  id="bridge"
                  className="mh-input"
                  value={channelKey}
                  onChange={(e) => setChannelKey(e.target.value)}
                  required
                />
              </div>
            )}
            <div>
              <label className="mh-label" htmlFor="reminders">
                Reminder offsets (minutes before start)
              </label>
              <input
                id="reminders"
                className="mh-input"
                value={reminderText}
                onChange={(e) => setReminderText(e.target.value)}
                placeholder="-1440,-60,-15"
              />
              <p className="mt-1 text-xs text-ink-500">
                Example: −24h (−1440), −1h (−60), −15m. Multi-interval reminders fire independently;
                duplicate destinations still dedupe per slot.
              </p>
            </div>
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

      <section className="mh-panel p-5" aria-labelledby="ics-heading">
        <h2 id="ics-heading" className="font-display text-xl font-semibold">
          ICS calendar feed
        </h2>
        <p className="mt-1 text-sm text-ink-600">
          Personalized Outlook-compatible feed scoped to favorites and subscriptions. Clients poll
          and refresh on their own interval — not push-realtime. Token is shown once; revoke anytime.
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
