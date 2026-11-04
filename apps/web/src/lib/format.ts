import { format, formatDistanceStrict, parseISO } from "date-fns";

export function fmtWhen(iso: string, tzHint?: string): string {
  try {
    const d = parseISO(iso);
    const base = format(d, "MMM d, yyyy HH:mm");
    return tzHint ? `${base} UTC (${tzHint})` : `${base} UTC`;
  } catch {
    return iso;
  }
}

export function fmtRange(start: string, end: string): string {
  try {
    return `${format(parseISO(start), "MMM d HH:mm")} → ${format(parseISO(end), "MMM d HH:mm")} UTC`;
  } catch {
    return `${start} → ${end}`;
  }
}

export function untilBack(endIso: string): string {
  try {
    const end = parseISO(endIso);
    const now = new Date();
    if (end <= now) return "window ended";
    return `expected back in ${formatDistanceStrict(end, now)}`;
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
