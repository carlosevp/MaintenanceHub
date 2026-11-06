import { useNavigate } from "react-router-dom";
import { useExperience } from "@/features/experience/ExperienceContext";

/**
 * Presentation-only demo story picker. Does not change EXPERIENCE_PROFILE
 * and cannot unlock APIs that the capability registry disables.
 */
export function ScenarioSelector() {
  const { scenarios, activeScenarioId, setActiveScenarioId, profile, can } = useExperience();
  const navigate = useNavigate();

  if (!can("demo_scenarios") || scenarios.length === 0) return null;

  return (
    <details
      className="mh-panel p-4"
      data-testid="scenario-selector"
      open={Boolean(activeScenarioId)}
    >
      <summary
        id="demo-stories-heading"
        className="cursor-pointer list-none font-display text-lg font-semibold text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden"
      >
        <span className="flex flex-wrap items-center justify-between gap-2">
          <span>Demo stories</span>
          <span className="text-xs font-sans font-medium uppercase tracking-wide text-ink-muted">
            Presentation only · {profile}
          </span>
        </span>
      </summary>
      <p className="mt-2 text-sm text-ink-muted">
        Guided paths through seeded data. Choosing a story cannot enable disabled APIs.
      </p>
      {activeScenarioId && (
        <button
          type="button"
          className="mh-btn-ghost mt-2 text-xs"
          onClick={() => setActiveScenarioId(null)}
        >
          Clear story
        </button>
      )}
      <ul className="mt-3 grid gap-2 sm:grid-cols-3" aria-labelledby="demo-stories-heading">
        {scenarios.map((s) => {
          const active = activeScenarioId === s.id;
          return (
            <li key={s.id}>
              <button
                type="button"
                disabled={!s.available}
                aria-pressed={active}
                title={
                  s.available
                    ? s.summary
                    : `Needs: ${(s.blocked_by || []).join(", ")} (restart demo with a higher profile)`
                }
                className={
                  active
                    ? "w-full rounded-md border border-accent bg-accent-soft px-3 py-2 text-left text-sm"
                    : s.available
                      ? "w-full rounded-md border border-ink-200 bg-surface-raised px-3 py-2 text-left text-sm hover:bg-accent-soft"
                      : "w-full cursor-not-allowed rounded-md border border-ink-200 px-3 py-2 text-left text-sm opacity-50"
                }
                onClick={() => {
                  if (!s.available) return;
                  setActiveScenarioId(s.id);
                  const path = s.focus?.path || "/";
                  navigate(path);
                }}
              >
                <div className="font-semibold text-ink">{s.label}</div>
                <div className="mt-1 text-xs text-ink-muted">{s.summary}</div>
                {!s.available && (
                  <div className="mt-1 text-xs text-warn">
                    Unavailable on {profile}
                    {s.blocked_by?.length
                      ? ` — restart with make demo-team or make demo-enterprise`
                      : ""}
                  </div>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
