import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { apiGet, apiPatchForm, apiPatchJson, apiPostEmpty, apiPostForm, ApiError } from "../api/client";
import type { ConfirmResponse, GrievanceDraftResponse } from "../api/types";
import LocationPicker, { type LocationValue } from "../components/LocationPicker";
import VoiceRecorder, { type VoiceClip } from "../components/VoiceRecorder";
import PhotoUpload from "../components/PhotoUpload";
import ReviewCard from "../components/ReviewCard";
import { useI18n, fill } from "../i18n/I18nContext";

function formData(location: LocationValue, text: string, clips: VoiceClip[], photo: File | null, landmark: string) {
  const data = new FormData();
  data.append("lat", String(location.lat));
  data.append("lon", String(location.lon));
  if (text.trim()) data.append("text", text.trim());
  if (landmark.trim()) data.append("landmark", landmark.trim());
  clips.forEach((clip) => {
    data.append("audio", clip.file, clip.file.name);
    data.append(
      "audio_metadata",
      JSON.stringify({
        recording_id: clip.recordingId,
        segment_index: clip.segmentIndex,
        mime_type: clip.file.type,
      }),
    );
  });
  if (photo) data.append("photo", photo, photo.name);
  return data;
}

function TipArtifact({ kind }: { kind: "location" | "voice" }) {
  return <span className={`tip-artifact tip-artifact--${kind}`} aria-hidden="true">
    {kind === "location" ? <><i /><b>⌖</b><em /></> : <><i /><i /><i /><i /><i /></>}
  </span>;
}

