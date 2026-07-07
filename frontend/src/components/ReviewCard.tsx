import { useState } from "react";
import type { GrievanceDraftResponse } from "../api/types";
import PhotoUpload from "./PhotoUpload";

interface ReviewCardProps {
  draft: GrievanceDraftResponse;
  onReplacePhoto: (file: File) => void;
  isReplacingPhoto: boolean;
  onConfirm: () => void;
  isConfirming: boolean;
}

const INCOMPLETE_FLAGS = new Set(["classification_failed", "transcription_failed"]);

export default function ReviewCard({
  draft,
  onReplacePhoto,
  isReplacingPhoto,
  onConfirm,
  isConfirming,
}: ReviewCardProps) {
  const [showPhotoPicker, setShowPhotoPicker] = useState(false);
  const [replacementPhoto, setReplacementPhoto] = useState<File | null>(null);

  const showIncompleteNote = draft.flags.some((flag) => INCOMPLETE_FLAGS.has(flag));
  const isMismatched = draft.image_match_status === "mismatched";

  return (
    <div className="review-card">
      <h2 className="review-card__title">03 — Review your complaint</h2>
      <dl className="review-card__grid">
        <div className="review-card__field">
          <dt>Ticket ID</dt>
          <dd className="mono">{draft.human_id}</dd>
        </div>
        <div className="review-card__field">
          <dt>Category</dt>
          <dd>{draft.category ?? "—"}</dd>
        </div>
        <div className="review-card__field">
          <dt>Department</dt>
          <dd>{draft.department_name ?? "—"}</dd>
        </div>
        <div className="review-card__field">
          <dt>Priority</dt>
          <dd>{draft.priority ?? "—"}</dd>
        </div>
        <div className="review-card__field">
          <dt>Term</dt>
          <dd>{draft.term ?? "—"}</dd>
        </div>
        <div className="review-card__field review-card__field--wide">
          <dt>Address</dt>
          <dd>{draft.address ?? "—"}</dd>
        </div>
        {draft.issue_text && (
          <div className="review-card__field review-card__field--wide">
            <dt>Description</dt>
            <dd>{draft.issue_text}</dd>
          </div>
        )}
      </dl>

      {showIncompleteNote && <p className="muted-note">Some details may be incomplete.</p>}

      {draft.pdf_url && (
        <p>
          <a href={draft.pdf_url} target="_blank" rel="noreferrer">
            View draft PDF
          </a>
        </p>
      )}

      {isMismatched && (
        <div className="review-card__warning">
          <p>
            <strong>Photo mismatch:</strong> the photo you attached doesn&apos;t appear to match the reported issue.
          </p>
          {!showPhotoPicker ? (
            <div className="review-card__actions">
              <button type="button" className="btn btn--secondary" onClick={() => setShowPhotoPicker(true)}>
                Upload a different photo
              </button>
              <button type="button" className="btn btn--primary" onClick={onConfirm} disabled={isConfirming}>
                {isConfirming ? "Submitting…" : "Continue without photo"}
              </button>
            </div>
          ) : (
            <div className="review-card__photo-retry">
              <PhotoUpload value={replacementPhoto} onChange={setReplacementPhoto} />
              <button
                type="button"
                className="btn btn--primary"
                disabled={!replacementPhoto || isReplacingPhoto}
                onClick={() => replacementPhoto && onReplacePhoto(replacementPhoto)}
              >
                {isReplacingPhoto ? "Checking photo…" : "Submit new photo"}
              </button>
            </div>
          )}
        </div>
      )}

      {!isMismatched && (
        <div className="review-card__actions">
          <button type="button" className="btn btn--primary" onClick={onConfirm} disabled={isConfirming}>
            {isConfirming ? "Submitting…" : "Confirm & Submit"}
          </button>
        </div>
      )}
    </div>
  );
}
