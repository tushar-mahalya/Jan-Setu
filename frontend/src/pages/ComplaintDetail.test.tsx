import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders, screen } from "../test/test-utils";
import ComplaintDetail from "./ComplaintDetail";
import { ApiError } from "../api/client";
import type { GrievanceDetail } from "../api/types";
import { en } from "../i18n/messages/en";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal()),
  apiGet: vi.fn(),
  downloadWithAuth: vi.fn(),
}));

import { apiGet, downloadWithAuth } from "../api/client";

function baseGrievance(overrides: Partial<GrievanceDetail> = {}): GrievanceDetail {
  return {
    id: "abc123",
    human_id: "JS-2001",
    category: "pothole_surface_damage",
    status: "registered",
    priority: "high",
    source: "web",
    created_at: "2026-01-01T10:00:00Z",
    address: "45 MG Road",
    issue_text: "Large pothole near the market.",
    department_key: "roads",
    department_name: "Roads Department",
    term: "short",
    confidence: 0.85,
    image_match_status: "matched",
    flags: [],
    report_count: 1,
    dispatch_ref: null,
    events: [{ status: "registered", note: "Filed", created_at: "2026-01-01T10:00:00Z" }],
    pdf_url: null,
    category_id: "pothole_surface_damage",
    category_label: "Pothole or road surface damage",
    domain_label: "Roads",
    safety_level: "none",
    asset_scope: "public",
    disposition: "standard_routing",
    review_status: "approved",
    transcript_metadata: [],
    voice_note_urls: [],
    structured_facts: null,
    routing: null,
    ...overrides,
  };
}

function renderDetail(route = "/complaints/abc123") {
  return renderWithProviders(
    <Routes>
      <Route path="/complaints/:id" element={<ComplaintDetail />} />
    </Routes>,
    { route },
  );
}

describe("ComplaintDetail", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset();
    vi.mocked(downloadWithAuth).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a loading state then the loaded fields", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(baseGrievance());
    renderDetail();
    expect(screen.getByRole("status", { name: en.loadingComplaint })).toBeInTheDocument();
    expect((await screen.findAllByText("JS-2001")).length).toBeGreaterThan(0);
    expect(screen.getByText("Roads Department")).toBeInTheDocument();
    expect(screen.getByText("Pothole or road surface damage")).toBeInTheDocument();
  });

  it("shows an error state and retries via refetch", async () => {
    const user = userEvent.setup();
    vi.mocked(apiGet).mockRejectedValueOnce(new ApiError(500, "boom")).mockResolvedValueOnce(baseGrievance());
    renderDetail();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en.retry }));
    expect((await screen.findAllByText("JS-2001")).length).toBeGreaterThan(0);
  });

  it("renders the summary block when structured_facts.summary is present", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(
      baseGrievance({ structured_facts: { summary: "Pothole is causing accidents." } }),
    );
    renderDetail();
    expect(await screen.findByText("Pothole is causing accidents.")).toBeInTheDocument();
  });

  it("falls back to no-usable-description when there is no summary or issue text", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(baseGrievance({ structured_facts: null, issue_text: null }));
    renderDetail();
    expect(await screen.findByText(en.noUsableDescription)).toBeInTheDocument();
  });

  it("renders transcripts and omits typed text when transcripts exist", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(
      baseGrievance({
        structured_facts: null,
        transcript_metadata: [{ text: "Voice clip text", language: "en", segment_index: 0 }],
      }),
    );
    renderDetail();
    expect(await screen.findByText("Voice clip text")).toBeInTheDocument();
  });

  it("shows the typed text when there are no transcripts and no summary", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(
      baseGrievance({ structured_facts: null, transcript_metadata: [], issue_text: "Plain typed description" }),
    );
    renderDetail();
    expect(await screen.findByText("Plain typed description")).toBeInTheDocument();
  });

  it("shows the grouped report_count note when report_count > 1", async () => {
    vi.mocked(apiGet).mockResolvedValueOnce(baseGrievance({ report_count: 3 }));
    renderDetail();
    await screen.findByRole("heading", { name: "Pothole or road surface damage" });
    expect(screen.getByText(en.groupedNote.replace("{count}", "3"))).toBeInTheDocument();
  });

  it("downloads the receipt on click, shows busy label, and no error on success", async () => {
    const user = userEvent.setup();
    vi.mocked(apiGet).mockResolvedValueOnce(baseGrievance({ pdf_url: "/files/receipt.pdf" }));
    let resolveDownload: () => void = () => {};
    vi.mocked(downloadWithAuth).mockImplementation(
      () => new Promise((resolve) => { resolveDownload = () => resolve(undefined); }),
    );
    renderDetail();
    const button = await screen.findByRole("button", { name: en.downloadReceipt });
    await user.click(button);
    expect(downloadWithAuth).toHaveBeenCalledWith("/files/receipt.pdf", "JS-2001.pdf");
    expect(await screen.findByRole("button", { name: en.preparingReceipt })).toBeInTheDocument();
    resolveDownload();
    expect(await screen.findByRole("button", { name: en.downloadReceipt })).toBeInTheDocument();
  });

  it("shows the ApiError message when download fails with an ApiError", async () => {
    const user = userEvent.setup();
    vi.mocked(apiGet).mockResolvedValueOnce(baseGrievance({ pdf_url: "/files/receipt.pdf" }));
    vi.mocked(downloadWithAuth).mockRejectedValueOnce(new ApiError(500, "Server exploded"));
    renderDetail();
    const button = await screen.findByRole("button", { name: en.downloadReceipt });
    await user.click(button);
    expect(await screen.findByText("Server exploded")).toBeInTheDocument();
  });

  it("shows the generic fallback message when download fails with a plain Error", async () => {
    const user = userEvent.setup();
    vi.mocked(apiGet).mockResolvedValueOnce(baseGrievance({ pdf_url: "/files/receipt.pdf" }));
    vi.mocked(downloadWithAuth).mockRejectedValueOnce(new Error("network down"));
    renderDetail();
    const button = await screen.findByRole("button", { name: en.downloadReceipt });
    await user.click(button);
    expect(await screen.findByText(en.receiptDownloadError)).toBeInTheDocument();
  });
});
