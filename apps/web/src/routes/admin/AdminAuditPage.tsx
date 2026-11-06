import { useEffect, useState } from "react";
import { api, ApiError } from "@/api/client";

type AuditRow = {
  id: string;
  actor_id?: string | null;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  summary: Record<string, unknown>;
  at?: string | null;
};

export function AdminAuditPage() {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [q, setQ] = useState("");
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    const params = new URLSearchParams();
    params.set("limit", "100");
    if (q) params.set("q", q);
    if (action) params.set("action", action);
    if (entityType) params.set("entity_type", entityType);
    setRows(await api.adminAudit(params));
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof ApiError ? e.detail : "Load failed"));
  }, []);

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Audit & activity</h2>
        <p className="mt-1 text-sm text-ink-600">
          Immutable historical evidence for publications, imports, permission changes, and admin
          actions. Searchable by action, entity type, and free text.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <input
            className="mh-input w-48"
            placeholder="Search text…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <input
            className="mh-input w-40"
            placeholder="Action contains…"
            value={action}
            onChange={(e) => setAction(e.target.value)}
          />
          <input
            className="mh-input w-40"
            placeholder="Entity type…"
            value={entityType}
            onChange={(e) => setEntityType(e.target.value)}
          />
          <button type="button" className="mh-btn-ghost" onClick={() => void reload()}>
            Search
          </button>
        </div>
        <ul className="mt-4 divide-y divide-ink-100 text-sm">
          {rows.length === 0 && <li className="py-6 text-ink-500">No audit rows match.</li>}
          {rows.map((r) => (
            <li key={r.id} className="py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="font-medium text-ink-950">
                  {r.action}{" "}
                  <span className="font-normal text-ink-500">
                    on {r.entity_type}
                    {r.entity_id ? `:${r.entity_id}` : ""}
                  </span>
                </div>
                <div className="text-xs text-ink-500">{r.at}</div>
              </div>
              <div className="mt-1 text-xs text-ink-500">
                actor {r.actor_id || "system"}
              </div>
              {r.summary && Object.keys(r.summary).length > 0 && (
                <pre className="mt-2 overflow-auto rounded bg-ink-50 p-2 text-xs text-ink-700">
                  {JSON.stringify(r.summary, null, 2)}
                </pre>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
