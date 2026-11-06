import clsx from "clsx";
import { kindLabel } from "@/lib/format";
import {
  presentationStatus,
  type PresentationMeta,
} from "@/lib/presentationStatus";

const TONE: Record<PresentationMeta["tone"], string> = {
  neutral: "border-ink-200 bg-accent-soft text-ink",
  info: "border-ink-200 bg-surface-raised text-ink-muted",
  warn: "border-warn/30 bg-warn-soft text-warn",
  danger: "border-danger/30 bg-danger-soft text-danger",
  ok: "border-ok/30 bg-ok-soft text-ok",
  muted: "border-ink-200 bg-surface text-ink-faint line-through",
};

/** Single primary presentation badge for lists and calendar. */
export function PrimaryStatusBadge({
  status,
  approvalState,
  kind,
  showExplanation = false,
}: {
  status: string;
  approvalState?: string | null;
  kind?: string | null;
  showExplanation?: boolean;
}) {
  const meta = presentationStatus({ status, approval_state: approvalState, kind });
  return (
    <span className="inline-flex max-w-full flex-col items-start gap-0.5">
      <span
        className={clsx(
          "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold",
          TONE[meta.tone],
        )}
        role="status"
        aria-label={`Status: ${meta.label}. ${meta.explanation}`}
        title={meta.explanation}
      >
        {meta.label}
      </span>
      {showExplanation && (
        <span className="text-[11px] leading-snug text-ink-muted">{meta.explanation}</span>
      )}
    </span>
  );
}

/** @deprecated Prefer PrimaryStatusBadge — kept for detail pages that still show technical state. */
export function StatusBadge({ status }: { status: string }) {
  return <PrimaryStatusBadge status={status} />;
}

export function KindBadge({ kind }: { kind: string }) {
  const outage = kind === "manual_outage";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold",
        outage
          ? "border-danger/40 bg-danger-soft text-danger"
          : "border-accent/30 bg-accent-soft text-accent-strong",
      )}
      aria-label={`Kind: ${kindLabel(kind)}`}
    >
      {kindLabel(kind)}
    </span>
  );
}

export function ApprovalBadge({ state }: { state: string }) {
  return (
    <PrimaryStatusBadge
      status="scheduled"
      approvalState={state === "approved_window" ? "approved_window" : "confirmed_scheduled"}
    />
  );
}
