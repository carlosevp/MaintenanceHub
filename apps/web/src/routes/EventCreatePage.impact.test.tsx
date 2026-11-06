import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExperienceProvider } from "@/features/experience/ExperienceContext";
import { EventCreatePage } from "./EventCreatePage";

const impactPreview = vi.fn();
const createEvent = vi.fn();
const impactConfirm = vi.fn();

vi.mock("@/api/client", () => ({
  api: {
    applications: vi.fn(async () => [
      { id: "app-1", key: "claims", name: "Claims", status: "active", environments: [] },
    ]),
    environments: vi.fn(async () => [
      { id: "env-1", key: "INT", name: "INT", sort_order: 1 },
      { id: "env-np", key: "NON-PROD", name: "NON-PROD", sort_order: 2 },
    ]),
    infraComponents: vi.fn(async () => [
      { id: "infra-1", key: "oracle-shared-nonprod", name: "Oracle NON-PROD" },
    ]),
    impactPreview: (...args: unknown[]) => impactPreview(...args),
    createEvent: (...args: unknown[]) => createEvent(...args),
    impactConfirm: (...args: unknown[]) => impactConfirm(...args),
  },
}));

function previewPayload(token = "tok-1") {
  return {
    revision_token: token,
    impact_revision: 0,
    dependency_fingerprint: "dep",
    analyzed_at: new Date().toISOString(),
    max_depth: 5,
    direct_targets: [
      {
        target_type: "infra_component",
        target_id: "infra-1",
        environment_id: "env-np",
        display_name: "Oracle",
        classification: "direct",
        selection: "direct",
      },
    ],
    suggested_downstream: [
      {
        target_type: "application",
        target_id: "app-1",
        environment_id: "env-1",
        display_name: "Claims",
        classification: "downstream_candidate",
        selection: "suggested",
        paths: [],
        origins: ["import"],
        warnings: [],
      },
    ],
    manual_additions: [],
    exclusions: [],
    proposed_effective_impacts: [],
    existing_decisions: [],
    warnings: [],
    audience: {
      unique_recipients: 1,
      email_destinations: ["a@x.com"],
      teams_bridge_channels: [],
      subscription_count: 1,
      users_with_multiple_subscriptions: 0,
      destinations_redacted: false,
      note: "note",
    },
    conflicts: [],
    read_only: true,
    notifications_sent: false,
  };
}

describe("EventCreatePage impact analysis stability", () => {
  beforeEach(() => {
    impactPreview.mockReset();
    createEvent.mockReset();
    impactConfirm.mockReset();
    impactPreview.mockImplementation(async () => previewPayload(`tok-${impactPreview.mock.calls.length}`));
    // Team+ profile so impact flow is available (Essentials fail-closed defaults otherwise)
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        profile: "team",
        label: "Team",
        capabilities: {
          impact_analysis: true,
          recurrence_editor: true,
          quick_publish: true,
          demo_scenarios: true,
        },
        scenarios: [],
      }),
    } as Response);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("bounds preview requests and preserves decisions across Details↔Impact navigation", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ExperienceProvider>
          <EventCreatePage />
        </ExperienceProvider>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByLabelText(/^Target$/i)).toBeInTheDocument());

    await user.type(screen.getByLabelText(/^What$/i), "Oracle window");
    const starts = screen.getByLabelText(/^Starts$/i);
    const ends = screen.getByLabelText(/^Ends$/i);
    await user.clear(starts);
    await user.type(starts, "2026-07-01T02:00");
    await user.clear(ends);
    await user.type(ends, "2026-07-01T04:00");

    await user.click(screen.getByRole("button", { name: /Continue to impact analysis/i }));

    await waitFor(() => expect(impactPreview).toHaveBeenCalled());
    const callsAfterEnter = impactPreview.mock.calls.length;
    expect(callsAfterEnter).toBeLessThanOrEqual(2);

    await waitFor(() => expect(screen.getByText(/Suggested downstream/i)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^Exclude$/i }));
    await waitFor(() => expect(impactPreview.mock.calls.length).toBeGreaterThan(callsAfterEnter));
    const afterExclude = impactPreview.mock.calls.length;

    // Navigate back to details and forward again — should not storm previews
    await user.click(screen.getByRole("button", { name: /^Back$/i }));
    await user.click(screen.getByRole("button", { name: /Continue to impact analysis/i }));
    await waitFor(() => expect(screen.getByText(/Suggested downstream/i)).toBeInTheDocument());
    // Bounded: re-enter should not explode request count
    expect(impactPreview.mock.calls.length).toBeLessThanOrEqual(afterExclude + 2);

    // Exclusion UI preserved (Include button means still excluded)
    expect(screen.getByRole("button", { name: /^Include$/i })).toBeInTheDocument();
  });
});
