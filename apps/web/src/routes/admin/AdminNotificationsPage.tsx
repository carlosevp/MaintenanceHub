import { FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "@/api/client";

type Template = {
  id: string;
  key: string;
  channel: string;
  subject_template: string;
  body_template: string;
};

export function AdminNotificationsPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [secrets, setSecrets] = useState<Record<string, unknown> | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [destType, setDestType] = useState("email_address");
  const [destination, setDestination] = useState("admin@demo.example.com");
  const [channelKey, setChannelKey] = useState("ops-channel");
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function reload() {
    const [t, s] = await Promise.all([api.notificationTemplates(), api.adminSecretsStatus()]);
    setTemplates(t);
    setSecrets(s);
    if (!selected && t[0]) {
      setSelected(t[0].key);
      setSubject(t[0].subject_template);
      setBody(t[0].body_template);
    }
  }

  useEffect(() => {
    void reload().catch((e) => setError(e instanceof ApiError ? e.detail : "Load failed"));
  }, []);

  useEffect(() => {
    const t = templates.find((x) => x.key === selected);
    if (t) {
      setSubject(t.subject_template);
      setBody(t.body_template);
    }
  }, [selected, templates]);

  async function saveTemplate(ev: FormEvent) {
    ev.preventDefault();
    try {
      await api.patchNotificationTemplate(selected, {
        subject_template: subject,
        body_template: body,
      });
      setMsg(`Saved template ${selected}`);
      await reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Save failed");
    }
  }

  async function testSend(ev: FormEvent) {
    ev.preventDefault();
    try {
      const r = await api.testNotification({
        template_key: selected || "event.created",
        destination_type: destType,
        destination,
        bridge_channel_key: destType === "teams_bridge_channel" ? channelKey : undefined,
      });
      setPreview(r.preview);
      setMsg(
        `Test ${r.status} via ${r.channel}. SMTP acceptance ≠ Teams delivery confirmation. ${r.note || ""}`,
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Test send failed");
    }
  }

  const smtp = ((secrets || {}).smtp || {}) as Record<string, unknown>;
  const bridge = ((secrets || {}).bridge || {}) as Record<string, unknown>;

  return (
    <div className="space-y-6">
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{error}</div>}
      {msg && <div className="rounded-lg border border-teal-200 bg-teal-50 px-4 py-3 text-sm text-teal-900">{msg}</div>}

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Delivery channels</h2>
        <p className="mt-1 text-sm text-ink-600">
          No Microsoft Graph or Teams APIs. Teams destinations route through the Power Automate
          email bridge only. Passwords are deployment-time only.
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
              <li>UI editable: {String(smtp.ui_editable)}</li>
            </ul>
            <button
              type="button"
              className="mh-btn-ghost mt-3 text-xs"
              onClick={() =>
                void api.adminTestIntegration("smtp").then((r) => setMsg(JSON.stringify(r)))
              }
            >
              Test SMTP
            </button>
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
            <button
              type="button"
              className="mh-btn-ghost mt-3 text-xs"
              onClick={() =>
                void api.adminTestIntegration("bridge").then((r) => setMsg(JSON.stringify(r)))
              }
            >
              Test bridge
            </button>
          </div>
        </div>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Notification templates</h2>
        <form className="mt-4 space-y-3" onSubmit={saveTemplate}>
          <div>
            <label className="mh-label">Template key</label>
            <select className="mh-input" value={selected} onChange={(e) => setSelected(e.target.value)}>
              {templates.map((t) => (
                <option key={t.key} value={t.key}>
                  {t.key} ({t.channel})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mh-label">Subject template</label>
            <input className="mh-input" value={subject} onChange={(e) => setSubject(e.target.value)} />
          </div>
          <div>
            <label className="mh-label">Body template</label>
            <textarea
              className="mh-input min-h-[140px] font-mono text-xs"
              value={body}
              onChange={(e) => setBody(e.target.value)}
            />
          </div>
          <button className="mh-btn" type="submit">
            Save template
          </button>
        </form>
      </section>

      <section className="mh-panel p-6">
        <h2 className="font-display text-xl font-semibold">Test notification</h2>
        <form className="mt-4 grid gap-3 md:grid-cols-2" onSubmit={testSend}>
          <div>
            <label className="mh-label">Destination type</label>
            <select className="mh-input" value={destType} onChange={(e) => setDestType(e.target.value)}>
              <option value="email_address">Email (SMTP)</option>
              <option value="teams_bridge_channel">Teams via email bridge</option>
            </select>
          </div>
          <div>
            <label className="mh-label">Destination</label>
            <input className="mh-input" value={destination} onChange={(e) => setDestination(e.target.value)} required />
          </div>
          {destType === "teams_bridge_channel" && (
            <div>
              <label className="mh-label">Bridge channel key</label>
              <input className="mh-input" value={channelKey} onChange={(e) => setChannelKey(e.target.value)} />
            </div>
          )}
          <div className="flex items-end">
            <button className="mh-btn" type="submit">
              Send test
            </button>
          </div>
        </form>
        {preview && (
          <div className="mt-4 rounded-lg border border-ink-100 bg-ink-50/70 p-4 text-sm">
            <div className="font-semibold">Preview</div>
            <div className="mt-2">
              <span className="text-ink-500">Subject:</span> {preview.subject}
            </div>
            <pre className="mt-2 whitespace-pre-wrap text-xs text-ink-800">{preview.body}</pre>
          </div>
        )}
      </section>
    </div>
  );
}
