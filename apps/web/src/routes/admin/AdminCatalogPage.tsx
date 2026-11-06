import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, ApiError, type Application, type Environment, type InfraComponent } from "@/api/client";

type Dep = {
  id: string;
  from_type: string;
  from_id: string;
  to_type: string;
  to_id: string;
  from_environment_id?: string | null;
  to_environment_id?: string | null;
  dependency_kind: string;
  origin: string;
  updated_at?: string | null;
  description: string;
};

export function AdminCatalogPage() {
  const [apps, setApps] = useState<Application[]>([]);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [infra, setInfra] = useState<InfraComponent[]>([]);
  const [deps, setDeps] = useState<Dep[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const [consumerApp, setConsumerApp] = useState("");
  const [providerType, setProviderType] = useState("application");
  const [providerId, setProviderId] = useState("");
  const [fromEnv, setFromEnv] = useState("");
  const [toEnv, setToEnv] = useState("");

  const [infraKey, setInfraKey] = useState("");
  const [infraName, setInfraName] = useState("");
  const [infraKind, setInfraKind] = useState("database");

  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of apps) m.set(a.id, a.name);
    for (const i of infra) m.set(i.id, i.name);
    return m;
  }, [apps, infra]);

  async function reload(filter = q) {
    const [a, e, i, d] = await Promise.all([
      api.applications(),
      api.environments(),
      api.infraComponents(),
      api.adminDependencies(filter || undefined),
    ]);
    setApps(a);
    setEnvs(e);
    setInfra(i);
    setDeps(d as Dep[]);
  }

  useEffect(() => {
    void reload().catch((err) =>
      setError(err instanceof ApiError ? err.detail : "Failed to load catalog"),
    );
  }, []);

  async function onCreateDep(ev: FormEvent) {
    ev.preventDefault();
    setError(null);
    setMsg(null);
    if (!consumerApp || !providerId) {
      setError("Select consumer application and provider.");
      return;
    }
    if (providerType === "application" && consumerApp === providerId && !fromEnv && !toEnv) {
      setError("Self-reference: Consumer cannot depend on itself.");
      return;
    }
    try {
      const res = await api.adminCreateDependency({
        from_type: "application",
        from_id: consumerApp,
        to_type: providerType,
        to_id: providerId,
        dependency_kind: "depends_on",
        from_environment_id: fromEnv || null,
        to_environment_id: toEnv || null,
      });
      setMsg(
        res.cycle_warning
          ? "Created with cycle warning (reverse edge already exists)."
          : "Dependency created: Consumer depends on Provider.",
      );
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Create failed");
    }
  }

  async function onDeleteDep(id: string) {
    if (!window.confirm("Delete this dependency edge? This does not cascade to CSV absences.")) return;
    try {
      await api.adminDeleteDependency(id);
      setMsg("Dependency removed.");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Delete failed");
    }
  }

  async function onCreateInfra(ev: FormEvent) {
    ev.preventDefault();
    try {
      await api.adminCreateInfra({ key: infraKey, name: infraName, kind: infraKind });
      setInfraKey("");
      setInfraName("");
      setMsg("Infrastructure component created.");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Infra create failed");
    }
  }

  const providerOptions =
    providerType === "infra_component"
      ? infra.map((i) => ({ id: i.id, label: `${i.name} (${i.key})` }))
      : apps.map((a) => ({ id: a.id, label: `${a.name} (${a.key})` }));

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}
      {msg && <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">{msg}</div>}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Dependency editor</h2>
        <p className="mt-1 text-sm text-ink-600">
          Direction is always <strong>Consumer depends on Provider</strong>. Duplicates and
          self-references are rejected. Partial CSV imports never delete missing edges.
        </p>
        <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={onCreateDep}>
          <div>
            <label className="mh-label">Consumer (application)</label>
            <select className="mh-input" value={consumerApp} onChange={(e) => setConsumerApp(e.target.value)} required>
              <option value="">Select…</option>
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mh-label">Consumer environment (optional)</label>
            <select className="mh-input" value={fromEnv} onChange={(e) => setFromEnv(e.target.value)}>
              <option value="">Any / unspecified</option>
              {envs.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.key}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mh-label">Provider type</label>
            <select className="mh-input" value={providerType} onChange={(e) => { setProviderType(e.target.value); setProviderId(""); }}>
              <option value="application">Application</option>
              <option value="infra_component">Infrastructure</option>
            </select>
          </div>
          <div>
            <label className="mh-label">Provider</label>
            <select className="mh-input" value={providerId} onChange={(e) => setProviderId(e.target.value)} required>
              <option value="">Select…</option>
              {providerOptions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mh-label">Provider environment (optional)</label>
            <select className="mh-input" value={toEnv} onChange={(e) => setToEnv(e.target.value)}>
              <option value="">Any / unspecified</option>
              {envs.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.key}
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end">
            <button className="mh-btn" type="submit">
              Add relationship
            </button>
          </div>
        </form>
      </section>

      <section className="mh-panel p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-semibold">Dependency list</h2>
            <p className="text-sm text-ink-600">{deps.length} relationships</p>
          </div>
          <div className="flex gap-2">
            <input
              className="mh-input w-56"
              placeholder="Filter…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <button type="button" className="mh-btn-ghost" onClick={() => void reload(q)}>
              Search
            </button>
          </div>
        </div>
        <ul className="mt-4 divide-y divide-ink-100">
          {deps.length === 0 && <li className="py-6 text-sm text-ink-500">No dependencies match.</li>}
          {deps.map((d) => (
            <li key={d.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0 text-sm">
                <div className="font-medium text-ink-950">
                  {nameById.get(d.from_id) || d.from_id}
                  <span className="mx-2 text-ink-400">depends on</span>
                  {nameById.get(d.to_id) || d.to_id}
                </div>
                <div className="mt-1 text-xs text-ink-500">
                  {d.from_type} → {d.to_type} · origin {d.origin} · {d.dependency_kind}
                  {d.updated_at ? ` · updated ${d.updated_at}` : ""}
                </div>
              </div>
              <button type="button" className="mh-btn-ghost text-xs" onClick={() => void onDeleteDep(d.id)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Infrastructure components</h2>
        <form className="mt-4 grid gap-3 md:grid-cols-4" onSubmit={onCreateInfra}>
          <div>
            <label className="mh-label">Key</label>
            <input className="mh-input" value={infraKey} onChange={(e) => setInfraKey(e.target.value)} required />
          </div>
          <div>
            <label className="mh-label">Name</label>
            <input className="mh-input" value={infraName} onChange={(e) => setInfraName(e.target.value)} required />
          </div>
          <div>
            <label className="mh-label">Kind</label>
            <input className="mh-input" value={infraKind} onChange={(e) => setInfraKind(e.target.value)} />
          </div>
          <div className="flex items-end">
            <button className="mh-btn" type="submit">
              Create infra
            </button>
          </div>
        </form>
        <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {infra.map((i) => (
            <li key={i.id} className="rounded-lg border border-ink-100 px-3 py-2 text-sm">
              <div className="font-medium">{i.name}</div>
              <div className="text-xs text-ink-500">
                {i.key} · {i.kind || "—"}
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-ink-500">
          Applications: {apps.length}. Use Catalog pages for ownership, tags, and CI links; this
          workspace focuses on dependency relationships and infra create.
        </p>
      </section>
    </div>
  );
}
