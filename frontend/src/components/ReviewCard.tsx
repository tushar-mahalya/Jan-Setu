import { useState } from "react";
import type { GrievanceDraftResponse } from "../api/types";
import PhotoUpload from "./PhotoUpload";
import { useI18n, type Catalog } from "../i18n/I18nContext";

interface Props {
  draft: GrievanceDraftResponse;
  onReplacePhoto: (file: File) => void;
  isReplacingPhoto: boolean;
  onUpdateReview: (changes: { category_id?: string; asset_scope?: string; summary?: string; clarification_answer?: string }) => void;
  isUpdatingReview: boolean;
  onConfirm: () => void;
  isConfirming: boolean;
}

const COMMON_CATEGORIES = [
  ["pothole_surface_damage", "catPothole"],
  ["streetlight_out", "catStreetlight"],
  ["missed_door_to_door_collection", "catMissedCollection"],
  ["open_dumping_or_litter", "catDumping"],
  ["pipeline_leak", "catPipelineLeak"],
  ["no_or_low_supply", "catLowSupply"],
  ["blocked_storm_drain", "catBlockedDrain"],
  ["sewage_overflow", "catSewage"],
  ["open_or_damaged_manhole", "catManhole"],
  ["fallen_or_hazardous_tree", "catFallenTree"],
  ["injured_or_trapped_animal", "catInjuredAnimal"],
  ["unmapped_service", "catOtherService"],
] as const satisfies readonly (readonly [string, keyof Catalog])[];

export default function ReviewCard({ draft, onReplacePhoto, isReplacingPhoto, onUpdateReview, isUpdatingReview, onConfirm, isConfirming }: Props) {
  const { t } = useI18n();
  const [showPhotoPicker, setShowPhotoPicker] = useState(false);
  const [showCorrection, setShowCorrection] = useState(false);
  const [replacementPhoto, setReplacementPhoto] = useState<File | null>(null);
  const [categoryId, setCategoryId] = useState("");
  const [assetScope, setAssetScope] = useState(draft.asset_scope ?? "unknown");
  const [summary, setSummary] = useState("");

  // Seed the correction form when it opens, not at mount: this component mounts
  // while the draft is still processing (category/summary null), so mount-time
  // useState seeds would go stale and leave Save disabled with no way out.
  const openCorrection = () => {
    const known = COMMON_CATEGORIES.some(([value]) => value === draft.category_id);
    setCategoryId(known && draft.category_id ? draft.category_id : "");
    setAssetScope(draft.asset_scope ?? "unknown");
    setSummary(draft.structured_facts?.summary ?? draft.issue_text ?? "");
    setShowCorrection(true);
  };
  const processing = draft.status === "processing";
  const mismatch = draft.image_match_status === "mismatched";
  const immediate = draft.safety_level === "immediate" || draft.disposition === "emergency_redirect";

  if (processing) return <article className="review-card review-card--processing" aria-live="polite">
    <div className="wizard-processing"><span />{t.reviewProcessing}</div>
    <p className="muted-note">{t.reviewProcessingNote}</p>
  </article>;

  return <article className="review-card" aria-labelledby="review-title">
    <header><span className="review-card__step">{t.finalCheck}</span><h1 id="review-title">{t.reviewTitle}</h1><p className="muted-note">{t.reviewSub}</p></header>
    {immediate && <div className="notice review-card__emergency" role="alert"><strong>{t.emergencyTitle}</strong><p>{t.emergencyBody}</p></div>}
    <dl className="review-card__grid">
      <div className="review-card__field"><dt>{t.fieldTicket}</dt><dd className="mono">{draft.human_id}</dd></div>
      <div className="review-card__field"><dt>{t.fieldIssue}</dt><dd>{draft.category_label ?? draft.category ?? t.beingIdentified}</dd></div>
      {draft.domain_label && <div className="review-card__field"><dt>{t.fieldServiceArea}</dt><dd>{draft.domain_label}</dd></div>}
      <div className="review-card__field"><dt>{t.fieldOwner}</dt><dd>{draft.routing?.owning_agency ?? draft.department_name ?? t.ownerReviewNeeded}</dd></div>
      <div className="review-card__field"><dt>{t.fieldHandling}</dt><dd>{draft.disposition?.replace(/_/g, " ") ?? t.beingIdentified}</dd></div>
      <div className="review-card__field review-card__field--wide"><dt>{t.fieldLocation}</dt><dd>{draft.address ?? t.locationPending}</dd></div>
      {(draft.structured_facts?.summary || draft.issue_text) && <div className="review-card__field review-card__field--wide"><dt>{t.fieldSummary}</dt><dd className="quote-block">{draft.structured_facts?.summary || draft.issue_text}</dd></div>}
    </dl>
    {!showCorrection ? <button type="button" className="btn-link review-card__correct" onClick={openCorrection}>{t.correctCta}</button> : <div className="review-card__correction">
      <label>{t.correctIssueLabel}<select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="" disabled>{t.chooseIssueType}</option>{COMMON_CATEGORIES.map(([value, labelKey]) => <option value={value} key={value}>{t[labelKey]}</option>)}</select></label>
      <label>{t.correctOwnershipLabel}<select value={assetScope} onChange={(event) => setAssetScope(event.target.value as "public" | "private" | "unknown")}><option value="public">{t.ownPublic}</option><option value="private">{t.ownPrivate}</option><option value="unknown">{t.ownUnsure}</option></select></label>
      <label>{t.correctSummaryLabel}<textarea rows={4} value={summary} maxLength={600} onChange={(event) => setSummary(event.target.value)} /></label>
      <div className="review-card__actions"><button type="button" className="btn-link" onClick={() => setShowCorrection(false)}>{t.cancel}</button><button type="button" className="app-button app-button--teal" disabled={!categoryId || !summary.trim() || isUpdatingReview} onClick={() => onUpdateReview({ category_id: categoryId, asset_scope: assetScope, summary })}>{isUpdatingReview ? t.saveCorrectionBusy : t.saveCorrection}</button></div>
    </div>}
    {draft.pdf_url && <a className="review-card__draft-link" href={draft.pdf_url} target="_blank" rel="noreferrer">{t.previewReceiptLink}</a>}
    {mismatch && <div className="review-card__warning" role="alert"><strong>{t.mismatchTitle}</strong>{draft.structured_facts?.contradictions?.length ? <><ul className="review-card__reasons">{draft.structured_facts.contradictions.map((reason, i) => <li key={i}>{reason}</li>)}</ul><p className="muted-note">{t.mismatchBody}</p></> : <p>{t.mismatchBody}</p>}{!showPhotoPicker ? <div className="review-card__actions"><button type="button" className="btn btn--secondary" onClick={() => setShowPhotoPicker(true)}>{t.chooseAnotherPhoto}</button></div> : <div className="review-card__photo-retry"><PhotoUpload value={replacementPhoto} onChange={setReplacementPhoto} /><button type="button" className="app-button app-button--teal" disabled={!replacementPhoto || isReplacingPhoto} onClick={() => replacementPhoto && onReplacePhoto(replacementPhoto)}>{isReplacingPhoto ? t.checkingPhoto : t.useThisPhoto}</button></div>}</div>}
    <div className="review-card__actions review-card__actions--submit"><p>{t.confirmNote}</p><button type="button" className="app-button app-button--orange" onClick={onConfirm} disabled={isConfirming}>{isConfirming ? t.confirmBusy : draft.review_status === "pending_official" ? t.sendOfficialCta : t.confirmCta}</button></div>
  </article>;
}
