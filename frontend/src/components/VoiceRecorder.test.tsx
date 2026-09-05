import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, screen, waitFor } from "../test/test-utils";
import VoiceRecorder, { type VoiceClip } from "./VoiceRecorder";
import { en } from "../i18n/messages/en";

/**
 * jsdom ships neither MediaRecorder nor navigator.mediaDevices, so both are
 * stubbed per-test. FakeMediaRecorder mirrors just enough of the real API
 * (ondataavailable/onstop callbacks, start/requestData/stop) to drive the
 * component's start -> segment -> stop lifecycle synchronously.
 */
class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob; size: number }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_stream: unknown, opts?: { mimeType?: string }) {
    this.mimeType = opts?.mimeType ?? "audio/webm";
  }
  start() {
    this.state = "recording";
  }
  requestData() {
    this.ondataavailable?.({ data: new Blob(["x"], { type: this.mimeType }), size: 1 });
  }
  stop() {
    this.state = "inactive";
    this.onstop?.();
  }
}

const fakeTrack = { stop: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() };
const fakeStream = { getTracks: () => [fakeTrack], getAudioTracks: () => [fakeTrack] };

function makeClip(recordingId: string, segmentIndex: number, name = "clip.webm"): VoiceClip {
  return { file: new File(["x"], name, { type: "audio/webm" }), recordingId, segmentIndex };
}

let getUserMedia: ReturnType<typeof vi.fn>;

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock");
  URL.revokeObjectURL = vi.fn();
  // The elapsed-time/waveform loop drives itself via rAF; a no-op stub keeps
  // it from ever running so no test depends on real timers reaching
  // SEGMENT_SECONDS/MAX_SECONDS.
  vi.stubGlobal("requestAnimationFrame", vi.fn(() => 0));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  if (!crypto.randomUUID) {
    vi.stubGlobal("crypto", { ...crypto, randomUUID: () => "test-uuid" });
  }
  getUserMedia = vi.fn().mockResolvedValue(fakeStream);
  // jsdom's navigator is a plain mutable object, so a direct assignment is
  // enough — no need to stub the whole navigator (which would break
  // userEvent internals that also read from it).
  (navigator as unknown as { mediaDevices: unknown }).mediaDevices = { getUserMedia };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("VoiceRecorder idle state", () => {
  it("renders the record button in idle state with no clip list when clips=[]", () => {
    renderWithProviders(<VoiceRecorder clips={[]} onClipsChange={vi.fn()} />);
    const button = screen.getByRole("button", { name: en.recordCta });
    expect(button).toHaveAttribute("data-recording", "false");
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});

describe("VoiceRecorder unsupported browser", () => {
  it("shows the unsupported message and never calls getUserMedia when MediaRecorder is unavailable", async () => {
    vi.stubGlobal("MediaRecorder", undefined);
    const user = userEvent.setup();
    renderWithProviders(<VoiceRecorder clips={[]} onClipsChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: en.recordCta }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.voiceUnsupported);
    expect(getUserMedia).not.toHaveBeenCalled();
  });
});

describe("VoiceRecorder start/stop lifecycle", () => {
  it("transitions idle -> recording and requests the microphone with audio constraints", async () => {
    const user = userEvent.setup();
    renderWithProviders(<VoiceRecorder clips={[]} onClipsChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: en.recordCta }));
    await screen.findByText(en.recordingNow);

    expect(getUserMedia).toHaveBeenCalledWith({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    expect(screen.getByRole("button", { name: en.stopRecordingAria })).toHaveAttribute("data-recording", "true");
  });

  it("stops recording, appends the finished clip via onClipsChange, and returns to idle", async () => {
    const onClipsChange = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<VoiceRecorder clips={[]} onClipsChange={onClipsChange} />);

    await user.click(screen.getByRole("button", { name: en.recordCta }));
    await screen.findByText(en.recordingNow);

    await user.click(screen.getByRole("button", { name: en.stopRecordingAria }));

    await waitFor(() => expect(onClipsChange).toHaveBeenCalledTimes(1));
    const [newClips] = onClipsChange.mock.calls[0] as [VoiceClip[]];
    expect(newClips).toHaveLength(1);
    expect(newClips[0].file).toBeInstanceOf(File);
    expect(newClips[0].segmentIndex).toBe(0);

    await screen.findByRole("button", { name: en.recordCta });
  });

  it("falls back to idle with the mic-off message when getUserMedia rejects", async () => {
    getUserMedia.mockRejectedValue(new Error("denied"));
    const user = userEvent.setup();
    renderWithProviders(<VoiceRecorder clips={[]} onClipsChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: en.recordCta }));

    expect(await screen.findByRole("alert")).toHaveTextContent(en.micOff);
    expect(screen.getByRole("button", { name: en.recordCta })).toBeInTheDocument();
  });
});

