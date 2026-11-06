import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/api/client";

type Template = {
  id: string;
  key: string;
  name?: string | null;
  description?: string | null;
  event_type?: string | null;
  status: string;
  channel: string;
  subject_template: string;
  body_template: string;
  body_plain_template?: string | null;
  body_html_template?: string | null;
  version: number;
  is_system: boolean;
};

type Placeholder = { key: string; label: string; sample: string; note?: string };
type EventType = { key: string; label: string };
type VersionRow = {
  version: number;
  change_note?: string | null;
  created_at?: string | null;
  status: string;
};

export function AdminNotificationsPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [secrets, setSecrets] = useState<Record<string, unknown> | null>(null);
  const [placeholders, setPlaceholders] = useState<Placeholder[]>([]);
  const [eventTypes, setEventTypes] = useState<EventType[]>([]);
  const [paNotes, setPaNotes] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string>("");
  const [name, setName] = useState("");
  const [eventType, setEventType] = useState("event.created");
  const [channel, setChannel] = useState("smtp");
  const [subject, setSubject] = useState("");
  const [bodyPlain, setBodyPlain] = useState("");
  const [bodyHtml, setBodyHtml] = useState("");
  const [changeNote, setChangeNote] = useState("");
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [destType, setDestType] = useState("email_address");
  const [destination, setDestination] = useState("admin@demo.example.com");
  const [channelKey, setChannelKey] = useState("ops-channel");
  const [teamsTarget, setTeamsTarget] = useState("ops-payments-channel@example.com");
  const [preview, setPreview] = useState<{
    subject: string;
    body_plain: string;
    body_html: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newKey, setNewKey] = useState("custom.alert");

  const current = useMemo(
    () => templates.find((x) => x.key === selected) || null,
    [templates, selected],
  );

  async function reload(preferKey?: string) {
    const [t, s, catalog] = await Promise.all([
      api.notificationTemplates(true),
      api.adminSecretsStatus(),
      api.notificationTemplateCatalog(),
    ]);
    setTemplates(t);
    setSecrets(s);
    setPlaceholders(catalog.placeholders || []);
    setEventTypes(catalog.event_types || []);
    setPaNotes(catalog.pa_notes || {});
    const key = preferKey || selected || t.find((x) => x.key === "pa.teams_alert")?.key || t[0]?.key;
    if (key) {
      setSelected(key);
      const row = t.find((x) => x.key === key);
      if (row) applyRow(row);
      const vers = await api.notificationTemplateVersions(key).catch(() => []);
      setVersions(vers);
    }
  }

  function applyRow(row: Template) {
    setName(row.name || row.key);
    setEventType(row.event_type || row.key);
    setChannel(row.channel);
    setSubject(row.subject_template);
    setBodyPlain(row.body_plain_template || row.body_template);
    setBodyHtml(row.body_html_template || "");
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof ApiError ? e.detail : "Load failed"));
  }, []);

  useEffect(() => {
    const t = templates.find((x) => x.key === selected);
    if (t) {
      applyRow(t);
      void api
        .notificationTemplateVersions(selected)
        .then(setVersions)
        .catch(() => setVersions([]));
    }
  }, [selected]);

  function insertPlaceholder(key: string) {
    const token = `{{${key}}}`;
    setBodyPlain((prev) => `${prev}${prev.endsWith("\n") || !prev ? "" : "\n"}${token}`);
  }

  async function saveTemplate(ev: FormEvent) {
    ev.preventDefault();
    try {
      await api.patchNotificationTemplate(selected, {
        name,
        event_type: eventType,
        channel,
        subject_template: subject,
        body_plain_template: bodyPlain,
        body_html_template: bodyHtml || null,
        change_note: changeNote || "admin update",
      });
      setMsg(`Saved ${selected} (new version)`);
      setChangeNote("");
      await reload(selected);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Save failed");
    }
  }

  async function createTemplate(ev: FormEvent) {
    ev.preventDefault();
    try {
      await api.createNotificationTemplate({
        key: newKey,
        name: name || newKey,
        event_type: eventType,
        channel,
        subject_template: subject || "[MaintenanceHub] Alert",
        body_plain_template: bodyPlain || "Title: {{title}}\n",
        body_html_template: bodyHtml || null,
        activate: true,
      });
      setCreating(false);
      setMsg(`Created ${newKey}`);
      await reload(newKey);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Create failed");
    }
  }

  async function runPreview() {
    try {
      const r = await api.previewNotificationTemplate(selected, {
        subject_template: subject,
        body_plain_template: bodyPlain,
        body_html_template: bodyHtml,
        context: { teams_target_email: teamsTarget, bridge_channel_key: channelKey },
      });
      setPreview({
        subject: r.subject,
        body_plain: r.body_plain,
        body_html: r.body_html,
      });
      setMsg("Preview rendered (values HTML-escaped in HTML body)");
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Preview failed");
    }
  }

  async function testSend(ev: FormEvent, captureOnly: boolean) {
    ev.preventDefault();
    try {
      const r = await api.testNotification({
        template_key: selected || "pa.teams_alert",
        destination_type: destType,
        destination,
        bridge_channel_key: destType === "teams_bridge_channel" ? channelKey : undefined,
        teams_target_email: teamsTarget,
        capture_only: captureOnly,
        context: { teams_target_email: teamsTarget, bridge_channel_key: channelKey },
      });
      setPreview({
        subject: r.preview.subject,
        body_plain: r.preview.body_plain || r.preview.body,
        body_html: r.preview.body_html || "",
      });
      setMsg(
        `Test ${r.status} via ${r.channel}. ${r.note || ""} Delivery ${r.delivery_id}.`,
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Test send failed");
    }
  }

  const smtp = ((secrets || {}).smtp || {}) as Record<string, unknown>;
  const bridge = ((secrets || {}).bridge || {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {error}
          <button type="button" className="ml-3 text-xs underline" onClick={() => setError(null)}>
            dismiss
          </button>
        </div>
      )}
      {msg && (
        <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">
          {msg}
        </div>
      )}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Delivery channels</h2>
        <p className="mt-1 text-sm text-ink-600">
          No Microsoft Graph or Teams APIs. Teams destinations route through the Power Automate
          email bridge only. Body <code>To:</code> lines are PA routing — not SMTP To.
        </p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-ink-100 p-4 text-sm">
            <h3 className="font-semibold">SMTP</h3>
            <ul className="mt-2 space-y-1 text-ink-700">
              <li>Enabled: {String(smtp.enabled)}</li>
              <li>
                Host: {String(smtp.host)}:{String(smtp.port)}
              </li>
              <li>From: {String(smtp.from_address)}</li>
              <li>Password configured: {String(smtp.password_configured)} (never shown)</li>
            </ul>
          </div>
          <div className="rounded-lg border border-ink-100 p-4 text-sm">
            <h3 className="font-semibold">Power Automate bridge</h3>
            <ul className="mt-2 space-y-1 text-ink-700">
              <li>Enabled: {String(bridge.enabled)}</li>
              <li>Mailbox: {String(bridge.mailbox || "—")}</li>
              <li>
                Subject template: <code className="text-xs">{String(bridge.subject_template)}</code>
              </li>
              <li className="text-ink-500">{String(bridge.note)}</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="mh-panel p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-semibold">Template Manager</h2>
            <p className="mt-1 text-sm text-ink-600">
              Admin CRUD, versions, activate/deactivate/restore. Sample PA template:{" "}
              <code>pa.teams_alert</code>.
            </p>
          </div>
          <button type="button" className="mh-btn-ghost" onClick={() => setCreating((v) => !v)}>
            {creating ? "Cancel create" : "New template"}
          </button>
        </div>

        {creating && (
          <form className="mt-4 grid gap-3 rounded-lg border border-ink-100 p-4 md:grid-cols-2" onSubmit={createTemplate}>
            <div>
              <label className="mh-label">New key</label>
              <input className="mh-input" value={newKey} onChange={(e) => setNewKey(e.target.value)} required />
            </div>
            <div className="flex items-end">
              <button className="mh-btn" type="submit">
                Create from editor
              </button>
            </div>
          </form>
        )}

        <form className="mt-4 space-y-3" onSubmit={saveTemplate}>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="mh-label">Template</label>
              <select
                className="mh-input"
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {templates.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.name || t.key} · {t.status} · v{t.version}
                    {t.is_system ? " · system" : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mh-label">Display name</label>
              <input className="mh-input" value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className="mh-label">Event type</label>
              <select className="mh-input" value={eventType} onChange={(e) => setEventType(e.target.value)}>
                {eventTypes.map((et) => (
                  <option key={et.key} value={et.key}>
                    {et.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mh-label">Channel</label>
              <select className="mh-input" value={channel} onChange={(e) => setChannel(e.target.value)}>
                <option value="smtp">smtp</option>
                <option value="bridge">bridge (PA)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="mh-label">Subject</label>
            <input className="mh-input font-mono text-sm" value={subject} onChange={(e) => setSubject(e.target.value)} />
            {paNotes.subject_default && (
              <p className="mt-1 text-xs text-ink-500">
                PA default subject: <code>{paNotes.subject_default}</code>
              </p>
            )}
          </div>

          <div>
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <label className="mh-label mb-0">Plain body</label>
              <div className="flex flex-wrap gap-1">
                {placeholders.slice(0, 8).map((p) => (
                  <button
                    key={p.key}
                    type="button"
                    className="rounded border border-ink-200 px-2 py-0.5 text-[11px] text-ink-700 hover:bg-ink-50"
                    title={p.note || p.label}
                    onClick={() => insertPlaceholder(p.key)}
                  >
                    {`{{${p.key}}}`}
                  </button>
                ))}
              </div>
            </div>
            <textarea
              className="mh-input min-h-[160px] font-mono text-xs"
              value={bodyPlain}
              onChange={(e) => setBodyPlain(e.target.value)}
            />
            <p className="mt-1 text-xs text-ink-500">
              {paNotes.routing_meaning ||
                "For PA Teams alerts, start with To: {{teams_target_email}} — routing for the flow, not SMTP To."}
            </p>
          </div>

          <div>
            <label className="mh-label">HTML body (optional)</label>
            <textarea
              className="mh-input min-h-[120px] font-mono text-xs"
              value={bodyHtml}
              onChange={(e) => setBodyHtml(e.target.value)}
            />
          </div>

          <div>
            <label className="mh-label">Change note</label>
            <input
              className="mh-input"
              value={changeNote}
              onChange={(e) => setChangeNote(e.target.value)}
              placeholder="Why this change?"
            />
          </div>

          <div className="flex flex-wrap gap-2">
            <button className="mh-btn" type="submit">
              Save new version
            </button>
            <button type="button" className="mh-btn-ghost" onClick={() => void runPreview()}>
              Preview
            </button>
            <button
              type="button"
              className="mh-btn-ghost"
              onClick={() =>
                void api
                  .cloneNotificationTemplate(selected)
                  .then((r) => reload(String(r.key)))
                  .then(() => setMsg("Cloned"))
                  .catch((e) => setError(e instanceof ApiError ? e.detail : "Clone failed"))
              }
            >
              Clone
            </button>
            {current?.status !== "active" && (
              <button
                type="button"
                className="mh-btn-ghost"
                onClick={() =>
                  void api
                    .activateNotificationTemplate(selected)
                    .then(() => reload(selected))
                    .then(() => setMsg("Activated"))
                }
              >
                Activate
              </button>
            )}
            {current?.status === "active" && (
              <button
                type="button"
                className="mh-btn-ghost"
                onClick={() =>
                  void api
                    .deactivateNotificationTemplate(selected)
                    .then(() => reload(selected))
                    .then(() => setMsg("Deactivated"))
                }
              >
                Deactivate
              </button>
            )}
            {!current?.is_system && (
              <button
                type="button"
                className="mh-btn-danger"
                onClick={() =>
                  void api
                    .archiveNotificationTemplate(selected)
                    .then(() => reload())
                    .then(() => setMsg("Archived"))
                }
              >
                Archive
              </button>
            )}
          </div>
        </form>

        {versions.length > 0 && (
          <div className="mt-6">
            <h3 className="font-semibold">Version history</h3>
            <ul className="mt-2 divide-y divide-ink-100 text-sm">
              {versions.map((v) => (
                <li key={v.version} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    v{v.version} · {v.status}
                    {v.change_note ? ` — ${v.change_note}` : ""}
                    {v.created_at ? (
                      <span className="text-ink-500"> · {new Date(v.created_at).toLocaleString()}</span>
                    ) : null}
                  </span>
                  <button
                    type="button"
                    className="mh-btn-ghost text-xs"
                    onClick={() =>
                      void api
                        .restoreNotificationTemplate(selected, v.version)
                        .then(() => reload(selected))
                        .then(() => setMsg(`Restored v${v.version}`))
                    }
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Preview & test send</h2>
        <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={(e) => void testSend(e, true)}>
          <div>
            <label className="mh-label">Destination type</label>
            <select className="mh-input" value={destType} onChange={(e) => setDestType(e.target.value)}>
              <option value="email_address">Email (SMTP)</option>
              <option value="teams_bridge_channel">Teams via email bridge</option>
            </select>
          </div>
          <div>
            <label className="mh-label">SMTP / bridge destination</label>
            <input
              className="mh-input"
              value={destination}
              onChange={(e) => setDestination(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mh-label">Teams target email (PA body To:)</label>
            <input className="mh-input" value={teamsTarget} onChange={(e) => setTeamsTarget(e.target.value)} />
          </div>
          {destType === "teams_bridge_channel" && (
            <div>
              <label className="mh-label">Bridge channel key</label>
              <input className="mh-input" value={channelKey} onChange={(e) => setChannelKey(e.target.value)} />
            </div>
          )}
          <div className="flex flex-wrap items-end gap-2 md:col-span-2">
            <button className="mh-btn" type="submit">
              Test send (demo capture)
            </button>
            <button
              className="mh-btn-ghost"
              type="button"
              onClick={(e) => void testSend(e as unknown as FormEvent, false)}
            >
              Test send (real path)
            </button>
          </div>
        </form>
        {preview && (
          <div className="mt-4 rounded-lg border border-ink-100 bg-ink-50/70 p-4 text-sm">
            <div className="font-semibold">Preview</div>
            <div className="mt-2">
              <span className="text-ink-500">Subject:</span> {preview.subject}
            </div>
            <pre className="mt-2 whitespace-pre-wrap text-xs text-ink-800">{preview.body_plain}</pre>
            {preview.body_html ? (
              <div className="mt-3">
                <div className="text-ink-500">HTML</div>
                <div
                  className="mt-1 rounded border border-ink-100 bg-white p-3 text-sm"
                  dangerouslySetInnerHTML={{ __html: preview.body_html }}
                />
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
