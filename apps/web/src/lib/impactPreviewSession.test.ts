import { describe, expect, it } from "vitest";
import {
  createPreviewRequestGate,
  selectionFingerprint,
  seedsFingerprint,
} from "./impactPreviewSession";

describe("impactPreviewSession", () => {
  it("only latest preview request id is current", () => {
    const gate = createPreviewRequestGate();
    const a = gate.next();
    const b = gate.next();
    expect(gate.isCurrent(a)).toBe(false);
    expect(gate.isCurrent(b)).toBe(true);
  });

  it("selection fingerprint changes when exclusion reason changes", () => {
    const base = selectionFingerprint(
      [{ target_type: "application", target_id: "a", environment_id: "e", reason: "x" }],
      [],
      [],
    );
    const changed = selectionFingerprint(
      [{ target_type: "application", target_id: "a", environment_id: "e", reason: "y" }],
      [],
      [],
    );
    expect(base).not.toBe(changed);
  });

  it("seeds fingerprint is order-independent", () => {
    const a = seedsFingerprint([
      { target_type: "application", target_id: "1", environment_id: null },
      { target_type: "infra_component", target_id: "2", environment_id: "e" },
    ]);
    const b = seedsFingerprint([
      { target_type: "infra_component", target_id: "2", environment_id: "e" },
      { target_type: "application", target_id: "1", environment_id: null },
    ]);
    expect(a).toBe(b);
  });
});
