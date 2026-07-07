import type { GrievanceStatus } from "../api/types";

type Tone = "neutral" | "info" | "warning" | "success" | "danger";

interface StatusMeta {
  label: string;
  tone: Tone;
  live?: boolean;
}

// Friendly, non-alarming labels for a citizen audience — the raw enum never
// reaches the screen. "live" statuses are actively being worked on by the
// system right now, so their chip pulses instead of sitting static.
const STATUS_META: Record<string, StatusMeta> = {
  draft: { label: "Draft", tone: "neutral" },
  processing: { label: "Processing", tone: "info", live: true },
  awaiting_confirmation: { label: "Awaiting Confirmation", tone: "info" },
  photo_mismatch: { label: "Photo Needs Review", tone: "warning" },
  registered: { label: "Registered", tone: "success" },
  pending_window: { label: "Grouping Reports", tone: "info", live: true },
  dispatching: { label: "Dispatching", tone: "info", live: true },
  submitted: { label: "Submitted", tone: "success" },
  duplicate: { label: "Also Reported", tone: "info" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  dispatch_failed: { label: "Dispatch Delayed", tone: "warning" },
};

export function metaForStatus(status: string): StatusMeta {
  return STATUS_META[status as GrievanceStatus] ?? { label: status.replace(/_/g, " "), tone: "neutral" };
}

export default function StatusChip({ status }: { status: string }) {
  const { label, tone, live } = metaForStatus(status);
  return (
    <span className={`status-chip status-chip--${tone}`} data-live={live ? "true" : undefined}>
      {label}
    </span>
  );
}
