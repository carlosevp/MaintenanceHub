/**
 * @maintenancehub/banner — embeddable maintenance/outage banner (M12/M18 harden).
 *
 * Fetches confirmed active/upcoming messages from MaintenanceHub.
 * Does not perform health monitoring. Dependency-free at runtime.
 * Compact-by-default: one primary notice + optional "View additional".
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
  status_path?: string | null;
};

export type BannerTheme = "light" | "dark" | "auto";

/** How the host reaches MaintenanceHub. */
export type BannerRouteKind = "browser" | "corporate" | "in_cluster" | "local_dev";

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
  /**
   * IANA timezone for Intl display (e.g. America/Chicago).
   * Default: viewer local timezone via Intl.
   */
  timeZone?: string;
  /** Locale for Intl (default: viewer locale / undefined). */
  locale?: string;
  /**
   * HTTPS origin for status page links (corporate MH UI).
   * Combined with message.status_path. Omit to hide links.
   */
  statusPageBaseUrl?: string;
  /** Compact = primary only + "View additional". Default true. */
  compact?: boolean;
  /** Start expanded when compact. Default false. */
  expanded?: boolean;
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

const PRESENTATION_RANK: Record<string, number> = {
  outage: 0,
  extended: 1,
  in_progress: 2,
  verifying: 3,
  upcoming: 4,
};

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

/** Logical identity — event + occurrence slot, never title alone. */
export function logicalMessageKey(m: BannerMessage): string {
  const eventId = m.event_id || m.id;
  if (m.occurrence_starts_at) return `${eventId}|${m.occurrence_starts_at}`;
  return `${eventId}|${m.id}`;
}

/** Dedupe + deterministic order (matches API multi-notice policy). */
export function normalizeBannerMessages(messages: BannerMessage[]): BannerMessage[] {
  const best = new Map<string, BannerMessage>();
  for (const m of messages) {
    const key = logicalMessageKey(m);
    const prev = best.get(key);
    if (!prev) {
      best.set(key, m);
      continue;
    }
    const pr = PRESENTATION_RANK[String(prev.presentation)] ?? 9;
    const nr = PRESENTATION_RANK[String(m.presentation)] ?? 9;
    if (nr < pr) best.set(key, m);
    else if (nr === pr) {
      if (`${m.starts_at}|${m.id}` < `${prev.starts_at}|${prev.id}`) best.set(key, m);
    }
  }
  return [...best.values()].sort((a, b) => {
    const ra = PRESENTATION_RANK[String(a.presentation)] ?? 9;
    const rb = PRESENTATION_RANK[String(b.presentation)] ?? 9;
    if (ra !== rb) return ra - rb;
    if (a.starts_at !== b.starts_at) return a.starts_at < b.starts_at ? -1 : 1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

/** Strip any accidental internal fields from API payloads. */
export function sanitizeBannerMessages(raw: unknown): BannerMessage[] {
  if (!Array.isArray(raw)) return [];
  const mapped = raw.map((item) => {
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
      status_path: clean.status_path != null ? String(clean.status_path) : null,
    };
  });
  return normalizeBannerMessages(mapped);
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
    throw new Error(`Banner fetch failed: network error (${String(err)})`);
  }
  if (!res.ok) {
    throw new Error(`Banner fetch failed: ${res.status} ${res.statusText}`);
  }
  const data = await res.json();
  return sanitizeBannerMessages(data);
}

/** Viewer timezone via Intl, with optional IANA override. */
export function resolveTimeZone(explicit?: string): string | undefined {
  if (explicit && explicit.trim()) return explicit.trim();
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return undefined;
  }
}

/**
 * Human-readable window via Intl (API remains ISO).
 * DST-aware when IANA zone is supplied / resolved.
 */
