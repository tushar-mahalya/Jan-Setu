import { describe, it, expect, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, screen } from "../test/test-utils";
import ReviewCard from "./ReviewCard";
import type { GrievanceDraftResponse } from "../api/types";

function baseDraft(overrides: Partial<GrievanceDraftResponse> = {}): GrievanceDraftResponse {
  return {
    id: "d1",
    human_id: "JS-1001",
    status: "awaiting_confirmation",
    category: "pothole_surface_damage",
    department_name: "Roads Dept",
    priority: "medium",
    term: "short",
    confidence: 0.9,
    address: "123 Main St",
    issue_text: "There is a large pothole outside my house.",
    image_match_status: "matched",
    flags: [],
    pdf_url: null,
    category_id: "pothole_surface_damage",
    category_label: "Pothole or road surface damage",
    domain_label: "Roads",
    safety_level: "none",
    asset_scope: "public",
    disposition: "standard_routing",
    review_status: "pending_citizen",
    structured_facts: { summary: "Large pothole outside the house." },
    routing: { owning_agency: "Roads Dept", dispatch_enabled: true, sla_hours: 48 },
    ...overrides,
  };
}

function baseProps(overrides: Partial<GrievanceDraftResponse> = {}) {
  return {
    draft: baseDraft(overrides),
    onReplacePhoto: vi.fn(),
    isReplacingPhoto: false,
    onUpdateReview: vi.fn(),
    isUpdatingReview: false,
    onConfirm: vi.fn(),
    isConfirming: false,
  };
}

function makeFile(name: string, type: string, size = 1024) {
  const file = new File([new Uint8Array(size)], name, { type });
  Object.defineProperty(file, "size", { value: size, configurable: true });
  return file;
}

