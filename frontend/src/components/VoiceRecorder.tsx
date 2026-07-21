import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { Transcript, TranscriptionPreview } from "../api/types";
import { apiPostForm } from "../api/client";
import { getAccessToken } from "../auth/AuthContext";
import { useI18n, fill } from "../i18n/I18nContext";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export interface VoiceClip {
  file: File;
  recordingId: string;
  segmentIndex: number;
}

interface Props {
  clips: VoiceClip[];
  onClipsChange: (clips: VoiceClip[]) => void;
  transcripts?: Transcript[];
  showTranscripts?: boolean;
  readOnly?: boolean;
  sourceUrls?: string[];
  previewEnabled?: boolean;
}
type RecorderPhase = "idle" | "requesting" | "recording" | "stopping";
type StopIntent = "rotate" | "finish" | null;

const SEGMENT_SECONDS = 30;
const MAX_SECONDS = 60;
const WAVEFORM_BARS = 18;

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return undefined;
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"].find(MediaRecorder.isTypeSupported);
}

function formatTime(seconds: number) {
  const wholeSeconds = Math.floor(seconds);
  return `${String(Math.floor(wholeSeconds / 60)).padStart(2, "0")}:${String(wholeSeconds % 60).padStart(2, "0")}`;
}

function languageLabel(language: string) {
  try { return new Intl.DisplayNames(["en"], { type: "language" }).of(language.split("-")[0]) ?? language; }
  catch { return language; }
}

