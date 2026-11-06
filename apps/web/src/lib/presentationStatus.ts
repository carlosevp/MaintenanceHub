/**
 * Consumer-facing presentation status — one primary label + short explanation.
 * Technical lifecycle/approval enums stay on event detail only.
 *
 * Approved windows are never presented as outages.
 */

export type PresentationStatus =
  | "scheduled"
  | "in_progress"
  | "expected_interruption"
  | "extended"
  | "completed"
  | "approved_window"
  | "cancelled";

export type PresentationMeta = {
  key: PresentationStatus;
  label: string;
  explanation: string;
  tone: "neutral" | "info" | "warn" | "danger" | "ok" | "muted";
};

type EventLike = {
  status: string;
  approval_state?: string | null;
  kind?: string | null;
};

export function presentationStatus(event: EventLike): PresentationMeta {
  const status = event.status;
  const approval = event.approval_state || "";
  const outage = event.kind === "manual_outage";

  // Approved (not confirmed) — never an outage signal
  if (approval === "approved_window" && !["in_progress", "extended", "verifying"].includes(status)) {
    return {
      key: "approved_window",
      label: "Approved window",
      explanation: "Planned on the calendar — not yet confirmed communication.",
      tone: "info",
    };
  }

  if (status === "extended") {
    return {
      key: "extended",
      label: "Extended",
      explanation: "Work is taking longer than the original window.",
      tone: "warn",
    };
  }

  if (status === "in_progress" || status === "verifying") {
    if (outage) {
      return {
        key: "expected_interruption",
        label: "Expected interruption",
        explanation: "A reported interruption is active. Status is human-published.",
        tone: "danger",
      };
    }
    return {
      key: "in_progress",
      label: "In progress",
      explanation:
        status === "verifying"
          ? "Window is open; publishers are verifying service."
          : "Confirmed work is underway now.",
      tone: "warn",
    };
  }

  if (status === "completed") {
    return {
      key: "completed",
      label: "Completed",
      explanation: "This window has finished.",
      tone: "ok",
    };
  }

  if (status === "cancelled") {
    return {
      key: "cancelled",
      label: "Cancelled",
      explanation: "This window was cancelled.",
      tone: "muted",
    };
  }

  // scheduled (and similar) when confirmed
  return {
    key: "scheduled",
    label: "Scheduled",
    explanation: "Confirmed and on the calendar.",
    tone: "neutral",
  };
}
