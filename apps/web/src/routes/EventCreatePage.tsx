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
import { useExperience } from "@/features/experience/ExperienceContext";
import clsx from "clsx";

type Step = "details" | "impact" | "audience" | "review";
const DRAFT_KEY = "mh_publish_draft_v1";
const STEP_LABELS: Record<Step, string> = {
  details: "Details",
  impact: "Impact",
  audience: "Audience",
  review: "Review",
};

const TEMPLATES = [
  {
    id: "blank",
    label: "Blank",
    title: "",
    description: "",
    impact: "",
  },
  {
    id: "db-patch",
    label: "DB patch window",
    title: "Database patch window",
    description: "Scheduled vendor patch on shared database infrastructure.",
    impact: "Brief connection resets; write traffic may queue.",
  },
  {
    id: "app-deploy",
    label: "App deploy",
    title: "Application deploy window",
    description: "Controlled deployment with verified rollback.",
    impact: "Read-only or brief unavailability during cutover.",
  },
];

export function EventCreatePage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { can, defaultTimezone, loading: experienceLoading } = useExperience();
  const reportingOutage = params.get("kind") === "manual_outage";
  const quick = params.get("quick") === "1" || reportingOutage;
  const useImpactFlow = can("impact_analysis") && !quick;
  const STEPS: Step[] = useImpactFlow
    ? ["details", "impact", "audience", "review"]
    : ["details", "review"];
  const initialKind = reportingOutage ? "manual_outage" : "planned_maintenance";

  const [step, setStep] = useState<Step>("details");
  const [showMore, setShowMore] = useState(!quick);
  const [apps, setApps] = useState<Application[]>([]);
  const [envs, setEnvs] = useState<Environment[]>([]);
  const [infra, setInfra] = useState<InfraComponent[]>([]);
  const [kind, setKind] = useState(initialKind);
  // Never prefill "Manual outage" when scheduling planned maintenance via Quick Publish.
  const [title, setTitle] = useState(reportingOutage ? "Manual outage" : "");
  const [description, setDescription] = useState("");
  const [impact, setImpact] = useState(
    reportingOutage ? "Service unavailable — investigating" : "",
  );
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [timezone, setTimezone] = useState(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch {
      return "UTC";
    }
  });
  const [tzSource, setTzSource] = useState<"browser" | "configured">("browser");
  const [targetKind, setTargetKind] = useState<"application" | "infra_component">("application");
  const [appId, setAppId] = useState("");
  const [envId, setEnvId] = useState("");
  const [infraId, setInfraId] = useState("");
  const [appId2, setAppId2] = useState("");
  const [envId2, setEnvId2] = useState("");
  const [recurring, setRecurring] = useState(false);
  const [recurrence, setRecurrence] = useState<RecurrenceValue>(defaultRecurrence());
  const [reminderOffsets, setReminderOffsets] = useState("-1440,-60");
  const [publisherNote, setPublisherNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmReady, setConfirmReady] = useState<ConfirmReady | null>(null);
  const [previewOk, setPreviewOk] = useState(false);
  const [audienceNote, setAudienceNote] = useState<string | null>(null);
  const [audienceCount, setAudienceCount] = useState<number | null>(null);
  const [reviewedExclusions, setReviewedExclusions] = useState<ExclusionRow[]>([]);
  const [reviewedManuals, setReviewedManuals] = useState<ImpactSeed[]>([]);
  const [draftSaved, setDraftSaved] = useState(false);

  // Apply configured deploy/demo TZ once experience loads (overrides bare UTC browser default).
  useEffect(() => {
    if (experienceLoading) return;
    let browser = "UTC";
    try {
      browser = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    } catch {
      /* keep UTC */
    }
    if (defaultTimezone) {
      setTimezone(defaultTimezone);
      setTzSource("configured");
    } else {
      setTimezone(browser);
      setTzSource("browser");
    }
  }, [defaultTimezone, experienceLoading]);

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
      // Do not auto-select Oracle/infra for Quick Publish — that conflicts with a simple app window.
      try {
        const raw = localStorage.getItem(DRAFT_KEY);
        if (raw && !quick) {
          const d = JSON.parse(raw) as Record<string, string>;
          if (d.title) setTitle(d.title);
          if (d.description) setDescription(d.description);
          if (d.impact) setImpact(d.impact);
          if (d.starts) setStarts(d.starts);
          if (d.ends) setEnds(d.ends);
          if (d.timezone) {
            setTimezone(d.timezone);
            setTzSource("browser");
          }
          if (d.kind) setKind(d.kind);
        }
      } catch {
        /* ignore bad draft */
      }
    })();
  }, [quick]);

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

  function applyTemplate(id: string) {
    const t = TEMPLATES.find((x) => x.id === id);
    if (!t) return;
    setTitle(t.title);
    setDescription(t.description);
    setImpact(t.impact);
  }

  function saveDraft() {
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ title, description, impact, starts, ends, timezone, kind }),
    );
    setDraftSaved(true);
    setTimeout(() => setDraftSaved(false), 2000);
  }

  function validateDetails(): boolean {
    setError(null);
    if (!title || !starts || !ends) {
      setError("Title and window are required");
      return false;
    }
    try {
      localWallTimeToUtcIso(starts, timezone);
      localWallTimeToUtcIso(ends, timezone);
    } catch (err) {
      setError(err instanceof ZonedDateTimeError ? err.message : "Invalid window in selected timezone");
      return false;
    }
    if (!seeds.length) {
      setError("Select at least one maintenance target");
      return false;
    }
    return true;
  }

  function onDetailsContinue(e: FormEvent) {
    e.preventDefault();
    if (!validateDetails()) return;
    if (useImpactFlow) {
      setStep("impact");
      return;
    }
    setStep("review");
  }

  async function onSimplePublish() {
    if (!validateDetails()) return;
    setBusy(true);
    setError(null);
    try {
      const startsAt = localWallTimeToUtcIso(starts, timezone);
      const endsAt = localWallTimeToUtcIso(ends, timezone);
      const created = await api.createEvent({
        kind,
        title,
        description: publisherNote ? `${description}\n\nPublisher note: ${publisherNote}` : description,
        expected_impact: impact,
        approval_state: "confirmed_scheduled",
        starts_at: startsAt,
        ends_at: endsAt,
        timezone,
        impacts: seeds,
      });
      localStorage.removeItem(DRAFT_KEY);
      navigate(`/events/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setBusy(false);
    }
  }

  function onImpactContinue() {
    if (!confirmReady || !previewOk) {
      setError("Complete a successful impact preview before continuing");
      return;
    }
    setError(null);
    void (async () => {
      try {
        const preview = await api.impactPreview({
          seeds,
          starts_at: startsIso,
          ends_at: endsIso,
          exclusions: confirmReady.exclusions,
          manual_additions: confirmReady.manualAdditions,
          max_depth: 5,
        });
        setAudienceCount(preview.audience.unique_recipients);
        setAudienceNote(preview.audience.note);
      } catch {
        setAudienceNote("Audience estimate unavailable until publish preview.");
      }
      setStep("audience");
    })();
  }

  function onAudienceContinue() {
    setError(null);
    setStep("review");
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
        description: publisherNote ? `${description}\n\nPublisher note: ${publisherNote}` : description,
        expected_impact: impact,
        approval_state: kind === "manual_outage" ? "confirmed_scheduled" : "approved_window",
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
      localStorage.removeItem(DRAFT_KEY);
      navigate(`/events/${published.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Publish failed");
    } finally {
      setBusy(false);
    }
  }

  const canPublish = Boolean(confirmReady) && previewOk && !busy;
  const stepIndex = STEPS.indexOf(step);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link to="/" className="text-sm font-medium text-accent hover:underline">
        ← My Applications
      </Link>
      <div className="mh-panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="font-display text-3xl font-semibold text-ink-950">
              {reportingOutage
                ? "Report an outage"
                : quick
                  ? "Schedule maintenance"
                  : kind === "manual_outage"
                    ? "Report an outage"
                    : "Publish maintenance"}
            </h1>
            <p className="mt-2 text-sm text-ink-muted">
              {useImpactFlow
                ? "What, when, impact, then who gets notified. Confirmed communication is never inferred from the window alone."
                : "What is changing, when, and who it affects. Add more detail only if you need it."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {!reportingOutage && (
              <Link to="/events/new?quick=1&kind=manual_outage" className="mh-btn-ghost text-sm">
                Report outage
              </Link>
            )}
            <button type="button" className="mh-btn-ghost text-sm" onClick={saveDraft}>
              {draftSaved ? "Draft saved" : "Save draft"}
            </button>
          </div>
        </div>

        <ol className="mt-4 flex flex-wrap gap-3 text-xs font-semibold uppercase tracking-wide" aria-label="Publish steps">
          {STEPS.map((s, i) => (
            <li
              key={s}
              className={clsx(step === s ? "text-accent" : i < stepIndex ? "text-ink-700" : "text-ink-400")}
              aria-current={step === s ? "step" : undefined}
            >
              {i + 1}. {STEP_LABELS[s]}
            </li>
          ))}
        </ol>

        {step === "details" && (
          <form className="mt-6 space-y-4" onSubmit={onDetailsContinue}>
            {!quick && (
              <div>
                <label className="mh-label" htmlFor="template">
                  Start from template
                </label>
                <select
                  id="template"
                  className="mh-input"
                  defaultValue="blank"
                  onChange={(e) => applyTemplate(e.target.value)}
                >
                  {TEMPLATES.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {!quick && (
              <div>
                <label className="mh-label" htmlFor="kind">
                  Type
                </label>
                <select
                  id="kind"
                  className="mh-input"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  <option value="planned_maintenance">Planned maintenance</option>
                  <option value="manual_outage">Manual outage</option>
                </select>
              </div>
            )}
            <div>
              <label className="mh-label" htmlFor="title">
                What
              </label>
              <input
                id="title"
                className="mh-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={reportingOutage ? "e.g. Claims login failures" : "e.g. Payments deploy window"}
                required
              />
            </div>

            <fieldset className="rounded-lg border border-ink-200 p-3">
              <legend className="px-1 text-sm font-semibold text-ink">
                What’s changing
              </legend>
              <div className="mb-3">
                <label className="mh-label" htmlFor="targetKind">
                  Target
                </label>
                <select
                  id="targetKind"
                  className="mh-input"
                  value={targetKind}
                  onChange={(e) => setTargetKind(e.target.value as "application" | "infra_component")}
                >
                  <option value="application">Application</option>
                  {!quick && <option value="infra_component">Infrastructure</option>}
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
                        {a.name.replace("[DEMO] ", "")}
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
                        {i.name.replace("[DEMO] ", "")}
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
                Time zone
              </label>
              <input
                id="tz"
                className="mh-input"
                value={timezone}
                onChange={(e) => {
                  setTimezone(e.target.value);
                  setTzSource("browser");
                }}
              />
              <p className="mt-1 text-xs text-ink-muted">
                {tzSource === "configured"
                  ? `Using configured demo/deploy zone ${timezone}. Change if your window is elsewhere.`
                  : `Using your browser zone (${timezone}). Times above are interpreted here.`}
              </p>
            </div>
            <div>
              <label className="mh-label" htmlFor="impact">
                Impact
              </label>
              <input
                id="impact"
                className="mh-input"
                value={impact}
                onChange={(e) => setImpact(e.target.value)}
                placeholder="e.g. Brief read-only window"
              />
            </div>
            <button
              type="button"
              className="text-sm font-medium text-accent underline"
              onClick={() => setShowMore((v) => !v)}
              aria-expanded={showMore}
            >
              {showMore ? "Hide more options" : "More options"}
            </button>
            {showMore && (
              <div className="space-y-4 rounded-lg border border-ink-200 bg-surface/50 p-3">
                <div>
                  <label className="mh-label" htmlFor="desc">
                    Message (optional)
                  </label>
                  <textarea
                    id="desc"
                    className="mh-input"
                    rows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Extra context for subscribers"
                  />
                </div>
                {kind === "planned_maintenance" && can("recurrence_editor") && (
                  <>
                    <RecurrenceEditor
                      enabled={recurring}
                      onEnabledChange={setRecurring}
                      value={recurrence}
                      onChange={setRecurrence}
                      startsAt={starts}
                      endsAt={ends}
                      timezone={timezone}
                    />
                    {recurring && (
                      <p className="text-xs text-ink-muted">
                        Series defaults apply to each occurrence. Overrides are edited after publish.
                      </p>
                    )}
                  </>
                )}
                {!quick && can("impact_analysis") && (
                  <p className="text-xs text-ink-muted">
                    Shared infrastructure impact analysis is available on the next step after details.
                  </p>
                )}
                <fieldset className="rounded-lg border border-dashed border-ink-200 p-3">
                  <legend className="px-1 text-xs font-semibold tracking-wide text-ink-muted">
                    Optional second app
                  </legend>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <select
                      className="mh-input"
                      value={appId2}
                      onChange={(e) => setAppId2(e.target.value)}
                    >
                      <option value="">None</option>
                      {apps.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name.replace("[DEMO] ", "")}
                        </option>
                      ))}
                    </select>
                    <select
                      className="mh-input"
                      value={envId2}
                      onChange={(e) => setEnvId2(e.target.value)}
                    >
                      <option value="">—</option>
                      {envs.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.key}
                        </option>
                      ))}
                    </select>
                  </div>
                </fieldset>
              </div>
            )}

            {error && (
              <p
                className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
                role="alert"
              >
                {error}
              </p>
            )}
            <button className="mh-btn" type="submit">
              {useImpactFlow ? "Continue to impact analysis" : "Continue to review"}
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
                onClick={onImpactContinue}
                disabled={!confirmReady || !previewOk}
              >
                Continue to audience
              </button>
            </div>
          </div>
        )}

        {step === "audience" && (
          <div className="mt-6 space-y-4">
            <div className="rounded-lg border border-ink-200 bg-ink-50 p-4 text-sm text-ink-700">
              <p className="font-semibold text-ink-900">
                Estimated unique recipients: {audienceCount ?? "—"}
              </p>
              <p className="mt-2">{audienceNote}</p>
              <p className="mt-2 text-xs">
                Matching uses effective confirmed impacts (including occurrence overrides). Multiple
                subscriptions for the same destination are deduplicated per delivery idempotency key —
                one notification per destination per event/reminder slot.
              </p>
            </div>
            <div>
              <label className="mh-label" htmlFor="reminders">
                Suggested reminder offsets (minutes before start, comma-separated)
              </label>
              <input
                id="reminders"
                className="mh-input"
                value={reminderOffsets}
                onChange={(e) => setReminderOffsets(e.target.value)}
              />
              <p className="mt-1 text-xs text-ink-500">
                Consumer subscriptions own actual reminder schedules. These offsets document the
                publisher expectation shown on Review.
              </p>
            </div>
            <div>
              <label className="mh-label" htmlFor="pubnote">
                Publisher note (optional)
              </label>
              <textarea
                id="pubnote"
                className="mh-input"
                rows={2}
                value={publisherNote}
                onChange={(e) => setPublisherNote(e.target.value)}
              />
            </div>
            {error && (
              <p
                className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
                role="alert"
              >
                {error}
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <button type="button" className="mh-btn-ghost" onClick={() => setStep("impact")}>
                Back
              </button>
              <button type="button" className="mh-btn" onClick={onAudienceContinue}>
                Continue to review
              </button>
            </div>
          </div>
        )}

        {step === "review" && (
          <div className="mt-6 space-y-4">
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-ink-500">Title</dt>
                <dd className="font-medium">{title}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-ink-500">Kind</dt>
                <dd className="font-medium">{kind}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-ink-500">Window</dt>
                <dd className="font-medium">
                  {starts} → {ends} ({timezone})
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Expected impact
                </dt>
                <dd className="font-medium">{impact || "—"}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Direct targets
                </dt>
                <dd className="font-medium">{seeds.length}</dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Reminder offsets
                </dt>
                <dd className="font-medium">{reminderOffsets}</dd>
              </div>
            </dl>
            <p className="rounded-md border border-ink-200 bg-ink-50 px-3 py-2 text-xs text-ink-600">
              Publishing validates a revision token server-side. Approved windows are not active
              outages until communication is confirmed and the lifecycle is executing.
            </p>
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
                onClick={() => setStep(useImpactFlow ? "audience" : "details")}
                disabled={busy}
              >
                Back
              </button>
              <button
                type="button"
                className="mh-btn"
                onClick={() => void (useImpactFlow ? onPublish() : onSimplePublish())}
                disabled={useImpactFlow ? !canPublish : busy}
              >
                {busy ? "Publishing…" : useImpactFlow ? "Confirm & publish" : "Publish"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