function RecordedClip({ clip, index, onRemove, transcript, showTranscript, sourceUrl, preview }: { clip: VoiceClip; index: number; onRemove?: () => void; transcript?: Transcript; showTranscript?: boolean; sourceUrl?: string; preview?: TranscriptionPreview }) {
  const { t } = useI18n();
  const [url, setUrl] = useState("");
  const [duration, setDuration] = useState<number | null>(null);

  useEffect(() => {
    if (sourceUrl) {
      let cancelled = false;
      let objectUrl = "";
      void fetch(`${API_BASE}${sourceUrl}`, { headers: { Authorization: `Bearer ${getAccessToken() ?? ""}` }, credentials: "include" })
        .then((response) => response.ok ? response.blob() : Promise.reject())
        .then((blob) => {
          objectUrl = URL.createObjectURL(blob);
          if (!cancelled) setUrl(objectUrl);
        })
        .catch(() => { if (!cancelled) setUrl(""); });
      return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
    }
    const objectUrl = URL.createObjectURL(clip.file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [clip.file, sourceUrl]);

  return <li className="voice-recorder__item">
    <div className="voice-recorder__clip-meta">
      <span aria-hidden="true">♪</span>
      <div><strong>{fill(t.voiceNoteN, { n: index + 1 })}</strong>{duration !== null && <small>{formatTime(duration)}</small>}</div>
    </div>
    <audio controls src={url || undefined} preload="metadata" onLoadedMetadata={(event) => {
      const nextDuration = event.currentTarget.duration;
      if (Number.isFinite(nextDuration)) setDuration(nextDuration);
    }} aria-label={fill(t.voiceNoteN, { n: index + 1 })} />
    {(showTranscript || preview) && <div className="voice-recorder__transcript" aria-live="polite">
      <strong>{t.whatWeHeard}{(transcript?.language ?? preview?.language) && <> · {languageLabel(transcript?.language ?? preview?.language ?? "und")}</>}</strong>
      {transcript ? <p>{transcript.text}</p> : preview?.status === "final" && preview.text ? <p>{preview.text}</p> : <p className="muted-note">{t.transcriptLater}</p>}
    </div>}
    {onRemove && <button type="button" className="btn-link" onClick={onRemove}>{t.removeClip}</button>}
  </li>;
}

export default function VoiceRecorder({ clips, onClipsChange, transcripts = [], showTranscripts = false, readOnly = false, sourceUrls = [], previewEnabled = false }: Props) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<RecorderPhase>("idle");
  const [previews, setPreviews] = useState<Record<string, TranscriptionPreview>>({});
  const previewKey = (clip: VoiceClip) => `${clip.recordingId}:${clip.segmentIndex}`;
  const [elapsed, setElapsed] = useState(0);
  const [levels, setLevels] = useState(() => Array(WAVEFORM_BARS).fill(0.08));
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const clipsRef = useRef(clips);
  const pendingClipsRef = useRef<VoiceClip[]>([]);
  const recordingIdRef = useRef("");
  const stopIntentRef = useRef<StopIntent>(null);
  const startedAtRef = useRef(0);
  const splitStartedRef = useRef(false);
  const mountedRef = useRef(true);
  const sessionRef = useRef(0);
  const phaseRef = useRef<RecorderPhase>("idle");

  useEffect(() => { clipsRef.current = clips; }, [clips]);
  useEffect(() => { phaseRef.current = phase; }, [phase]);

  const stopMedia = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    analyserRef.current?.disconnect();
    analyserRef.current = null;
    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    if (audioContext && audioContext.state !== "closed") void audioContext.close();
  };

  const finishSession = (session: number) => {
    stopMedia();
    if (!mountedRef.current || session !== sessionRef.current) return;
    const completedClips = pendingClipsRef.current;
    pendingClipsRef.current = [];
    if (completedClips.length) {
      onClipsChange([...clipsRef.current, ...completedClips]);
      if (previewEnabled) {
        for (const clip of completedClips) {
          const form = new FormData();
          form.append("audio", clip.file, clip.file.name);
          const key = `${clip.recordingId}:${clip.segmentIndex}`;
          void apiPostForm<TranscriptionPreview>("/api/grievances/transcription-preview", form)
            .then((preview) => setPreviews((current) => ({ ...current, [key]: preview })))
            .catch(() => setPreviews((current) => ({ ...current, [key]: { status: "unavailable" } })));
        }
      }
    }
    stopIntentRef.current = null;
    recorderRef.current = null;
    phaseRef.current = "idle";
    setPhase("idle");
    setLevels(Array(WAVEFORM_BARS).fill(0.08));
  };

  const startSegment = (session: number, mimeType?: string) => {
    const stream = streamRef.current;
    if (!stream || !mountedRef.current || session !== sessionRef.current) return;
    const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    const chunks: Blob[] = [];
    const segmentNumber = pendingClipsRef.current.length + 1;
    recorderRef.current = recorder;

    recorder.ondataavailable = (event) => {
      if (event.data.size && session === sessionRef.current) chunks.push(event.data);
    };
    recorder.onerror = () => {
      if (!mountedRef.current || session !== sessionRef.current) return;
      setError(t.voiceInterrupted);
      stopIntentRef.current = "finish";
      phaseRef.current = "stopping";
      setPhase("stopping");
      if (recorder.state !== "inactive") recorder.stop();
    };
    recorder.onstop = () => {
      const isCurrent = mountedRef.current && session === sessionRef.current;
      const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" });
      if (isCurrent && blob.size) {
        const extension = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm";
        pendingClipsRef.current.push({
          file: new File(
            [blob],
            `voice-note-${session}-${segmentNumber}.${extension}`,
            { type: blob.type, lastModified: Date.now() },
          ),
          recordingId: recordingIdRef.current,
          segmentIndex: segmentNumber - 1,
        });
      }
      if (recorderRef.current === recorder) recorderRef.current = null;
      if (!isCurrent) return;
      if (stopIntentRef.current === "rotate" && phaseRef.current === "recording") {
        stopIntentRef.current = null;
        try {
          startSegment(session, mimeType);
        } catch {
          setError(t.voiceCannotContinue);
          finishSession(session);
        }
        return;
      }
      finishSession(session);
    };
    recorder.start(250);
  };

  const stopRecording = () => {
    if (phaseRef.current !== "recording") return;
    phaseRef.current = "stopping";
    setPhase("stopping");
    stopIntentRef.current = "finish";
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") {
      recorder.requestData();
      recorder.stop();
    } else if (!recorder && !streamRef.current) {
      finishSession(sessionRef.current);
    }
  };

  const rotateSegment = () => {
    const recorder = recorderRef.current;
    if (phaseRef.current !== "recording" || recorder?.state !== "recording") return;
    splitStartedRef.current = true;
    stopIntentRef.current = "rotate";
    recorder.requestData();
    recorder.stop();
  };

  const startRecording = async () => {
    if (phaseRef.current !== "idle") return;
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError(t.voiceUnsupported);
      return;
    }

    const session = ++sessionRef.current;
    phaseRef.current = "requesting";
    setPhase("requesting");
    setElapsed(0);
    pendingClipsRef.current = [];
    recordingIdRef.current = crypto.randomUUID();
    stopIntentRef.current = null;
    splitStartedRef.current = false;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (!mountedRef.current || session !== sessionRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      stream.getAudioTracks()[0]?.addEventListener("ended", stopRecording, { once: true });

      const AudioContextClass = window.AudioContext;
      if (AudioContextClass) {
        const audioContext = new AudioContextClass();
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 64;
        analyser.smoothingTimeConstant = 0.72;
        audioContext.createMediaStreamSource(stream).connect(analyser);
        audioContextRef.current = audioContext;
        analyserRef.current = analyser;
      }

      startedAtRef.current = performance.now();
      startSegment(session, pickMimeType());
      phaseRef.current = "recording";
      setPhase("recording");
    } catch {
      stopMedia();
      if (!mountedRef.current || session !== sessionRef.current) return;
      phaseRef.current = "idle";
      setPhase("idle");
      setError(t.micOff);
    }
  };

  useEffect(() => {
    if (phase !== "recording") return;
    let frame = 0;
    let lastPaint = 0;
    const frequencyData = new Uint8Array(analyserRef.current?.frequencyBinCount ?? 0);

    const update = (now: number) => {
      const nextElapsed = Math.min((now - startedAtRef.current) / 1000, MAX_SECONDS);
      if (now - lastPaint >= 80) {
        setElapsed(nextElapsed);
        const analyser = analyserRef.current;
        if (analyser && frequencyData.length) {
          analyser.getByteFrequencyData(frequencyData);
          setLevels(Array.from({ length: WAVEFORM_BARS }, (_, index) => {
            const sourceIndex = Math.min(frequencyData.length - 1, Math.floor(index * frequencyData.length / WAVEFORM_BARS));
            return Math.max(0.08, frequencyData[sourceIndex] / 255);
          }));
        }
        lastPaint = now;
      }
      if (nextElapsed >= MAX_SECONDS) {
        setElapsed(MAX_SECONDS);
        stopRecording();
        return;
      }
      if (nextElapsed >= SEGMENT_SECONDS && !splitStartedRef.current) rotateSegment();
      frame = window.requestAnimationFrame(update);
    };
    frame = window.requestAnimationFrame(update);
    return () => window.cancelAnimationFrame(frame);
  }, [phase]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      sessionRef.current += 1;
      const recorder = recorderRef.current;
      recorderRef.current = null;
      if (recorder && recorder.state !== "inactive") recorder.stop();
      stopMedia();
      pendingClipsRef.current = [];
    };
  }, []);

  const isBusy = phase === "requesting" || phase === "stopping";
  const status = phase === "requesting"
    ? t.micWaiting
    : phase === "recording"
      ? t.recordingNow
      : phase === "stopping"
        ? t.savingNote
        : t.recordCta;

  return <div className="voice-recorder" data-phase={phase}>
    {!readOnly && <>
      <div className="voice-recorder__controls">
        <button
          type="button"
          className="record-btn"
          data-recording={phase === "recording"}
          onClick={phase === "recording" ? stopRecording : startRecording}
          disabled={isBusy}
          aria-label={phase === "recording" ? t.stopRecordingAria : status}
        >
          <span className="record-btn__shape" aria-hidden="true" />
        </button>
        <div className="voice-recorder__status">
          <strong>{status}</strong>
          <p className="record-timer"><span>{formatTime(elapsed)}</span><span aria-hidden="true"> / </span><span>{formatTime(MAX_SECONDS)}</span></p>
        </div>
        <div className="voice-waveform" aria-hidden="true">
          {levels.map((level, index) => <i key={index} style={{ "--voice-level": level } as CSSProperties} />)}
        </div>
      </div>
      <div className="voice-recorder__message" aria-live="polite">
        {phase === "recording" && elapsed >= SEGMENT_SECONDS
          ? <span className="voice-recorder__warning">{t.voiceThirtyLeft}</span>
          : <span>{t.voiceMax}</span>}
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </>}
    {clips.length > 0 && <ul className="voice-recorder__list" aria-label={readOnly ? t.notesTranscriptsAria : t.attachedNotesAria}>
      {clips.map((clip, index) => <RecordedClip
        clip={clip}
        index={index}
        key={`${clip.recordingId}-${clip.segmentIndex}`}
        transcript={transcripts.find((item) => item.recording_id === clip.recordingId && Number(item.segment_index) === clip.segmentIndex) ?? transcripts[index]}
        showTranscript={showTranscripts}
        sourceUrl={sourceUrls[index]}
        preview={previews[previewKey(clip)]}
        onRemove={readOnly ? undefined : () => onClipsChange(clipsRef.current.filter((_, clipIndex) => clipIndex !== index))}
      />)}
    </ul>}
  </div>;
}
