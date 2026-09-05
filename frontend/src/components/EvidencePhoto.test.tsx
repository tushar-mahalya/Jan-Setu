import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { EvidencePhoto } from "./EvidencePhoto";

const createObjectURL = vi.fn(() => "blob:fake-url");
const revokeObjectURL = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(URL, { createObjectURL, revokeObjectURL });
});

describe("EvidencePhoto", () => {
  it("renders the fetched image with its alt text and caption", async () => {
    const load = vi.fn().mockResolvedValue("blob:photo");
    render(<EvidencePhoto path="/api/grievances/1/photo" alt="Attached photo" caption="Your photo" load={load} />);

    const image = await screen.findByRole("img", { name: "Attached photo" });
    expect(image).toHaveAttribute("src", "blob:photo");
    expect(screen.getByText("Your photo")).toBeInTheDocument();
    expect(load).toHaveBeenCalledWith("/api/grievances/1/photo");
  });

  it("shows a placeholder until the bytes arrive", () => {
    render(<EvidencePhoto path="/p" alt="a" load={() => new Promise(() => {})} />);
    expect(document.querySelector(".evidence-photo__pending")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("reports a failure instead of rendering a broken image", async () => {
    const load = vi.fn().mockRejectedValue(new Error("403"));
    render(<EvidencePhoto path="/p" alt="a" load={load} />);
    await waitFor(() => expect(screen.getByText(/could not be loaded/i)).toBeInTheDocument());
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("revokes the object URL on unmount so blobs are not leaked", async () => {
    const load = vi.fn().mockResolvedValue("blob:photo");
    const { unmount } = render(<EvidencePhoto path="/p" alt="a" load={load} />);
    await screen.findByRole("img");
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:photo");
  });
});
