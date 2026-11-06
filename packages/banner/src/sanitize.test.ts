import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  buildEmbedSnippet,
  dismissMessage,
  filterVisibleMessages,
  isDismissed,
  renderBannerHtml,
  sanitizeBannerMessages,
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
    expect(out[0].presentation).toBe("in_progress");
    expect(JSON.stringify(out)).not.toContain("SECRET");
    expect(JSON.stringify(out)).not.toContain("timeline");
    expect(JSON.stringify(out)).not.toContain("created_by");
    expect(JSON.stringify(out)).not.toContain("leak");
  });

  it("never maps approved-only to outage presentation", () => {
    const out = sanitizeBannerMessages([
      {
        id: "2",
        kind: "manual_outage",
        title: "Should not be outage label from approved",
        status: "scheduled",
        presentation: "upcoming",
        starts_at: "2026-11-10T02:00:00Z",
        ends_at: "2026-11-10T04:00:00Z",
        approval_state: "approved_window",
      },
    ]);
    expect(out[0].presentation).toBe("upcoming");
  });
});

describe("renderBannerHtml", () => {
  it("renders accessible labels and dismiss for upcoming", () => {
    const html = renderBannerHtml(
      [
        {
          id: "1",
          kind: "manual_outage",
          title: "Login down",
          status: "in_progress",
          presentation: "outage",
          starts_at: "2026-11-10T02:00:00Z",
          ends_at: "2026-11-10T04:00:00Z",
          approval_state: "confirmed_scheduled",
          dismissible: false,
        },
        {
          id: "2",
          kind: "planned_maintenance",
          title: "Tomorrow patch",
          status: "scheduled",
          presentation: "upcoming",
          starts_at: "2026-11-11T02:00:00Z",
          ends_at: "2026-11-11T04:00:00Z",
          approval_state: "confirmed_scheduled",
          dismissible: true,
          revision: "r1",
        },
      ],
      "mh-banner",
      { theme: "dark", showDismiss: true },
    );
    expect(html).toContain('role="region"');
    expect(html).toContain("Outage");
    expect(html).toContain("Login down");
    expect(html).toContain('data-theme="dark"');
    expect(html).toContain("data-mh-dismiss");
    expect(html).toContain("Upcoming");
  });
});

describe("dismiss + revision re-show", () => {
  beforeEach(() => {
    installMemoryLocalStorage();
  });
  afterEach(() => {
    localStorage.clear();
  });

  it("hides dismissed upcoming until revision changes", () => {
    const msg = {
      id: "up-1",
      kind: "planned_maintenance",
      title: "Soon",
      status: "scheduled",
      presentation: "upcoming" as const,
      starts_at: "2026-11-12T02:00:00Z",
      ends_at: "2026-11-12T04:00:00Z",
      approval_state: "confirmed_scheduled",
      dismissible: true,
      revision: "ends|scheduled|v1",
    };
    const opts = { applicationKey: "claims", environmentKey: "INT" };
    expect(isDismissed(msg, opts)).toBe(false);
    dismissMessage(msg, opts);
    expect(isDismissed(msg, opts)).toBe(true);
    expect(filterVisibleMessages([msg], opts)).toHaveLength(0);

    const extended = { ...msg, ends_at: "2026-11-12T06:00:00Z", revision: "ends|extended|v2" };
    expect(isDismissed(extended, opts)).toBe(false);
    expect(filterVisibleMessages([extended], opts)).toHaveLength(1);
  });

  it("does not dismiss active outage", () => {
    const msg = {
      id: "o-1",
      kind: "manual_outage",
      title: "Down",
      status: "in_progress",
      presentation: "outage" as const,
      starts_at: "2026-11-10T02:00:00Z",
      ends_at: "2026-11-10T04:00:00Z",
      approval_state: "confirmed_scheduled",
      dismissible: false,
      revision: "r",
    };
    dismissMessage(msg, { applicationKey: "claims" });
    expect(isDismissed(msg, { applicationKey: "claims" })).toBe(false);
  });
});

describe("buildEmbedSnippet", () => {
  it("emits Claims INT snippet without secrets", () => {
    const snip = buildEmbedSnippet({
      apiBaseUrl: "https://mh.example.com",
      applicationKey: "claims",
      environmentKey: "INT",
      theme: "light",
      advanceHours: 24,
    });
    expect(snip).toContain('applicationKey: "claims"');
    expect(snip).toContain('environmentKey: "INT"');
    expect(snip).toContain("embed.js");
    expect(snip).not.toContain("client_secret");
    expect(snip).not.toContain("accessToken");
  });
});
