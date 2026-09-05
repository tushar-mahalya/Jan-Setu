import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import Dashboard from "./Dashboard";
import { apiGet } from "../api/client";
import type { GrievanceSummary } from "../api/types";
import { en } from "../i18n/messages/en";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  apiGet: vi.fn(),
}));

const mockedApiGet = vi.mocked(apiGet);

describe("Dashboard", () => {
  beforeEach(() => {
    mockedApiGet.mockReset();
  });

  it("shows a loading skeleton while the query is pending", () => {
    mockedApiGet.mockReturnValue(new Promise(() => {}));
    renderWithProviders(<Dashboard />);
    expect(screen.getByRole("status", { name: en.dashLoadingAria })).toBeInTheDocument();
  });

  it("shows an error notice and retries on click", async () => {
    const user = userEvent.setup();
    mockedApiGet.mockRejectedValue(new Error("boom"));
    renderWithProviders(<Dashboard />);

    expect(await screen.findByRole("alert")).toHaveTextContent(en.dashErrorTitle);
    const callsBefore = mockedApiGet.mock.calls.length;

    await user.click(screen.getByRole("button", { name: en.retry }));
    await waitFor(() => expect(mockedApiGet.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("shows the empty state with a CTA link when there are no complaints", async () => {
    mockedApiGet.mockResolvedValue([]);
    renderWithProviders(<Dashboard />);

    expect(await screen.findByRole("heading", { name: en.emptyTitle })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.emptyCta })).toHaveAttribute("href", "/complaints/new");
  });

  it("renders one row per complaint, covering the high/normal/null priority branches", async () => {
    const items: GrievanceSummary[] = [
      {
        id: "1",
        human_id: "JS-001",
        category: "road_damage",
        status: "registered",
        priority: "high",
        source: "web",
        created_at: "2026-01-05T10:00:00Z",
      },
      {
        id: "2",
        human_id: "JS-002",
        category: "garbage",
        status: "processing",
        priority: "medium",
        source: "whatsapp",
        created_at: "2026-02-10T10:00:00Z",
      },
      {
        id: "3",
        human_id: "JS-003",
        category: null,
        status: "draft",
        priority: null,
        source: "web",
        created_at: "2026-03-15T10:00:00Z",
      },
    ];
    mockedApiGet.mockResolvedValue(items);
    renderWithProviders(<Dashboard />);

    const row1 = await screen.findByRole("row", { name: /JS-001/ });
    expect(row1).toHaveAttribute("href", "/complaints/1");
    expect(row1).toHaveTextContent(en.priorityHigh);

    const row2 = screen.getByRole("row", { name: /JS-002/ });
    expect(row2).toHaveAttribute("href", "/complaints/2");
    expect(row2).toHaveTextContent(en.priorityNormal);

    const row3 = screen.getByRole("row", { name: /JS-003/ });
    expect(row3).toHaveAttribute("href", "/complaints/3");
    expect(row3).toHaveTextContent(en.municipalRouting);
    expect(row3).toHaveTextContent(en.categoryPending);
  });
});
