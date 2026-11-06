import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Application, type Environment } from "@/api/client";
import { useAuth } from "@/features/auth/AuthContext";

export function CatalogPage() {
  const { user } = useAuth();
  const canWrite =
    user?.roles.some((r) =>
      ["publisher", "application_owner", "platform_administrator"].includes(r),
    ) ?? false;

  const [apps, setApps] = useState<Application[]>([]);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [envA, setEnvA] = useState("");
  const [envAName, setEnvAName] = useState("");
  const [envB, setEnvB] = useState("");
  const [envBName, setEnvBName] = useState("");

  async function load(search?: string) {
    setLoading(true);
    setError(null);
    try {
      const [a, e] = await Promise.all([api.applications(search), api.environments()]);
      setApps(a);
      setEnvs(e);
      if (!envA && e[0]) setEnvA(e[0].id);
      if (!envB && e[1]) setEnvB(e[1].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load catalog");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const environments = [];
      if (envA && envAName) environments.push({ environment_id: envA, display_name: envAName });
      if (envB && envBName) environments.push({ environment_id: envB, display_name: envBName });
      await api.createApplication({ key, name, description, environments });
      setKey("");
      setName("");
      setDescription("");
      setEnvAName("");
      setEnvBName("");
      await load(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-semibold text-ink-950">Application catalog</h1>
        <p className="mt-1 text-sm text-ink-600">
          Applications, environments with per-app display names, and ownership.
        </p>
      </div>

      <div className="flex gap-2">
        <input
          className="mh-input max-w-md"
          placeholder="Search applications…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void load(q);
          }}
        />
        <button type="button" className="mh-btn-ghost" onClick={() => void load(q)}>
          Search
        </button>
      </div>

      {error && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
          {error}
        </p>
      )}
      {loading && <p className="text-sm text-ink-500">Loading…</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="mh-panel p-5">
          <h2 className="font-display text-xl font-semibold">Applications</h2>
          {apps.length === 0 && !loading ? (
            <p className="mt-4 text-sm text-ink-500">No applications match.</p>
          ) : (
            <ul className="mt-3 divide-y divide-ink-100">
              {apps.map((a) => (
                <li key={a.id} className="py-3">
                  <Link to={`/catalog/${a.id}`} className="font-semibold hover:underline">
                    {a.name}
                  </Link>
                  <p className="text-xs text-ink-500">
                    {a.key} · {a.status}
                  </p>
                  <p className="mt-1 text-sm text-ink-600">
                    Envs:{" "}
                    {a.environments.map((ae) => ae.display_name).join(", ") || "none"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        {canWrite && (
          <section className="mh-panel p-5">
            <h2 className="font-display text-xl font-semibold">Create application</h2>
            <form className="mt-4 space-y-3" onSubmit={onCreate}>
              <div>
                <label className="mh-label" htmlFor="key">
                  Key
                </label>
                <input id="key" className="mh-input" value={key} onChange={(e) => setKey(e.target.value)} required />
              </div>
              <div>
                <label className="mh-label" htmlFor="name">
                  Name
                </label>
                <input id="name" className="mh-input" value={name} onChange={(e) => setName(e.target.value)} required />
              </div>
              <div>
                <label className="mh-label" htmlFor="desc">
                  Description
                </label>
                <textarea
                  id="desc"
                  className="mh-input"
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <div>
                  <label className="mh-label">Env A</label>
                  <select className="mh-input" value={envA} onChange={(e) => setEnvA(e.target.value)}>
                    {envs.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.key}
                      </option>
                    ))}
                  </select>
                  <input
                    className="mh-input mt-2"
                    placeholder="Per-app display name"
                    value={envAName}
                    onChange={(e) => setEnvAName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="mh-label">Env B</label>
                  <select className="mh-input" value={envB} onChange={(e) => setEnvB(e.target.value)}>
                    {envs.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.key}
                      </option>
                    ))}
                  </select>
                  <input
                    className="mh-input mt-2"
                    placeholder="Different display name"
                    value={envBName}
                    onChange={(e) => setEnvBName(e.target.value)}
                  />
                </div>
              </div>
              <button className="mh-btn" type="submit">
                Create
              </button>
            </form>
          </section>
        )}
      </div>
    </div>
  );
}
