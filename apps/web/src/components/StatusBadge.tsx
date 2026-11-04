import clsx from "clsx";
import { kindLabel, statusLabel } from "@/lib/format";

const STATUS_META: Record<
  string,
  { label: string; icon: string; className: string }
> = {
  scheduled: {
    label: "Scheduled",
    icon: "◷",
    className: "bg-ink-100 text-ink-800 border-ink-300",
  },
  in_progress: {
    label: "In progress",
    icon: "●",
    className: "bg-warn-soft text-warn border-amber-300 animate-pulse-soft",
  },
  extended: {
    label: "Extended",
    icon: "↻",
    className: "bg-orange-100 text-orange-900 border-orange-300",
  },
  verifying: {
    label: "Verifying",
    icon: "◐",
    className: "bg-sky-100 text-sky-900 border-sky-300",
  },
  completed: {
    label: "Completed",
    icon: "✓",
    className: "bg-emerald-50 text-emerald-900 border-emerald-300",
  },
  cancelled: {
    label: "Cancelled",
    icon: "✕",
    className: "bg-ink-50 text-ink-500 border-ink-200 line-through",
  },
};

export function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] || {
    label: statusLabel(status),
    icon: "•",
    className: "bg-ink-100 text-ink-700 border-ink-200",
  };
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-semibold",
        meta.className,
      )}
      role="status"
      aria-label={`Status: ${meta.label}`}
    >
      <span aria-hidden="true">{meta.icon}</span>
      <span>{meta.label}</span>
    </span>
  );
}

export function KindBadge({ kind }: { kind: string }) {
  const outage = kind === "manual_outage";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-semibold",
        outage
          ? "border-danger/40 bg-danger-soft text-danger"
          : "border-accent/30 bg-accent-soft text-accent-strong",
      )}
      aria-label={`Kind: ${kindLabel(kind)}`}
    >
      <span aria-hidden="true">{outage ? "!" : "⚙"}</span>
      {kindLabel(kind)}
    </span>
  );
}

export function ApprovalBadge({ state }: { state: string }) {
  const confirmed = state === "confirmed_scheduled";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium",
        confirmed
          ? "border-teal-300 bg-teal-50 text-teal-900"
          : "border-violet-200 bg-violet-50 text-violet-900",
      )}
      aria-label={`Approval: ${statusLabel(state)}`}
    >
      <span aria-hidden="true">{confirmed ? "✔" : "◇"}</span>
      {confirmed ? "Confirmed scheduled" : "Approved window"}
    </span>
  );
}
