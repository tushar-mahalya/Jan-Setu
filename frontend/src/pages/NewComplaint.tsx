import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { apiPatchForm, apiPostEmpty, apiPostForm, ApiError } from "../api/client";
import type { ConfirmResponse, GrievanceDraftResponse } from "../api/types";
import LocationPicker, { type LocationValue } from "../components/LocationPicker";
import VoiceRecorder from "../components/VoiceRecorder";
import PhotoUpload from "../components/PhotoUpload";
import ReviewCard from "../components/ReviewCard";

function buildDraftFormData(location: LocationValue, text: string, clips: File[], photo: File | null): FormData {
  const formData = new FormData();
  formData.append("lat", String(location.lat));
  formData.append("lon", String(location.lon));
  if (text.trim()) formData.append("text", text.trim());
  clips.forEach((clip) => formData.append("audio", clip, clip.name));
  if (photo) formData.append("photo", photo, photo.name);
  return formData;
}

export default function NewComplaint() {
  const [location, setLocation] = useState<LocationValue | null>(null);
  const [description, setDescription] = useState("");
  const [clips, setClips] = useState<File[]>([]);
  const [photo, setPhoto] = useState<File | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [draft, setDraft] = useState<GrievanceDraftResponse | null>(null);
  const [confirmResult, setConfirmResult] = useState<ConfirmResponse | null>(null);

  const createDraft = useMutation({
    mutationFn: (formData: FormData) => apiPostForm<GrievanceDraftResponse>("/api/grievances/draft", formData),
    onSuccess: (data) => setDraft(data),
  });

  const replacePhoto = useMutation({
    mutationFn: (photoFile: File) => {
      const formData = new FormData();
      formData.append("photo", photoFile, photoFile.name);
      return apiPatchForm<GrievanceDraftResponse>(`/api/grievances/${draft!.id}/photo`, formData);
    },
    onSuccess: (data) => setDraft(data),
  });

  const confirmDraft = useMutation({
    mutationFn: () => apiPostEmpty<ConfirmResponse>(`/api/grievances/${draft!.id}/confirm`),
    onSuccess: (data) => setConfirmResult(data),
  });

  const handleSubmit = () => {
    setValidationError(null);
    if (!location) {
      setValidationError("Please choose a location on the map.");
      return;
    }
    if (!description.trim() && clips.length === 0) {
      setValidationError("Provide a description (text or voice note).");
      return;
    }
    createDraft.mutate(buildDraftFormData(location, description, clips, photo));
  };

  if (confirmResult) {
    const stampTone: "warning" | "accent" | undefined =
      confirmResult.status === "duplicate" || confirmResult.status === "dispatch_failed"
        ? "warning"
        : confirmResult.status === "pending_window" || confirmResult.status === "dispatching"
          ? "accent"
          : undefined;
    return (
      <main className="page page--narrow">
        <div className="success-panel">
          <span className="eyebrow">Complaint filed</span>
          <span className="success-stamp" data-tone={stampTone}>
            {confirmResult.status.replace(/_/g, " ")}
          </span>
          <h1 className="mono">{confirmResult.human_id}</h1>
          {confirmResult.status === "duplicate" && confirmResult.report_count !== null && (
            <p>
              {confirmResult.report_count} other {confirmResult.report_count === 1 ? "person has" : "people have"}{" "}
              reported this issue.
            </p>
          )}
          <Link to="/dashboard" className="btn btn--primary">
            Back to Dashboard
          </Link>
        </div>
      </main>
    );
  }

  if (draft) {
    return (
      <main className="page page--narrow">
        <ReviewCard
          draft={draft}
          onReplacePhoto={(file) => replacePhoto.mutate(file)}
          isReplacingPhoto={replacePhoto.isPending}
          onConfirm={() => confirmDraft.mutate()}
          isConfirming={confirmDraft.isPending}
        />
        {confirmDraft.isError && (
          <p className="field-error">
            {confirmDraft.error instanceof ApiError ? confirmDraft.error.message : "Could not confirm the complaint."}
          </p>
        )}
      </main>
    );
  }

  return (
    <main className="page page--narrow">
      <header className="page__header">
        <div>
          <span className="eyebrow">Jan-Setu Citizen Portal</span>
          <h1>File a New Complaint</h1>
        </div>
      </header>

      {createDraft.isPending && <div className="processing-banner">Reviewing your complaint…</div>}

      <section className="form-section">
        <h2 className="form-section__title">01 — Location</h2>
        <LocationPicker value={location} onChange={setLocation} />
      </section>

      <section className="form-section">
        <h2 className="form-section__title">02 — Description</h2>
        <textarea
          className="textarea"
          rows={5}
          placeholder="Describe the issue…"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        <VoiceRecorder clips={clips} onClipsChange={setClips} />
      </section>

      <section className="form-section">
        <h2 className="form-section__title">03 — Photo (optional)</h2>
        <PhotoUpload value={photo} onChange={setPhoto} />
      </section>

      {(validationError || createDraft.isError) && (
        <p className="field-error">
          {validationError ??
            (createDraft.error instanceof ApiError ? createDraft.error.message : "Could not submit the complaint.")}
        </p>
      )}

      <div className="form-actions">
        <button type="button" className="btn btn--primary" onClick={handleSubmit} disabled={createDraft.isPending}>
          {createDraft.isPending ? "Reviewing…" : "Submit"}
        </button>
      </div>
    </main>
  );
}
