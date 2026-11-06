import { describe, expect, it } from "vitest";
import { renderBannerHtml, sanitizeBannerMessages } from "./index";

describe("sanitizeBannerMessages", () => {
  it("strips internal fields", () => {
    const out = sanitizeBannerMessages([
      {
        id: "1",
        kind: "planned_maintenance",
        title: "Patch",
        status: "in_progress",
        starts_at: "2026-11-10T02:00:00Z",
        ends_at: "2026-11-10T04:00:00Z",
        expected_impact: "RO",
        approval_state: "confirmed_scheduled",
        description: "SECRET INTERNAL",
        timeline: [{ note: "nope" }],
        created_by: "admin",
      },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0].title).toBe("Patch");
    expect(JSON.stringify(out)).not.toContain("SECRET");
    expect(JSON.stringify(out)).not.toContain("timeline");
    expect(JSON.stringify(out)).not.toContain("created_by");
  });
});

describe("renderBannerHtml", () => {
  it("renders accessible labels", () => {
    const html = renderBannerHtml([
      {
        id: "1",
        kind: "manual_outage",
        title: "Login down",
        status: "in_progress",
        starts_at: "2026-11-10T02:00:00Z",
        ends_at: "2026-11-10T04:00:00Z",
        approval_state: "confirmed_scheduled",
      },
    ]);
    expect(html).toContain("role=\"region\"");
    expect(html).toContain("Outage");
    expect(html).toContain("Login down");
  });
});
