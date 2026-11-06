/**
 * @maintenancehub/banner — embeddable maintenance/outage banner.
 *
 * Fetches confirmed active/upcoming messages from MaintenanceHub.
 * Does not perform health monitoring.
 */

export type BannerMessage = {
  id: string;
  kind: string;
  title: string;
  status: string;
  starts_at: string;
  ends_at: string;
  expected_impact?: string | null;
  approval_state: string;
};

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
  fetchImpl?: typeof fetch;
};

export type MountBannerOptions = FetchBannerOptions & {
  /** CSS selector or element */
  target: string | HTMLElement;
  /** Poll interval ms (0 = once). Default 60_000 */
  pollIntervalMs?: number;
  className?: string;
};

const FORBIDDEN_KEYS = new Set([
  "description",
  "timeline",
  "created_by",
  "updated_by",
  "raw_payload",
  "internal_notes",
  "note",
]);

/** Strip any accidental internal fields from API payloads. */
export function sanitizeBannerMessages(raw: unknown): BannerMessage[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const src = (item && typeof item === "object" ? item : {}) as Record<string, unknown>;
    const clean: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(src)) {
      if (FORBIDDEN_KEYS.has(k)) continue;
      clean[k] = v;
    }
    return {
      id: String(clean.id ?? ""),
      kind: String(clean.kind ?? ""),
      title: String(clean.title ?? ""),
      status: String(clean.status ?? ""),
      starts_at: String(clean.starts_at ?? ""),
      ends_at: String(clean.ends_at ?? ""),
      expected_impact: (clean.expected_impact as string | null | undefined) ?? null,
      approval_state: String(clean.approval_state ?? ""),
    };
  });
}

export async function fetchBannerMessages(opts: FetchBannerOptions): Promise<BannerMessage[]> {
  const fetchFn = opts.fetchImpl ?? fetch;
  const base = opts.apiBaseUrl.replace(/\/$/, "");
  const params = new URLSearchParams({ application_key: opts.applicationKey });
  if (opts.environmentKey) params.set("environment_key", opts.environmentKey);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.accessToken) {
    headers.Authorization = `Bearer ${opts.accessToken}`;
  }
  const res = await fetchFn(`${base}/api/v1/public/banner?${params}`, {
    headers,
  });
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

export function renderBannerHtml(messages: BannerMessage[], className = "mh-banner"): string {
  if (!messages.length) {
    return `<div class="${className} ${className}--empty" role="status" hidden></div>`;
  }
  const items = messages
    .map((m) => {
      const outage = m.kind === "manual_outage";
      return `<li class="${className}__item ${outage ? className + "__item--outage" : ""}">
  <span class="${className}__kind" aria-label="Kind: ${kindLabel(m.kind)}">${kindLabel(m.kind)}</span>
  <span class="${className}__status" aria-label="Status: ${m.status}">${m.status.replace(/_/g, " ")}</span>
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
  return `<aside class="${className}" role="region" aria-label="Maintenance and outage communications">
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
 */
export function mountMaintenanceBanner(opts: MountBannerOptions): BannerHandle {
  const el =
    typeof opts.target === "string" ? document.querySelector(opts.target) : opts.target;
  if (!el) {
    throw new Error(`Banner target not found: ${String(opts.target)}`);
  }
  const className = opts.className ?? "mh-banner";
  let timer: ReturnType<typeof setInterval> | undefined;

  const refresh = async () => {
    try {
      const messages = await fetchBannerMessages(opts);
      el.innerHTML = renderBannerHtml(messages, className);
    } catch (err) {
      el.innerHTML = `<div class="${className} ${className}--error" role="alert">Unable to load maintenance notices.</div>`;
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
      el.innerHTML = "";
    },
  };
}
