import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Application } from "@/api/client";

export function CatalogDetailPage() {
  const { id } = useParams();
  const [app, setApp] = useState<Application | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      try {
        setApp(await api.application(id));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Not found");
      }
    })();
  }, [id]);

  if (error) {
    return (
      <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
        {error}
      </p>
    );
  }
  if (!app) return <p className="text-sm text-ink-500">Loading…</p>;

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Link to="/catalog" className="text-sm font-medium text-accent hover:underline">
        ← Catalog
      </Link>
      <div className="mh-panel p-6">
        <h1 className="font-display text-3xl font-semibold">{app.name}</h1>
        <p className="mt-1 text-sm text-ink-500">
          {app.key} · {app.status}
        </p>
        {app.description && <p className="mt-4 text-ink-800">{app.description}</p>}
        <h2 className="mt-6 font-display text-lg font-semibold">Environments</h2>
        <ul className="mt-2 space-y-2">
          {app.environments.map((ae) => (
            <li key={ae.id} className="rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-sm">
              <span className="font-semibold">{ae.display_name}</span>
              {ae.environment && (
                <span className="text-ink-500">
                  {" "}
                  (global {ae.environment.key} — {ae.environment.name})
                </span>
              )}
            </li>
          ))}
        </ul>
        <Link
          className="mh-btn mt-6 inline-flex"
          to={`/?` /* dashboard filter via state not wired; deep link to events */}
          onClick={(e) => {
            e.preventDefault();
            window.location.href = `/`;
          }}
        >
          View on dashboard
        </Link>
      </div>
    </div>
  );
}
