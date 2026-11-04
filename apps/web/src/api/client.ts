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
  sort_order: number;
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
  as_of: string;
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
  environments: () => request<Environment[]>("/api/v1/environments"),
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
};
