const TOKEN_KEY = "mh_token";

export type Me = {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
};

export type Application = {
  id: string;
  key: string;
  name: string;
  description?: string | null;
  status: string;
  environments: Array<{
    id: string;
    environment_id: string;
    display_name: string;
    environment?: { id: string; key: string; name: string; sort_order: number };
  }>;
};

export type Environment = {
  id: string;
  key: string;
  name: string;
  description?: string | null;
  sort_order: number;
  is_active?: boolean;
};

export type SubscriptionTarget = {
  id: string;
  target_type: string;
  target_id: string;
  application_id?: string | null;
  application_name?: string | null;
  application_key?: string | null;
  environment_id?: string | null;
  environment_name?: string | null;
  environment_key?: string | null;
  event_title?: string | null;
  label: string;
  scope_label: string;
  missing: boolean;
};

export type Subscription = {
  id: string;
  user_id: string;
  is_active: boolean;
  digest_mode: string;
  destination_type: string;
  destination: string;
  bridge_channel_key?: string | null;
  notify_events: string[];
  notify_event_labels: string[];
  channel_label: string;
  targets: SubscriptionTarget[];
  reminders: Array<{ id: string; offset_minutes: number; label?: string | null }>;
};

export type CalendarReachability = {
  base_url?: string | null;
  configured: boolean;
  https: boolean;
  microsoft_cloud_reachable: boolean;
  subscription_supported: boolean;
  code: string;
  message: string;
};

export type RecurrenceInfo = {
  rrule: string;
  until_at?: string | null;
  summary: string;
  exceptions: Array<{
    id: string;
    original_starts_at: string;
    action: string;
    new_starts_at?: string | null;
    new_ends_at?: string | null;
  }>;
};

export type MaintenanceEvent = {
  id: string;
  kind: string;
  title: string;
  description?: string | null;
  expected_impact?: string | null;
  status: string;
  approval_state: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  is_recurring: boolean;
  impacts: Array<{
    id: string;
    target_type: string;
    target_id: string;
    environment_id?: string | null;
  }>;
  recurrence?: RecurrenceInfo | null;
  is_occurrence?: boolean;
  occurrence_starts_at?: string | null;
};

export type DashboardSummary = {
  current: { count: number; items: MaintenanceEvent[] };
  upcoming: { count: number; items: MaintenanceEvent[] };
  recent: { count: number; items: MaintenanceEvent[] };
  outages: { count: number; items: MaintenanceEvent[] };
  extended?: { count: number; items: MaintenanceEvent[] };
  cancelled?: { count: number; items: MaintenanceEvent[] };
  as_of: string;
  note?: string;
};

export type CalendarEvent = {
  id: string;
  title: string;
  kind: string;
  status: string;
  approval_state: string;
  starts_at: string;
  ends_at: string;
  timezone: string;
  is_occurrence: boolean;
  occurrence_starts_at?: string | null;
};

export type TimelineEntry = {
  id: string;
  at: string;
  actor_id?: string | null;
  entry_type: string;
  payload: Record<string, unknown>;
};

export type ImpactSeed = {
  target_type: string;
  target_id: string;
  environment_id?: string | null;
};

export type SuggestedImpact = {
  target_type: string;
  target_id: string;
  environment_id?: string | null;
  environment_key?: string | null;
  display_name: string;
  classification: string;
  selection?: string;
  origins?: string[];
  dependency_kinds?: string[];
  warnings?: string[];
  paths?: Array<
    Array<{
      dependency_id: string;
      consumer_type: string;
      consumer_id: string;
      consumer_name: string;
      consumer_environment_id?: string | null;
      consumer_environment_key?: string | null;
      provider_type: string;
      provider_id: string;
      provider_name: string;
      provider_environment_id?: string | null;
      provider_environment_key?: string | null;
      origin: string;
      dependency_kind: string;
    }>
  >;
};

