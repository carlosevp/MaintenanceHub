/**
 * @maintenancehub/banner — embeddable maintenance/outage banner (M12/M18).
 *
 * Fetches confirmed active/upcoming messages from MaintenanceHub.
 * Does not perform health monitoring. Dependency-free at runtime.
 */

export type BannerPresentation =
  | "outage"
  | "in_progress"
  | "extended"
  | "verifying"
  | "upcoming";

export type BannerMessage = {
  id: string;
  event_id?: string;
  kind: string;
  title: string;
  status: string;
  presentation?: BannerPresentation | string;
  starts_at: string;
  ends_at: string;
  expected_impact?: string | null;
  approval_state: string;
  revision?: string;
  dismissible?: boolean;
  occurrence_starts_at?: string | null;
};

export type BannerTheme = "light" | "dark" | "auto";

export type FetchBannerOptions = {
  /** API base, e.g. https://maintenancehub.example.com */
  apiBaseUrl: string;
  /**
   * Optional Bearer token. Prefer omitting this in browser embeds —
   * `/public/banner` is readable without credentials for the minimal public DTO.
   * Never place long-lived `client_secret` values in frontend code; use a BFF
   * if you need authenticated server-side fetches.
   */
  accessToken?: string;
  applicationKey: string;
  environmentKey?: string;
  /** Hours ahead for upcoming windows (server default typically 24). */
  advanceHours?: number;
  /** Use OpenShift-stable internal path instead of /public/banner. */
  internal?: boolean;
  fetchImpl?: typeof fetch;
};

export type MountBannerOptions = FetchBannerOptions & {
  /** CSS selector or element */
  target: string | HTMLElement;
  /** Poll interval ms (0 = once). Default 60_000 */
  pollIntervalMs?: number;
  className?: string;
  /** light | dark | auto (prefers-color-scheme). Default light. */
  theme?: BannerTheme;
  /** Persist dismissals for upcoming notices. Default true. */
  dismissible?: boolean;
  /** localStorage key prefix for dismissals. */
  storageKey?: string;
};

const FORBIDDEN_KEYS = new Set([
  "description",
  "timeline",
  "created_by",
  "updated_by",
  "raw_payload",
  "internal_notes",
  "note",
  "client_secret",
  "access_token",
  "password",
]);

function asPresentation(raw: unknown, kind: string, status: string): BannerPresentation {
  const p = typeof raw === "string" ? raw : "";
  if (
    p === "outage" ||
    p === "in_progress" ||
    p === "extended" ||
    p === "verifying" ||
    p === "upcoming"
  ) {
    return p;
  }
  // Never treat approved_window as outage.
  if (kind === "manual_outage" && (status === "in_progress" || status === "extended")) {
    return "outage";
  }
  if (status === "extended") return "extended";
  if (status === "verifying") return "verifying";
  if (status === "in_progress") return "in_progress";
  return "upcoming";
}

/** Strip any accidental internal fields from API payloads. */
export function sanitizeBannerMessages(raw: unknown): BannerMessage[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const src = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
    const clean: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(src)) {
      if (FORBIDDEN_KEYS.has(k)) continue;
      if (typeof k === "string" && (k.includes("secret") || k.includes("password"))) continue;
      clean[k] = v;
    }
    const kind = String(clean.kind ?? "");
    const status = String(clean.status ?? "");
    const presentation = asPresentation(clean.presentation, kind, status);
    const dismissible =
      typeof clean.dismissible === "boolean" ? clean.dismissible : presentation === "upcoming";
    return {
      id: String(clean.id ?? ""),
      event_id: clean.event_id != null ? String(clean.event_id) : undefined,
      kind,
      title: String(clean.title ?? ""),
      status,
      presentation,
      starts_at: String(clean.starts_at ?? ""),
      ends_at: String(clean.ends_at ?? ""),
      expected_impact: (clean.expected_impact as string | null | undefined) ?? null,
      approval_state: String(clean.approval_state ?? ""),
      revision: clean.revision != null ? String(clean.revision) : undefined,
      dismissible,
      occurrence_starts_at:
        clean.occurrence_starts_at != null ? String(clean.occurrence_starts_at) : null,
    };
  });
}

