import { describe, expect, it } from "vitest";
import { presentationStatus } from "./presentationStatus";

describe("presentationStatus", () => {
  it("never presents approved windows as outages", () => {
    const meta = presentationStatus({
      status: "scheduled",
      approval_state: "approved_window",
      kind: "manual_outage",
    });
    expect(meta.key).toBe("approved_window");
    expect(meta.label).toBe("Approved window");
  });

  it("maps active outage to expected interruption", () => {
    const meta = presentationStatus({
      status: "in_progress",
      approval_state: "confirmed_scheduled",
      kind: "manual_outage",
    });
    expect(meta.key).toBe("expected_interruption");
  });

  it("maps confirmed future work to scheduled", () => {
    const meta = presentationStatus({
      status: "scheduled",
      approval_state: "confirmed_scheduled",
      kind: "planned_maintenance",
    });
    expect(meta.key).toBe("scheduled");
  });

  it("maps extended windows", () => {
    expect(
      presentationStatus({
        status: "extended",
        approval_state: "confirmed_scheduled",
        kind: "planned_maintenance",
      }).label,
    ).toBe("Extended");
  });
});
