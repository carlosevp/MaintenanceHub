import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Application } from "@/api/client";

/**
 * Embed banner screen — select app/env, copy dependency-free snippet, L/D preview.
 * Uses the same public DTO as @maintenancehub/banner (no internal notes).
 */

type Msg = {
  id: string;
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
};

type Theme = "light" | "dark";

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

function buildSnippet(opts: {
  apiBase: string;
  appKey: string;
  envKey: string;
  theme: Theme;
  advanceHours: number;
}): string {
  const envLine = opts.envKey
    ? `\n      environmentKey: ${JSON.stringify(opts.envKey)},`
    : "";
  return `<!-- MaintenanceHub banner — Claims INT / host app embed. No secrets. -->
<link rel="stylesheet" href="${opts.apiBase}/static/banner/style.css" />
<div id="mh-banner-root"></div>
<script src="${opts.apiBase}/static/banner/embed.js" defer></script>
<script>
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.MaintenanceHubBanner) return;
    window.MaintenanceHubBanner.mount({
      target: "#mh-banner-root",
      apiBaseUrl: ${JSON.stringify(opts.apiBase)},
      applicationKey: ${JSON.stringify(opts.appKey)},${envLine}
      advanceHours: ${opts.advanceHours},
      theme: ${JSON.stringify(opts.theme)},
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
  const [messages, setMessages] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [raw, setRaw] = useState("");
  const [copied, setCopied] = useState(false);
  const [apiBase, setApiBase] = useState(
    () => (typeof window !== "undefined" ? window.location.origin : "http://localhost:8000"),
  );

  useEffect(() => {
    void api.applications().then(setApps).catch(() => setApps([]));
  }, []);

  useEffect(() => {
    void load();
    // Initial preview for Claims INT / selected pair
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

  const snippet = useMemo(
    () =>
      buildSnippet({
        apiBase: apiBase.replace(/\/$/, ""),
        appKey,
        envKey,
        theme,
        advanceHours,
      }),
    [apiBase, appKey, envKey, theme, advanceHours],
  );

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
        blob.includes("description") ||
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
          Select an application and environment, copy a dependency-free snippet, and preview
          light/dark presentation. Confirmed notices only — never paste{" "}
          <code className="text-ink">client_secret</code> into host pages. Not monitoring.
        </p>
      </header>

      <section className="mh-panel space-y-4 p-6" aria-labelledby="embed-config">
        <h2 id="embed-config" className="font-display text-xl font-semibold text-ink">
          Configure
        </h2>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => void load(e)}>
          <div className="sm:col-span-2">
            <label className="mh-label" htmlFor="api-base">
              API base URL
            </label>
            <input
              id="api-base"
              className="mh-input"
              value={apiBase}
              onChange={(e) => setApiBase(e.target.value)}
            />
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
          Live preview
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
          {messages.length === 0 ? (
            <p className={theme === "dark" ? "mt-2 text-sm text-slate-400" : "mt-2 text-sm text-ink-500"}>
              No active/upcoming confirmed messages in the advance window.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {messages.map((m) => {
                const outage = m.presentation === "outage" || m.kind === "manual_outage";
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
                      {m.starts_at} → {m.ends_at}
                    </span>
                    {m.expected_impact && (
                      <span className="block text-xs text-ink-600">
                        Impact: {m.expected_impact}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </aside>
      </section>

      <section className="space-y-3" aria-labelledby="embed-snippet">
        <div className="flex items-center justify-between gap-2">
          <h2 id="embed-snippet" className="font-display text-xl font-semibold text-ink">
            Copy-paste snippet
          </h2>
          <button className="mh-btn-ghost" type="button" onClick={() => void copySnippet()}>
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <pre className="mh-panel overflow-x-auto p-4 text-xs leading-relaxed text-ink-700">
          {snippet}
        </pre>
        <p className="text-xs text-ink-faint">
          Internal OpenShift path:{" "}
          <code>
            {apiBase.replace(/\/$/, "")}/api/v1/internal/banner?application_key={appKey}
            {envKey ? `&environment_key=${envKey}` : ""}
          </code>
        </p>
      </section>

      {raw && (
        <section className="space-y-2" aria-labelledby="embed-json">
          <h2 id="embed-json" className="font-display text-lg font-semibold text-ink">
            Public JSON
          </h2>
          <pre className="mh-panel overflow-x-auto p-4 text-xs text-ink-700">{raw}</pre>
        </section>
      )}
    </div>
  );
}
