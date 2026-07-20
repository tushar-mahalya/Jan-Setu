import { useState } from "react";
import type { GrievanceDraftResponse } from "../api/types";
import PhotoUpload from "./PhotoUpload";

interface Props {
  draft: GrievanceDraftResponse;
  onReplacePhoto: (file: File) => void;
  isReplacingPhoto: boolean;
  onUpdateReview: (changes: { category_id?: string; asset_scope?: string; summary?: string; clarification_answer?: string }) => void;
  isUpdatingReview: boolean;
  onConfirm: () => void;
  isConfirming: boolean;
}

const INCOMPLETE_FLAGS = new Set(["classification_failed", "transcription_failed", "official_review_required"]);
const COMMON_CATEGORIES = [
  ["pothole_surface_damage", "Pothole or road surface damage"],
  ["streetlight_out", "Streetlight not working"],
  ["missed_door_to_door_collection", "Missed waste collection"],
  ["open_dumping_or_litter", "Open dumping or litter"],
  ["pipeline_leak", "Water pipeline leak"],
  ["no_or_low_supply", "No or low water supply"],
  ["blocked_storm_drain", "Blocked storm drain"],
  ["sewage_overflow", "Sewage overflow"],
  ["open_or_damaged_manhole", "Open or damaged manhole"],
  ["fallen_or_hazardous_tree", "Fallen or hazardous tree"],
  ["injured_or_trapped_animal", "Injured or trapped animal"],
  ["unmapped_service", "Other civic service"],
] as const;

export default function ReviewCard({ draft, onReplacePhoto, isReplacingPhoto, onUpdateReview, isUpdatingReview, onConfirm, isConfirming }: Props) {
  const [showPhotoPicker, setShowPhotoPicker] = useState(false);
  const [showCorrection, setShowCorrection] = useState(false);
  const [replacementPhoto, setReplacementPhoto] = useState<File | null>(null);
  const [categoryId, setCategoryId] = useState("");
  const [assetScope, setAssetScope] = useState(draft.asset_scope ?? "unknown");
  const [summary, setSummary] = useState("");
  const [clarificationAnswer, setClarificationAnswer] = useState("");

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
  const incomplete = draft.flags.some((flag) => INCOMPLETE_FLAGS.has(flag));
  const mismatch = draft.image_match_status === "mismatched";
  const immediate = draft.safety_level === "immediate" || draft.disposition === "emergency_redirect";
  const clarification = draft.structured_facts?.clarification_question;

  if (processing) return <article className="review-card review-card--processing" aria-live="polite">
    <div className="wizard-processing"><span />Reading your report, checking jurisdiction, and preparing routing…</div>
    <p className="muted-note">Your evidence is saved. This page updates automatically.</p>
  </article>;

  return <article className="review-card" aria-labelledby="review-title">
    <header><span className="review-card__step">Final check</span><h1 id="review-title">Review what we understood</h1><p className="muted-note">Confirm the facts—not the bureaucracy. Department, urgency, and routing are determined from reviewed policy.</p></header>
    {immediate && <div className="notice review-card__emergency" role="alert"><strong>Possible immediate safety risk</strong><p>Do not wait for this portal if anyone is in danger. Contact the appropriate local emergency service now. This report will also require official review.</p></div>}
    <dl className="review-card__grid">
      <div className="review-card__field"><dt>Ticket ID</dt><dd className="mono">{draft.human_id}</dd></div>
      <div className="review-card__field"><dt>Issue</dt><dd>{draft.category_label ?? draft.category ?? "Being identified"}</dd></div>
      {draft.domain_label && <div className="review-card__field"><dt>Service area</dt><dd>{draft.domain_label}</dd></div>}
      <div className="review-card__field"><dt>Proposed owner</dt><dd>{draft.routing?.owning_agency ?? draft.department_name ?? "Official review needed"}</dd></div>
      <div className="review-card__field"><dt>Handling</dt><dd>{draft.disposition?.replace(/_/g, " ") ?? "Municipal review"}</dd></div>
      <div className="review-card__field review-card__field--wide"><dt>Location</dt><dd>{draft.address ?? "Coordinates attached; jurisdiction being resolved"}</dd></div>
      {(draft.structured_facts?.summary || draft.issue_text) && <div className="review-card__field review-card__field--wide"><dt>Issue summary</dt><dd className="quote-block">{draft.structured_facts?.summary || draft.issue_text}</dd></div>}
    </dl>
    {clarification && <div className="review-card__clarification"><strong>One detail would help</strong><label>{clarification}<textarea rows={3} value={clarificationAnswer} onChange={(event) => setClarificationAnswer(event.target.value)} /></label><button type="button" className="app-button app-button--soft" disabled={!clarificationAnswer.trim() || isUpdatingReview} onClick={() => onUpdateReview({ clarification_answer: clarificationAnswer })}>{isUpdatingReview ? "Saving…" : "Add this detail"}</button></div>}
    {incomplete && <div className="notice" data-tone="muted"><strong>Official review required</strong><p>Free-model inference was uncertain, evidence conflicts, ownership is unknown, or this report needs safety review. Your original evidence remains attached.</p></div>}
    {!showCorrection ? <button type="button" className="btn-link review-card__correct" onClick={openCorrection}>Something is wrong? Correct it</button> : <div className="review-card__correction">
      <label>Issue type<select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}><option value="" disabled>Choose the issue type</option>{COMMON_CATEGORIES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
      <label>Asset ownership<select value={assetScope} onChange={(event) => setAssetScope(event.target.value as "public" | "private" | "unknown")}><option value="public">Public civic asset</option><option value="private">Private property/asset</option><option value="unknown">Not sure</option></select></label>
      <label>Corrected summary<textarea rows={4} value={summary} maxLength={600} onChange={(event) => setSummary(event.target.value)} /></label>
      <div className="review-card__actions"><button type="button" className="btn-link" onClick={() => setShowCorrection(false)}>Cancel</button><button type="button" className="app-button app-button--teal" disabled={!categoryId || !summary.trim() || isUpdatingReview} onClick={() => onUpdateReview({ category_id: categoryId, asset_scope: assetScope, summary })}>{isUpdatingReview ? "Rechecking…" : "Save correction"}</button></div>
    </div>}
    {draft.pdf_url && <a className="review-card__draft-link" href={draft.pdf_url} target="_blank" rel="noreferrer">Preview draft receipt ↗</a>}
    {mismatch && <div className="review-card__warning" role="alert"><strong>Photo evidence may conflict with the description.</strong><p>This never proves your report is false. Replace the photo or continue; an official can review the original evidence.</p>{!showPhotoPicker ? <div className="review-card__actions"><button type="button" className="btn btn--secondary" onClick={() => setShowPhotoPicker(true)}>Choose another photo</button></div> : <div className="review-card__photo-retry"><PhotoUpload value={replacementPhoto} onChange={setReplacementPhoto} /><button type="button" className="app-button app-button--teal" disabled={!replacementPhoto || isReplacingPhoto} onClick={() => replacementPhoto && onReplacePhoto(replacementPhoto)}>{isReplacingPhoto ? "Checking new photo…" : "Use this photo"}</button></div>}</div>}
    <div className="review-card__actions review-card__actions--submit"><p>By continuing, you confirm the citizen-provided facts. Automated routing may still be corrected by an assigned official.</p><button type="button" className="app-button app-button--orange" onClick={onConfirm} disabled={isConfirming}>{isConfirming ? "Filing complaint…" : draft.review_status === "pending_official" ? "Send for official review" : "Confirm & file complaint"}</button></div>
  </article>;
}