export function formatWindowIntl(
  start: string,
  end: string,
  opts?: { locale?: string; timeZone?: string },
): string {
  try {
    const s = new Date(start);
    const e = new Date(end);
    if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) {
      return `${start} → ${end}`;
    }
    const tz = resolveTimeZone(opts?.timeZone);
    const fmtOpts: Intl.DateTimeFormatOptions = {
      dateStyle: "medium",
      timeStyle: "short",
      ...(tz ? { timeZone: tz } : {}),
    };
    const fmt = new Intl.DateTimeFormat(opts?.locale, fmtOpts);
    return `${fmt.format(s)} → ${fmt.format(e)}`;
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
  const normalized = normalizeBannerMessages(messages);
  if (opts.dismissible === false) return normalized;
  return normalized.filter((m) => !isDismissed(m, opts));
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderItem(
  m: BannerMessage,
  className: string,
  options: {
    showDismiss?: boolean;
    timeZone?: string;
    locale?: string;
    statusPageBaseUrl?: string;
    primary?: boolean;
  },
): string {
  const presentation = asPresentation(m.presentation, m.kind, m.status);
  const outage = presentation === "outage";
  const dismissBtn =
    options.showDismiss && m.dismissible
      ? `<button type="button" class="${className}__dismiss" data-mh-dismiss="${escapeHtml(m.id)}" aria-label="Dismiss upcoming notice">Dismiss</button>`
      : "";
  const statusHref =
    options.statusPageBaseUrl && m.status_path
      ? `${options.statusPageBaseUrl.replace(/\/$/, "")}${m.status_path.startsWith("/") ? m.status_path : `/${m.status_path}`}`
      : null;
  const statusLink = statusHref
    ? `<a class="${className}__status-link" href="${escapeHtml(statusHref)}" rel="noopener noreferrer">Status</a>`
    : "";
  const primaryClass = options.primary ? ` ${className}__item--primary` : "";
  return `<li class="${className}__item ${outage ? className + "__item--outage" : ""} ${className}__item--${presentation}${primaryClass}" data-mh-id="${escapeHtml(m.id)}" data-mh-revision="${escapeHtml(m.revision || "")}">
  <div class="${className}__meta">
    <span class="${className}__kind">${kindLabel(m.kind)}</span>
    <span class="${className}__status">${presentationLabel(presentation)}</span>
    ${statusLink}
    ${dismissBtn}
  </div>
  <strong class="${className}__title">${escapeHtml(m.title)}</strong>
  <span class="${className}__window">${escapeHtml(formatWindowIntl(m.starts_at, m.ends_at, { locale: options.locale, timeZone: options.timeZone }))}</span>
  ${
    m.expected_impact
      ? `<span class="${className}__impact">Impact: ${escapeHtml(m.expected_impact)}</span>`
      : ""
  }
</li>`;
}

export function renderBannerHtml(
  messages: BannerMessage[],
  className = "mh-banner",
  options?: {
    theme?: BannerTheme;
    showDismiss?: boolean;
    timeZone?: string;
    locale?: string;
    statusPageBaseUrl?: string;
    compact?: boolean;
    expanded?: boolean;
  },
): string {
  const theme = options?.theme ?? "light";
  const themeAttr = theme === "auto" ? "auto" : theme;
  const list = normalizeBannerMessages(messages);
  if (!list.length) {
    return `<div class="${className} ${className}--empty" data-theme="${themeAttr}" role="status" hidden></div>`;
  }

  const compact = options?.compact !== false;
  const expanded = Boolean(options?.expanded);
  const primary = list[0];
  const additional = list.slice(1);
  const showAll = !compact || expanded || additional.length === 0;
  const visible = showAll ? list : [primary];

  const items = visible
    .map((m, i) =>
      renderItem(m, className, {
        showDismiss: options?.showDismiss,
        timeZone: options?.timeZone,
        locale: options?.locale,
        statusPageBaseUrl: options?.statusPageBaseUrl,
        primary: i === 0,
      }),
    )
    .join("");

  const toggle =
    compact && additional.length > 0
      ? `<button type="button" class="${className}__more" data-mh-toggle-more aria-expanded="${showAll ? "true" : "false"}">${
          showAll ? "Show less" : `View ${additional.length} additional`
        }</button>`
      : "";

  return `<aside class="${className}" data-theme="${themeAttr}" data-mh-compact="${compact ? "1" : "0"}" data-mh-expanded="${showAll ? "1" : "0"}" role="region" aria-label="Maintenance and outage communications" aria-live="polite">
  <p class="${className}__heading">MaintenanceHub notices</p>
  <ul class="${className}__list">${items}</ul>
  ${toggle}
</aside>`;
}

export type BannerHandle = {
  refresh: () => Promise<void>;
  destroy: () => void;
  setExpanded: (expanded: boolean) => void;
};

/**
 * Mount a live banner into the DOM. Returns handle to refresh/destroy.
 * Host failures render a soft error; empty results hide the region.
 * Scoped class prefix avoids host CSS breakage.
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
  const compact = opts.compact !== false;
  let expanded = Boolean(opts.expanded);
  let timer: ReturnType<typeof setInterval> | undefined;
  let messagesCache: BannerMessage[] = [];

  const paint = (visible: BannerMessage[]) => {
    el.innerHTML = renderBannerHtml(visible, className, {
      theme,
      showDismiss: allowDismiss,
      timeZone: opts.timeZone,
      locale: opts.locale,
      statusPageBaseUrl: opts.statusPageBaseUrl,
      compact,
      expanded,
    });
  };

  const onClick = (ev: Event) => {
    const t = ev.target as HTMLElement | null;
    if (!t) return;
    const more = t.closest("[data-mh-toggle-more]") as HTMLElement | null;
    if (more) {
      expanded = !expanded;
      const visible = filterVisibleMessages(messagesCache, {
        applicationKey: opts.applicationKey,
        environmentKey: opts.environmentKey,
        storageKey: opts.storageKey,
        dismissible: allowDismiss,
      });
      paint(visible);
      return;
    }
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
      paint(visible);
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
    setExpanded: (next: boolean) => {
      expanded = next;
      const visible = filterVisibleMessages(messagesCache, {
        applicationKey: opts.applicationKey,
        environmentKey: opts.environmentKey,
        storageKey: opts.storageKey,
        dismissible: allowDismiss,
      });
      paint(visible);
    },
    destroy: () => {
      if (timer) clearInterval(timer);
      el.removeEventListener("click", onClick);
      el.innerHTML = "";
    },
  };
}

/** Detect insecure / local API bases for browser snippets. */
export function classifyApiBase(url: string): {
  kind: BannerRouteKind;
  https: boolean;
  warn?: string;
} {
  const raw = String(url || "").trim();
  let parsed: URL | null = null;
  try {
    parsed = new URL(raw);
  } catch {
    return { kind: "local_dev", https: false, warn: "Invalid API base URL." };
  }
  const host = parsed.hostname;
  const https = parsed.protocol === "https:";
  const localHost =
    host === "localhost" ||
    host === "127.0.0.1" ||
    host === "0.0.0.0" ||
    host.endsWith(".local");
  const cluster =
    host.endsWith(".svc") ||
    host.endsWith(".svc.cluster.local") ||
    host === "maintenancehub-api" ||
    (!https && !localHost && (host.includes("internal") || parsed.port === "8000"));

  if (localHost) {
    return {
      kind: "local_dev",
      https,
      warn: "Local/dev API base — do not ship this snippet to production hosts.",
    };
  }
  if (cluster || raw.includes("maintenancehub-api:")) {
    return {
      kind: "in_cluster",
      https,
      warn: "In-cluster DNS is for BFFs/OpenShift pods — browsers need the HTTPS corporate route.",
    };
  }
  if (!https) {
    return {
      kind: "corporate",
      https: false,
      warn: "Browser embeds should use HTTPS for the public/corporate MaintenanceHub base.",
    };
  }
  return { kind: "browser", https: true };
}

/** Build a copy-paste snippet for host apps (Claims INT, etc.). */
export function buildEmbedSnippet(opts: {
  apiBaseUrl: string;
  applicationKey: string;
  environmentKey?: string;
  theme?: BannerTheme;
  advanceHours?: number;
  timeZone?: string;
  statusPageBaseUrl?: string;
  routeKind?: BannerRouteKind;
  /** Absolute URL to embed.js (dependency-free IIFE). */
  embedScriptUrl?: string;
  styleUrl?: string;
}): { snippet: string; warn?: string; kind: BannerRouteKind } {
  const classified = classifyApiBase(opts.apiBaseUrl);
  const kind = opts.routeKind || classified.kind;
  const theme = opts.theme ?? "light";
  const envLine = opts.environmentKey
    ? `\n      environmentKey: ${JSON.stringify(opts.environmentKey)},`
    : "";
  const adv =
    opts.advanceHours != null ? `\n      advanceHours: ${Number(opts.advanceHours)},` : "";
  const tz = opts.timeZone ? `\n      timeZone: ${JSON.stringify(opts.timeZone)},` : "";
  const status = opts.statusPageBaseUrl
    ? `\n      statusPageBaseUrl: ${JSON.stringify(opts.statusPageBaseUrl.replace(/\/$/, ""))},`
    : "";
  const base = opts.apiBaseUrl.replace(/\/$/, "");
  const scriptSrc = opts.embedScriptUrl || `${base}/static/banner/embed.js`;
  const styleHref = opts.styleUrl || `${base}/static/banner/style.css`;
  const warnLines: string[] = [];
  if (classified.warn) warnLines.push(classified.warn);
  if (kind === "browser" && !classified.https) {
    warnLines.push("Prefer an https:// corporate MaintenanceHub URL for browser snippets.");
  }
  if (kind === "in_cluster") {
    warnLines.push("Use /api/v1/internal/banner from the BFF; do not expose cluster DNS to browsers.");
  }
  const commentWarn = warnLines.length
    ? `\n<!-- WARNING: ${warnLines.join(" ")} -->`
    : "";

  const snippet = `<!-- MaintenanceHub banner — confirmed notices only; no secrets.${commentWarn} -->
<!-- route: ${kind} | API stays ISO-8601; UI formats with Intl -->
<link rel="stylesheet" href="${styleHref}" />
<div id="mh-banner-root"></div>
<script src="${scriptSrc}" defer></script>
<script>
  document.addEventListener("DOMContentLoaded", function () {
    if (!window.MaintenanceHubBanner) return;
    window.MaintenanceHubBanner.mount({
      target: "#mh-banner-root",
      apiBaseUrl: ${JSON.stringify(base)},
      applicationKey: ${JSON.stringify(opts.applicationKey)},${envLine}${adv}${tz}${status}
      theme: ${JSON.stringify(theme)},
      compact: true,
      pollIntervalMs: 60000
    });
  });
</script>`;

  return {
    snippet,
    warn: warnLines[0],
    kind,
  };
}