export type ImpactPreview = {
  revision_token: string;
  impact_revision: number;
  dependency_fingerprint: string;
  analyzed_at: string;
  max_depth: number;
  direct_targets: SuggestedImpact[];
  suggested_downstream: SuggestedImpact[];
  manual_additions: SuggestedImpact[];
  exclusions: Array<ImpactSeed & { reason?: string | null }>;
  proposed_effective_impacts: Array<ImpactSeed & { display_name?: string }>;
  warnings: Array<{
    code: string;
    message: string;
    subject_type?: string | null;
    subject_id?: string | null;
  }>;
  audience: {
    unique_recipients: number;
    email_destinations: string[];
    teams_bridge_channels: string[];
    subscription_count: number;
    users_with_multiple_subscriptions: number;
    destinations_redacted?: boolean;
    note: string;
  };
  conflicts: Array<{
    event_id: string;
    title: string;
    occurrence_id: string;
    starts_at: string;
    ends_at: string;
    classification: string;
    explanation: string;
    status: string;
  }>;
  read_only: boolean;
  notifications_sent: boolean;
};

export type InfraComponent = {
  id: string;
  key: string;
  name: string;
  kind?: string | null;
  description?: string | null;
};

function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (!headers.has("Content-Type") && init.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || body.title || detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<Me>("/api/v1/auth/me"),
  dashboard: (params: URLSearchParams) =>
    request<DashboardSummary>(`/api/v1/dashboard/summary?${params}`),
  calendar: (params: URLSearchParams) =>
    request<CalendarEvent[]>(`/api/v1/calendar/events?${params}`),
  applications: (q?: string) =>
    request<Application[]>(`/api/v1/applications${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  application: (id: string) => request<Application>(`/api/v1/applications/${id}`),
  createApplication: (body: unknown) =>
    request<Application>("/api/v1/applications", { method: "POST", body: JSON.stringify(body) }),
  environments: (includeInactive = false) =>
    request<Environment[]>(
      `/api/v1/environments${includeInactive ? "?include_inactive=true" : ""}`,
    ),
  createEnvironment: (body: unknown) =>
    request<Environment>("/api/v1/environments", { method: "POST", body: JSON.stringify(body) }),
  updateEnvironment: (id: string, body: unknown) =>
    request<Environment>(`/api/v1/environments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deactivateEnvironment: (id: string) =>
    request<Environment>(`/api/v1/environments/${id}/deactivate`, { method: "POST" }),
  putAppEnvironments: (appId: string, body: unknown) =>
    request<unknown>(`/api/v1/applications/${appId}/environments`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  events: (params: URLSearchParams) =>
    request<MaintenanceEvent[]>(`/api/v1/events?${params}`),
  event: (id: string) => request<MaintenanceEvent>(`/api/v1/events/${id}`),
  createEvent: (body: unknown) =>
    request<MaintenanceEvent>("/api/v1/events", { method: "POST", body: JSON.stringify(body) }),
  transition: (id: string, body: unknown) =>
    request<MaintenanceEvent>(`/api/v1/events/${id}/transition`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  extend: (id: string, body: unknown) =>
    request<MaintenanceEvent>(`/api/v1/events/${id}/extend`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancel: (id: string, note?: string) =>
    request<MaintenanceEvent>(`/api/v1/events/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  timeline: (id: string) => request<TimelineEntry[]>(`/api/v1/events/${id}/timeline`),
  favorites: () => request<{ application_ids: string[] }>("/api/v1/me/favorites"),
  putFavorites: (application_ids: string[]) =>
    request<{ application_ids: string[] }>("/api/v1/me/favorites", {
      method: "PUT",
      body: JSON.stringify({ application_ids }),
    }),
  previewRecurrence: (body: unknown) =>
    request<{ summary: string; occurrences: Array<{ starts_at: string; ends_at: string; original_starts_at: string }> }>(
      "/api/v1/events/recurrence/preview",
      { method: "POST", body: JSON.stringify(body) },
    ),
  eventOccurrences: (id: string, from: string, to: string) =>
    request<
      Array<{
        occurrence_id: string;
        original_starts_at: string;
        starts_at: string;
        ends_at: string;
        cancelled: boolean;
        is_exception: boolean;
        status: string;
        phase: string;
        has_record?: boolean;
        expected_impact?: string | null;
        description?: string | null;
      }>
    >(`/api/v1/events/${id}/occurrences?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
  cancelOccurrence: (id: string, original_starts_at: string) =>
    request<Record<string, unknown>>(`/api/v1/events/${id}/occurrences/cancel`, {
      method: "POST",
      body: JSON.stringify({ original_starts_at }),
    }),
  occurrenceTransition: (
    id: string,
    body: { original_starts_at: string; status: string; note?: string },
  ) =>
    request<Record<string, unknown>>(`/api/v1/events/${id}/occurrences/transition`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  occurrenceExtend: (
    id: string,
    body: { original_starts_at: string; new_ends_at: string; note?: string },
  ) =>
    request<Record<string, unknown>>(`/api/v1/events/${id}/occurrences/extend`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  occurrencePatch: (id: string, body: unknown) =>
    request<Record<string, unknown>>(`/api/v1/events/${id}/occurrences`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  occurrenceHistory: (id: string, original_starts_at: string) =>
    request<{
      occurrence_id: string;
      timeline: TimelineEntry[];
      deliveries: Array<{
        id: string;
        idempotency_key: string;
        status: string;
        subject?: string | null;
      }>;
    }>(
      `/api/v1/events/${id}/occurrences/history?original_starts_at=${encodeURIComponent(original_starts_at)}`,
    ),
  seriesEdit: (id: string, body: unknown) =>
    request<MaintenanceEvent>(`/api/v1/events/${id}/series-edit`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  infraComponents: (q?: string) =>
    request<InfraComponent[]>(
      `/api/v1/infra-components${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    ),
  impactPreview: (body: unknown) =>
    request<ImpactPreview>("/api/v1/impact-analysis/preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  impactConfirm: (eventId: string, body: unknown) =>
    request<MaintenanceEvent>(`/api/v1/impact-analysis/events/${eventId}/confirm`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  statusApplication: (applicationKey: string, environmentKey?: string) => {
    const q = environmentKey ? `?environment_key=${encodeURIComponent(environmentKey)}` : "";
    return request<Record<string, unknown>>(
      `/api/v1/status/applications/${encodeURIComponent(applicationKey)}${q}`,
    );
  },
  statusEvent: (eventId: string) =>
    request<Record<string, unknown>>(`/api/v1/status/events/${encodeURIComponent(eventId)}`),
  statusScheduled: (eventId: string) =>
    request<Record<string, unknown>>(`/api/v1/status/scheduled/${encodeURIComponent(eventId)}`),
  subscriptions: () => request<Subscription[]>("/api/v1/subscriptions"),
  createSubscription: (body: unknown) =>
    request<Subscription>("/api/v1/subscriptions", { method: "POST", body: JSON.stringify(body) }),
  updateSubscription: (id: string, body: unknown) =>
    request<Subscription>(`/api/v1/subscriptions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteSubscription: (id: string) =>
    request<void>(`/api/v1/subscriptions/${id}`, { method: "DELETE" }),
  calendarReachability: () =>
    request<CalendarReachability>("/api/v1/calendar/reachability"),
  downloadCalendarIcs: async () => {
    const headers = new Headers();
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const res = await fetch("/api/v1/calendar/download.ics", { headers });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch {
        /* ignore */
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.blob();
  },
  createCalendarToken: (body: unknown) =>
    request<{
      token: string;
      feed_url: string;
      id: string;
      reachability?: CalendarReachability;
    }>("/api/v1/calendar-tokens", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listCalendarTokens: () =>
    request<
      Array<{
        id: string;
        scopes: string[];
        label?: string | null;
        revoked_at?: string | null;
        created_at?: string | null;
      }>
    >("/api/v1/calendar-tokens"),
  revokeCalendarToken: (id: string) =>
    request<void>(`/api/v1/calendar-tokens/${id}`, { method: "DELETE" }),


  // ----- M15 Administration -----
  adminOverview: () => request<Record<string, unknown>>("/api/v1/admin/overview"),
  adminSecretsStatus: () => request<Record<string, unknown>>("/api/v1/admin/secrets-status"),
  adminUsers: (q?: string) =>
    request<
      Array<{
        id: string;
        email: string;
        display_name: string;
        is_active: boolean;
        roles: string[];
      }>
    >(`/api/v1/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  adminGrants: (params?: URLSearchParams) =>
    request<
      Array<{
        id: string;
        user_id?: string | null;
        directory_group?: string | null;
        application_id: string;
        role: string;
      }>
    >(`/api/v1/admin/grants${params ? `?${params}` : ""}`),
  adminCreateGrant: (body: { user_id: string; application_id: string; role: string }) =>
    request<{ id: string }>("/api/v1/admin/grants", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminDeleteGrant: (id: string) =>
    request<void>(`/api/v1/admin/grants/${id}`, { method: "DELETE" }),
  adminDependencies: (q?: string) =>
    request<
      Array<{
        id: string;
        from_type: string;
        from_id: string;
        to_type: string;
        to_id: string;
        from_environment_id?: string | null;
        to_environment_id?: string | null;
        dependency_kind: string;
        origin: string;
        updated_at?: string | null;
        description: string;
      }>
    >(`/api/v1/admin/dependencies${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  adminCreateDependency: (body: unknown) =>
    request<Record<string, unknown>>("/api/v1/admin/dependencies", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminDeleteDependency: (id: string) =>
    request<void>(`/api/v1/admin/dependencies/${id}`, { method: "DELETE" }),
  adminCreateInfra: (body: unknown) =>
    request<InfraComponent>("/api/v1/admin/infra-components", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminDeliveries: (params?: URLSearchParams) =>
    request<
      Array<{
        id: string;
        idempotency_key: string;
        channel: string;
        destination_type: string;
        destination: string;
        subject?: string | null;
        status: string;
        event_id?: string | null;
        attempt_count: number;
        last_error?: string | null;
        created_at?: string | null;
      }>
    >(`/api/v1/admin/deliveries${params ? `?${params}` : ""}`),
  adminJobs: (params?: URLSearchParams) =>
    request<
      Array<{
        id: string;
        job_type: string;
        status: string;
        attempt_count: number;
        last_error?: string | null;
        leased_by?: string | null;
        idempotency_key?: string | null;
        run_at?: string | null;
        created_at?: string | null;
      }>
    >(`/api/v1/admin/jobs${params ? `?${params}` : ""}`),
  adminRetryJob: (id: string) =>
    request<Record<string, unknown>>(`/api/v1/admin/jobs/${id}/retry`, { method: "POST" }),
  adminAudit: (params?: URLSearchParams) =>
    request<
      Array<{
        id: string;
        actor_id?: string | null;
        action: string;
        entity_type: string;
        entity_id?: string | null;
        summary: Record<string, unknown>;
        at?: string | null;
      }>
    >(`/api/v1/admin/audit${params ? `?${params}` : ""}`),
  adminIntegrations: () =>
    request<Record<string, unknown>>("/api/v1/admin/settings/integrations"),
  adminTestIntegration: (kind: string) =>
    request<Record<string, unknown>>(
      `/api/v1/admin/settings/integrations/test?kind=${encodeURIComponent(kind)}`,
      { method: "POST" },
    ),
  adminSnPoll: (body: { dry_run?: boolean; fixture_records?: unknown[] }) =>
    request<Record<string, unknown>>("/api/v1/admin/servicenow/poll-now", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminSnUnmatched: (status = "open") =>
    request<
      Array<{
        id: string;
        external_id: string;
        reason: string;
        status: string;
        raw_payload?: unknown;
        resolved_event_id?: string | null;
      }>
    >(`/api/v1/admin/servicenow/unmatched?status=${encodeURIComponent(status)}`),
  adminSnResolve: (id: string, body: { action: string; event_id?: string }) =>
    request<Record<string, unknown>>(`/api/v1/admin/servicenow/unmatched/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminImports: () =>
    request<
      Array<{
        id: string;
        kind: string;
        filename: string;
        status: string;
        created_at?: string | null;
        committed_at?: string | null;
        result_summary?: Record<string, unknown> | null;
      }>
    >("/api/v1/admin/imports"),
  adminUploadCsv: async (file: File, kind: string, overwriteManual = false) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    fd.append("overwrite_manual_dependencies", overwriteManual ? "true" : "false");
    const headers = new Headers();
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const res = await fetch("/api/v1/admin/imports/csv", { method: "POST", headers, body: fd });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail || detail;
      } catch {
        /* ignore */
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json() as Promise<{ id: string; status: string; kind: string; filename: string }>;
  },
  adminPreviewImport: (id: string) =>
    request<Record<string, unknown>>(`/api/v1/admin/imports/${id}/preview`, { method: "POST" }),
  adminCommitImport: (id: string) =>
    request<Record<string, unknown>>(`/api/v1/admin/imports/${id}/commit`, { method: "POST" }),
  adminRoleMappings: () =>
    request<
      Array<{
        id: string;
        directory_group: string;
        role: string;
        application_id?: string | null;
      }>
    >("/api/v1/admin/role-mappings"),
  adminCreateRoleMapping: (body: {
    directory_group: string;
    role: string;
    application_id?: string | null;
  }) =>
    request<Record<string, unknown>>("/api/v1/admin/role-mappings", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  adminDeleteRoleMapping: (id: string) =>
    request<void>(`/api/v1/admin/role-mappings/${id}`, { method: "DELETE" }),
  adminServiceCredentials: () =>
    request<
      Array<{
        id: string;
        name: string;
        client_id: string;
        scopes: string[];
        application_id?: string | null;
        revoked_at?: string | null;
      }>
    >("/api/v1/admin/service-credentials"),
  adminCreateServiceCred: (body: { name: string; scopes?: string[]; application_id?: string }) =>
    request<{ id: string; client_id: string; client_secret: string }>(
      "/api/v1/admin/service-credentials",
      { method: "POST", body: JSON.stringify(body) },
    ),
  adminRotateServiceCred: (id: string) =>
    request<{ client_id: string; client_secret: string }>(
      `/api/v1/admin/service-credentials/${id}/rotate`,
      { method: "POST" },
    ),
  adminRevokeServiceCred: (id: string) =>
    request<Record<string, unknown>>(`/api/v1/admin/service-credentials/${id}/revoke`, {
      method: "POST",
    }),
  notificationTemplates: (includeArchived = false) =>
    request<
      Array<{
        id: string;
        key: string;
        name?: string | null;
        description?: string | null;
        event_type?: string | null;
        status: string;
        channel: string;
        subject_template: string;
        body_template: string;
        body_plain_template?: string | null;
        body_html_template?: string | null;
        version: number;
        is_system: boolean;
      }>
    >(`/api/v1/notification-templates${includeArchived ? "?include_archived=true" : ""}`),
  notificationTemplateCatalog: () =>
    request<{
      event_types: Array<{ key: string; label: string }>;
      placeholders: Array<{ key: string; label: string; sample: string; note?: string }>;
      pa_notes: Record<string, string>;
    }>("/api/v1/notification-templates/catalog"),
  createNotificationTemplate: (body: unknown) =>
    request<Record<string, unknown>>("/api/v1/notification-templates", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchNotificationTemplate: (
    key: string,
    body: Record<string, unknown>,
  ) =>
    request<Record<string, unknown>>(`/api/v1/notification-templates/${key}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  cloneNotificationTemplate: (key: string, body: { new_key?: string; new_name?: string } = {}) =>
    request<Record<string, unknown>>(`/api/v1/notification-templates/${key}/clone`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  activateNotificationTemplate: (key: string) =>
    request<Record<string, unknown>>(`/api/v1/notification-templates/${key}/activate`, {
      method: "POST",
    }),
  deactivateNotificationTemplate: (key: string) =>
    request<Record<string, unknown>>(`/api/v1/notification-templates/${key}/deactivate`, {
      method: "POST",
    }),
  archiveNotificationTemplate: (key: string) =>
    request<Record<string, unknown>>(`/api/v1/notification-templates/${key}/archive`, {
      method: "POST",
    }),
  notificationTemplateVersions: (key: string) =>
    request<
      Array<{
        version: number;
        change_note?: string | null;
        changed_by?: string | null;
        created_at?: string | null;
        subject_template: string;
        body_plain_template?: string | null;
        status: string;
      }>
    >(`/api/v1/notification-templates/${key}/versions`),
  restoreNotificationTemplate: (key: string, version: number) =>
    request<Record<string, unknown>>(`/api/v1/notification-templates/${key}/restore`, {
      method: "POST",
      body: JSON.stringify({ version }),
    }),
  previewNotificationTemplate: (key: string, body: unknown = {}) =>
    request<{
      subject: string;
      body_plain: string;
      body_html: string;
      pa_note?: string;
    }>(`/api/v1/notification-templates/${key}/preview`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  testNotification: (body: unknown) =>
    request<{
      delivery_id: string;
      status: string;
      channel: string;
      subject?: string | null;
      preview: { subject: string; body: string; body_plain?: string; body_html?: string };
      rendered_payload?: Record<string, unknown>;
      note?: string;
    }>("/api/v1/notifications/test", { method: "POST", body: JSON.stringify(body) }),
  supportGroups: () =>
    request<Array<{ id: string; key: string; name: string; directory_group?: string | null }>>(
      "/api/v1/support-groups",
    ),
  createSupportGroup: (body: unknown) =>
    request<Record<string, unknown>>("/api/v1/support-groups", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
