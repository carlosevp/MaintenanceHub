import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SubscriptionsPage } from "./SubscriptionsPage";

const { api } = vi.hoisted(() => ({
  api: {
    subscriptions: vi.fn(),
    applications: vi.fn(),
    environments: vi.fn(),
    calendarReachability: vi.fn(),
    listCalendarTokens: vi.fn(),
    me: vi.fn(),
    createSubscription: vi.fn(),
    updateSubscription: vi.fn(),
    deleteSubscription: vi.fn(),
    createCalendarToken: vi.fn(),
    revokeCalendarToken: vi.fn(),
    downloadCalendarIcs: vi.fn(),
  },
}));

vi.mock("@/api/client", () => ({
  api,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SubscriptionsPage", () => {
  it("shows friendly names and calendar download/subscribe options", async () => {
    api.subscriptions.mockResolvedValue([
      {
        id: "s1",
        user_id: "u1",
        is_active: true,
        digest_mode: "none",
        destination_type: "email_address",
        destination: "viewer@demo.example.com",
        notify_events: ["start", "cancellation"],
        notify_event_labels: ["Start", "Cancellation"],
        channel_label: "Email",
        targets: [
          {
            id: "t1",
            target_type: "app_environment",
            target_id: "app:env",
            application_name: "Claims Portal",
            environment_name: "Integration",
            environment_key: "INT",
            label: "Claims Portal · Integration (INT)",
            scope_label: "Environment: Integration (INT)",
            missing: false,
          },
        ],
        reminders: [{ id: "r1", offset_minutes: -1440, label: "24h before start" }],
      },
    ]);
    api.applications.mockResolvedValue([
      {
        id: "app1",
        key: "claims",
        name: "Claims Portal",
        status: "active",
        environments: [
          {
            id: "ae1",
            environment_id: "env1",
            display_name: "Claims-INT",
            environment: { id: "env1", key: "INT", name: "Integration", sort_order: 20 },
          },
        ],
      },
    ]);
    api.environments.mockResolvedValue([
      { id: "env1", key: "INT", name: "Integration", sort_order: 20, is_active: true },
    ]);
    api.calendarReachability.mockResolvedValue({
      configured: true,
      https: false,
      microsoft_cloud_reachable: false,
      subscription_supported: false,
      code: "internal_only",
      message: "localhost is not reachable from Microsoft cloud",
      base_url: "http://127.0.0.1:8000",
    });
    api.listCalendarTokens.mockResolvedValue([]);
    api.me.mockResolvedValue({
      id: "u1",
      email: "viewer@demo.example.com",
      display_name: "Viewer",
      roles: ["viewer"],
    });

    render(
      <MemoryRouter>
        <SubscriptionsPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Claims Portal · Integration \(INT\)/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/app:env/)).not.toBeInTheDocument();
    expect(screen.getByText(/24h before start/)).toBeInTheDocument();
    expect(screen.getByText(/Notices: Start, Cancellation/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download calendar \(\.ics\)/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create subscription feed/i })).toBeInTheDocument();
    expect(screen.getByText(/Microsoft cloud/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Downloaded calendars are static snapshots/i),
    ).toBeInTheDocument();
  });

  it("allows selecting advance reminders and notify types", async () => {
    const user = userEvent.setup();
    api.subscriptions.mockResolvedValue([]);
    api.applications.mockResolvedValue([
      { id: "app1", key: "claims", name: "Claims Portal", status: "active", environments: [] },
    ]);
    api.environments.mockResolvedValue([
      { id: "env1", key: "INT", name: "Integration", sort_order: 20, is_active: true },
    ]);
    api.calendarReachability.mockResolvedValue({
      configured: false,
      https: false,
      microsoft_cloud_reachable: false,
      subscription_supported: false,
      code: "missing",
      message: "No public HTTPS base URL",
    });
    api.listCalendarTokens.mockResolvedValue([]);
    api.me.mockResolvedValue({
      id: "u1",
      email: "viewer@demo.example.com",
      display_name: "Viewer",
      roles: ["viewer"],
    });
    api.createSubscription.mockResolvedValue({
      id: "s2",
      user_id: "u1",
      is_active: true,
      digest_mode: "none",
      destination_type: "email_address",
      destination: "viewer@demo.example.com",
      notify_events: ["start"],
      notify_event_labels: ["Start"],
      channel_label: "Email",
      targets: [],
      reminders: [],
    });

    render(
      <MemoryRouter>
        <SubscriptionsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByRole("combobox", { name: /^Application$/i })).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox", { name: /^Application$/i }), "app1");
    await user.click(screen.getByRole("radio", { name: /Entire application/i }));
    await user.click(screen.getByRole("button", { name: /^Subscribe$/i }));

    await waitFor(() => expect(api.createSubscription).toHaveBeenCalled());
    const body = api.createSubscription.mock.calls[0][0];
    expect(body.targets[0].target_type).toBe("application");
    expect(body.reminders.length).toBeGreaterThan(0);
    expect(body.notify_events).toContain("start");
  });
});
