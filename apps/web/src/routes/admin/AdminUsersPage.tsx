import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, ApiError, type Application } from "@/api/client";

type UserRow = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  roles: string[];
};

type Grant = {
  id: string;
  user_id?: string | null;
  directory_group?: string | null;
  application_id: string;
  role: string;
};

type RoleMap = {
  id: string;
  directory_group: string;
  role: string;
  application_id?: string | null;
};

type Cred = {
  id: string;
  name: string;
  client_id: string;
  scopes: string[];
  revoked_at?: string | null;
};

export function AdminUsersPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [apps, setApps] = useState<Application[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [maps, setMaps] = useState<RoleMap[]>([]);
  const [creds, setCreds] = useState<Cred[]>([]);
  const [q, setQ] = useState("");
  const [userId, setUserId] = useState("");
  const [appId, setAppId] = useState("");
  const [role, setRole] = useState("publisher");
  const [group, setGroup] = useState("mh-publishers");
  const [mapRole, setMapRole] = useState("publisher");
  const [credName, setCredName] = useState("");
  const [onceSecret, setOnceSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const appName = useMemo(() => new Map(apps.map((a) => [a.id, a.name])), [apps]);
  const userName = useMemo(() => new Map(users.map((u) => [u.id, u.email])), [users]);

  async function reload(filter = q) {
    const [u, a, g, m, c] = await Promise.all([
      api.adminUsers(filter || undefined),
      api.applications(),
      api.adminGrants(),
      api.adminRoleMappings(),
      api.adminServiceCredentials(),
    ]);
    setUsers(u);
    setApps(a);
    setGrants(g);
    setMaps(m);
    setCreds(c);
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof ApiError ? e.detail : "Load failed"));
  }, []);

  async function addGrant(ev: FormEvent) {
    ev.preventDefault();
    try {
      await api.adminCreateGrant({ user_id: userId, application_id: appId, role });
      setMsg("Grant created (audited).");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Grant failed");
    }
  }

  async function addMap(ev: FormEvent) {
    ev.preventDefault();
    try {
      await api.adminCreateRoleMapping({ directory_group: group, role: mapRole });
      setMsg("Directory group mapping created. Live AD requires deployment-time IdP.");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Mapping failed");
    }
  }

  async function createCred(ev: FormEvent) {
    ev.preventDefault();
    try {
      const r = await api.adminCreateServiceCred({ name: credName, scopes: ["banner:read"] });
      setOnceSecret(`${r.client_id} / ${r.client_secret}`);
      setCredName("");
      setMsg("Service credential created — secret shown once only.");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Credential create failed");
    }
  }

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}
      {msg && <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">{msg}</div>}
      {onceSecret && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          One-time secret (copy now): <code className="break-all">{onceSecret}</code>
        </div>
      )}

      <section className="mh-panel p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-semibold">Users</h2>
            <p className="text-sm text-ink-600">
              Local-dev demo users. No fake production AD login — OIDC/LDAP bind is deployment-time.
            </p>
          </div>
          <div className="flex gap-2">
            <input className="mh-input w-48" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" />
            <button type="button" className="mh-btn-ghost" onClick={() => void reload(q)}>
              Search
            </button>
          </div>
        </div>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {users.map((u) => (
            <li key={u.id} className="flex flex-wrap justify-between gap-2 py-2">
              <div>
                <div className="font-medium">{u.display_name}</div>
                <div className="text-xs text-ink-500">{u.email}</div>
              </div>
              <div className="text-xs text-ink-600">{u.roles.join(", ") || "—"}</div>
            </li>
          ))}
        </ul>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Application grants</h2>
        <form className="mt-4 grid gap-3 md:grid-cols-4" onSubmit={addGrant}>
          <div>
            <label className="mh-label">User</label>
            <select className="mh-input" value={userId} onChange={(e) => setUserId(e.target.value)} required>
              <option value="">Select…</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mh-label">Application</label>
            <select className="mh-input" value={appId} onChange={(e) => setAppId(e.target.value)} required>
              <option value="">Select…</option>
              {apps.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mh-label">Role</label>
            <select className="mh-input" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="publisher">publisher</option>
              <option value="application_owner">application_owner</option>
            </select>
          </div>
          <div className="flex items-end">
            <button className="mh-btn" type="submit">
              Grant
            </button>
          </div>
        </form>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {grants.map((g) => (
            <li key={g.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                {g.user_id ? userName.get(g.user_id) || g.user_id : g.directory_group} →{" "}
                {appName.get(g.application_id) || g.application_id} ({g.role})
              </div>
              <button
                type="button"
                className="mh-btn-ghost text-xs"
                onClick={() =>
                  void api.adminDeleteGrant(g.id).then(() => reload()).catch((e) =>
                    setError(e instanceof ApiError ? e.detail : "Delete failed"),
                  )
                }
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Directory group → role maps</h2>
        <p className="mt-1 text-sm text-ink-600">
          Applied when OIDC/LDAP is configured. Surfaces prepare for live AD; local_dev uses seeded
          maps for demo only.
        </p>
        <form className="mt-4 grid gap-3 md:grid-cols-3" onSubmit={addMap}>
          <div>
            <label className="mh-label">Directory group</label>
            <input className="mh-input" value={group} onChange={(e) => setGroup(e.target.value)} required />
          </div>
          <div>
            <label className="mh-label">Role</label>
            <select className="mh-input" value={mapRole} onChange={(e) => setMapRole(e.target.value)}>
              <option value="viewer">viewer</option>
              <option value="publisher">publisher</option>
              <option value="application_owner">application_owner</option>
              <option value="platform_administrator">platform_administrator</option>
            </select>
          </div>
          <div className="flex items-end">
            <button className="mh-btn" type="submit">
              Add mapping
            </button>
          </div>
        </form>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {maps.map((m) => (
            <li key={m.id} className="flex justify-between gap-2 py-2">
              <span>
                {m.directory_group} → {m.role}
              </span>
              <button
                type="button"
                className="mh-btn-ghost text-xs"
                onClick={() =>
                  void api.adminDeleteRoleMapping(m.id).then(() => reload()).catch((e) =>
                    setError(e instanceof ApiError ? e.detail : "Delete failed"),
                  )
                }
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Service credentials</h2>
        <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={createCred}>
          <div>
            <label className="mh-label">Name</label>
            <input className="mh-input" value={credName} onChange={(e) => setCredName(e.target.value)} required />
          </div>
          <button className="mh-btn" type="submit">
            Create (banner:read)
          </button>
        </form>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {creds.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-ink-500">
                  {c.client_id} · {c.scopes.join(", ")}
                  {c.revoked_at ? ` · revoked ${c.revoked_at}` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                {!c.revoked_at && (
                  <>
                    <button
                      type="button"
                      className="mh-btn-ghost text-xs"
                      onClick={() =>
                        void api.adminRotateServiceCred(c.id).then((r) => {
                          setOnceSecret(`${r.client_id} / ${r.client_secret}`);
                          setMsg("Rotated — secret shown once.");
                        })
                      }
                    >
                      Rotate
                    </button>
                    <button
                      type="button"
                      className="mh-btn-ghost text-xs"
                      onClick={() =>
                        void api.adminRevokeServiceCred(c.id).then(() => reload())
                      }
                    >
                      Revoke
                    </button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
