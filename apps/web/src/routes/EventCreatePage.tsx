import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  type Application,
  type Environment,
  type ImpactSeed,
  type InfraComponent,
} from "@/api/client";
import { ImpactAnalysisPanel } from "@/components/ImpactAnalysisPanel";
import { RecurrenceEditor, defaultRecurrence, type RecurrenceValue } from "@/components/RecurrenceEditor";
import type { ConfirmReady, ExclusionRow } from "@/lib/impactPreviewSession";
import { localWallTimeToUtcIso, ZonedDateTimeError } from "@/lib/zonedDateTime";

export function EventCreatePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const initialKind = params.get("kind") === "manual_outage" ? "manual_outage" : "planned_maintenance";

  const [step, setStep] = useState<"details" | "impact">("details");
  const [apps, setApps] = useState<Application[]>([]);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [infra, setInfra] = useState<InfraComponent[]>([]);
  const [kind, setKind] = useState(initialKind);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [impact, setImpact] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [timezone, setTimezone] = useState("America/Chicago");
  const [targetKind, setTargetKind] = useState<"application" | "infra_component">("application");
  const [appId, setAppId] = useState("");
  const [envId, setEnvId] = useState("");
  const [infraId, setInfraId] = useState("");
  const [appId2, setAppId2] = useState("");
  const [envId2, setEnvId2] = useState("");
  const [recurring, setRecurring] = useState(false);
  const [recurrence, setRecurrence] = useState<RecurrenceValue>(defaultRecurrence());
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmReady, setConfirmReady] = useState<ConfirmReady | null>(null);
  const [previewOk, setPreviewOk] = useState(false);
  const [reviewedExclusions, setReviewedExclusions] = useState<ExclusionRow[]>([]);
  const [reviewedManuals, setReviewedManuals] = useState<ImpactSeed[]>([]);

  useEffect(() => {
    void (async () => {
      const [a, e, i] = await Promise.all([
        api.applications(),
        api.environments(),
        api.infraComponents(),
      ]);
      setApps(a);
      setEnvs(e);
      setInfra(i);
      if (a[0]) setAppId(a[0].id);
      if (i[0]) setInfraId(i[0].id);
      if (e.find((x) => x.key === "PROD")) setEnvId(e.find((x) => x.key === "PROD")!.id);
      else if (e[0]) setEnvId(e[0].id);
      const nonProd = e.find((x) => x.key === "NON-PROD");
      if (nonProd && i.some((x) => x.key.includes("oracle"))) {
        setTargetKind("infra_component");
        setInfraId(i.find((x) => x.key.includes("oracle"))!.id);
        setEnvId(nonProd.id);
      }
    })();
  }, []);

  const seeds = useMemo(() => {
    const out: ImpactSeed[] = [];
    if (targetKind === "infra_component" && infraId) {
      out.push({
        target_type: "infra_component",
        target_id: infraId,
        environment_id: envId || null,
      });
    } else if (appId) {
      out.push({
        target_type: "application",
        target_id: appId,
        environment_id: envId || null,
      });
    }
    if (appId2) {
      out.push({
        target_type: "application",
        target_id: appId2,
        environment_id: envId2 || null,
      });
    }
    return out;
  }, [targetKind, infraId, appId, envId, appId2, envId2]);

  const startsIso = useMemo(() => {
    if (!starts) return "";
    try {
      return localWallTimeToUtcIso(starts, timezone);
    } catch {
      return "";
    }
  }, [starts, timezone]);

  const endsIso = useMemo(() => {
    if (!ends) return "";
    try {
      return localWallTimeToUtcIso(ends, timezone);
    } catch {
      return "";
    }
  }, [ends, timezone]);

  const onConfirmReady = useCallback((state: ConfirmReady | null) => {
    setConfirmReady(state);
  }, []);

  const onPreviewStatus = useCallback(
    (status: { busy: boolean; error: string | null; ok: boolean }) => {
      setPreviewOk(status.ok);
      if (status.error) setError(status.error);
    },
    [],
  );

  function onDetailsContinue(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!title || !starts || !ends) {
      setError("Title and window are required");
      return;
    }
    try {
      localWallTimeToUtcIso(starts, timezone);
      localWallTimeToUtcIso(ends, timezone);
    } catch (err) {
      setError(err instanceof ZonedDateTimeError ? err.message : "Invalid window in selected timezone");
      return;
    }
    if (!seeds.length) {
      setError("Select at least one maintenance target");
      return;
    }
    setStep("impact");
  }

  async function onPublish() {
    if (!confirmReady || !previewOk) {
      setError("Complete a successful impact preview before publishing");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const startsAt = localWallTimeToUtcIso(starts, timezone);
      const endsAt = localWallTimeToUtcIso(ends, timezone);
      const body: Record<string, unknown> = {
        kind,
        title,
        description,
        expected_impact: impact,
        approval_state: "approved_window",
        starts_at: startsAt,
        ends_at: endsAt,
        timezone,
        impacts: seeds,
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
        if (recurrence.until) {
          rec.until = localWallTimeToUtcIso(recurrence.until, timezone);
        }
        if (recurrence.count) rec.count = recurrence.count;
        body.recurrence = rec;
      }
      const created = await api.createEvent(body);
      // Re-preview with event_id so revision token matches confirm validation
      const preview = await api.impactPreview({
        seeds,
        starts_at: created.starts_at,
        ends_at: created.ends_at,
        event_id: created.id,
        exclusions: confirmReady.exclusions,
        manual_additions: confirmReady.manualAdditions,
        max_depth: 5,
      });
      const include = preview.suggested_downstream
        .filter((s) => s.selection !== "excluded")
        .map((s) => ({
          target_type: s.target_type,
          target_id: s.target_id,
          environment_id: s.environment_id ?? null,
        }));
      const published = await api.impactConfirm(created.id, {
        revision_token: preview.revision_token,
        seeds,
        starts_at: created.starts_at,
        ends_at: created.ends_at,
        exclusions: confirmReady.exclusions,
        manual_additions: confirmReady.manualAdditions,
        include_downstream: include,
        max_depth: 5,
        publish: true,
      });
      navigate(`/events/${published.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setBusy(false);
    }
  }

  const canPublish = Boolean(confirmReady) && previewOk && !busy;

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← Dashboard
      </Link>
      <div className="mh-panel p-6">
        <h1 className="font-display text-3xl font-semibold text-ink-950">
          {kind === "manual_outage" ? "Report manual outage" : "Publish maintenance"}
        </h1>
        <p className="mt-2 text-sm text-ink-600">
          {step === "details"
            ? "Capture the window and direct targets, then review impact analysis before publish."
            : "Confirm suggested impacts, reach, and conflicts. Publishing validates a revision token server-side."}
        </p>

        <ol className="mt-4 flex gap-3 text-xs font-semibold uppercase tracking-wide" aria-label="Publish steps">
          <li className={step === "details" ? "text-accent" : "text-ink-400"}>1. Details</li>
          <li className={step === "impact" ? "text-accent" : "text-ink-400"}>2. Impact analysis</li>
        </ol>

        {step === "details" && (
          <form className="mt-6 space-y-4" onSubmit={onDetailsContinue}>
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
              <input
                id="title"
                className="mh-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
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
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mh-label" htmlFor="starts">
                  Starts (local in selected TZ)
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
                  Ends (local in selected TZ)
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
              <input
                id="tz"
                className="mh-input"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              />
              <p className="mt-1 text-xs text-ink-500">
                datetime-local values are interpreted in this zone (not the browser zone).
              </p>
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
                Primary target
              </legend>
              <div className="mb-3">
                <label className="mh-label" htmlFor="targetKind">
                  Target type
                </label>
                <select
                  id="targetKind"
                  className="mh-input"
                  value={targetKind}
                  onChange={(e) => setTargetKind(e.target.value as "application" | "infra_component")}
                >
                  <option value="application">Application</option>
                  <option value="infra_component">Infrastructure component</option>
                </select>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {targetKind === "application" ? (
                  <select
                    className="mh-input"
                    value={appId}
                    onChange={(e) => setAppId(e.target.value)}
                    required
                    aria-label="Application"
                  >
                    {apps.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <select
                    className="mh-input"
                    value={infraId}
                    onChange={(e) => setInfraId(e.target.value)}
                    required
                    aria-label="Infrastructure component"
                  >
                    {infra.map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.name}
                      </option>
                    ))}
                  </select>
                )}
                <select
                  className="mh-input"
                  value={envId}
                  onChange={(e) => setEnvId(e.target.value)}
                  aria-label="Environment"
                >
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
                Optional second application impact
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
              <p
                className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
                role="alert"
              >
                {error}
              </p>
            )}
            <button className="mh-btn" type="submit">
              Continue to impact analysis
            </button>
          </form>
        )}

        {step === "impact" && startsIso && endsIso && (
          <div className="mt-6 space-y-4">
            <ImpactAnalysisPanel
              seeds={seeds}
              startsAt={startsIso}
              endsAt={endsIso}
              exclusions={reviewedExclusions}
              manuals={reviewedManuals}
              onExclusionsChange={setReviewedExclusions}
              onManualsChange={setReviewedManuals}
              onConfirmReady={onConfirmReady}
              onPreviewStatus={onPreviewStatus}
            />
            {error && (
              <p
                className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
                role="alert"
              >
                {error}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="mh-btn-ghost"
                onClick={() => setStep("details")}
                disabled={busy}
              >
                Back
              </button>
              <button
                type="button"
                className="mh-btn"
                onClick={() => void onPublish()}
                disabled={!canPublish}
              >
                {busy ? "Publishing…" : "Confirm impacts & publish"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
