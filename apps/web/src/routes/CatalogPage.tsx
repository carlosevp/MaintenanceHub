import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Application, type Environment } from "@/api/client";
import { useAuth } from "@/features/auth/AuthContext";

type EnvAssignment = {
  environment_id: string;
  display_name: string;
};

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
  const [selectedEnvIds, setSelectedEnvIds] = useState<string[]>([]);
  const [displayNames, setDisplayNames] = useState<Record<string, string>>({});

  const assignmentPreview = useMemo(() => {
    return selectedEnvIds
      .map((id) => {
        const env = envs.find((e) => e.id === id);
        if (!env) return null;
        const label = displayNames[id]?.trim() || `${name || "App"}-${env.key}`;
        return `${label} (${env.key})`;
      })
      .filter(Boolean);
  }, [selectedEnvIds, envs, displayNames, name]);

  async function load(search?: string) {
    setLoading(true);
    setError(null);
    try {
      const [a, e] = await Promise.all([api.applications(search), api.environments()]);
      setApps(a);
      setEnvs(e);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load catalog");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function toggleEnv(id: string) {
    setSelectedEnvIds((prev) => {
      if (prev.includes(id)) {
        const next = prev.filter((x) => x !== id);
        setDisplayNames((dn) => {
          const copy = { ...dn };
          delete copy[id];
          return copy;
        });
        return next;
      }
      const env = envs.find((e) => e.id === id);
      if (env && !displayNames[id]) {
        setDisplayNames((dn) => ({
          ...dn,
          [id]: name ? `${name}-${env.key}` : env.name,
        }));
      }
      return [...prev, id];
    });
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!selectedEnvIds.length) {
      setError("Select at least one environment from the catalog.");
      return;
    }
    try {
      const environments: EnvAssignment[] = selectedEnvIds.map((environment_id) => {
        const env = envs.find((x) => x.id === environment_id);
        return {
          environment_id,
          display_name:
            displayNames[environment_id]?.trim() ||
            `${name}-${env?.key || "ENV"}`,
        };
      });
      await api.createApplication({ key, name, description, environments });
      setKey("");
      setName("");
      setDescription("");
      setSelectedEnvIds([]);
      setDisplayNames({});
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
          Applications attach to environment definitions from the admin catalog. An environment
          definition (e.g. INT) is not the same as a deployment instance (e.g. Claims/INT).
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
                    Deployments:{" "}
                    {a.environments
                      .map((ae) =>
                        ae.environment
                          ? `${ae.display_name} (${ae.environment.key})`
                          : ae.display_name,
                      )
                      .join(", ") || "none"}
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
                <input
                  id="key"
                  className="mh-input"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="mh-label" htmlFor="name">
                  Name
                </label>
                <input
                  id="name"
                  className="mh-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
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

              <fieldset>
                <legend className="mh-label">Environments for this application</legend>
                <p className="mt-1 text-xs text-ink-500">
                  Choose catalog definitions (DEV, INT, QA…). Optionally set a per-app deployment
                  display name.
                </p>
                {envs.length === 0 ? (
                  <p className="mt-2 text-sm text-ink-500">
                    No active environments. Ask an administrator to add them under Administration.
                  </p>
                ) : (
                  <ul className="mt-2 max-h-64 space-y-2 overflow-y-auto">
                    {envs.map((env) => {
                      const checked = selectedEnvIds.includes(env.id);
                      return (
                        <li
                          key={env.id}
                          className="rounded-lg border border-ink-100 px-3 py-2 text-sm"
                        >
                          <label className="flex items-start gap-2">
                            <input
                              type="checkbox"
                              className="mt-1"
                              checked={checked}
                              onChange={() => toggleEnv(env.id)}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="font-medium">
                                {env.name} ({env.key})
                              </span>
                              {env.description && (
                                <span className="mt-0.5 block text-xs text-ink-500">
                                  {env.description}
                                </span>
                              )}
                              {checked && (
                                <input
                                  className="mh-input mt-2"
                                  placeholder={`Deployment name (e.g. ${name || "App"}-${env.key})`}
                                  value={displayNames[env.id] || ""}
                                  onChange={(e) =>
                                    setDisplayNames((dn) => ({
                                      ...dn,
                                      [env.id]: e.target.value,
                                    }))
                                  }
                                  aria-label={`Display name for ${env.key}`}
                                />
                              )}
                            </span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </fieldset>

              {assignmentPreview.length > 0 && (
                <p className="rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-xs text-ink-700">
                  Will create deployments: {assignmentPreview.join(" · ")}
                </p>
              )}

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
