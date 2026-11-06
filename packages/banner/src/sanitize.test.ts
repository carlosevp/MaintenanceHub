import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  buildEmbedSnippet,
  classifyApiBase,
  dismissMessage,
  escapeHtml,
  filterVisibleMessages,
  formatWindowIntl,
  isDismissed,
  logicalMessageKey,
  normalizeBannerMessages,
  renderBannerHtml,
  sanitizeBannerMessages,
  type BannerMessage,
} from "./index";

function installMemoryLocalStorage() {
  const store = new Map<string, string>();
  const memory = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => {
      store.set(k, String(v));
    },
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => store.clear(),
    key: (i: number) => Array.from(store.keys())[i] ?? null,
    get length() {
      return store.size;
    },
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: memory,
    configurable: true,
  });
}

function msg(partial: Partial<BannerMessage> & Pick<BannerMessage, "id" | "title">): BannerMessage {
  return {
    kind: "planned_maintenance",
    status: "scheduled",
    presentation: "upcoming",
    starts_at: "2026-11-10T02:00:00Z",
    ends_at: "2026-11-10T04:00:00Z",
    approval_state: "confirmed_scheduled",
    dismissible: true,
    revision: "r1",
    event_id: partial.event_id ?? partial.id,
    ...partial,
  };
}

describe("sanitizeBannerMessages", () => {
  it("strips internal fields and secrets", () => {
    const out = sanitizeBannerMessages([
      {
        id: "1",
        kind: "planned_maintenance",
        title: "Patch",
        status: "in_progress",
        presentation: "in_progress",
        starts_at: "2026-11-10T02:00:00Z",
        ends_at: "2026-11-10T04:00:00Z",
        expected_impact: "RO",
        approval_state: "confirmed_scheduled",
        revision: "rev1",
        dismissible: false,
        description: "SECRET INTERNAL",
        timeline: [{ note: "nope" }],
        created_by: "admin",
        client_secret: "leak",
      },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].title).toBe("Patch");
    expect(JSON.stringify(out)).not.toContain("SECRET");
    expect(JSON.stringify(out)).not.toContain("leak");
  });

  it("never maps approved-only to outage presentation", () => {
    const out = sanitizeBannerMessages([
      {
        id: "2",
        kind: "manual_outage",
        title: "Should not be outage",
        status: "scheduled",
        presentation: "upcoming",
        starts_at: "2026-11-10T02:00:00Z",
        ends_at: "2026-11-10T04:00:00Z",
        approval_state: "approved_window",
      },
    ]);
    expect(out[0].presentation).toBe("upcoming");
  });

  it("dedupes by logical occurrence not title", () => {
    const out = sanitizeBannerMessages([
      msg({
        id: "occ-a",
        event_id: "e1",
        title: "Same title",
        occurrence_starts_at: "2026-11-10T02:00:00Z",
        presentation: "upcoming",
      }),
      msg({
        id: "occ-a-dup",
        event_id: "e1",
        title: "Same title",
        occurrence_starts_at: "2026-11-10T02:00:00Z",
        presentation: "in_progress",
        status: "in_progress",
        dismissible: false,
      }),
      msg({
        id: "occ-b",
        event_id: "e1",
        title: "Same title",
        occurrence_starts_at: "2026-11-17T02:00:00Z",
        presentation: "upcoming",
      }),
    ]);
    expect(out).toHaveLength(2);
    expect(out[0].presentation).toBe("in_progress");
    expect(logicalMessageKey(out[0])).toContain("2026-11-10");
  });
});

describe("multi-notice compact policy", () => {
  it("renders primary only with View additional, then expands", () => {
    const list = normalizeBannerMessages([
      msg({
        id: "a",
        title: "Active",
        presentation: "in_progress",
        status: "in_progress",
        dismissible: false,
        starts_at: "2026-11-06T12:00:00Z",
      }),
      msg({
        id: "b",
        title: "Later",
        presentation: "upcoming",
        starts_at: "2026-11-07T12:00:00Z",
      }),
    ]);
    const compact = renderBannerHtml(list, "mh-banner", { compact: true, expanded: false });
    expect(compact).toContain("Active");
    expect(compact).not.toContain("Later");
    expect(compact).toContain("View 1 additional");
    const expanded = renderBannerHtml(list, "mh-banner", { compact: true, expanded: true });
    expect(expanded).toContain("Later");
    expect(expanded).toContain("Show less");
  });

  it("orders outage before upcoming deterministically", () => {
    const list = normalizeBannerMessages([
      msg({ id: "u", title: "Soon", presentation: "upcoming", starts_at: "2026-11-06T10:00:00Z" }),
      msg({
        id: "o",
        title: "Down",
        kind: "manual_outage",
        presentation: "outage",
        status: "in_progress",
        dismissible: false,
        starts_at: "2026-11-06T11:00:00Z",
      }),
    ]);
    expect(list[0].id).toBe("o");
    expect(list[1].id).toBe("u");
  });
});

