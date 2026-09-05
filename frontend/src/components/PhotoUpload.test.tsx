import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { fireEvent } from "@testing-library/react";

function withFiles(input: HTMLInputElement, files: File[]) {
  Object.defineProperty(input, "files", { value: files, configurable: true });
}
import { renderWithProviders, screen } from "../test/test-utils";
import PhotoUpload from "./PhotoUpload";

function makeFile(name: string, type: string, size = 1024) {
  const file = new File([new Uint8Array(size)], name, { type });
  Object.defineProperty(file, "size", { value: size, configurable: true });
  return file;
}

describe("PhotoUpload", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:mock");
    URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the drop zone when there is no value", () => {
    renderWithProviders(<PhotoUpload value={null} onChange={vi.fn()} />);
    expect(screen.getByText("Add a clear photo")).toBeInTheDocument();
    expect(screen.getByText("Choose photo")).toBeInTheDocument();
  });

  it("calls onChange with a valid file, then shows preview when rerendered with value", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container, rerender } = renderWithProviders(<PhotoUpload value={null} onChange={onChange} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("photo.png", "image/png", 2048);

    await user.upload(input, file);

    expect(onChange).toHaveBeenCalledWith(file);

    rerender(<PhotoUpload value={file} onChange={onChange} />);

    expect(await screen.findByAltText("Selected photo evidence for this complaint")).toBeInTheDocument();
    expect(screen.getByText(/photo\.png/)).toBeInTheDocument();
    expect(screen.getByText(/MB/)).toBeInTheDocument();
  });

  it("rejects a wrong MIME type and does not call onChange", () => {
    const onChange = vi.fn();
    const { container } = renderWithProviders(<PhotoUpload value={null} onChange={onChange} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("doc.pdf", "application/pdf");
    // userEvent.upload respects the input's `accept` attribute and silently
    // skips non-matching files, so it can't reach the component's own MIME
    // check. Use fireEvent.change with a manually-set FileList instead.
    withFiles(input, [file]);
    fireEvent.change(input);

    expect(screen.getByRole("alert")).toHaveTextContent("Choose a JPEG, PNG, or WebP image.");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("rejects an oversized file and sets the size-error message", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { container } = renderWithProviders(<PhotoUpload value={null} onChange={onChange} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = makeFile("big.png", "image/png");
    Object.defineProperty(file, "size", { value: 6 * 1024 * 1024 });

    await user.upload(input, file);

    expect(screen.getByRole("alert")).toHaveTextContent("Photo must be 5 MiB or smaller.");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("calls onChange(null) when remove is clicked", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const file = makeFile("photo.png", "image/png");
    renderWithProviders(<PhotoUpload value={file} onChange={onChange} />);

    await user.click(screen.getByText("Remove"));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("clicking change photo triggers the hidden input click", async () => {
    const user = userEvent.setup();
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});
    const file = makeFile("photo.png", "image/png");
    renderWithProviders(<PhotoUpload value={file} onChange={vi.fn()} />);

    await user.click(screen.getByText("Change"));

    expect(clickSpy).toHaveBeenCalled();
  });

  it("handles drag-and-drop of a valid file via the drop handler", () => {
    const onChange = vi.fn();
    const { container } = renderWithProviders(<PhotoUpload value={null} onChange={onChange} />);
    const label = container.querySelector("label.photo-drop") as HTMLLabelElement;
    const file = makeFile("dropped.jpeg", "image/jpeg");

    fireEvent.dragEnter(label);
    fireEvent.dragLeave(label);
    fireEvent.dragEnter(label);
    fireEvent.dragOver(label, { dataTransfer: { files: [file] } });
    fireEvent.drop(label, { dataTransfer: { files: [file] } });

    expect(onChange).toHaveBeenCalledWith(file);
  });
});
