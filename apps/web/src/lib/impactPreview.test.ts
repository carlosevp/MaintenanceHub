import { describe, expect, it } from "vitest";

/** Contract checks for M14 impact preview DTO used by ImpactAnalysisPanel. */

type PathHop = {
  consumer_name: string;
  provider_name: string;
  origin: string;
};

function summarizePaths(paths: PathHop[][]): string {
  if (!paths.length) return "No path recorded";
  return paths
    .slice(0, 2)
    .map((p) => p.map((h) => `${h.consumer_name} → ${h.provider_name} [${h.origin}]`).join(" · "))
    .join(" | ");
}

function uniqueDestinations(
  rows: Array<{ destination_type: string; destination: string }>,
): number {
  const seen = new Set<string>();
  for (const r of rows) seen.add(`${r.destination_type}:${r.destination}`);
  return seen.size;
}

describe("impact preview helpers", () => {
  it("summarizes expandable dependency paths", () => {
    expect(
      summarizePaths([
        [
          { consumer_name: "Claims", provider_name: "Oracle", origin: "import" },
          { consumer_name: "Portal", provider_name: "Claims", origin: "manual" },
        ],
      ]),
    ).toContain("Claims → Oracle");
  });

  it("dedupes audience destinations", () => {
    expect(
      uniqueDestinations([
        { destination_type: "email_address", destination: "a@x.com" },
        { destination_type: "email_address", destination: "a@x.com" },
        { destination_type: "teams_bridge_channel", destination: "ops" },
      ]),
    ).toBe(2);
  });

  it("treats empty path list as unavailable evidence", () => {
    expect(summarizePaths([])).toBe("No path recorded");
  });
});
