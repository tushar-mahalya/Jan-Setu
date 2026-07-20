import { useEffect, useRef, useState, type CSSProperties } from "react";

interface Props { clips: File[]; onClipsChange: (clips: File[]) => void }
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

function RecordedClip({ clip, index, onRemove }: { clip: File; index: number; onRemove: () => void }) {
  const [url, setUrl] = useState("");
  const [duration, setDuration] = useState<number | null>(null);

  useEffect(() => {
    const objectUrl = URL.createObjectURL(clip);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [clip]);

  return <li className="voice-recorder__item">
    <div className="voice-recorder__clip-meta">
      <span aria-hidden="true">♪</span>
      <div><strong>Voice note {index + 1}</strong>{duration !== null && <small>{formatTime(duration)}</small>}</div>
    </div>
    <audio controls src={url || undefined} preload="metadata" onLoadedMetadata={(event) => {
      const nextDuration = event.currentTarget.duration;
      if (Number.isFinite(nextDuration)) setDuration(nextDuration);
    }} aria-label={`Voice note ${index + 1}`} />
    <button type="button" className="btn-link" onClick={onRemove}>Remove / हटाएँ</button>
  </li>;
}

export default function VoiceRecorder({ clips, onClipsChange }: Props) {
  const [phase, setPhase] = useState<RecorderPhase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [levels, setLevels] = useState(() => Array(WAVEFORM_BARS).fill(0.08));
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const clipsRef = useRef(clips);
  const pendingClipsRef = useRef<File[]>([]);
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
    if (completedClips.length) onClipsChange([...clipsRef.current, ...completedClips]);
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
      setError("Recording stopped unexpectedly. Please try again. / रिकॉर्डिंग रुक गई। कृपया फिर कोशिश करें।");
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
        pendingClipsRef.current.push(new File(
          [blob],
          `voice-note-${session}-${segmentNumber}.${extension}`,
          { type: blob.type, lastModified: Date.now() },
        ));
      }
      if (recorderRef.current === recorder) recorderRef.current = null;
      if (!isCurrent) return;
      if (stopIntentRef.current === "rotate" && phaseRef.current === "recording") {
        stopIntentRef.current = null;
        try {
          startSegment(session, mimeType);
        } catch {
          setError("Could not continue recording. Your first part is saved. / रिकॉर्डिंग जारी नहीं रह सकी।");
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
      setError("Voice recording is not supported. Type your description instead. / कृपया विवरण लिखें।");
      return;
    }

    const session = ++sessionRef.current;
    phaseRef.current = "requesting";
    setPhase("requesting");
    setElapsed(0);
    pendingClipsRef.current = [];
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
      setError("Microphone access is off. Allow it in browser settings or type your description. / माइक्रोफोन अनुमति दें या विवरण लिखें।");
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
    ? "Waiting for microphone… / माइक्रोफोन की अनुमति…"
    : phase === "recording"
      ? "Recording… / रिकॉर्डिंग जारी…"
      : phase === "stopping"
        ? "Saving voice note… / वॉइस नोट सहेजा जा रहा है…"
        : "Record voice note / वॉइस नोट";

  return <div className="voice-recorder" data-phase={phase}>
    <div className="voice-recorder__controls">
      <button
        type="button"
        className="record-btn"
        data-recording={phase === "recording"}
        onClick={phase === "recording" ? stopRecording : startRecording}
        disabled={isBusy}
        aria-label={phase === "recording" ? "Stop recording" : status}
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
        ? <span className="voice-recorder__warning">30 seconds left — recording will stop automatically.</span>
        : <span>Maximum 60 seconds · recording stops automatically when time is up.</span>}
    </div>
    {error && <p className="field-error" role="alert">{error}</p>}
    {clips.length > 0 && <ul className="voice-recorder__list" aria-label="Attached voice notes">
      {clips.map((clip, index) => <RecordedClip
        clip={clip}
        index={index}
        key={`${clip.name}-${clip.lastModified}`}
        onRemove={() => onClipsChange(clipsRef.current.filter((_, clipIndex) => clipIndex !== index))}
      />)}
    </ul>}
  </div>;
}
