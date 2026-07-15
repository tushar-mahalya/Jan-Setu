import { useState } from "react";
import type { GrievanceDraftResponse } from "../api/types";
import PhotoUpload from "./PhotoUpload";

interface Props {
  draft: GrievanceDraftResponse;
  onReplacePhoto: (file: File) => void;
  isReplacingPhoto: boolean;
  onConfirm: () => void;
  isConfirming: boolean;
}

const INCOMPLETE_FLAGS = new Set(["classification_failed", "transcription_failed"]);

export default function ReviewCard({ draft, onReplacePhoto, isReplacingPhoto, onConfirm, isConfirming }: Props) {
  const [showPhotoPicker, setShowPhotoPicker] = useState(false);
  const [replacementPhoto, setReplacementPhoto] = useState<File | null>(null);
  const incomplete = draft.flags.some((flag) => INCOMPLETE_FLAGS.has(flag));
  const mismatch = draft.image_match_status === "mismatched";

  return <article className="review-card" aria-labelledby="review-title">
    <header><span className="review-card__step">Final check</span><h1 id="review-title">Review your complaint</h1><p className="muted-note">Confirm the routing details below. You can still go back if something is missing.</p></header>
    <dl className="review-card__grid">
      <div className="review-card__field"><dt>Ticket ID</dt><dd className="mono">{draft.human_id}</dd></div>
      <div className="review-card__field"><dt>Category</dt><dd>{draft.category ?? "Being identified"}</dd></div>
      <div className="review-card__field"><dt>Department</dt><dd>{draft.department_name ?? "Being routed"}</dd></div>
      <div className="review-card__field"><dt>Priority</dt><dd>{draft.priority ?? "Standard"}</dd></div>
      <div className="review-card__field review-card__field--wide"><dt>Location</dt><dd>{draft.address ?? "Coordinates attached"}</dd></div>
      {draft.issue_text && <div className="review-card__field review-card__field--wide"><dt>Your description</dt><dd className="quote-block">{draft.issue_text}</dd></div>}
    </dl>
    {incomplete && <div className="notice" data-tone="muted"><strong>Some automated details are still being resolved.</strong><p>You can submit now. The complaint and your evidence will remain attached.</p></div>}
    {draft.pdf_url && <a className="review-card__draft-link" href={draft.pdf_url} target="_blank" rel="noreferrer">Preview draft receipt ↗</a>}
    {mismatch && <div className="review-card__warning" role="alert"><strong>We couldn’t confidently match the photo to this issue.</strong><p>Choose another photo, or continue without using it. Your written or voice description will still be submitted.</p>{!showPhotoPicker ? <div className="review-card__actions"><button type="button" className="btn btn--secondary" onClick={() => setShowPhotoPicker(true)}>Choose another photo</button><button type="button" className="app-button app-button--orange" onClick={onConfirm} disabled={isConfirming}>{isConfirming ? "Filing complaint…" : "Continue without photo"}</button></div> : <div className="review-card__photo-retry"><PhotoUpload value={replacementPhoto} onChange={setReplacementPhoto} /><button type="button" className="app-button app-button--teal" disabled={!replacementPhoto || isReplacingPhoto} onClick={() => replacementPhoto && onReplacePhoto(replacementPhoto)}>{isReplacingPhoto ? "Checking new photo…" : "Use this photo"}</button></div>}</div>}
    {!mismatch && <div className="review-card__actions review-card__actions--submit"><p>By submitting, you confirm these details describe the civic issue you observed.</p><button type="button" className="app-button app-button--orange" onClick={onConfirm} disabled={isConfirming}>{isConfirming ? "Filing complaint…" : "Confirm & file complaint"}</button></div>}
  </article>;
}