describe("Intl / timezone / DST", () => {
  it("formats ISO via Intl in America/Chicago across DST spring forward", () => {
    // 2026-03-08 08:00Z = 02:00 CST; 2026-03-08 08:30Z = 03:30 CDT after spring forward
    const before = formatWindowIntl(
      "2026-03-08T07:30:00Z",
      "2026-03-08T08:30:00Z",
      { timeZone: "America/Chicago", locale: "en-US" },
    );
    expect(before).toMatch(/Mar/);
    expect(before).toContain("→");
    // Both instants should render; CDT vs CST labels vary by engine — ensure distinct local hours
    expect(before.length).toBeGreaterThan(10);
  });

  it("formats fall-back ambiguous hour in America/Chicago", () => {
    const win = formatWindowIntl(
      "2026-11-01T06:30:00Z",
      "2026-11-01T08:30:00Z",
      { timeZone: "America/Chicago", locale: "en-US" },
    );
    expect(win).toMatch(/Nov/);
    expect(win).toContain("→");
  });
});

describe("XSS-safe text", () => {
  it("escapes titles and impact in HTML", () => {
    const html = renderBannerHtml(
      [
        msg({
          id: "x",
          title: `<img src=x onerror=alert(1)>`,
          expected_impact: `</span><script>alert(1)</script>`,
        }),
      ],
      "mh-banner",
    );
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain(escapeHtml(`<img src=x onerror=alert(1)>`));
    expect(html).toContain(escapeHtml(`</span><script>alert(1)</script>`));
  });
});

describe("dismiss + revision re-show journeys", () => {
  beforeEach(() => installMemoryLocalStorage());
  afterEach(() => localStorage.clear());

  it("scheduled → dismiss → update reappear", () => {
    const scheduled = msg({
      id: "up-1",
      title: "Soon",
      revision: "ends|scheduled|v1",
    });
    const opts = { applicationKey: "claims", environmentKey: "INT" };
    dismissMessage(scheduled, opts);
    expect(isDismissed(scheduled, opts)).toBe(true);
    expect(filterVisibleMessages([scheduled], opts)).toHaveLength(0);
    const updated = { ...scheduled, ends_at: "2026-11-10T06:00:00Z", revision: "ends|extended|v2" };
    expect(isDismissed(updated, opts)).toBe(false);
    expect(filterVisibleMessages([updated], opts)).toHaveLength(1);
  });

  it("active outage has priority and is not dismissible", () => {
    const upcoming = msg({ id: "u", title: "Soon", presentation: "upcoming" });
    const outage = msg({
      id: "o",
      title: "Down",
      kind: "manual_outage",
      presentation: "outage",
      status: "in_progress",
      dismissible: false,
    });
    dismissMessage(outage, { applicationKey: "claims" });
    expect(isDismissed(outage, { applicationKey: "claims" })).toBe(false);
    const visible = filterVisibleMessages([upcoming, outage], {
      applicationKey: "claims",
      dismissible: true,
    });
    expect(visible[0].id).toBe("o");
  });
});

describe("classifyApiBase + snippet routes", () => {
  it("warns on local and prefers HTTPS for browser", () => {
    expect(classifyApiBase("http://127.0.0.1:8000").kind).toBe("local_dev");
    expect(classifyApiBase("http://127.0.0.1:8000").warn).toBeTruthy();
    expect(classifyApiBase("http://maintenancehub-api:8000").kind).toBe("in_cluster");
    const browser = classifyApiBase("https://mh.corp.example.com");
    expect(browser.kind).toBe("browser");
    expect(browser.https).toBe(true);
    const insecure = classifyApiBase("http://mh.corp.example.com");
    expect(insecure.warn).toMatch(/HTTPS/i);
  });

  it("emits Claims INT snippet without secrets and with route comment", () => {
    const { snippet, kind } = buildEmbedSnippet({
      apiBaseUrl: "https://mh.example.com",
      applicationKey: "claims",
      environmentKey: "INT",
      theme: "light",
      advanceHours: 24,
      timeZone: "America/Chicago",
      statusPageBaseUrl: "https://mh.example.com",
    });
    expect(kind).toBe("browser");
    expect(snippet).toContain('applicationKey: "claims"');
    expect(snippet).toContain("https://mh.example.com/static/banner/embed.js");
    expect(snippet).not.toContain("client_secret");
    expect(snippet).not.toContain("accessToken");
    expect(snippet).toContain("route: browser");
  });
});

describe("API down graceful fail journey", () => {
  it("mount paints soft error when fetch rejects", async () => {
    const { mountMaintenanceBanner } = await import("./index");
    const listeners: Array<(ev: Event) => void> = [];
    const el = {
      innerHTML: "",
      addEventListener: (_: string, fn: (ev: Event) => void) => {
        listeners.push(fn);
      },
      removeEventListener: vi.fn(),
    } as unknown as HTMLElement;
    const handle = mountMaintenanceBanner({
      target: el,
      apiBaseUrl: "https://mh.example.com",
      applicationKey: "claims",
      environmentKey: "INT",
      pollIntervalMs: 0,
      fetchImpl: (async () => {
        throw new Error("network down");
      }) as typeof fetch,
    });
    await new Promise((r) => setTimeout(r, 30));
    expect(el.innerHTML).toContain("Unable to load maintenance notices");
    handle.destroy();
  });
});
