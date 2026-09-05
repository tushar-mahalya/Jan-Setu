import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/test-utils";
import StatusChip, { metaForStatus } from "./StatusChip";
import { en } from "../i18n/messages/en";

describe("metaForStatus", () => {
  it("maps a known status to its tone/key/live metadata", () => {
    expect(metaForStatus("draft")).toEqual({ key: "stDraft", tone: "neutral" });
    expect(metaForStatus("registered")).toEqual({ key: "stRegistered", tone: "success" });
  });

  it("marks live statuses as live: true", () => {
    expect(metaForStatus("processing")).toEqual({ key: "stProcessing", tone: "info", live: true });
    expect(metaForStatus("pending_window").live).toBe(true);
    expect(metaForStatus("dispatching").live).toBe(true);
  });

  it("does not set live for non-live known statuses", () => {
    expect(metaForStatus("submitted").live).toBeUndefined();
  });

  it("falls back to a humanized label for an unknown status", () => {
    expect(metaForStatus("some_status")).toEqual({
      key: "stFallback",
      tone: "neutral",
      fallback: "Some Status",
    });
  });

  it("returns undefined fallback for an empty string status", () => {
    expect(metaForStatus("")).toEqual({ key: "stFallback", tone: "neutral", fallback: undefined });
  });
});

describe("StatusChip", () => {
  it("renders the localized label for a known status", () => {
    renderWithProviders(<StatusChip status="registered" />);
    expect(screen.getByText(en.stRegistered)).toBeInTheDocument();
  });

  it("renders the humanized fallback label for an unknown status", () => {
    renderWithProviders(<StatusChip status="weird_thing" />);
    expect(screen.getByText("Weird Thing")).toBeInTheDocument();
  });

  it("sets data-live only for statuses marked live", () => {
    const { container } = renderWithProviders(<StatusChip status="processing" />);
    expect(container.querySelector(".status-chip")).toHaveAttribute("data-live", "true");
  });

  it("does not set data-live for a non-live status", () => {
    const { container } = renderWithProviders(<StatusChip status="registered" />);
    expect(container.querySelector(".status-chip")).not.toHaveAttribute("data-live");
  });
});
