import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/test-utils";
import StatusTimeline, { formatDateTime } from "./StatusTimeline";
import { en } from "../i18n/messages/en";
import type { GrievanceEvent } from "../api/types";

describe("formatDateTime", () => {
  it("formats a valid ISO date using the given locale", () => {
    const result = formatDateTime("2024-03-15T10:30:00Z", "en-IN");
    const expected = new Date("2024-03-15T10:30:00Z").toLocaleString("en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
    });
    expect(result).toBe(expected);
  });

  it("returns the raw string when the date cannot be parsed", () => {
    expect(formatDateTime("not-a-date", "en-IN")).toBe("not-a-date");
  });
});

describe("StatusTimeline", () => {
  it("shows the empty-timeline message when events is empty", () => {
    renderWithProviders(<StatusTimeline events={[]} />);
    expect(screen.getByText(en.timelineEmpty)).toBeInTheDocument();
  });

  it("renders one list item per event with status chip and formatted time", () => {
    const events: GrievanceEvent[] = [
      { status: "draft", note: null, created_at: "2024-03-15T10:30:00Z" },
      { status: "registered", note: null, created_at: "2024-03-16T09:00:00Z" },
    ];
    renderWithProviders(<StatusTimeline events={events} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(screen.getByText(en.stDraft)).toBeInTheDocument();
    expect(screen.getByText(en.stRegistered)).toBeInTheDocument();
  });

  it("renders the note paragraph only when event.note is truthy", () => {
    const events: GrievanceEvent[] = [
      { status: "draft", note: "Waiting on evidence", created_at: "2024-03-15T10:30:00Z" },
      { status: "registered", note: null, created_at: "2024-03-16T09:00:00Z" },
    ];
    const { container } = renderWithProviders(<StatusTimeline events={events} />);
    expect(screen.getByText("Waiting on evidence")).toBeInTheDocument();
    expect(container.querySelectorAll(".status-timeline__note")).toHaveLength(1);
  });
});