describe("ReviewCard", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  });

  it("renders only the processing view when status is processing", () => {
    const props = baseProps({ status: "processing" });
    renderWithProviders(<ReviewCard {...props} />);

    expect(screen.getByText("Reading your report, checking jurisdiction, and preparing routing…")).toBeInTheDocument();
    expect(screen.queryByText("Review what we understood")).not.toBeInTheDocument();
  });

  it("shows the immediate-safety banner when safety_level is immediate", () => {
    const props = baseProps({ safety_level: "immediate" });
    renderWithProviders(<ReviewCard {...props} />);
    expect(screen.getByText("Possible immediate safety risk")).toBeInTheDocument();
  });

  it("shows the immediate-safety banner when disposition is emergency_redirect", () => {
    const props = baseProps({ safety_level: "none", disposition: "emergency_redirect" });
    renderWithProviders(<ReviewCard {...props} />);
    expect(screen.getByText("Possible immediate safety risk")).toBeInTheDocument();
  });

  it("does not show the immediate-safety banner otherwise", () => {
    const props = baseProps();
    renderWithProviders(<ReviewCard {...props} />);
    expect(screen.queryByText("Possible immediate safety risk")).not.toBeInTheDocument();
  });

  it("does not show the mismatch warning when image_match_status is not mismatched", () => {
    const props = baseProps({ image_match_status: "matched" });
    renderWithProviders(<ReviewCard {...props} />);
    expect(screen.queryByText("Photo evidence may conflict with the description.")).not.toBeInTheDocument();
  });

  it("shows the mismatch warning and reveals the retry flow, enabling confirm once a photo is chosen", async () => {
    const user = userEvent.setup();
    const onReplacePhoto = vi.fn();
    const props = { ...baseProps({ image_match_status: "mismatched" }), onReplacePhoto };
    const { container } = renderWithProviders(<ReviewCard {...props} />);

    expect(screen.getByText("Photo evidence may conflict with the description.")).toBeInTheDocument();
    await user.click(screen.getByText("Choose another photo"));

    const confirmBtn = screen.getByText("Use this photo");
    expect(confirmBtn).toBeDisabled();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("new.png", "image/png");
    await user.upload(input, file);

    expect(confirmBtn).toBeEnabled();
    await user.click(confirmBtn);
    expect(onReplacePhoto).toHaveBeenCalledWith(file);
  });

  it("opens the correction form seeded from draft fields, edits, and saves", async () => {
    const user = userEvent.setup();
    const onUpdateReview = vi.fn();
    const props = { ...baseProps(), onUpdateReview };
    renderWithProviders(<ReviewCard {...props} />);

    await user.click(screen.getByText("Something is wrong? Correct it"));

    const categorySelect = screen.getByLabelText("Issue type") as HTMLSelectElement;
    expect(categorySelect.value).toBe("pothole_surface_damage");
    const summaryBox = screen.getByLabelText("Corrected summary") as HTMLTextAreaElement;
    expect(summaryBox.value).toBe("Large pothole outside the house.");

    const saveBtn = screen.getByText("Save correction");
    expect(saveBtn).toBeEnabled();

    await user.selectOptions(categorySelect, "streetlight_out");
    await user.selectOptions(screen.getByLabelText("Asset ownership"), "private");
    await user.clear(summaryBox);
    await user.type(summaryBox, "Streetlight is broken.");

    await user.click(saveBtn);

    expect(onUpdateReview).toHaveBeenCalledWith({
      category_id: "streetlight_out",
      asset_scope: "private",
      summary: "Streetlight is broken.",
    });
  });

  it("disables Save when summary is cleared, and Cancel closes the form", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ReviewCard {...baseProps()} />);

    await user.click(screen.getByText("Something is wrong? Correct it"));
    const summaryBox = screen.getByLabelText("Corrected summary") as HTMLTextAreaElement;
    await user.clear(summaryBox);

    expect(screen.getByText("Save correction")).toBeDisabled();

    await user.click(screen.getByText("Cancel"));
    expect(screen.queryByLabelText("Corrected summary")).not.toBeInTheDocument();
  });

  it("seeds an empty category when draft.category_id is not a known category", async () => {
    const user = userEvent.setup();
    const props = baseProps({ category_id: "not_a_known_category" });
    renderWithProviders(<ReviewCard {...props} />);

    await user.click(screen.getByText("Something is wrong? Correct it"));
    const categorySelect = screen.getByLabelText("Issue type") as HTMLSelectElement;
    expect(categorySelect.value).toBe("");
    expect(screen.getByText("Save correction")).toBeDisabled();
  });

  it("falls back to issue_text for the correction summary when structured_facts.summary is absent", async () => {
    const user = userEvent.setup();
    const props = baseProps({ structured_facts: null, issue_text: "Fallback issue text" });
    renderWithProviders(<ReviewCard {...props} />);

    await user.click(screen.getByText("Something is wrong? Correct it"));
    const summaryBox = screen.getByLabelText("Corrected summary") as HTMLTextAreaElement;
    expect(summaryBox.value).toBe("Fallback issue text");
  });

  it("renders the pdf preview link only when pdf_url is present", () => {
    const { rerender } = renderWithProviders(<ReviewCard {...baseProps({ pdf_url: null })} />);
    expect(screen.queryByText("Preview draft receipt ↗")).not.toBeInTheDocument();

    rerender(<ReviewCard {...baseProps({ pdf_url: "https://example.com/draft.pdf" })} />);
    const link = screen.getByText("Preview draft receipt ↗");
    expect(link).toHaveAttribute("href", "https://example.com/draft.pdf");
  });

  it("shows confirm label/disabled state and calls onConfirm (default review_status)", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const props = { ...baseProps({ review_status: "pending_citizen" }), onConfirm };
    renderWithProviders(<ReviewCard {...props} />);

    const btn = screen.getByText("Confirm & file complaint");
    await user.click(btn);
    expect(onConfirm).toHaveBeenCalled();
  });

  it("shows the official-review label when review_status is pending_official", () => {
    renderWithProviders(<ReviewCard {...baseProps({ review_status: "pending_official" })} />);
    expect(screen.getByText("Send for official review")).toBeInTheDocument();
  });

  it("shows busy label and disables the submit button when isConfirming", () => {
    const props = { ...baseProps(), isConfirming: true };
    renderWithProviders(<ReviewCard {...props} />);
    const btn = screen.getByText("Filing complaint…");
    expect(btn).toBeDisabled();
  });

  it("shows actual contradiction reasons when mismatched and contradictions present", () => {
    const props = baseProps({
      image_match_status: "mismatched",
      structured_facts: {
        summary: "Water pipe burst",
        contradictions: ["Photo shows a water pipe burst, unrelated to reported computer failures"],
      },
    });
    renderWithProviders(<ReviewCard {...props} />);

    expect(screen.getByText("Photo evidence may conflict with the description.")).toBeInTheDocument();
    expect(screen.getByText("Photo shows a water pipe burst, unrelated to reported computer failures")).toBeInTheDocument();
  });

  it("falls back to generic mismatch body when contradictions array is empty", () => {
    const props = baseProps({
      image_match_status: "mismatched",
      structured_facts: { summary: "Something", contradictions: [] },
    });
    renderWithProviders(<ReviewCard {...props} />);

    expect(screen.getByText("Photo evidence may conflict with the description.")).toBeInTheDocument();
    expect(screen.getByText("This never proves your report is false. Replace the photo or continue; an official can review the original evidence.")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });
});
