import type { GrievanceStatus } from "../api/types";

type Tone = "neutral" | "info" | "warning" | "success";
interface StatusMeta { label: string; hindi: string; tone: Tone; live?: boolean }

const STATUS_META: Record<string, StatusMeta> = {
  draft: { label: "Draft", hindi: "प्रारूप", tone: "neutral" },
  processing: { label: "Processing", hindi: "जाँच जारी", tone: "info", live: true },
  awaiting_confirmation: { label: "Awaiting confirmation", hindi: "पुष्टि बाकी", tone: "info" },
  photo_mismatch: { label: "Photo needs review", hindi: "फोटो की जाँच करें", tone: "warning" },
  registered: { label: "Registered", hindi: "दर्ज", tone: "success" },
  pending_window: { label: "Grouping reports", hindi: "रिपोर्ट जोड़ी जा रही हैं", tone: "info", live: true },
  dispatching: { label: "Sending to department", hindi: "विभाग को भेजा जा रहा है", tone: "info", live: true },
  submitted: { label: "Submitted", hindi: "जमा", tone: "success" },
  duplicate: { label: "Also reported", hindi: "पहले भी दर्ज", tone: "info" },
  cancelled: { label: "Cancelled", hindi: "रद्द", tone: "neutral" },
  dispatch_failed: { label: "Dispatch delayed", hindi: "भेजने में देरी", tone: "warning" },
};

export function metaForStatus(status: string): StatusMeta {
  const fallbackLabel = status
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
  return STATUS_META[status as GrievanceStatus] ?? {
    label: fallbackLabel || "Status", hindi: "स्थिति", tone: "neutral",
  };
}

export default function StatusChip({ status }: { status: string }) {
  const { label, hindi, tone, live } = metaForStatus(status);
  return (
    <span className={`status-chip status-chip--${tone}`} data-live={live ? "true" : undefined}>
      <span>{label}</span><span className="status-chip__translation" lang="hi">{hindi}</span>
    </span>
  );
}
