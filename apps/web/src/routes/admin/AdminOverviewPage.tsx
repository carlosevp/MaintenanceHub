import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "@/api/client";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border border-ink-100 bg-ink-50/60 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-ink-500">{label}</div>
      <div className="mt-1 font-display text-2xl font-semibold text-ink-950">{value}</div>
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export function AdminOverviewPage() {
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [secrets, setSecrets] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [o, s] = await Promise.all([api.adminOverview(), api.adminSecretsStatus()]);
        setOverview(o);
        setSecrets(s);
      } catch (e) {
        setError(e instanceof ApiError ? e.detail : "Failed to load overview");
      }
    })();
  }, []);

  if (error) {
    return <div className="mh-panel p-6 text-sm text-red-700">{error}</div>;
  }
  if (!overview || !secrets) {
    return <div className="py-12 text-center text-sm text-ink-500">Loading administration overview…</div>;
  }

  const catalog = (overview.catalog || {}) as Record<string, number>;
  const jobs = (overview.jobs || {}) as Record<string, number>;
  const sn = (overview.servicenow || {}) as Record<string, unknown>;
  const deliveries = (overview.deliveries || {}) as Record<string, number>;
  const integrations = (overview.integrations || {}) as Record<string, unknown>;
  const openshift = (secrets.openshift_only || []) as string[];

  return (
    <div className="space-y-6">
      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Platform snapshot</h2>
        <p className="mt-1 text-sm text-ink-600">
          As of {String(overview.as_of)}. Auth mode: <code>{String(integrations.auth_mode)}</code>.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Applications" value={catalog.applications ?? 0} />
          <Stat label="Dependencies" value={catalog.dependencies ?? 0} />
          <Stat label="Users" value={Number(overview.users) || 0} />
          <Stat label="App grants" value={Number(overview.grants) || 0} />
          <Stat label="SN unmatched" value={Number(sn.unmatched_open) || 0} hint="Open CI mismatches" />
          <Stat label="Failed jobs" value={(jobs.failed || 0) + (jobs.dead || 0)} />
          <Stat label="Failed deliveries" value={deliveries.failed ?? 0} />
          <Stat
            label="SMTP / Bridge / SN"
            value={`${integrations.smtp_enabled ? "on" : "off"} / ${
              integrations.bridge_enabled ? "on" : "off"
            } / ${integrations.servicenow_enabled ? "on" : "off"}`}
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-2 text-sm">
          <Link className="mh-btn-ghost" to="/admin/catalog">
            Manage catalog
          </Link>
          <Link className="mh-btn-ghost" to="/admin/servicenow">
            ServiceNow & CSV
          </Link>
          <Link className="mh-btn-ghost" to="/admin/jobs">
            Jobs & delivery
          </Link>
        </div>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Secrets & deployment configuration</h2>
        <p className="mt-2 text-sm text-ink-700">{String(secrets.deployment_note)}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-teal-200 bg-teal-50/70 px-4 py-3 text-sm text-teal-950">
            <strong>Runtime-editable (UI/API)</strong>
            <ul className="mt-2 list-inside list-disc text-xs">
              {((secrets.runtime_editable as string[]) || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-950">
            <strong>OpenShift Secret / deploy-only</strong>
            <p className="mt-1 text-xs">Never returned as values: {openshift.join(", ")}</p>
            <ul className="mt-2 list-inside list-disc text-xs">
              {((secrets.deployment_only as string[]) || []).slice(0, 12).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {(["smtp", "bridge", "servicenow", "auth"] as const).map((key) => {
            const block = (secrets[key] || {}) as Record<string, unknown>;
            return (
              <div key={key} className="rounded-lg border border-ink-100 p-4">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">{key}</h3>
                <dl className="mt-2 space-y-1 text-sm text-ink-800">
                  {Object.entries(block).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-4">
                      <dt className="text-ink-500">{k}</dt>
                      <dd className="text-right font-mono text-xs">
                        {typeof v === "boolean" ? (v ? "yes" : "no") : String(v ?? "—")}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
