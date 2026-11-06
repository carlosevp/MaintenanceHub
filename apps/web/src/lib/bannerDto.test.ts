import { describe, expect, it } from "vitest";

/** Mirrors public banner DTO contract used by BannerDemoPage. */
const PUBLIC_KEYS = new Set([
  "id",
  "event_id",
  "kind",
  "title",
  "status",
  "presentation",
  "starts_at",
  "ends_at",
  "expected_impact",
  "approval_state",
  "revision",
  "dismissible",
  "occurrence_starts_at",
  "status_path",
]);

function assertPublicDto(raw: Record<string, unknown>): boolean {
  return Object.keys(raw).every((k) => PUBLIC_KEYS.has(k));
}

describe("banner public DTO contract", () => {
  it("accepts minimal public fields", () => {
    expect(
      assertPublicDto({
        id: "1",
        kind: "planned_maintenance",
        title: "Patch",
        status: "scheduled",
        starts_at: "2026-01-01T00:00:00Z",
        ends_at: "2026-01-01T02:00:00Z",
        expected_impact: null,
        approval_state: "confirmed_scheduled",
      }),
    ).toBe(true);
  });

  it("rejects internal fields", () => {
    expect(
      assertPublicDto({
        id: "1",
        kind: "planned_maintenance",
        title: "Patch",
        status: "scheduled",
        starts_at: "a",
        ends_at: "b",
        approval_state: "confirmed_scheduled",
        description: "nope",
      }),
    ).toBe(false);
  });
});
