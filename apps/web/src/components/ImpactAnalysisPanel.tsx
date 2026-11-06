import { useEffect, useId, useRef, useState } from "react";
import {
  api,
  type ImpactPreview,
  type ImpactSeed,
  type SuggestedImpact,
} from "@/api/client";
import {
  createPreviewRequestGate,
  impactSeedKey,
  selectionFingerprint,
  type ConfirmReady,
  type ExclusionRow,
} from "@/lib/impactPreviewSession";
import { seedsKey } from "@/lib/zonedDateTime";

type Props = {
  seeds: ImpactSeed[];
  startsAt: string;
  endsAt: string;
  eventId?: string | null;
  originalStartsAt?: string | null;
  /** Lifted reviewed decisions — survive Details ↔ Impact navigation */
  exclusions: ExclusionRow[];
  manuals: ImpactSeed[];
  onExclusionsChange: (rows: ExclusionRow[]) => void;
  onManualsChange: (rows: ImpactSeed[]) => void;
  onConfirmReady: (state: ConfirmReady | null) => void;
  onPreviewStatus: (status: { busy: boolean; error: string | null; ok: boolean }) => void;
};

function pathLabel(sug: SuggestedImpact): string {
  if (!sug.paths?.length) return "No path recorded";
  return sug.paths
    .slice(0, 2)
    .map((p) =>
      p
        .map(
          (h) =>
            `${h.consumer_name}${h.consumer_environment_key ? ` (${h.consumer_environment_key})` : ""} → ${h.provider_name}${h.provider_environment_key ? ` (${h.provider_environment_key})` : ""} [${h.origin}]`,
        )
        .join(" · "),
    )
    .join(" | ");
}

