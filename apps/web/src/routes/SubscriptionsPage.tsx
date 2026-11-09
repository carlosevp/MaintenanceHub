import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type Application,
  type CalendarReachability,
  type Environment,
  type Subscription,
} from "@/api/client";

const REMINDER_OPTIONS = [
  { minutes: -1440, label: "24 hours before" },
  { minutes: -240, label: "4 hours before" },
  { minutes: -30, label: "30 minutes before" },
] as const;

const NOTIFY_OPTIONS = [
  { key: "start", label: "Start" },
  { key: "extension", label: "Extension" },
  { key: "cancellation", label: "Cancellation" },
  { key: "completion", label: "Completion" },
] as const;

type TargetMode = "app_environment" | "application";

export function SubscriptionsPage() {
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [appSearch, setAppSearch] = useState("");
  const [mode, setMode] = useState<TargetMode>("app_environment");
  const [appId, setAppId] = useState("");
  const [envIds, setEnvIds] = useState<string[]>([]);
  const [destType, setDestType] = useState("email_address");
  const [destination, setDestination] = useState("");
  const [channelKey, setChannelKey] = useState("ops-demo");
  const [reminders, setReminders] = useState<number[]>([-1440, -240]);
  const [notifyEvents, setNotifyEvents] = useState<string[]>([
    "start",
    "extension",
    "cancellation",
    "completion",
  ]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [icsUrl, setIcsUrl] = useState<string | null>(null);
  const [reachability, setReachability] = useState<CalendarReachability | null>(null);
  const [tokens, setTokens] = useState<
    Array<{ id: string; label?: string | null; revoked_at?: string | null }>
  >([]);

  const filteredApps = useMemo(() => {
    const q = appSearch.trim().toLowerCase();
    if (!q) return apps;
    return apps.filter(
      (a) => a.name.toLowerCase().includes(q) || a.key.toLowerCase().includes(q),
    );
  }, [apps, appSearch]);

  const selectedApp = apps.find((a) => a.id === appId) || null;
  const appEnvChoices = useMemo(() => {
    if (!selectedApp) return envs;
    const linked = selectedApp.environments
      .map((ae) => ae.environment)
      .filter((e): e is Environment => Boolean(e));
    return linked.length ? linked : envs;
  }, [selectedApp, envs]);

  const previewSummary = useMemo(() => {
    if (!selectedApp) return "Select an application to preview.";
    if (mode === "application") {
      return `${selectedApp.name} — entire application (any environment)`;
    }
    const labels = envIds
      .map((id) => {
        const e = appEnvChoices.find((x) => x.id === id) || envs.find((x) => x.id === id);
        return e ? `${e.name} (${e.key})` : null;
      })
      .filter(Boolean);
    if (!labels.length) return `${selectedApp.name} — select one or more environments`;
    return `${selectedApp.name} — ${labels.join(", ")}`;
  }, [selectedApp, mode, envIds, appEnvChoices, envs]);

  async function load() {
    setError(null);
    try {
      const [s, a, e, reach, tok] = await Promise.all([
        api.subscriptions(),
        api.applications(),
        api.environments(),
        api.calendarReachability(),
        api.listCalendarTokens(),
      ]);
      setSubs(s);
      setApps(a);
      setEnvs(e);
      setReachability(reach);
      setTokens(tok.filter((t) => !t.revoked_at));
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

  function buildTargets() {
    if (mode === "application") {
      return appId ? [{ target_type: "application", target_id: appId }] : [];
    }
    return envIds
      .filter(Boolean)
      .map((envId) => ({
        target_type: "app_environment",
        target_id: `${appId}:${envId}`,
      }));
  }

  function resetForm() {
    setEditingId(null);
    setMode("app_environment");
    setReminders([-1440, -240]);
    setNotifyEvents(["start", "extension", "cancellation", "completion"]);
    setEnvIds([]);
  }

  function startEdit(sub: Subscription) {
    setEditingId(sub.id);
    setDestType(sub.destination_type);
    setDestination(sub.destination);
    setChannelKey(sub.bridge_channel_key || "ops-demo");
    setNotifyEvents(sub.notify_events.length ? sub.notify_events : ["start", "extension", "cancellation", "completion"]);
    setReminders(sub.reminders.map((r) => r.offset_minutes));
    const first = sub.targets[0];
    if (first?.target_type === "application") {
      setMode("application");
      setAppId(first.application_id || first.target_id);
      setEnvIds([]);
    } else {
      setMode("app_environment");
      const appFromTarget = first?.application_id || first?.target_id.split(":")[0] || "";
      setAppId(appFromTarget);
      setEnvIds(
        sub.targets
          .filter((t) => t.target_type === "app_environment")
          .map((t) => t.environment_id || t.target_id.split(":")[1])
          .filter(Boolean) as string[],
      );
    }
    setMsg(null);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMsg(null);
    const targets = buildTargets();
    if (!targets.length) {
      setError("Select an application and at least one environment (or entire application).");
      return;
    }
    if (!reminders.length) {
      setError("Choose at least one advance reminder.");
      return;
    }
    if (!notifyEvents.length) {
      setError("Choose at least one notification type.");
      return;
    }
    const body = {
      destination_type: destType,
      destination,
      bridge_channel_key: destType === "teams_bridge_channel" ? channelKey : null,
      targets,
      reminders: reminders.map((offset_minutes) => ({ offset_minutes })),
      notify_events: notifyEvents,
    };
    try {
      if (editingId) {
        await api.updateSubscription(editingId, body);
        setMsg("Alert updated.");
      } else {
        await api.createSubscription(body);
        setMsg("Alert created.");
      }
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    }
  }

  async function onDelete(id: string) {
    setError(null);
    try {
      await api.deleteSubscription(id);
      if (editingId === id) resetForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Remove failed");
    }
  }

  function toggleEnv(id: string) {
    setEnvIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function toggleReminder(minutes: number) {
    setReminders((prev) =>
      prev.includes(minutes) ? prev.filter((x) => x !== minutes) : [...prev, minutes].sort((a, b) => a - b),
    );
  }

  function toggleNotify(key: string) {
    setNotifyEvents((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key],
    );
  }

  async function createIcs() {
    setError(null);
    try {
      const body = await api.createCalendarToken({
        scopes: ["favorites", "subscriptions"],
        label: "Outlook",
      });
      setIcsUrl(body.feed_url);
      if (body.reachability) setReachability(body.reachability);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create calendar subscription");
    }
  }

  async function downloadIcs() {
    setError(null);
    setMsg(null);
    try {
      const blob = await api.downloadCalendarIcs();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "maintenancehub-calendar.ics";
      a.click();
      URL.revokeObjectURL(url);
      setMsg("Calendar downloaded.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Download failed");
    }
  }

  async function revokeToken(id: string) {
    try {
      await api.revokeCalendarToken(id);
      if (icsUrl) setIcsUrl(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Revoke failed");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="mh-eyebrow">Consumer</p>
        <h1 className="font-display text-3xl font-semibold text-ink">My Alerts</h1>
        <p className="mt-1 max-w-3xl text-sm text-ink-muted">
          Search applications, pick environments, choose advance reminders and lifecycle notices,
          then review or edit your alerts. Channels and timing stay visible without technical IDs.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}
      {msg && (
        <p className="rounded-md border border-accent/20 bg-accent-soft px-3 py-2 text-sm text-ink-800" role="status">
          {msg}
        </p>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <section className="mh-panel p-5" aria-labelledby="subs-list">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 id="subs-list" className="font-display text-xl font-semibold">
                Active alerts
              </h2>
              <p className="text-sm text-ink-muted">{subs.length} subscription{subs.length === 1 ? "" : "s"}</p>
            </div>
          </div>
          {subs.length === 0 ? (
            <p className="mt-4 text-sm text-ink-500">
              No alerts yet. Create one on the right — search an app, choose environments, and
              subscribe.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {subs.map((s) => (
                <li
                  key={s.id}
                  className="rounded-xl border border-ink-100 bg-surface/60 px-4 py-3"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="font-semibold text-ink">
                        {s.targets.map((t) => t.label).join(" · ") || "No targets"}
                      </div>
                      <div className="text-sm text-ink-600">
                        {s.targets.map((t) => t.scope_label).filter(Boolean).join(" · ")}
                      </div>
                      {s.targets.some((t) => t.missing) && (
                        <p className="text-xs text-danger">
                          One or more catalog references are missing or retired.
                        </p>
                      )}
                      <div className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-xs text-ink-500">
                        <span>
                          Channel: {s.channel_label}
                          {s.destination_type === "email_address" ? ` → ${s.destination}` : ""}
                          {s.bridge_channel_key ? ` · route ${s.bridge_channel_key}` : ""}
                        </span>
                        <span>
                          Reminders:{" "}
                          {s.reminders.map((r) => r.label || `${r.offset_minutes}m`).join(", ") ||
                            "none"}
                        </span>
                        <span>
                          Notices: {s.notify_event_labels.join(", ") || "All lifecycle events"}
                        </span>
                      </div>
                    </div>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        className="mh-btn-ghost text-xs"
                        onClick={() => startEdit(s)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="mh-btn-ghost text-xs text-danger"
                        onClick={() => void onDelete(s.id)}
                      >
                        Unsubscribe
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="mh-panel p-5" aria-labelledby="subs-create">
          <h2 id="subs-create" className="font-display text-xl font-semibold">
            {editingId ? "Edit alert" : "Subscribe"}
          </h2>
          <p className="mt-1 text-sm text-ink-muted">{previewSummary}</p>
          <form className="mt-4 space-y-4" onSubmit={onSubmit}>
            <div>
              <label className="mh-label" htmlFor="app-search">
                Search applications
              </label>
              <input
                id="app-search"
                className="mh-input"
                value={appSearch}
                onChange={(e) => setAppSearch(e.target.value)}
                placeholder="Name or key…"
              />
              <label className="mh-label mt-3" htmlFor="sub-app">
                Application
              </label>
              <select
                id="sub-app"
                className="mh-input"
                value={appId}
                onChange={(e) => {
                  setAppId(e.target.value);
                  setEnvIds([]);
                }}
                required
              >
                <option value="">Select…</option>
                {filteredApps.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              {selectedApp && (
                <p className="mt-1 text-xs">
                  <Link
                    className="text-accent underline"
                    to={`/status/apps/${selectedApp.key}`}
                  >
                    Open status page
                  </Link>
                </p>
              )}
            </div>

            <fieldset>
              <legend className="mh-label">Scope</legend>
              <div className="mt-1 flex flex-wrap gap-3 text-sm">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="scope"
                    checked={mode === "app_environment"}
                    onChange={() => setMode("app_environment")}
                  />
                  Selected environments
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="scope"
                    checked={mode === "application"}
                    onChange={() => setMode("application")}
                  />
                  Entire application
                </label>
              </div>
            </fieldset>

            {mode === "app_environment" && (
              <fieldset>
                <legend className="mh-label">Environments</legend>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {appEnvChoices.map((e) => (
                    <label
                      key={e.id}
                      className="flex items-center gap-2 rounded-lg border border-ink-100 px-3 py-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={envIds.includes(e.id)}
                        onChange={() => toggleEnv(e.id)}
                      />
                      <span>
                        <span className="font-medium">{e.name}</span>
                        <span className="text-ink-500"> ({e.key})</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            )}

            <fieldset>
              <legend className="mh-label">Advance reminders</legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {REMINDER_OPTIONS.map((opt) => (
                  <label
                    key={opt.minutes}
                    className="flex items-center gap-2 rounded-lg border border-ink-100 px-3 py-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={reminders.includes(opt.minutes)}
                      onChange={() => toggleReminder(opt.minutes)}
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset>
              <legend className="mh-label">Notify on</legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {NOTIFY_OPTIONS.map((opt) => (
                  <label
                    key={opt.key}
                    className="flex items-center gap-2 rounded-lg border border-ink-100 px-3 py-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={notifyEvents.includes(opt.key)}
                      onChange={() => toggleNotify(opt.key)}
                    />
                    {opt.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <div>
              <label className="mh-label" htmlFor="dest-type">
                Notification channel
              </label>
              <select
                id="dest-type"
                className="mh-input"
                value={destType}
                onChange={(e) => setDestType(e.target.value)}
              >
                <option value="email_address">Email</option>
                <option value="teams_bridge_channel">Teams via email bridge</option>
              </select>
            </div>
            <div>
              <label className="mh-label" htmlFor="dest">
                {destType === "email_address" ? "Email address" : "Bridge mailbox / destination"}
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
                  Bridge route key
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

            <div className="flex flex-wrap gap-2">
              <button className="mh-btn" type="submit">
                {editingId ? "Save changes" : "Subscribe"}
              </button>
              {editingId && (
                <button className="mh-btn-ghost" type="button" onClick={resetForm}>
                  Cancel edit
                </button>
              )}
            </div>
          </form>
        </section>
      </div>

      <section className="mh-panel p-5" aria-labelledby="calendar-heading">
        <h2 id="calendar-heading" className="font-display text-xl font-semibold">
          Outlook calendar
        </h2>
        <p className="mt-1 max-w-3xl text-sm text-ink-muted">
          Two choices: subscribe to a refreshable feed when Outlook can reach your configured HTTPS
          URL, or download a static <code>.ics</code> snapshot that never exposes an internal URL.
        </p>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <div className="rounded-xl border border-ink-100 p-4">
            <h3 className="font-display text-lg font-semibold">Option A — Subscribe</h3>
            <p className="mt-1 text-sm text-ink-600">
              Tokenized ICS feed scoped to favorites and subscriptions. Create or revoke anytime.
              Feeds stay minimally informative.
            </p>
            {reachability && (
              <p
                className={`mt-3 rounded-md px-3 py-2 text-xs ${
                  reachability.subscription_supported
                    ? "border border-accent/20 bg-accent-soft text-ink-800"
                    : "border border-amber-200 bg-amber-50 text-amber-950"
                }`}
                role="note"
              >
                {reachability.message}
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <button type="button" className="mh-btn" onClick={() => void createIcs()}>
                Create subscription feed
              </button>
            </div>
            {icsUrl && (
              <p className="mt-3 break-all rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-xs">
                Feed URL (copy now — token shown once): {icsUrl}
              </p>
            )}
            {tokens.length > 0 && (
              <ul className="mt-3 space-y-2 text-sm">
                {tokens.map((t) => (
                  <li key={t.id} className="flex items-center justify-between gap-2">
                    <span className="text-ink-600">{t.label || "Calendar feed"}</span>
                    <button
                      type="button"
                      className="mh-btn-ghost text-xs"
                      onClick={() => void revokeToken(t.id)}
                    >
                      Revoke
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-ink-100 p-4">
            <h3 className="font-display text-lg font-semibold">Option B — Download calendar (.ics)</h3>
            <p className="mt-1 text-sm text-ink-600">
              Snapshot for your selected app/environment subscriptions. Uses the same ICS
              generation as the feed — recurrence, overrides, cancellations, and timezones as
              supported — without a public calendar endpoint.
            </p>
            <button type="button" className="mh-btn mt-3" onClick={() => void downloadIcs()}>
              Download calendar (.ics)
            </button>
            <p className="mt-3 text-xs text-ink-500">
              Downloaded calendars are static snapshots. New maintenance and later changes will not
              automatically appear. Download again to get an updated copy.
            </p>
            <div className="mt-3 text-xs text-ink-600">
              <p className="font-medium text-ink">Outlook on the web — import</p>
              <ol className="mt-1 list-decimal space-y-1 pl-4">
                <li>Open Outlook on the web → Calendar.</li>
                <li>Add calendar → Upload from file (wording varies by tenant).</li>
                <li>Choose the downloaded <code>.ics</code> file and import.</li>
              </ol>
              <p className="mt-2">
                Re-importing a newer file does not reliably reconcile prior events unless your
                Outlook tenant merges by UID — treat each download as a fresh snapshot.
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
