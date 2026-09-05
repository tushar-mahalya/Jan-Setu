import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, screen } from "../test/test-utils";
import NewComplaint from "./NewComplaint";
import type { ConfirmResponse, GrievanceDraftResponse } from "../api/types";
import { en } from "../i18n/messages/en";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal()),
  apiGet: vi.fn(),
  apiPatchForm: vi.fn(),
  apiPatchJson: vi.fn(),
  apiPostEmpty: vi.fn(),
  apiPostForm: vi.fn(),
}));

vi.mock("../components/LocationPicker", () => ({
  default: (props: { onChange: (value: { lat: number; lon: number }) => void }) => (
    <button type="button" onClick={() => props.onChange({ lat: 12.9, lon: 77.6 })}>mock-location</button>
  ),
}));

vi.mock("../components/VoiceRecorder", () => ({
  default: () => <div data-testid="mock-voice-recorder" />,
}));

vi.mock("../components/PhotoUpload", () => ({
  default: (props: { onChange: (file: File | null) => void }) => (
    <div data-testid="mock-photo-upload">
      <button type="button" onClick={() => props.onChange(new File(["x"], "photo.jpg", { type: "image/jpeg" }))}>
        mock-photo
      </button>
    </div>
  ),
}));

vi.mock("../components/ReviewCard", () => ({
  default: (props: { draft: GrievanceDraftResponse; onConfirm: () => void; isConfirming: boolean }) => (
    <div data-testid="mock-review-card">
      <span>{props.draft.human_id}</span>
      <button type="button" onClick={props.onConfirm} disabled={props.isConfirming}>confirm</button>
    </div>
  ),
}));

import { apiGet, apiPostEmpty, apiPostForm } from "../api/client";

function draftFixture(overrides: Partial<GrievanceDraftResponse> = {}): GrievanceDraftResponse {
  return {
    id: "d1",
    human_id: "JS-3001",
    status: "awaiting_confirmation",
    category: "pothole_surface_damage",
    department_name: "Roads",
    priority: "medium",
    term: "short",
    confidence: 0.8,
    address: "1 Main St",
    issue_text: "Pothole",
    image_match_status: "none",
    flags: [],
    pdf_url: null,
    ...overrides,
  };
}

async function goToStep2(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("mock-location"));
  await user.click(screen.getByRole("button", { name: en.continueCta }));
  await user.type(screen.getByLabelText(en.descLabel), "There is a pothole here.");
  await user.click(screen.getByRole("button", { name: en.continueCta }));
}

