import type { GrievanceStatus } from "../api/types";
import { useI18n, type Catalog } from "../i18n/I18nContext";

type Tone = "neutral" | "info" | "warning" | "success";
interface StatusMeta { key: keyof Catalog; tone: Tone; live?: boolean; fallback?: string }

const STATUS_META: Record<string, Omit<StatusMeta, "fallback">> = {
  draft: { key: "stDraft", tone: "neutral" },
  processing: { key: "stProcessing", tone: "info", live: true },
  awaiting_confirmation: { key: "stAwaiting", tone: "info" },
  photo_mismatch: { key: "stPhotoMismatch", tone: "warning" },
  registered: { key: "stRegistered", tone: "success" },
  pending_window: { key: "stGrouping", tone: "info", live: true },
  dispatching: { key: "stDispatching", tone: "info", live: true },
  submitted: { key: "stSubmitted", tone: "success" },
  duplicate: { key: "stDuplicate", tone: "info" },
  cancelled: { key: "stCancelled", tone: "neutral" },
  dispatch_failed: { key: "stDispatchFailed", tone: "warning" },
};

export function metaForStatus(status: string): StatusMeta {
  const meta = STATUS_META[status as GrievanceStatus];
  if (meta) return meta;
  const fallbackLabel = status
    .replace(/_/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
  return { key: "stFallback", tone: "neutral", fallback: fallbackLabel || undefined };
}

export default function StatusChip({ status }: { status: string }) {
  const { t } = useI18n();
  const meta = metaForStatus(status);
  return (
    <span className={`status-chip status-chip--${meta.tone}`} data-live={meta.live ? "true" : undefined}>
      <span>{meta.fallback ?? t[meta.key]}</span>
    </span>
  );
}
