import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { apiGet, apiPatchForm, apiPatchJson, apiPostEmpty, apiPostForm, ApiError } from "../api/client";
import type { ConfirmResponse, GrievanceDraftResponse } from "../api/types";
import LocationPicker, { type LocationValue } from "../components/LocationPicker";
import VoiceRecorder from "../components/VoiceRecorder";
import PhotoUpload from "../components/PhotoUpload";
import ReviewCard from "../components/ReviewCard";
import { metaForStatus } from "../components/StatusChip";

const steps = [
  { title: "Choose location", short: "Location" },
  { title: "Describe the issue", short: "Details" },
  { title: "Add a photo", short: "Photo" },
  { title: "Review & submit", short: "Review" },
];

function formData(location: LocationValue, text: string, clips: File[], photo: File | null) {
  const data = new FormData();
  data.append("lat", String(location.lat));
  data.append("lon", String(location.lon));
  if (text.trim()) data.append("text", text.trim());
  clips.forEach((clip) => data.append("audio", clip, clip.name));
  if (photo) data.append("photo", photo, photo.name);
  return data;
}

function TipArtifact({ kind }: { kind: "location" | "voice" }) {
  return <span className={`tip-artifact tip-artifact--${kind}`} aria-hidden="true">
    {kind === "location" ? <><i /><b>⌖</b><em /></> : <><i /><i /><i /><i /><i /></>}
  </span>;
}