export default function NewComplaint() {
  const { t } = useI18n();
  const steps = [
    { title: t.stepLocationTitle, short: t.stepLocationShort },
    { title: t.stepDetailsTitle, short: t.stepDetailsShort },
    { title: t.stepPhotoTitle, short: t.stepPhotoShort },
    { title: t.stepReviewTitle, short: t.stepReviewShort },
  ];
  const [step, setStep] = useState(0);
  const [location, setLocation] = useState<LocationValue | null>(null);
  const [recenter, setRecenter] = useState<[number, number] | null>(null);
  const [geoLocating, setGeoLocating] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [landmark, setLandmark] = useState("");
  const [description, setDescription] = useState("");
  const [clips, setClips] = useState<VoiceClip[]>([]);
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
    if (step === 0 && !location) return setError(t.errNoLocation);
    if (step === 1 && !description.trim() && !clips.length) return setError(t.errNoDetails);
    if (step === 2) {
      if (!location) return;
      create.mutate(formData(location, description, clips, photo, landmark));
      return;
    }
    setStep((current) => Math.min(3, current + 1));
  };
  const previous = () => {
    setError(null);
    setStep((current) => Math.max(0, current - 1));
  };
  const locate = () => {
    setGeoError(null);
    if (!navigator.geolocation) {
      setGeoError(t.geoUnsupported);
      return;
    }
    setGeoLocating(true);
    navigator.geolocation.getCurrentPosition(
      (result) => {
        const next: [number, number] = [result.coords.latitude, result.coords.longitude];
        setLocation({ lat: next[0], lon: next[1] });
        setRecenter(next);
        setGeoLocating(false);
      },
      (geo) => {
        setGeoLocating(false);
        setGeoError(`${geo.code === geo.PERMISSION_DENIED ? t.geoDenied : t.geoFailed} ${t.geoTapMap}`);
      },
      { enableHighAccuracy: true, timeout: 8000 },
    );
  };

  if (result) {
    return <section className="filed-receipt" aria-labelledby="filed-title">
      <div className="filed-receipt__art" aria-hidden="true"><div>✓</div><i /><b /></div>
      <span className="filed-stamp">{t.filedStamp}</span>
      <h1 id="filed-title">{result.human_id}</h1>
      <p>{t.receiptBody}</p>
      {result.status === "duplicate" && result.report_count !== null && <p className="filed-receipt__grouped">{fill(t.receiptGrouped, { count: result.report_count })}</p>}
      <Link to="/dashboard" className="app-button app-button--orange">{t.trackCta}</Link>
    </section>;
  }

  return <div className="wizard-page">
    <header className="wizard-header">
      <Link to="/dashboard" className="wizard-back" aria-label={t.leaveWizardAria}>‹</Link>
      <div><span>{fill(t.stepCounter, { current: step + 1, total: 4 })}</span><h1>{steps[step].title}</h1></div>
    </header>
    <ol className="wizard-stepper" aria-label={t.progressAria}>
      {steps.map((item, index) => <li key={item.short} className={index === step ? "is-current" : index < step ? "is-complete" : ""} aria-current={index === step ? "step" : undefined}><span>{index < step ? "✓" : index + 1}</span><b>{item.short}</b></li>)}
    </ol>
    {create.isPending && <div className="wizard-processing" role="status" aria-live="polite"><span />{t.wizardProcessing}</div>}
    <div className="wizard-stage" key={step}>
      {step === 0 && <div className="wizard-split"><div><LocationPicker value={location} onChange={setLocation} recenter={recenter} /><label className="wizard-landmark"><span>{t.landmarkLabel}</span><input type="text" value={landmark} maxLength={160} placeholder={t.landmarkPlaceholder} onChange={(event) => setLandmark(event.target.value)} /></label></div><div className="wizard-aside"><button type="button" className="wizard-locate" onClick={locate} disabled={geoLocating}><span className="wizard-locate__icon" aria-hidden="true">⌖</span>{geoLocating ? t.locatingNow : t.useMyLocation}</button>{geoError && <div className="notice" data-tone="warning" role="alert"><p>{geoError}</p></div>}<aside className="wizard-tip"><TipArtifact kind="location" /><b>{t.tipLocationTitle}</b><p>{t.tipLocationBody}</p><small>{t.tipLocationNote}</small></aside></div></div>}
      {step === 1 && <div className="wizard-split"><div className="wizard-description"><label className="visually-hidden" htmlFor="complaint-description">{t.descLabel}</label><textarea id="complaint-description" rows={7} placeholder={t.descPlaceholder} value={description} onChange={(event) => setDescription(event.target.value)} maxLength={2000} aria-describedby="description-count" /><span id="description-count" className="character-count">{fill(t.charCount, { count: description.length })}</span><VoiceRecorder clips={clips} onClipsChange={setClips} previewEnabled /></div><aside className="wizard-tip"><TipArtifact kind="voice" /><b>{t.tipVoiceTitle}</b><p>{t.tipVoiceBody}</p><small>{t.tipVoiceNote}</small></aside></div>}
      {step === 2 && <div className="wizard-photo"><div className="wizard-photo__intro"><span aria-hidden="true">▣</span><div><h2>{t.photoIntroTitle}</h2><p>{t.photoIntroBody}</p></div></div><PhotoUpload value={photo} onChange={setPhoto} /><button type="button" className="wizard-skip" onClick={next} disabled={create.isPending}>{t.continueWithoutPhoto}</button></div>}
      {step === 3 && draft && <ReviewCard draft={draft} onReplacePhoto={(file) => replace.mutate(file)} isReplacingPhoto={replace.isPending} onUpdateReview={(changes) => review.mutate(changes)} isUpdatingReview={review.isPending} onConfirm={() => confirm.mutate()} isConfirming={confirm.isPending} />}
    </div>
    {(() => {
      const mutationError = create.error ?? replace.error ?? review.error ?? confirm.error;
      if (!error && !mutationError) return null;
      return <p className="app-error wizard-error" role="alert">{error ?? (mutationError instanceof ApiError ? mutationError.message : t.wizardErrorFallback)}</p>;
    })()}
    {step < 3 && <footer className="wizard-actions">{step > 0 && <button type="button" className="app-button app-button--soft" onClick={previous}>{t.back}</button>}{step !== 2 && <button type="button" className="app-button app-button--teal" onClick={next} disabled={create.isPending}>{t.continueCta}</button>}{step === 2 && photo && <button type="button" className="app-button app-button--teal" onClick={next} disabled={create.isPending}>{t.reviewComplaintCta}</button>}</footer>}
  </div>;
}
