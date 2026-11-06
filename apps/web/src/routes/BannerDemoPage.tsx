import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Application } from "@/api/client";

/**
 * Embed banner screen — select app/env, copy dependency-free snippet, L/D preview.
 * Compact primary + additional; warns on non-HTTPS / local / in-cluster bases.
 */

type Msg = {
  id: string;
  event_id?: string;
  kind: string;
  title: string;
  status: string;
  presentation?: string;
  starts_at: string;
  ends_at: string;
  expected_impact?: string | null;
  approval_state: string;
  revision?: string;
  dismissible?: boolean;
  status_path?: string | null;
};

type Theme = "light" | "dark";
type RouteKind = "browser" | "corporate" | "in_cluster" | "local_dev";

function presentationLabel(p?: string, status?: string): string {
  switch (p) {
    case "outage":
      return "Outage";
    case "in_progress":
      return "In progress";
    case "extended":
      return "Extended";
    case "verifying":
      return "Verifying";
    case "upcoming":
      return "Upcoming";
    default:
      return (status || "scheduled").replaceAll("_", " ");
  }
}

function formatWindow(start: string, end: string, timeZone?: string): string {
  try {
    const opts: Intl.DateTimeFormatOptions = {
      dateStyle: "medium",
      timeStyle: "short",
      ...(timeZone ? { timeZone } : {}),
    };
    const fmt = new Intl.DateTimeFormat(undefined, opts);
    return `${fmt.format(new Date(start))} → ${fmt.format(new Date(end))}`;
  } catch {
    return `${start} → ${end}`;
  }
}

function classifyBase(url: string): { kind: RouteKind; warn?: string; https: boolean } {
  try {
    const u = new URL(url);
    const host = u.hostname;
    const https = u.protocol === "https:";
    const local =
      host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host.endsWith(".local");
    if (local) {
      return {
        kind: "local_dev",
        https,
        warn: "Local/dev API base — do not ship this snippet to production hosts. Prefer HTTPS corporate URL for browsers.",
      };
    }
    if (
      host.endsWith(".svc") ||
      host.endsWith(".svc.cluster.local") ||
      host === "maintenancehub-api"
    ) {
      return {
        kind: "in_cluster",
        https,
        warn: "In-cluster DNS is for BFFs/OpenShift — browsers need the HTTPS corporate route.",
      };
    }
    if (!https) {
      return {
        kind: "corporate",
        https: false,
        warn: "Browser embeds should use an https:// MaintenanceHub base.",
      };
    }
    return { kind: "browser", https: true };
  } catch {
    return { kind: "local_dev", https: false, warn: "Invalid API base URL." };
  }
}

function buildSnippet(opts: {
  apiBase: string;
  appKey: string;
  envKey: string;
  theme: Theme;
  advanceHours: number;
  timeZone: string;
  routeKind: RouteKind;
  warn?: string;
}): string {
  const base = opts.apiBase.replace(/\/$/, "");
  const envLine = opts.envKey
    ? `\n      environmentKey: ${JSON.stringify(opts.envKey)},`
    : "";
  const warnComment = opts.warn ? `\n<!-- WARNING: ${opts.warn} -->` : "";
  const tzLine = opts.timeZone
    ? `\n      timeZone: ${JSON.stringify(opts.timeZone)},`
    : "";
  return `<!-- MaintenanceHub banner — confirmed notices only; no secrets.${warnComment} -->
<!-- route: ${opts.routeKind} | API ISO-8601; UI formats with Intl -->
<link rel="stylesheet" href="${base}/static/banner/style.css" />
<div id="mh-banner-root"></div>
<script src="${base}/static/banner/embed.js" defer></script>
<script>
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.MaintenanceHubBanner) return;
    window.MaintenanceHubBanner.mount({
      target: "#mh-banner-root",
      apiBaseUrl: ${JSON.stringify(base)},
      applicationKey: ${JSON.stringify(opts.appKey)},${envLine}
      advanceHours: ${opts.advanceHours},${tzLine}
      statusPageBaseUrl: ${JSON.stringify(base)},
      theme: ${JSON.stringify(opts.theme)},
      compact: true,
      pollIntervalMs: 60000
    });
  });
</script>`;
}