export default function NewComplaint() {
  const [step, setStep] = useState(0);
  const [location, setLocation] = useState<LocationValue | null>(null);
  const [description, setDescription] = useState("");
  const [clips, setClips] = useState<File[]>([]);
  const [photo, setPhoto] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<GrievanceDraftResponse | null>(null);
  const [result, setResult] = useState<ConfirmResponse | null>(null);
  const create = useMutation({ mutationFn: (data: FormData) => apiPostForm<GrievanceDraftResponse>("/api/grievances/draft", data), onSuccess: (value) => { setDraft(value); setStep(3); } });
  const replace = useMutation({ mutationFn: (file: File) => { const data = new FormData(); data.append("photo", file, file.name); return apiPatchForm<GrievanceDraftResponse>(`/api/grievances/${draft!.id}/photo`, data); }, onSuccess: setDraft });
  const review = useMutation({ mutationFn: (changes: { category_id?: string; asset_scope?: string; summary?: string; clarification_answer?: string }) => apiPatchJson<GrievanceDraftResponse>(`/api/grievances/${draft!.id}/review`, changes), onSuccess: setDraft });
  const confirm = useMutation({ mutationFn: () => apiPostEmpty<ConfirmResponse>(`/api/grievances/${draft!.id}/confirm`), onSuccess: setResult });

  useEffect(() => {
    if (!draft || draft.status !== "processing") return;
    let cancelled = false;
    const poll = window.setInterval(() => {
      apiGet<GrievanceDraftResponse>(`/api/grievances/${draft.id}/draft`).then((value) => {
        if (!cancelled) setDraft(value);
      }).catch(() => undefined);
    }, 1500);
    return () => { cancelled = true; window.clearInterval(poll); };
  }, [draft?.id, draft?.status]);
  const next = () => {
    setError(null);
    if (step === 0 && !location) return setError("Choose the exact issue location on the map before continuing.");
    if (step === 1 && !description.trim() && !clips.length) return setError("Add a description or a voice note so we can route this correctly.");
    if (step === 2) {
      if (!location) return;
      create.mutate(formData(location, description, clips, photo));
      return;
    }
    setStep((current) => Math.min(3, current + 1));
  };
  const previous = () => {
    setError(null);
    setStep((current) => Math.max(0, current - 1));
  };

  if (result) {
    const status = metaForStatus(result.status);
    return <section className="filed-receipt" aria-labelledby="filed-title">
      <div className="filed-receipt__art" aria-hidden="true"><div>✓</div><i /><b /></div>
      <span className="filed-stamp">{status.label} · शिकायत दर्ज</span>
      <h1 id="filed-title">{result.human_id}</h1>
      <p>Your complaint is filed. Save this ticket number and return to your dashboard to see every update.</p>
      {result.status === "duplicate" && result.report_count !== null && <p className="filed-receipt__grouped"><strong>{result.report_count}</strong> citizens have reported this issue. Your report has been grouped with theirs.</p>}
      <Link to="/dashboard" className="app-button app-button--orange">Track this complaint</Link>
    </section>;
  }

  return <div className="wizard-page">
    <header className="wizard-header">
      <Link to="/dashboard" className="wizard-back" aria-label="Leave complaint form and return to dashboard">‹</Link>
      <div><span>Step {step + 1} of 4</span><h1>{steps[step].title}</h1></div>
    </header>
    <ol className="wizard-stepper" aria-label="Complaint filing progress">
      {steps.map((item, index) => <li key={item.short} className={index === step ? "is-current" : index < step ? "is-complete" : ""} aria-current={index === step ? "step" : undefined}><span>{index < step ? "✓" : index + 1}</span><b>{item.short}</b></li>)}
    </ol>
    {create.isPending && <div className="wizard-processing" role="status" aria-live="polite"><span />Reading your report and finding the right department…</div>}
    <div className="wizard-stage" key={step}>
      {step === 0 && <div className="wizard-split"><div><LocationPicker value={location} onChange={setLocation} /></div><aside className="wizard-tip"><TipArtifact kind="location" /><b>Pin the exact place</b><p>Use your current location, tap the map, or drag the pin. A precise location helps the right team find the issue without calling you for directions.</p><small>Location is attached only to this complaint.</small></aside></div>}
      {step === 1 && <div className="wizard-split"><div className="wizard-description"><label className="visually-hidden" htmlFor="complaint-description">Describe the civic issue</label><textarea id="complaint-description" rows={7} placeholder="What happened? Include a nearby landmark, how long the problem has existed, and any safety risk." value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} aria-describedby="description-count" /><span id="description-count" className="character-count">{description.length}/2000 characters · or add a voice note</span><VoiceRecorder clips={clips} onClipsChange={setClips} /></div><aside className="wizard-tip"><TipArtifact kind="voice" /><b>Tell it in your own words</b><p>Type or record a voice note. Mention what is broken, when you noticed it, and whether anyone is at immediate risk.</p><small>You need either text or one voice note.</small></aside></div>}
      {step === 2 && <div className="wizard-photo"><div className="wizard-photo__intro"><span aria-hidden="true">▣</span><div><h2>Help the department see the issue</h2><p>A clear, well-lit photo is optional. Avoid faces, number plates, or unrelated personal information.</p></div></div><PhotoUpload value={photo} onChange={setPhoto} /><button type="button" className="wizard-skip" onClick={next} disabled={create.isPending}>Continue without a photo</button></div>}
      {step === 3 && draft && <ReviewCard draft={draft} onReplacePhoto={(file) => replace.mutate(file)} isReplacingPhoto={replace.isPending} onUpdateReview={(changes) => review.mutate(changes)} isUpdatingReview={review.isPending} onConfirm={() => confirm.mutate()} isConfirming={confirm.isPending} />}
    </div>
    {(() => {
      const mutationError = create.error ?? replace.error ?? review.error ?? confirm.error;
      if (!error && !mutationError) return null;
      return <p className="app-error wizard-error" role="alert">{error ?? (mutationError instanceof ApiError ? mutationError.message : "Could not continue. Your entries are still here—please try again.")}</p>;
    })()}
    {step < 3 && <footer className="wizard-actions">{step > 0 && <button type="button" className="app-button app-button--soft" onClick={previous}>Back</button>}{step !== 2 && <button type="button" className="app-button app-button--teal" onClick={next} disabled={create.isPending}>Continue →</button>}{step === 2 && photo && <button type="button" className="app-button app-button--teal" onClick={next} disabled={create.isPending}>Review complaint →</button>}</footer>}
  </div>;
}
