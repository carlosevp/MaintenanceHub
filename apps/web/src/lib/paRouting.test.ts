import { describe, expect, it } from "vitest";
import {
  PA_ROUTING_LINE,
  PA_SUBJECT,
  isPaStyle,
  joinPaRouting,
  splitPaRouting,
} from "./paRouting";

describe("paRouting", () => {
  it("splits routing from content", () => {
    const { routing, content } = splitPaRouting(
      "To: {{teams_target_email}}\n\nTitle: {{title}}\n",
    );
    expect(routing).toBe(PA_ROUTING_LINE);
    expect(content.startsWith("Title:")).toBe(true);
  });

  it("rejoins without dropping contract", () => {
    expect(joinPaRouting("Hello")).toBe(`${PA_ROUTING_LINE}\n\nHello`);
  });

  it("detects PA style", () => {
    expect(isPaStyle({ key: "pa.teams_alert" })).toBe(true);
    expect(isPaStyle({ subject: PA_SUBJECT })).toBe(true);
    expect(isPaStyle({ key: "event.created", channel: "smtp" })).toBe(false);
  });
});