export async function fetchBannerMessages(opts: FetchBannerOptions): Promise<BannerMessage[]> {
  const fetchFn = opts.fetchImpl ?? fetch;
  const base = opts.apiBaseUrl.replace(/\/$/, "");
  const params = new URLSearchParams({ application_key: opts.applicationKey });
  if (opts.environmentKey) params.set("environment_key", opts.environmentKey);
  if (opts.advanceHours != null) params.set("advance_hours", String(opts.advanceHours));
  const path = opts.internal ? "/api/v1/internal/banner" : "/api/v1/public/banner";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.accessToken) {
    headers.Authorization = `Bearer ${opts.accessToken}`;
  }
  let res: Response;
  try {
    res = await fetchFn(`${base}${path}?${params}`, { headers });
  } catch (err) {
    // Graceful host failure — network / CORS / offline
    throw new Error(`Banner fetch failed: network error (${String(err)})`);
  }
  if (!res.ok) {
    throw new Error(`Banner fetch failed: ${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  return sanitizeBannerMessages(data);
}

function formatWindow(start: string, end: string): string {
  try {
    const s = new Date(start);
    const e = new Date(end);
    return `${s.toLocaleString()} → ${e.toLocaleString()}`;
  } catch {
    return `${start} → ${end}`;
  }
}

function kindLabel(kind: string): string {
  return kind === "manual_outage" ? "Outage" : "Maintenance";
}

function presentationLabel(p: string): string {
  switch (p) {
    case "outage":
      return "Outage";
    case "in_progress":
      return "In progress";
    case "extended":
      return "Extended";
    case "verifying":
      return "Verifying";
    default:
      return "Upcoming";
  }
}

function dismissStorageKey(
  prefix: string,
  applicationKey: string,
  environmentKey: string | undefined,
  messageId: string,
): string {
  return `${prefix}:${applicationKey}:${environmentKey || "*"}:${messageId}`;
}

export function isDismissed(
  message: BannerMessage,
  opts: { applicationKey: string; environmentKey?: string; storageKey?: string },
): boolean {
  if (typeof localStorage === "undefined") return false;
  if (!message.dismissible) return false;
  const key = dismissStorageKey(
    opts.storageKey ?? "mh-banner-dismiss",
    opts.applicationKey,
    opts.environmentKey,
    message.id,
  );
  try {
    const stored = localStorage.getItem(key);
    if (!stored) return false;
    const revision = message.revision || `${message.ends_at}|${message.status}`;
    return stored === revision;
  } catch {
    return false;
  }
}

export function dismissMessage(
  message: BannerMessage,
  opts: { applicationKey: string; environmentKey?: string; storageKey?: string },
): void {
  if (typeof localStorage === "undefined") return;
  if (!message.dismissible) return;
  const key = dismissStorageKey(
    opts.storageKey ?? "mh-banner-dismiss",
    opts.applicationKey,
    opts.environmentKey,
    message.id,
  );
  const revision = message.revision || `${message.ends_at}|${message.status}`;
  try {
    localStorage.setItem(key, revision);
  } catch {
    /* ignore quota / private mode */
  }
}

export function filterVisibleMessages(
  messages: BannerMessage[],
  opts: {
    applicationKey: string;
    environmentKey?: string;
    storageKey?: string;
    dismissible?: boolean;
  },
): BannerMessage[] {
  if (opts.dismissible === false) return messages;
  return messages.filter((m) => !isDismissed(m, opts));
}

export function renderBannerHtml(
  messages: BannerMessage[],
  className = "mh-banner",
  options?: { theme?: BannerTheme; showDismiss?: boolean },
): string {
  const theme = options?.theme ?? "light";
  const themeAttr = theme === "auto" ? "auto" : theme;
  if (!messages.length) {
    return `<div class="${className} ${className}--empty" data-theme="${themeAttr}" role="status" hidden></div>`;
  }
  const items = messages
    .map((m) => {
      const presentation = asPresentation(m.presentation, m.kind, m.status);
      const outage = presentation === "outage" || m.kind === "manual_outage";
      const dismissBtn =
        options?.showDismiss && m.dismissible
          ? `<button type="button" class="${className}__dismiss" data-mh-dismiss="${escapeHtml(m.id)}" aria-label="Dismiss upcoming notice">Dismiss</button>`
          : "";
      return `<li class="${className}__item ${outage ? className + "__item--outage" : ""} ${className}__item--${presentation}" data-mh-id="${escapeHtml(m.id)}" data-mh-revision="${escapeHtml(m.revision || "")}">
  <div class="${className}__meta">
    <span class="${className}__kind" aria-label="Kind: ${kindLabel(m.kind)}">${kindLabel(m.kind)}</span>
    <span class="${className}__status" aria-label="Status: ${presentationLabel(presentation)}">${presentationLabel(presentation)}</span>
    ${dismissBtn}
  </div>
  <strong class="${className}__title">${escapeHtml(m.title)}</strong>
  <span class="${className}__window">${escapeHtml(formatWindow(m.starts_at, m.ends_at))}</span>
  ${
    m.expected_impact
      ? `<span class="${className}__impact">Impact: ${escapeHtml(m.expected_impact)}</span>`
      : ""
  }
</li>`;
    })
    .join("");
  return `<aside class="${className}" data-theme="${themeAttr}" role="region" aria-label="Maintenance and outage communications" aria-live="polite">
  <p class="${className}__heading">MaintenanceHub notices</p>
  <ul class="${className}__list">${items}</ul>
</aside>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export type BannerHandle = {
  refresh: () => Promise<void>;
  destroy: () => void;
};

/**
 * Mount a live banner into the DOM. Returns handle to refresh/destroy.
 * Host failures render a soft error; empty results hide the region.
 */
export function mountMaintenanceBanner(opts: MountBannerOptions): BannerHandle {
  const el =
    typeof opts.target === "string" ? document.querySelector(opts.target) : opts.target;
  if (!el) {
    throw new Error(`Banner target not found: ${String(opts.target)}`);
  }
  const className = opts.className ?? "mh-banner";
  const theme = opts.theme ?? "light";
  const allowDismiss = opts.dismissible !== false;
  let timer: ReturnType<typeof setInterval> | undefined;
  let messagesCache: BannerMessage[] = [];

  const onClick = (ev: Event) => {
    const t = ev.target as HTMLElement | null;
    if (!t) return;
    const btn = t.closest("[data-mh-dismiss]") as HTMLElement | null;
    if (!btn) return;
    const id = btn.getAttribute("data-mh-dismiss");
    const msg = messagesCache.find((m) => m.id === id);
    if (!msg) return;
    dismissMessage(msg, {
      applicationKey: opts.applicationKey,
      environmentKey: opts.environmentKey,
      storageKey: opts.storageKey,
    });
    void refresh();
  };
  el.addEventListener("click", onClick);

  const refresh = async () => {
    try {
      const raw = await fetchBannerMessages(opts);
      messagesCache = raw;
      const visible = filterVisibleMessages(raw, {
        applicationKey: opts.applicationKey,
        environmentKey: opts.environmentKey,
        storageKey: opts.storageKey,
        dismissible: allowDismiss,
      });
      el.innerHTML = renderBannerHtml(visible, className, {
        theme,
        showDismiss: allowDismiss,
      });
    } catch (err) {
      el.innerHTML = `<div class="${className} ${className}--error" data-theme="${theme}" role="alert">Unable to load maintenance notices.</div>`;
      console.warn("[MaintenanceHub banner]", err);
    }
  };

  void refresh();
  const interval = opts.pollIntervalMs ?? 60_000;
  if (interval > 0) {
    timer = setInterval(() => void refresh(), interval);
  }

  return {
    refresh,
    destroy: () => {
      if (timer) clearInterval(timer);
      el.removeEventListener("click", onClick);
      el.innerHTML = "";
    },
  };
}

/** Build a copy-paste snippet for host apps (Claims INT, etc.). */
export function buildEmbedSnippet(opts: {
  apiBaseUrl: string;
  applicationKey: string;
  environmentKey?: string;
  theme?: BannerTheme;
  advanceHours?: number;
  /** Absolute URL to embed.js (dependency-free IIFE). */
  embedScriptUrl?: string;
  styleUrl?: string;
}): string {
  const theme = opts.theme ?? "light";
  const envLine = opts.environmentKey
    ? `\n  environmentKey: ${JSON.stringify(opts.environmentKey)},`
    : "";
  const adv =
    opts.advanceHours != null ? `\n  advanceHours: ${Number(opts.advanceHours)},` : "";
  const scriptSrc = opts.embedScriptUrl || "/vendor/maintenancehub-banner/embed.js";
  const styleHref = opts.styleUrl || "/vendor/maintenancehub-banner/style.css";
  return `<!-- MaintenanceHub banner — confirmed notices only; no secrets -->
<link rel="stylesheet" href="${styleHref}" />
<div id="mh-banner-root"></div>
<script src="${scriptSrc}" defer></script>
<script>
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.MaintenanceHubBanner) return;
    window.MaintenanceHubBanner.mount({
      target: "#mh-banner-root",
      apiBaseUrl: ${JSON.stringify(opts.apiBaseUrl)},
      applicationKey: ${JSON.stringify(opts.applicationKey)},${envLine}${adv}
      theme: ${JSON.stringify(theme)},
      pollIntervalMs: 60000
    });
  });
</script>`;
}