export function BannerDemoPage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [appKey, setAppKey] = useState("claims");
  const [envKey, setEnvKey] = useState("INT");
  const [advanceHours, setAdvanceHours] = useState(24);
  const [theme, setTheme] = useState<Theme>("light");
  const [expanded, setExpanded] = useState(false);
  const [timeZone, setTimeZone] = useState(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const [messages, setMessages] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState("");
  const [copied, setCopied] = useState(false);
  const [apiBase, setApiBase] = useState("https://maintenancehub.example.com");

  useEffect(() => {
    void api.applications().then(setApps).catch(() => setApps([]));
  }, []);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedApp = useMemo(
    () => apps.find((a) => a.key === appKey) ?? null,
    [apps, appKey],
  );

  const envOptions = useMemo(() => {
    const envs = selectedApp?.environments ?? [];
    return envs
      .map((e) => ({
        key: e.environment?.key || "",
        label: e.display_name || e.environment?.name || e.environment?.key || "",
      }))
      .filter((e) => e.key);
  }, [selectedApp]);

  const classified = useMemo(() => classifyBase(apiBase), [apiBase]);

  const snippet = useMemo(
    () =>
      buildSnippet({
        apiBase: apiBase.replace(/\/$/, ""),
        appKey,
        envKey,
        theme,
        advanceHours,
        timeZone,
        routeKind: classified.kind,
        warn: classified.warn,
      }),
    [apiBase, appKey, envKey, theme, advanceHours, timeZone, classified],
  );

  const primary = messages[0];
  const additional = messages.slice(1);
  const visible = !expanded && additional.length > 0 ? (primary ? [primary] : []) : messages;

  async function load(e?: FormEvent) {
    e?.preventDefault();
    setError(null);
    try {
      const params = new URLSearchParams({ application_key: appKey });
      if (envKey) params.set("environment_key", envKey);
      params.set("advance_hours", String(advanceHours));
      const res = await fetch(`/api/v1/public/banner?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = (await res.json()) as Msg[];
      setMessages(data);
      setRaw(JSON.stringify(data, null, 2));
      const blob = JSON.stringify(data);
      if (
        blob.includes('"description"') ||
        blob.includes("timeline") ||
        blob.includes("client_secret")
      ) {
        setError("Unexpected internal fields in public DTO");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
      setMessages([]);
    }
  }

  async function copySnippet() {
    try {
      await navigator.clipboard.writeText(snippet);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Clipboard unavailable — select the snippet manually.");
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-8">
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← Overview
      </Link>

      <header className="space-y-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-ink-faint">
          Embed
        </p>
        <h1 className="font-display text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          Banner embed
        </h1>
        <p className="max-w-2xl text-sm text-ink-600">
          Select an application and environment, copy a dependency-free snippet for an{" "}
          <strong className="font-medium text-ink">independent host</strong>, and preview
          compact light/dark presentation. Confirmed notices only — never paste{" "}
          <code className="text-ink">client_secret</code>. Not monitoring.
        </p>
      </header>

      <section className="mh-panel space-y-4 p-6" aria-labelledby="embed-config">
        <h2 id="embed-config" className="font-display text-xl font-semibold text-ink">
          Configure
        </h2>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => void load(e)}>
          <div className="sm:col-span-2">
            <label className="mh-label" htmlFor="api-base">
              Browser / corporate API base (HTTPS)
            </label>
            <input
              id="api-base"
              className="mh-input"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
              placeholder="https://maintenancehub.example.com"
            />
            <p className="mt-1 text-xs text-ink-faint">
              Route: <code>{classified.kind}</code>
              {classified.https ? " · HTTPS" : " · not HTTPS"}
            </p>
            {classified.warn && (
              <p className="mt-2 rounded-md border border-amber-300/60 bg-amber-50 px-3 py-2 text-xs text-amber-900" role="status">
                {classified.warn}
              </p>
            )}
          </div>
          <div>
            <label className="mh-label" htmlFor="app-key">
              Application
            </label>
            {apps.length > 0 ? (
              <select
                id="app-key"
                className="mh-input"
                value={appKey}
                onChange={(e) => {
                  setAppKey(e.target.value);
                  const next = apps.find((a) => a.key === e.target.value);
                  const first = next?.environments?.[0];
                  const ek = first?.environment?.key || envKey;
                  setEnvKey(ek || "");
                }}
              >
                {apps.map((a) => (
                  <option key={a.id} value={a.key}>
                    {a.name} ({a.key})
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="app-key"
                className="mh-input"
                value={appKey}
                onChange={(e) => setAppKey(e.target.value)}
              />
            )}
          </div>
          <div>
            <label className="mh-label" htmlFor="env-key">
              Environment
            </label>
            {envOptions.length > 0 ? (
              <select
                id="env-key"
                className="mh-input"
                value={envKey}
                onChange={(e) => setEnvKey(e.target.value)}
              >
                {envOptions.map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.label} ({e.key})
                  </option>
                ))}
              </select>
            ) : (
              <input
                id="env-key"
                className="mh-input"
                value={envKey}
                onChange={(e) => setEnvKey(e.target.value)}
                placeholder="INT"
              />
            )}
          </div>
          <div>
            <label className="mh-label" htmlFor="advance">
              Advance window (hours)
            </label>
            <input
              id="advance"
              type="number"
              min={0}
              max={168}
              className="mh-input"
              value={advanceHours}
              onChange={(e) => setAdvanceHours(Number(e.target.value) || 0)}
            />
          </div>
          <div>
            <label className="mh-label" htmlFor="tz">
              Viewer timezone (IANA)
            </label>
            <input
              id="tz"
              className="mh-input"
              value={timeZone}
              onChange={(e) => setTimeZone(e.target.value)}
              placeholder="America/Chicago"
            />
          </div>
          <div>
            <label className="mh-label">Preview theme</label>
            <div className="mt-1 flex gap-2">
              {(["light", "dark"] as Theme[]).map((t) => (
                <button
                  key={t}
                  type="button"
                  className={theme === t ? "mh-btn" : "mh-btn-ghost"}
                  onClick={() => setTheme(t)}
                >
                  {t === "light" ? "Light" : "Dark"}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-end gap-2 sm:col-span-2">
            <button className="mh-btn" type="submit">
              Refresh preview
            </button>
            <button className="mh-btn-ghost" type="button" onClick={() => void copySnippet()}>
              {copied ? "Copied" : "Copy snippet"}
            </button>
          </div>
        </form>
        {error && (
          <p
            className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
            role="alert"
          >
            {error}
          </p>
        )}
      </section>

      <section className="space-y-3" aria-labelledby="embed-preview">
        <h2 id="embed-preview" className="font-display text-xl font-semibold text-ink">
          Live preview (compact)
        </h2>
        <aside
          className={
            theme === "dark"
              ? "rounded-xl border border-teal-900/40 bg-[#0f1a1f] p-4 text-[#e8eef4]"
              : "rounded-xl border border-teal-700/30 bg-gradient-to-b from-teal-50 to-teal-50/40 p-4"
          }
          role="region"
          aria-label="Maintenance and outage communications"
          data-theme={theme}
        >
          <p
            className={
              theme === "dark"
                ? "text-xs font-bold uppercase tracking-wide text-teal-300"
                : "text-xs font-bold uppercase tracking-wide text-teal-800"
            }
          >
            MaintenanceHub notices · {appKey}
            {envKey ? ` / ${envKey}` : ""}
          </p>
          {visible.length === 0 ? (
            <p className={theme === "dark" ? "mt-2 text-sm text-slate-400" : "mt-2 text-sm text-ink-500"}>
              No active/upcoming confirmed messages in the advance window.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {visible.map((m) => {
                const outage = m.presentation === "outage";
                return (
                  <li
                    key={m.id}
                    className={
                      outage
                        ? "rounded-lg border border-red-300/50 bg-red-50/80 px-3 py-2 text-sm text-ink"
                        : theme === "dark"
                          ? "rounded-lg border border-teal-800 bg-[#16262c] px-3 py-2 text-sm"
                          : "rounded-lg border border-teal-200 bg-white px-3 py-2 text-sm"
                    }
                  >
                    <span className="mr-2 text-xs font-bold uppercase text-teal-800">
                      {m.kind === "manual_outage" ? "Outage" : "Maintenance"}
                    </span>
                    <span className="mr-2 text-xs font-bold uppercase text-ink-500">
                      {presentationLabel(m.presentation, m.status)}
                    </span>
                    <strong className="block">{m.title}</strong>
                    <span className="text-xs text-ink-600">
                      {formatWindow(m.starts_at, m.ends_at, timeZone)}
                    </span>
                    {m.expected_impact && (
                      <span className="block text-xs text-ink-600">
                        Impact: {m.expected_impact}
                      </span>
                    )}
                    {m.status_path && (
                      <span className="mt-1 block text-xs">
                        <a className="text-accent underline" href={m.status_path}>
                          Status
                        </a>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {additional.length > 0 && (
            <button
              type="button"
              className="mt-3 text-xs font-semibold text-teal-800 underline"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Show less" : `View ${additional.length} additional`}
            </button>
          )}
        </aside>
      </section>

      <section className="space-y-3" aria-labelledby="embed-snippet">
        <div className="flex items-center justify-between gap-2">
          <h2 id="embed-snippet" className="font-display text-xl font-semibold text-ink">
            Copy-paste snippet (independent host)
          </h2>
          <button className="mh-btn-ghost" type="button" onClick={() => void copySnippet()}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="mh-panel overflow-x-auto p-4 text-xs leading-relaxed text-ink-700">
          {snippet}
        </pre>
        <div className="space-y-1 text-xs text-ink-faint">
          <p>
            <strong className="text-ink-600">Browser / corporate:</strong>{" "}
            <code>https://&lt;mh&gt;/api/v1/public/banner?…</code>
          </p>
          <p>
            <strong className="text-ink-600">In-cluster (OpenShift BFF):</strong>{" "}
            <code>
              http://maintenancehub-api:8000/api/v1/internal/banner?application_key={appKey}
              {envKey ? `&environment_key=${envKey}` : ""}
            </code>
          </p>
          <p>
            <strong className="text-ink-600">Local demo:</strong>{" "}
            <code>http://127.0.0.1:8000</code> — never ship.
          </p>
        </div>
      </section>

      {raw && (
        <section className="space-y-2" aria-labelledby="embed-json">
          <h2 id="embed-json" className="font-display text-lg font-semibold text-ink">
            Public JSON (ISO times)
          </h2>
          <pre className="mh-panel overflow-x-auto p-4 text-xs text-ink-700">{raw}</pre>
        </section>
      )}
    </div>
  );
}