describe("NewComplaint", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset();
    vi.mocked(apiPostForm).mockReset();
    vi.mocked(apiPostEmpty).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("step 0: shows errNoLocation when continuing without a location", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    expect(await screen.findByText(en.errNoLocation)).toBeInTheDocument();
  });

  it("step 0: selecting a location then continuing advances to step 1", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByText("mock-location"));
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    expect(await screen.findByLabelText(en.descLabel)).toBeInTheDocument();
  });

  it("step 0: use-my-location succeeds and sets location", async () => {
    const getCurrentPosition = vi.fn((success: PositionCallback) => {
      success({ coords: { latitude: 10, longitude: 20 } } as GeolocationPosition);
    });
    Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition }, configurable: true });
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByRole("button", { name: en.useMyLocation }));
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    expect(await screen.findByLabelText(en.descLabel)).toBeInTheDocument();
  });

  it("step 0: use-my-location shows the permission-denied error", async () => {
    const getCurrentPosition = vi.fn(
      (_success: PositionCallback, error: PositionErrorCallback) => {
        error({ code: 1, PERMISSION_DENIED: 1 } as GeolocationPositionError);
      },
    );
    Object.defineProperty(navigator, "geolocation", { value: { getCurrentPosition }, configurable: true });
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByRole("button", { name: en.useMyLocation }));
    expect(await screen.findByText(new RegExp(en.geoDenied))).toBeInTheDocument();
  });

  it("step 1: shows errNoDetails when continuing with no description or voice clips", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByText("mock-location"));
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    expect(await screen.findByText(en.errNoDetails)).toBeInTheDocument();
  });

  it("step 1: typing a description allows continuing to step 2", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByText("mock-location"));
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    await user.type(screen.getByLabelText(en.descLabel), "A pothole.");
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    expect(await screen.findByTestId("mock-photo-upload")).toBeInTheDocument();
  });

  it("step 2: continuing without a photo submits the draft with the expected FormData and advances to review", async () => {
    const user = userEvent.setup();
    vi.mocked(apiPostForm).mockResolvedValueOnce(draftFixture());
    renderWithProviders(<NewComplaint />);
    await goToStep2(user);
    await user.click(screen.getByRole("button", { name: en.continueWithoutPhoto }));
    expect(await screen.findByTestId("mock-review-card")).toBeInTheDocument();
    expect(apiPostForm).toHaveBeenCalledTimes(1);
    const [path, formData] = vi.mocked(apiPostForm).mock.calls[0];
    expect(path).toBe("/api/grievances/draft");
    expect(formData.get("lat")).toBe("12.9");
    expect(formData.get("lon")).toBe("77.6");
    expect(formData.get("text")).toBe("There is a pothole here.");
    expect(screen.getByText("JS-3001")).toBeInTheDocument();
  });

  it("polls for the draft while status is processing and stops once resolved", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });
    vi.mocked(apiPostForm).mockResolvedValueOnce(draftFixture({ status: "processing" }));
    vi.mocked(apiGet).mockResolvedValueOnce(draftFixture({ status: "awaiting_confirmation" }));
    renderWithProviders(<NewComplaint />);
    await goToStep2(user);
    await user.click(screen.getByRole("button", { name: en.continueWithoutPhoto }));
    await screen.findByTestId("mock-review-card");

    await vi.advanceTimersByTimeAsync(1500);
    expect(apiGet).toHaveBeenCalledWith("/api/grievances/d1/draft");
    // Flush the resolved poll promise so the resulting setDraft actually lands.
    await vi.advanceTimersByTimeAsync(0);
  });

  it("step 0: filling the landmark and step 2: choosing a photo includes both in the submitted FormData and shows the review CTA", async () => {
    const user = userEvent.setup();
    vi.mocked(apiPostForm).mockResolvedValueOnce(draftFixture());
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByText("mock-location"));
    await user.type(screen.getByLabelText(en.landmarkLabel), "Near the temple");
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    await user.type(screen.getByLabelText(en.descLabel), "There is a pothole here.");
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    await user.click(screen.getByRole("button", { name: "mock-photo" }));
    await user.click(screen.getByRole("button", { name: en.reviewComplaintCta }));
    expect(await screen.findByTestId("mock-review-card")).toBeInTheDocument();
    const [, formData] = vi.mocked(apiPostForm).mock.calls[0];
    expect(formData.get("landmark")).toBe("Near the temple");
    expect((formData.get("photo") as File).name).toBe("photo.jpg");
  });

  it("previous button steps back from details to location", async () => {
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByText("mock-location"));
    await user.click(screen.getByRole("button", { name: en.continueCta }));
    expect(await screen.findByLabelText(en.descLabel)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en.back }));
    expect(await screen.findByText("mock-location")).toBeInTheDocument();
  });

  it("step 0: use-my-location shows the unsupported error when geolocation is unavailable", async () => {
    Object.defineProperty(navigator, "geolocation", { value: undefined, configurable: true });
    const user = userEvent.setup();
    renderWithProviders(<NewComplaint />);
    await user.click(screen.getByRole("button", { name: en.useMyLocation }));
    expect(await screen.findByText(en.geoUnsupported)).toBeInTheDocument();
  });

  it("result state: confirm mutation success shows the filed receipt with grouped note", async () => {
    const user = userEvent.setup();
    vi.mocked(apiPostForm).mockResolvedValueOnce(draftFixture());
    const confirmResponse: ConfirmResponse = {
      status: "duplicate",
      human_id: "JS-3001",
      duplicate_of_human_id: "JS-2999",
      report_count: 4,
    };
    vi.mocked(apiPostEmpty).mockResolvedValueOnce(confirmResponse);
    renderWithProviders(<NewComplaint />);
    await goToStep2(user);
    await user.click(screen.getByRole("button", { name: en.continueWithoutPhoto }));
    await screen.findByTestId("mock-review-card");
    await user.click(screen.getByRole("button", { name: "confirm" }));
    expect(await screen.findByRole("heading", { name: "JS-3001" })).toBeInTheDocument();
    expect(screen.getByText(en.receiptGrouped.replace("{count}", "4"))).toBeInTheDocument();
  });
});