export function ImpactAnalysisPanel({
  seeds,
  startsAt,
  endsAt,
  eventId,
  originalStartsAt,
  exclusions,
  manuals,
  onExclusionsChange,
  onManualsChange,
  onConfirmReady,
  onPreviewStatus,
}: Props) {
  const baseId = useId();
  const [preview, setPreview] = useState<ImpactPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [manualAppId, setManualAppId] = useState("");
  const [manualEnvId, setManualEnvId] = useState("");
  const [apps, setApps] = useState<Array<{ id: string; name: string }>>([]);
  const [envs, setEnvs] = useState<Array<{ id: string; key: string }>>([]);
  const gateRef = useRef(createPreviewRequestGate());
  const onConfirmReadyRef = useRef(onConfirmReady);
  const onPreviewStatusRef = useRef(onPreviewStatus);
  onConfirmReadyRef.current = onConfirmReady;
  onPreviewStatusRef.current = onPreviewStatus;

  const excludedMap = Object.fromEntries(
    exclusions.map((e) => [impactSeedKey(e), e]),
  );

  async function runPreview(nextExclusions: ExclusionRow[] = exclusions, nextManuals: ImpactSeed[] = manuals) {
    if (!seeds.length || !startsAt || !endsAt) return;
    const reqId = gateRef.current.next();
    // Selection change immediately invalidates any prior confirm token
    onConfirmReadyRef.current(null);
    setBusy(true);
    setError(null);
    onPreviewStatusRef.current({ busy: true, error: null, ok: false });
    try {
      const body = {
        seeds,
        starts_at: startsAt,
        ends_at: endsAt,
        event_id: eventId || undefined,
        original_starts_at: originalStartsAt || undefined,
        exclusions: nextExclusions.map((e) => ({
          target_type: e.target_type,
          target_id: e.target_id,
          environment_id: e.environment_id ?? null,
          reason: e.reason || "Excluded by publisher",
        })),
        manual_additions: nextManuals,
        max_depth: 5,
      };
      const p = await api.impactPreview(body);
      if (!gateRef.current.isCurrent(reqId)) return;
      setPreview(p);
      const includeDownstream = (p.suggested_downstream || [])
        .filter((s) => s.selection !== "excluded")
        .filter((s) => !nextExclusions.some((e) => impactSeedKey(e) === impactSeedKey(s)))
        .map((s) => ({
          target_type: s.target_type,
          target_id: s.target_id,
          environment_id: s.environment_id ?? null,
        }));
      const exclusionsNormalized = nextExclusions.map((e) => ({
        ...e,
        reason: e.reason || "Excluded by publisher",
      }));
      const ready: ConfirmReady = {
        revisionToken: p.revision_token,
        exclusions: exclusionsNormalized,
        manualAdditions: nextManuals,
        includeDownstream,
        selectionFingerprint: selectionFingerprint(
          exclusionsNormalized,
          nextManuals,
          includeDownstream,
        ),
      };
      onConfirmReadyRef.current(ready);
      onPreviewStatusRef.current({ busy: false, error: null, ok: true });
      setError(null);
    } catch (err) {
      if (!gateRef.current.isCurrent(reqId)) return;
      const msg = err instanceof Error ? err.message : "Preview failed";
      setError(msg);
      setPreview(null);
      onConfirmReadyRef.current(null);
      onPreviewStatusRef.current({ busy: false, error: msg, ok: false });
    } finally {
      if (gateRef.current.isCurrent(reqId)) setBusy(false);
    }
  }

  useEffect(() => {
    void (async () => {
      const [a, e] = await Promise.all([api.applications(), api.environments()]);
      setApps(a.map((x) => ({ id: x.id, name: x.name })));
      setEnvs(e.map((x) => ({ id: x.id, key: x.key })));
      if (a[0]) setManualAppId(a[0].id);
      if (e[0]) setManualEnvId(e[0].id);
    })();
  }, []);

  const seedFp = seedsKey(seeds);
  useEffect(() => {
    void runPreview(exclusions, manuals);
    // Re-run when window/seeds/event identity change — not on every parent callback identity
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedFp, startsAt, endsAt, eventId, originalStartsAt]);

  function toggleExclude(row: SuggestedImpact) {
    const key = impactSeedKey(row);
    const exists = exclusions.some((e) => impactSeedKey(e) === key);
    const next = exists
      ? exclusions.filter((e) => impactSeedKey(e) !== key)
      : [
          ...exclusions,
          {
            target_type: row.target_type,
            target_id: row.target_id,
            environment_id: row.environment_id ?? null,
            reason: "Excluded by publisher",
          },
        ];
    onExclusionsChange(next);
    void runPreview(next, manuals);
  }

  function commitExclusionReason(row: SuggestedImpact, reason: string) {
    const key = impactSeedKey(row);
    const next = exclusions.map((e) =>
      impactSeedKey(e) === key ? { ...e, reason } : e,
    );
    onExclusionsChange(next);
    void runPreview(next, manuals);
  }

  function addManual() {
    if (!manualAppId) return;
    const row: ImpactSeed = {
      target_type: "application",
      target_id: manualAppId,
      environment_id: manualEnvId || null,
    };
    if (manuals.some((m) => impactSeedKey(m) === impactSeedKey(row))) return;
    const next = [...manuals, row];
    onManualsChange(next);
    void runPreview(exclusions, next);
  }

  function removeManual(index: number) {
    const next = manuals.filter((_, j) => j !== index);
    onManualsChange(next);
    void runPreview(exclusions, next);
  }

  return (
    <section className="space-y-4" aria-labelledby={`${baseId}-heading`} aria-busy={busy}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id={`${baseId}-heading`} className="font-display text-xl font-semibold text-ink-950">
            Impact analysis
          </h2>
          <p className="mt-1 text-sm text-ink-600">
            Review direct targets, downstream suggestions, reach, and advisory conflicts before
            publish. Preview never sends notifications.
          </p>
        </div>
        <button
          type="button"
          className="mh-btn-ghost"
          onClick={() => void runPreview()}
          disabled={busy}
        >
          {busy ? "Analyzing…" : "Refresh preview"}
        </button>
      </div>

      {error && (
        <p
          className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
          role="alert"
        >
          {error}
        </p>
      )}

      {preview && (
        <>
          <div className="grid gap-3 sm:grid-cols-3" role="group" aria-label="Preview summary">
            <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Direct</p>
              <p className="text-lg font-semibold text-ink-900">{preview.direct_targets.length}</p>
            </div>
            <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Suggested</p>
              <p className="text-lg font-semibold text-ink-900">
                {preview.suggested_downstream.length}
              </p>
            </div>
            <div className="rounded-lg border border-ink-200 bg-ink-50/60 px-3 py-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Audience</p>
              <p className="text-lg font-semibold text-ink-900">
                {preview.audience.unique_recipients} unique
              </p>
            </div>
          </div>

          {preview.warnings.length > 0 && (
            <ul
              className="space-y-1 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-950"
              aria-label="Freshness and data warnings"
            >
              {preview.warnings.map((w, i) => (
                <li key={`${w.code}-${i}`}>
                  <span className="font-medium">{w.code}:</span> {w.message}
                </li>
              ))}
            </ul>
          )}

          <div>
            <h3 className="text-sm font-semibold text-ink-800">Direct targets</h3>
            <ul className="mt-2 divide-y divide-ink-100 rounded-lg border border-ink-200">
              {preview.direct_targets.map((d) => (
                <li key={impactSeedKey(d)} className="px-3 py-2 text-sm">
                  <span className="font-medium text-ink-900">{d.display_name}</span>
                  <span className="text-ink-500">
                    {" "}
                    · {d.target_type}
                    {d.environment_key ? ` / ${d.environment_key}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 className="text-sm font-semibold text-ink-800">Suggested downstream</h3>
            <p className="text-xs text-ink-500">
              Include notifies subscribers of possible impact — it does not mark those apps
              unavailable.
            </p>
            <ul className="mt-2 divide-y divide-ink-100 rounded-lg border border-ink-200">
              {preview.suggested_downstream.length === 0 && (
                <li className="px-3 py-2 text-sm text-ink-500">No recorded dependents.</li>
              )}
              {preview.suggested_downstream.map((s) => {
                const key = impactSeedKey(s);
                const isEx = Boolean(excludedMap[key]) || s.selection === "excluded";
                const open = expanded[key];
                return (
                  <li key={key} className="px-3 py-2">
                    <div className="flex flex-wrap items-start gap-2">
                      <button
                        type="button"
                        className="text-left text-sm font-medium text-ink-900 underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                        aria-expanded={open}
                        onClick={() => setExpanded((p) => ({ ...p, [key]: !open }))}
                      >
                        {s.display_name}
                        {s.environment_key ? ` (${s.environment_key})` : ""}
                      </button>
                      <span className="rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-600">
                        {s.classification}
                      </span>
                      <div className="ml-auto flex gap-2">
                        <button
                          type="button"
                          className="mh-btn-ghost !px-2 !py-1 text-xs"
                          aria-pressed={isEx}
                          onClick={() => toggleExclude(s)}
                        >
                          {isEx ? "Include" : "Exclude"}
                        </button>
                      </div>
                    </div>
                    {isEx && (
                      <label className="mt-2 block text-xs text-ink-600">
                        Exclusion reason
                        <input
                          className="mh-input mt-1"
                          defaultValue={excludedMap[key]?.reason ?? ""}
                          onBlur={(e) => commitExclusionReason(s, e.target.value)}
                        />
                      </label>
                    )}
                    {open && (
                      <div className="mt-2 space-y-1 text-xs text-ink-600">
                        <p>{pathLabel(s)}</p>
                        {s.warnings?.map((w) => (
                          <p key={w} className="text-amber-800">
                            {w}
                          </p>
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>

          <fieldset className="rounded-lg border border-dashed border-ink-200 p-3">
            <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-ink-500">
              Manually add affected application
            </legend>
            <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <select
                className="mh-input"
                value={manualAppId}
                onChange={(e) => setManualAppId(e.target.value)}
                aria-label="Manual application"
              >
                {apps.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
              <select
                className="mh-input"
                value={manualEnvId}
                onChange={(e) => setManualEnvId(e.target.value)}
                aria-label="Manual environment"
              >
                {envs.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.key}
                  </option>
                ))}
              </select>
              <button type="button" className="mh-btn-ghost" onClick={addManual}>
                Add
              </button>
            </div>
            {manuals.length > 0 && (
              <ul className="mt-2 space-y-1 text-sm">
                {manuals.map((m, i) => (
                  <li key={`${m.target_id}-${i}`} className="flex justify-between gap-2">
                    <span>
                      {apps.find((a) => a.id === m.target_id)?.name ?? m.target_id}
                      {m.environment_id
                        ? ` / ${envs.find((e) => e.id === m.environment_id)?.key ?? ""}`
                        : ""}
                    </span>
                    <button
                      type="button"
                      className="text-xs text-danger underline"
                      onClick={() => removeManual(i)}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </fieldset>

          <div className="grid gap-3 lg:grid-cols-2">
            <div className="rounded-lg border border-ink-200 p-3">
              <h3 className="text-sm font-semibold text-ink-800">Notification reach</h3>
              <p className="mt-1 text-xs text-ink-500">{preview.audience.note}</p>
              <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
                <div>
                  <dt className="text-ink-500">Unique recipients</dt>
                  <dd className="font-semibold">{preview.audience.unique_recipients}</dd>
                </div>
                <div>
                  <dt className="text-ink-500">Subscriptions</dt>
                  <dd className="font-semibold">{preview.audience.subscription_count}</dd>
                </div>
              </dl>
              {!preview.audience.destinations_redacted &&
                preview.audience.email_destinations.length > 0 && (
                  <ul
                    className="mt-2 max-h-28 overflow-auto text-xs text-ink-700"
                    aria-label="Email destinations"
                  >
                    {preview.audience.email_destinations.map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                )}
              {!preview.audience.destinations_redacted &&
                preview.audience.teams_bridge_channels.length > 0 && (
                  <ul className="mt-1 text-xs text-ink-700" aria-label="Teams bridge channels">
                    {preview.audience.teams_bridge_channels.map((t) => (
                      <li key={t}>Teams: {t}</li>
                    ))}
                  </ul>
                )}
            </div>
            <div className="rounded-lg border border-ink-200 p-3">
              <h3 className="text-sm font-semibold text-ink-800">Scheduling conflicts</h3>
              <p className="mt-1 text-xs text-ink-500">Advisory only — does not block publish.</p>
              {preview.conflicts.length === 0 ? (
                <p className="mt-2 text-sm text-ink-500">No overlapping windows detected.</p>
              ) : (
                <ul className="mt-2 space-y-2 text-sm">
                  {preview.conflicts.map((c) => (
                    <li
                      key={`${c.event_id}-${c.occurrence_id}`}
                      className="rounded border border-ink-100 px-2 py-1.5"
                    >
                      <p className="font-medium text-ink-900">{c.title}</p>
                      <p className="text-xs text-ink-600">
                        {c.classification} — {c.explanation}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>

          <p className="text-[11px] text-ink-400">
            Revision token {preview.revision_token} · impact_revision {preview.impact_revision}
          </p>
        </>
      )}
    </section>
  );
}
