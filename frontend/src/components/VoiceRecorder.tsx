import { useEffect, useRef, useState } from "react";
interface Props { clips: File[]; onClipsChange: (clips: File[]) => void }
function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return undefined;
  return ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"].find(MediaRecorder.isTypeSupported);
}
export default function VoiceRecorder({ clips, onClipsChange }: Props) {
  const [isRecording, setIsRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const clipsRef = useRef(clips);
  const mountedRef = useRef(true);
  const sessionRef = useRef(0);
  const clipUrlsRef = useRef(new Map<File, string>());
  useEffect(() => { clipsRef.current = clips; }, [clips]);
  useEffect(() => {
    clips.forEach((clip) => {
      if (!clipUrlsRef.current.has(clip)) clipUrlsRef.current.set(clip, URL.createObjectURL(clip));
    });
    clipUrlsRef.current.forEach((url, clip) => {
      if (!clips.includes(clip)) { URL.revokeObjectURL(url); clipUrlsRef.current.delete(clip); }
    });
  }, [clips]);
  useEffect(() => {
    if (!isRecording) return;
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [isRecording]);
  useEffect(() => () => {
    mountedRef.current = false;
    sessionRef.current += 1;
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    recorderRef.current = null; streamRef.current = null; chunksRef.current = [];
    clipUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    clipUrlsRef.current.clear();
  }, []);

  const start = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setError("Voice recording is not supported. Type your description instead. / कृपया विवरण लिखें।"); return;
    }
    const session = ++sessionRef.current;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current || session !== sessionRef.current) {
        stream.getTracks().forEach((track) => track.stop()); return;
      }
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder; chunksRef.current = []; setSeconds(0);
      recorder.ondataavailable = (event) => { if (event.data.size && session === sessionRef.current) chunksRef.current.push(event.data); };
      recorder.onstop = () => {
        const isCurrent = mountedRef.current && session === sessionRef.current && recorderRef.current === recorder;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (isCurrent && blob.size) {
          const extension = blob.type.includes("ogg") ? "ogg" : "webm";
          onClipsChange([...clipsRef.current, new File([blob], `voice-note-${Date.now()}.${extension}`, { type: blob.type })]);
        }
        stream.getTracks().forEach((track) => track.stop());
        if (streamRef.current === stream) streamRef.current = null;
        if (recorderRef.current === recorder) recorderRef.current = null;
        chunksRef.current = [];
        if (mountedRef.current && session === sessionRef.current) setIsRecording(false);
      };
      recorder.start(); setIsRecording(true);
    } catch {
      streamRef.current?.getTracks().forEach((track) => track.stop()); streamRef.current = null;
      if (!mountedRef.current || session !== sessionRef.current) return;
      setIsRecording(false); setError("Microphone access is off. Allow it in browser settings or type your description. / माइक्रोफोन अनुमति दें या विवरण लिखें।");
    }
  };
  const stop = () => { if (recorderRef.current?.state === "recording") recorderRef.current.stop(); setIsRecording(false); };

  return <div className="voice-recorder">
    <div className="voice-recorder__controls">
      <button type="button" className="record-btn" data-recording={isRecording} onClick={isRecording ? stop : start} aria-label={isRecording ? "Stop recording" : "Record voice note"}>
        <span aria-hidden="true">{isRecording ? "■" : "●"}</span>
      </button>
      <div><strong>{isRecording ? "Recording… / रिकॉर्डिंग जारी…" : "Record voice note / वॉइस नोट"}</strong><p className="record-timer">{String(Math.floor(seconds / 60)).padStart(2,"0")}:{String(seconds % 60).padStart(2,"0")}</p></div>
    </div>
    {error && <p className="field-error" role="alert">{error}</p>}
    {clips.length > 0 && <ul className="voice-recorder__list" aria-label="Attached voice notes">{clips.map((clip, index) => <li className="voice-recorder__item" key={`${clip.name}-${clip.lastModified}`}>
      <audio controls src={clipUrlsRef.current.get(clip)} aria-label={`Voice note ${index + 1}`} />
      <button type="button" className="btn-link" onClick={() => onClipsChange(clipsRef.current.filter((_, i) => i !== index))}>Remove / हटाएँ</button>
    </li>)}</ul>}
  </div>;
}
