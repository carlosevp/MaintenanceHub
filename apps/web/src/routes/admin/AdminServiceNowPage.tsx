import { FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "@/api/client";

type ImportJob = {
  id: string;
  kind: string;
  filename: string;
  status: string;
  created_at?: string | null;
  committed_at?: string | null;
  result_summary?: Record<string, unknown> | null;
};

type Unmatched = {
  id: string;
  external_id: string;
  reason: string;
  status: string;
  resolved_event_id?: string | null;
};

export function AdminServiceNowPage() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [secrets, setSecrets] = useState<Record<string, unknown> | null>(null);
  const [unmatched, setUnmatched] = useState<Unmatched[]>([]);
  const [imports, setImports] = useState<ImportJob[]>([]);
  const [pollResult, setPollResult] = useState<Record<string, unknown> | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [activeImportId, setActiveImportId] = useState<string | null>(null);
  const [kind, setKind] = useState("cmdb_ci");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function reload() {
    const [s, sec, u, im] = await Promise.all([
      api.adminIntegrations(),
      api.adminSecretsStatus(),
      api.adminSnUnmatched("open"),
      api.adminImports(),
    ]);
    setSettings(s);
    setSecrets(sec);
    setUnmatched(u);
    setImports(im);
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof ApiError ? e.detail : "Load failed"));
  }, []);

  async function testSn() {
    try {
      const r = await api.adminTestIntegration("servicenow");
      setMsg(`Connection test: ${JSON.stringify(r)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Test failed");
    }
  }

  async function dryRun() {
    try {
      const r = await api.adminSnPoll({ dry_run: true });
      setPollResult(r);
      setMsg(`Dry-run fetched ${String(r.fetched ?? 0)} records — no DB writes.`);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Dry-run failed");
    }
  }

  async function pollNow() {
    if (!window.confirm("Enqueue a live/fixture poll-now job?")) return;
    try {
      const r = await api.adminSnPoll({ dry_run: false });
      setPollResult(r);
      setMsg(r.enqueued_job_id ? `Enqueued job ${r.enqueued_job_id}` : "Poll completed.");
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Poll failed");
    }
  }

  async function resolve(id: string, action: string) {
    try {
      await api.adminSnResolve(id, { action });
      setMsg(`Unmatched ${id} → ${action}`);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Resolve failed");
    }
  }

  async function onUpload(ev: FormEvent) {
    ev.preventDefault();
    if (!file) {
      setError("Choose a CSV file.");
      return;
    }
    try {
      const job = await api.adminUploadCsv(file, kind, false);
      setActiveImportId(job.id);
      const p = await api.adminPreviewImport(job.id);
      setPreview(p);
      setMsg(`Uploaded ${job.filename} (${job.kind}). Preview ready — partial ≠ full snapshot.`);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Upload failed");
    }
  }

  async function commitImport() {
    if (!activeImportId) return;
    if (
      !window.confirm(
        "Commit this import? Absent relationships in a partial CSV are never deleted.",
      )
    )
      return;
    try {
      const r = await api.adminCommitImport(activeImportId);
      setMsg(`Committed: ${JSON.stringify(r.result || r)}`);
      setPreview(null);
      setActiveImportId(null);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Commit failed");
    }
  }

  const snSecrets = ((secrets || {}).servicenow || {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}
      {msg && <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">{msg}</div>}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">ServiceNow integration</h2>
        <p className="mt-1 text-sm text-ink-600">
          Read-only poll adapter. Passwords are never shown. Endpoint and schedule come from
          deployment configuration.
        </p>
        {settings && (
          <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
            <div>
              Enabled: <strong>{String(settings.servicenow_enabled)}</strong>
            </div>
            <div>
              Fixture mode: <strong>{String(settings.servicenow_use_fixture)}</strong>
            </div>
            <div>
              Instance: <code>{String(settings.servicenow_instance_url || "—")}</code>
            </div>
            <div>
              Password configured: <strong>{String(snSecrets.password_configured)}</strong>
            </div>
            <div>
              Query: <code>{String(snSecrets.query || "—")}</code>
            </div>
            <div>
              Poll interval (s): <strong>{String(snSecrets.poll_interval_seconds || "—")}</strong>
            </div>
          </dl>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className="mh-btn-ghost" onClick={() => void testSn()}>
            Connection test
          </button>
          <button type="button" className="mh-btn-ghost" onClick={() => void dryRun()}>
            Dry-run poll
          </button>
          <button type="button" className="mh-btn" onClick={() => void pollNow()}>
            Poll now
          </button>
        </div>
        {pollResult && (
          <pre className="mt-4 max-h-48 overflow-auto rounded-lg bg-ink-950 p-3 text-xs text-ink-50">
            {JSON.stringify(pollResult, null, 2)}
          </pre>
        )}
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Unmatched changes</h2>
        <ul className="mt-3 divide-y divide-ink-100">
          {unmatched.length === 0 && (
            <li className="py-4 text-sm text-ink-500">No open unmatched records.</li>
          )}
          {unmatched.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
              <div>
                <div className="font-medium">{u.external_id}</div>
                <div className="text-xs text-ink-500">{u.reason}</div>
              </div>
              <div className="flex gap-2">
                <button type="button" className="mh-btn-ghost text-xs" onClick={() => void resolve(u.id, "ignore")}>
                  Ignore
                </button>
                <button type="button" className="mh-btn-ghost text-xs" onClick={() => void resolve(u.id, "create")}>
                  Create event
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">CMDB CSV import</h2>
        <p className="mt-1 text-sm text-ink-600">
          Upload → preview → commit. Use kind <code>cmdb_ci</code> or <code>ci_relationships</code>.
          Imports are <strong>partial by default</strong> — absences never delete existing
          relationships (including when labeled full; snapshot deletion remains unsupported).
        </p>
        <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={onUpload}>
          <div>
            <label className="mh-label">Kind</label>
            <select className="mh-input" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="cmdb_ci">CI export (cmdb_ci)</option>
              <option value="ci_relationships">Relationship export (ci_relationships)</option>
            </select>
          </div>
          <div>
            <label className="mh-label">CSV file</label>
            <input
              className="mh-input"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>
          <button className="mh-btn" type="submit">
            Upload & preview
          </button>
        </form>
        {preview && (
          <div className="mt-4 space-y-3">
            <div className="rounded-lg border border-ink-100 bg-ink-50/70 p-3 text-sm">
              Rows: {String(preview.total_rows)} · valid {String(preview.valid_rows)} · errors{" "}
              {String(preview.error_count)}
            </div>
            <pre className="max-h-56 overflow-auto rounded-lg bg-ink-950 p-3 text-xs text-ink-50">
              {JSON.stringify(preview, null, 2)}
            </pre>
            <button type="button" className="mh-btn" onClick={() => void commitImport()}>
              Confirm commit
            </button>
          </div>
        )}
        <h3 className="mt-6 text-sm font-semibold uppercase tracking-wide text-ink-500">History</h3>
        <ul className="mt-2 divide-y divide-ink-100 text-sm">
          {imports.map((j) => (
            <li key={j.id} className="py-2">
              <span className="font-medium">{j.filename}</span> · {j.kind} · {j.status}
              {j.committed_at ? ` · committed ${j.committed_at}` : ""}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