describe("VoiceRecorder clip list", () => {
  it("renders one list item per clip with an audio element, and remove filters that clip out", async () => {
    const onClipsChange = vi.fn();
    const clip0 = makeClip("rec-1", 0);
    const clip1 = makeClip("rec-2", 0);
    const user = userEvent.setup();
    renderWithProviders(<VoiceRecorder clips={[clip0, clip1]} onClipsChange={onClipsChange} />);

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(document.querySelectorAll("audio")).toHaveLength(2);

    const removeButtons = screen.getAllByRole("button", { name: en.removeClip });
    expect(removeButtons).toHaveLength(2);

    await user.click(removeButtons[0]);
    expect(onClipsChange).toHaveBeenCalledWith([clip1]);
  });

  it("readOnly hides the record controls but still renders the clip list without remove buttons", () => {
    const clip0 = makeClip("rec-1", 0);
    renderWithProviders(<VoiceRecorder clips={[clip0]} onClipsChange={vi.fn()} readOnly />);

    expect(screen.queryByRole("button", { name: en.recordCta })).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: en.removeClip })).not.toBeInTheDocument();
  });
});

describe("VoiceRecorder transcripts", () => {
  it("shows the transcript text when a matching transcript is provided", () => {
    const clip0 = makeClip("rec-1", 0);
    renderWithProviders(
      <VoiceRecorder
        clips={[clip0]}
        onClipsChange={vi.fn()}
        showTranscripts
        transcripts={[{ recording_id: "rec-1", segment_index: 0, text: "Hello world", language: "en" }]}
      />,
    );
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("shows the not-yet-available fallback when no transcript or preview matches", () => {
    const clip0 = makeClip("rec-1", 0);
    renderWithProviders(<VoiceRecorder clips={[clip0]} onClipsChange={vi.fn()} showTranscripts transcripts={[]} />);
    expect(screen.getByText(en.transcriptLater)).toBeInTheDocument();
  });
});

describe("RecordedClip sourceUrl fetch (read-only notes/transcripts list)", () => {
  it("fetches the audio and sets the object URL as the audio src once loaded", async () => {
    const clip0 = makeClip("rec-1", 0);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(new Blob(["x"])) }),
    );
    renderWithProviders(
      <VoiceRecorder clips={[clip0]} onClipsChange={vi.fn()} sourceUrls={["/api/grievances/1/recordings/rec-1"]} readOnly />,
    );

    const audio = document.querySelector("audio") as HTMLAudioElement;
    await waitFor(() => expect(audio.getAttribute("src")).toBe("blob:mock"));
  });

  it("leaves the src unset and renders without crashing when the fetch fails", async () => {
    const clip0 = makeClip("rec-1", 0);
    const fetchMock = vi.fn().mockResolvedValue({ ok: false });
    vi.stubGlobal("fetch", fetchMock);
    renderWithProviders(
      <VoiceRecorder clips={[clip0]} onClipsChange={vi.fn()} sourceUrls={["/api/grievances/1/recordings/rec-1"]} readOnly />,
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const audio = document.querySelector("audio") as HTMLAudioElement;
    await waitFor(() => expect(audio.getAttribute("src")).toBeNull());
  });
});
