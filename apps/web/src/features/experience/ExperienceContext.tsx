import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ExperienceCapabilities = Record<string, boolean>;

export type DemoScenario = {
  id: string;
  label: string;
  summary: string;
  profile_hint: string;
  focus: Record<string, string>;
  available: boolean;
  blocked_by?: string[];
};

export type ExperienceState = {
  profile: "essentials" | "team" | "enterprise";
  label: string;
  capabilities: ExperienceCapabilities;
  scenarios: DemoScenario[];
  activeScenarioId: string | null;
  setActiveScenarioId: (id: string | null) => void;
  activeScenario: DemoScenario | null;
  loading: boolean;
  can: (capability: string) => boolean;
  refresh: () => Promise<void>;
};

const ExperienceContext = createContext<ExperienceState | null>(null);

/** Fail-closed defaults when API unreachable — Essentials, never silent Enterprise. */
const DEFAULT_CAPS: ExperienceCapabilities = {
  overview: true,
  calendar: true,
  my_alerts: true,
  quick_publish: true,
  event_detail: true,
  status_pages: true,
  catalog_browse: true,
  impact_analysis: false,
  recurrence_editor: false,
  banner_embed: false,
  admin_workspace: false,
  admin_users: false,
  servicenow: false,
  csv_import: false,
  oidc_ldap_surfaces: false,
  notification_admin: false,
  demo_scenarios: true,
};

export function ExperienceProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<ExperienceState["profile"]>("essentials");
  const [label, setLabel] = useState("Essentials");
  const [capabilities, setCapabilities] = useState<ExperienceCapabilities>(DEFAULT_CAPS);
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/experience");
      if (!res.ok) throw new Error("experience fetch failed");
      const body = (await res.json()) as {
        profile: ExperienceState["profile"];
        label: string;
        capabilities: ExperienceCapabilities;
        scenarios?: DemoScenario[];
      };
      setProfile(body.profile);
      setLabel(body.label);
      setCapabilities(body.capabilities);
      setScenarios(body.scenarios ?? []);
    } catch {
      /* keep Essentials defaults — never unlock Enterprise silently */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const can = useCallback(
    (capability: string) => Boolean(capabilities[capability] === true),
    [capabilities],
  );

  const activeScenario = useMemo(
    () => scenarios.find((s) => s.id === activeScenarioId) ?? null,
    [scenarios, activeScenarioId],
  );

  const value = useMemo(
    () => ({
      profile,
      label,
      capabilities,
      scenarios,
      activeScenarioId,
      setActiveScenarioId,
      activeScenario,
      loading,
      can,
      refresh,
    }),
    [
      profile,
      label,
      capabilities,
      scenarios,
      activeScenarioId,
      activeScenario,
      loading,
      can,
      refresh,
    ],
  );

  return <ExperienceContext.Provider value={value}>{children}</ExperienceContext.Provider>;
}

export function useExperience() {
  const ctx = useContext(ExperienceContext);
  if (!ctx) throw new Error("useExperience requires ExperienceProvider");
  return ctx;
}
