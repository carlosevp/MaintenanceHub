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
  from_environment_key?: string | null;
  to_environment_key?: string | null;
  consumer_label?: string;
  provider_label?: string;
  summary?: string;
  cross_environment?: boolean;
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

  const [envKey, setEnvKey] = useState("");
  const [envName, setEnvName] = useState("");
  const [envDescription, setEnvDescription] = useState("");
  const [envSort, setEnvSort] = useState(100);
  const [editingEnvId, setEditingEnvId] = useState<string | null>(null);

  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const a of apps) m.set(a.id, a.name);
    for (const i of infra) m.set(i.id, i.name);
    return m;
  }, [apps, infra]);

  const envById = useMemo(() => {
    const m = new Map<string, Environment>();
    for (const e of envs) m.set(e.id, e);
    return m;
  }, [envs]);

  const dependencyPreview = useMemo(() => {
    const consumer = nameById.get(consumerApp) || (consumerApp ? "Consumer" : "…");
    const provider =
      nameById.get(providerId) ||
      (providerId ? "Provider" : "…");
    const cEnv = fromEnv ? envById.get(fromEnv)?.key : null;
    const pEnv = toEnv ? envById.get(toEnv)?.key : null;
    const left = cEnv ? `${consumer} ${cEnv}` : `${consumer} (all environments)`;
    const right = pEnv ? `${provider} ${pEnv}` : `${provider} (all environments)`;
    return `${left} → depends on → ${right}`;
  }, [consumerApp, providerId, fromEnv, toEnv, nameById, envById]);

  async function reload(filter = q) {
    const [a, e, i, d] = await Promise.all([
      api.applications(),
      api.environments(true),
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
      const summary =
        typeof res.summary === "string" ? res.summary : dependencyPreview;
      setMsg(
        res.cycle_warning
          ? `Created with cycle warning: ${summary}`
          : `Dependency created: ${summary}`,
      );
      setFromEnv("");
      setToEnv("");
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

  function startEditEnv(env: Environment) {
    setEditingEnvId(env.id);
    setEnvKey(env.key);
    setEnvName(env.name);
    setEnvDescription(env.description || "");
    setEnvSort(env.sort_order);
  }

  function resetEnvForm() {
    setEditingEnvId(null);
    setEnvKey("");
    setEnvName("");
    setEnvDescription("");
    setEnvSort(100);
  }

  async function onSaveEnv(ev: FormEvent) {
    ev.preventDefault();
    setError(null);
    setMsg(null);
    const code = envKey.trim().toUpperCase();
    if (!editingEnvId) {
      if (!code) {
        setError("Environment code is required.");
        return;
      }
      const duplicate = envs.find((e) => e.key.toUpperCase() === code);
      if (duplicate) {
        setError(
          `Environment code "${code}" already exists (${duplicate.name}). Choose a unique code.`,
        );
        return;
      }
    }
    try {
      if (editingEnvId) {
        await api.updateEnvironment(editingEnvId, {
          name: envName,
          description: envDescription || null,
          sort_order: envSort,
        });
        setMsg("Environment updated. Existing application associations are unchanged.");
      } else {
        await api.createEnvironment({
          key: code,
          name: envName,
          description: envDescription || null,
          sort_order: envSort,
          is_active: true,
        });
        setMsg("Environment created.");
      }
      resetEnvForm();
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Environment save failed");
    }
  }

  async function onDeactivateEnv(id: string) {
    if (
      !window.confirm(
        "Deactivate this environment definition? Prefer deactivate over delete so historical records keep stable identities.",
      )
    ) {
      return;
    }
    try {
      await api.deactivateEnvironment(id);
      setMsg("Environment deactivated.");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Deactivate failed");
    }
  }

  async function onReactivateEnv(id: string) {
    try {
      await api.updateEnvironment(id, { is_active: true });
      setMsg("Environment reactivated.");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Reactivate failed");
    }
  }

  const providerOptions =
    providerType === "infra_component"
      ? infra.map((i) => ({ id: i.id, label: `${i.name} (${i.key})` }))
      : apps.map((a) => ({ id: a.id, label: `${a.name} (${a.key})` }));

  const activeEnvs = envs.filter((e) => e.is_active !== false);

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}
      {msg && <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">{msg}</div>}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Environment catalog</h2>
        <p className="mt-1 text-sm text-ink-600">
          Manage environment <em>definitions</em> (DEV, INT, QA, UAT, PROD, PERF, DR, custom). These
          are not application deployment instances — assign definitions to apps when creating or
          editing applications.
        </p>
        <form
          key={editingEnvId ? `edit-${editingEnvId}` : "create-env"}
          className="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-5"
          onSubmit={onSaveEnv}
          autoComplete="off"
        >
          <div>
            <label className="mh-label" htmlFor="env-code">
              Code
            </label>
            <input
              id="env-code"
              name="env_code_new"
              className="mh-input"
              value={envKey}
              onChange={(e) => setEnvKey(e.target.value.toUpperCase())}
              placeholder="e.g. PERF"
              required={!editingEnvId}
              disabled={Boolean(editingEnvId)}
              autoComplete="off"
            />
          </div>
          <div>
            <label className="mh-label" htmlFor="env-name">
              Display name
            </label>
            <input
              id="env-name"
              name="env_display_name_new"
              className="mh-input"
              value={envName}
              onChange={(e) => setEnvName(e.target.value)}
              placeholder="e.g. Performance"
              required
              autoComplete="off"
            />
          </div>
          <div>
            <label className="mh-label" htmlFor="env-desc">
              Description
            </label>
            <input
              id="env-desc"
              className="mh-input"
              value={envDescription}
              onChange={(e) => setEnvDescription(e.target.value)}
              placeholder="Optional"
              autoComplete="off"
            />
          </div>
          <div>
            <label className="mh-label" htmlFor="env-sort">
              Sort order
            </label>
            <input
              id="env-sort"
              className="mh-input"
              type="number"
              value={envSort}
              onChange={(e) => setEnvSort(Number(e.target.value))}
            />
          </div>
          <div className="flex items-end gap-2">
            <button className="mh-btn" type="submit">
              {editingEnvId ? "Save changes" : "Add environment"}
            </button>
            {editingEnvId && (
              <button className="mh-btn-ghost" type="button" onClick={resetEnvForm}>
                Cancel edit
              </button>
            )}
          </div>
        </form>
        <p className="mt-2 text-xs text-ink-500">
          {editingEnvId
            ? `Editing ${envKey}. Code is immutable; application deployments that use this definition stay linked.`
            : "New environment form starts empty. Codes must be unique. Existing app↔environment associations are never changed by creating a definition."}
        </p>
        <ul className="mt-4 divide-y divide-ink-100">
          {envs.map((env) => (
            <li key={env.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
              <div>
                <div className="font-medium">
                  {env.name}{" "}
                  <span className="text-ink-500">({env.key})</span>
                  {env.is_active === false && (
                    <span className="ml-2 rounded bg-ink-100 px-1.5 py-0.5 text-xs text-ink-600">
                      inactive
                    </span>
                  )}
                </div>
                <div className="text-xs text-ink-500">
                  sort {env.sort_order}
                  {env.description ? ` · ${env.description}` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <button type="button" className="mh-btn-ghost text-xs" onClick={() => startEditEnv(env)}>
                  Edit
                </button>
                {env.is_active === false ? (
                  <button
                    type="button"
                    className="mh-btn-ghost text-xs"
                    onClick={() => void onReactivateEnv(env.id)}
                  >
                    Reactivate
                  </button>
                ) : (
                  <button
                    type="button"
                    className="mh-btn-ghost text-xs"
                    onClick={() => void onDeactivateEnv(env.id)}
                  >
                    Deactivate
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Dependency editor</h2>
        <p className="mt-1 text-sm text-ink-600">
          <strong>Consumer</strong> (depends on) → <strong>Provider</strong> (dependency). If the
          provider is affected by maintenance, the consumer may also be impacted. Environments on
          each side are independent — cross-environment edges are supported (e.g. Claims DEV depends
          on Member API INT).
        </p>
        <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={onCreateDep}>
          <div>
            <label className="mh-label">Consumer application</label>
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
            <label className="mh-label">Consumer environment</label>
            <select className="mh-input" value={fromEnv} onChange={(e) => setFromEnv(e.target.value)}>
              <option value="">All environments (agnostic)</option>
              {activeEnvs.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name} ({e.key})
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-ink-500">
              Blank means the relationship applies in every consumer environment — not that the
              environment is unknown.
            </p>
          </div>
          <div>
            <label className="mh-label">Provider type</label>
            <select className="mh-input" value={providerType} onChange={(e) => { setProviderType(e.target.value); setProviderId(""); }}>
              <option value="application">Application</option>
              <option value="infra_component">Infrastructure / service</option>
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
            <label className="mh-label">Provider environment</label>
            <select className="mh-input" value={toEnv} onChange={(e) => setToEnv(e.target.value)}>
              <option value="">All environments (agnostic)</option>
              {activeEnvs.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.name} ({e.key})
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-ink-500">
              Blank matches provider maintenance in any environment. Pin a code when only one
              provider environment should trigger impact.
            </p>
          </div>
          <div className="flex flex-col justify-end gap-2">
            <p className="rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-xs text-ink-700">
              {dependencyPreview}
              {fromEnv && toEnv && fromEnv !== toEnv
                ? " · Cross-environment dependency"
                : ""}
            </p>
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
                  {d.summary ||
                    `${d.consumer_label || nameById.get(d.from_id) || d.from_id} → depends on → ${
                      d.provider_label || nameById.get(d.to_id) || d.to_id
                    }`}
                </div>
                <div className="mt-1 text-xs text-ink-500">
                  Consumer depends on Provider
                  {d.cross_environment ? " · cross-environment" : ""}
                  {` · origin ${d.origin}`}
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
          Applications: {apps.length}. Environment definitions: {envs.length}. Use Catalog pages for
          ownership, tags, and CI links.
        </p>
      </section>
    </div>
  );
}
