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

export type ExperienceState = {
  profile: "essentials" | "team" | "enterprise";
  label: string;
  capabilities: ExperienceCapabilities;
  loading: boolean;
  can: (capability: string) => boolean;
  refresh: () => Promise<void>;
};

const ExperienceContext = createContext<ExperienceState | null>(null);

const DEFAULT_CAPS: ExperienceCapabilities = {
  overview: true,
  calendar: true,
  my_alerts: true,
  quick_publish: true,
  event_detail: true,
  status_pages: true,
  catalog_browse: true,
  impact_analysis: true,
  recurrence_editor: true,
  banner_embed: true,
  admin_workspace: true,
  admin_users: true,
  servicenow: true,
  csv_import: true,
  oidc_ldap_surfaces: true,
  notification_admin: true,
};

export function ExperienceProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<ExperienceState["profile"]>("enterprise");
  const [label, setLabel] = useState("Enterprise");
  const [capabilities, setCapabilities] = useState<ExperienceCapabilities>(DEFAULT_CAPS);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/experience");
      if (!res.ok) throw new Error("experience fetch failed");
      const body = (await res.json()) as {
        profile: ExperienceState["profile"];
        label: string;
        capabilities: ExperienceCapabilities;
      };
      setProfile(body.profile);
      setLabel(body.label);
      setCapabilities(body.capabilities);
    } catch {
      /* keep defaults — enterprise-safe for local without API */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const can = useCallback((capability: string) => Boolean(capabilities[capability]), [capabilities]);

  const value = useMemo(
    () => ({ profile, label, capabilities, loading, can, refresh }),
    [profile, label, capabilities, loading, can, refresh],
  );

  return <ExperienceContext.Provider value={value}>{children}</ExperienceContext.Provider>;
}

export function useExperience() {
  const ctx = useContext(ExperienceContext);
  if (!ctx) throw new Error("useExperience requires ExperienceProvider");
  return ctx;
}
