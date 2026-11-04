import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type Application, type Environment } from "@/api/client";
import { RecurrenceEditor, defaultRecurrence, type RecurrenceValue } from "@/components/RecurrenceEditor";

export function EventCreatePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const initialKind = params.get("kind") === "manual_outage" ? "manual_outage" : "planned_maintenance";

  const [apps, setApps] = useState<Application[]>([]);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [kind, setKind] = useState(initialKind);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [impact, setImpact] = useState("");
  const [approval, setApproval] = useState("confirmed_scheduled");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [timezone, setTimezone] = useState("America/Chicago");
  const [appId, setAppId] = useState("");
  const [envId, setEnvId] = useState("");
  const [appId2, setAppId2] = useState("");
  const [envId2, setEnvId2] = useState("");
  const [recurring, setRecurring] = useState(false);
  const [recurrence, setRecurrence] = useState<RecurrenceValue>(defaultRecurrence());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void (async () => {
      const [a, e] = await Promise.all([api.applications(), api.environments()]);
      setApps(a);
      setEnvs(e);
      if (a[0]) setAppId(a[0].id);
      if (e.find((x) => x.key === "PROD")) setEnvId(e.find((x) => x.key === "PROD")!.id);
      else if (e[0]) setEnvId(e[0].id);
    })();
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const impacts = [
        { target_type: "application", target_id: appId, environment_id: envId || null },
      ];
      if (appId2) {
        impacts.push({
          target_type: "application",
          target_id: appId2,
          environment_id: envId2 || null,
        });
      }
      const body: Record<string, unknown> = {
        kind,
        title,
        description,
        expected_impact: impact,
        approval_state: approval,
        starts_at: new Date(starts).toISOString(),
        ends_at: new Date(ends).toISOString(),
        timezone,
        impacts,
      };
      if (recurring && kind === "planned_maintenance") {
        const rec: Record<string, unknown> = {
          freq: recurrence.freq,
          interval: recurrence.interval,
        };
        if (recurrence.freq === "CUSTOM") rec.rrule = recurrence.rrule;
        if (recurrence.freq === "WEEKLY") rec.byweekday = recurrence.byweekday;
        if (recurrence.freq === "MONTHLY" && recurrence.bymonthday != null) {
          rec.bymonthday = recurrence.bymonthday;
        }
        if (recurrence.until) rec.until = new Date(recurrence.until).toISOString();
        if (recurrence.count) rec.count = recurrence.count;
        body.recurrence = rec;
      }
      const created = await api.createEvent(body);
      navigate(`/events/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← Dashboard
      </Link>
      <div className="mh-panel p-6">
        <h1 className="font-display text-3xl font-semibold text-ink-950">
          {kind === "manual_outage" ? "Report manual outage" : "Publish maintenance"}
        </h1>
        <p className="mt-2 text-sm text-ink-600">
          Distinguish approved windows from confirmed scheduled work before broad communication.
        </p>

        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <div>
            <label className="mh-label" htmlFor="kind">
              Kind
            </label>
            <select id="kind" className="mh-input" value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="planned_maintenance">Planned maintenance</option>
              <option value="manual_outage">Manual outage</option>
            </select>
          </div>
          <div>
            <label className="mh-label" htmlFor="title">
              Title
            </label>
            <input id="title" className="mh-input" value={title} onChange={(e) => setTitle(e.target.value)} required />
          </div>
          <div>
            <label className="mh-label" htmlFor="desc">
              Description
            </label>
            <textarea
              id="desc"
              className="mh-input"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div>
            <label className="mh-label" htmlFor="impact">
              Expected impact
            </label>
            <input id="impact" className="mh-input" value={impact} onChange={(e) => setImpact(e.target.value)} />
          </div>
          <div>
            <label className="mh-label" htmlFor="approval">
              Approval state
            </label>
            <select
              id="approval"
              className="mh-input"
              value={approval}
              onChange={(e) => setApproval(e.target.value)}
            >
              <option value="confirmed_scheduled">Confirmed scheduled work</option>
              <option value="approved_window">Approved window only</option>
            </select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mh-label" htmlFor="starts">
                Starts
              </label>
              <input
                id="starts"
                type="datetime-local"
                className="mh-input"
                value={starts}
                onChange={(e) => setStarts(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="mh-label" htmlFor="ends">
                Ends
              </label>
              <input
                id="ends"
                type="datetime-local"
                className="mh-input"
                value={ends}
                onChange={(e) => setEnds(e.target.value)}
                required
              />
            </div>
          </div>
          <div>
            <label className="mh-label" htmlFor="tz">
              Timezone (IANA)
            </label>
            <input id="tz" className="mh-input" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
          </div>

          {kind === "planned_maintenance" && (
            <RecurrenceEditor
              enabled={recurring}
              onEnabledChange={setRecurring}
              value={recurrence}
              onChange={setRecurrence}
              startsAt={starts}
              endsAt={ends}
              timezone={timezone}
            />
          )}

          <fieldset className="rounded-lg border border-ink-200 p-3">
            <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-ink-500">
              Primary impact
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <select className="mh-input" value={appId} onChange={(e) => setAppId(e.target.value)} required>
                {apps.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <select className="mh-input" value={envId} onChange={(e) => setEnvId(e.target.value)}>
                {envs.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.key} — {e.name}
                  </option>
                ))}
              </select>
            </div>
          </fieldset>

          <fieldset className="rounded-lg border border-dashed border-ink-200 p-3">
            <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-ink-500">
              Optional second impact
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <select className="mh-input" value={appId2} onChange={(e) => setAppId2(e.target.value)}>
                <option value="">None</option>
                {apps.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <select className="mh-input" value={envId2} onChange={(e) => setEnvId2(e.target.value)}>
                <option value="">—</option>
                {envs.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.key}
                  </option>
                ))}
              </select>
            </div>
          </fieldset>

          {error && (
            <p className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </p>
          )}
          <button className="mh-btn" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Publish"}
          </button>
        </form>
      </div>
    </div>
  );
}
