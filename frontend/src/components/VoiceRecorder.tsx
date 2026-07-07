import { useEffect, useMemo, useRef, useState } from "react";

interface VoiceRecorderProps {
  clips: File[];
  onClipsChange: (clips: File[]) => void;
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) return undefined;
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type));
}

export default function VoiceRecorder({ clips, onClipsChange }: VoiceRecorderProps) {
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const clipUrls = useMemo(() => clips.map((clip) => URL.createObjectURL(clip)), [clips]);
  useEffect(() => {
    return () => {
      clipUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [clipUrls]);

  const startRecording = async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setError("Voice recording isn't supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const extension = blob.type.includes("ogg") ? "ogg" : "webm";
        const file = new File([blob], `voice-note-${Date.now()}.${extension}`, { type: blob.type });
        onClipsChange([...clips, file]);
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
    } catch {
      setError("Microphone access was denied or unavailable.");
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setIsRecording(false);
  };

  const removeClip = (index: number) => {
    onClipsChange(clips.filter((_, i) => i !== index));
  };

  return (
    <div className="voice-recorder">
      <div className="voice-recorder__controls">
        <button
          type="button"
          className={`btn ${isRecording ? "btn--danger" : "btn--secondary"}`}
          onClick={isRecording ? stopRecording : startRecording}
        >
          {isRecording ? "Stop Recording" : "Record Voice Note"}
        </button>
        {isRecording && <span className="voice-recorder__indicator">Recording…</span>}
      </div>
      {error && <p className="field-error">{error}</p>}
      {clips.length > 0 && (
        <ul className="voice-recorder__list">
          {clips.map((clip, index) => (
            <li className="voice-recorder__item" key={`${clip.name}-${index}`}>
              <audio controls src={clipUrls[index]} />
              <button type="button" className="btn-link" onClick={() => removeClip(index)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
