import { format, formatDistanceStrict, parseISO } from "date-fns";

function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** Prefer configured deploy/demo zone when browser reports bare UTC (common in agents). */
export function resolveDisplayTimeZone(configured?: string | null): string {
  const browser = browserTimeZone();
  const cfg = configured?.trim();
  if (cfg) return cfg;
  return browser;
}

function userTimeZone(): string {
  return browserTimeZone();
}

/** Human wall time in the viewer's timezone (falls back to event TZ hint). */
export function fmtWhen(iso: string, tzHint?: string): string {
  try {
    const d = parseISO(iso);
    const tz = userTimeZone();
    const formatted = new Intl.DateTimeFormat(undefined, {
      timeZone: tz,
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(d);
    return `${formatted} (${tzHint && tzHint !== tz ? `${tz} · event ${tzHint}` : tz})`;
  } catch {
    return iso;
  }
}

export function fmtRange(start: string, end: string, _tzHint?: string): string {
  try {
    const tz = userTimeZone();
    const opts: Intl.DateTimeFormatOptions = {
      timeZone: tz,
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    };
    const a = new Intl.DateTimeFormat(undefined, opts).format(parseISO(start));
    const b = new Intl.DateTimeFormat(undefined, {
      ...opts,
      month: undefined,
      day: undefined,
    }).format(parseISO(end));
    const sameDay =
      format(parseISO(start), "yyyy-MM-dd") === format(parseISO(end), "yyyy-MM-dd");
    if (sameDay) {
      return `${a} – ${b}`;
    }
    const bFull = new Intl.DateTimeFormat(undefined, opts).format(parseISO(end));
    return `${a} – ${bFull}`;
  } catch {
    return `${start} → ${end}`;
  }
}

export function untilBack(endIso: string): string {
  try {
    const end = parseISO(endIso);
    const now = new Date();
    if (end <= now) return "window ended";
    return `Expected back in ${formatDistanceStrict(end, now)}`;
  } catch {
    return "";
  }
}

export function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

export function kindLabel(kind: string): string {
  if (kind === "manual_outage") return "Manual outage";
  if (kind === "planned_maintenance") return "Planned maintenance";
  return kind;
}

export function detectUserTimeZone(): string {
  return userTimeZone();
}
