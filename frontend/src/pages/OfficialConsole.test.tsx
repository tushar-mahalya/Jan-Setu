import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders, screen } from "../test/test-utils";
import OfficialConsole from "./OfficialConsole";

const TOKEN_KEY = "jan-setu-official-token";
const PROFILE_KEY = "jan-setu-official-profile";

type QueueItem = {
  id: string;
  human_id: string;
  status: string;
  review_status: string | null;
  category_id: string | null;
  category_label: string;
  domain: string;
  department_key: string | null;
  priority: string | null;
  safety_level: string | null;
  disposition: string | null;
  confidence: number | null;
  address: string | null;
  issue_text: string | null;
  structured_facts: Record<string, unknown> | null;
  routing: Record<string, unknown> | null;
  flags: string[];
  created_at: string;
  state_version: number;
};

function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "g1",
    human_id: "JS-4001",
    status: "registered",
    review_status: "pending_official",
    category_id: "pothole_surface_damage",
    category_label: "Pothole",
    domain: "roads",
    department_key: "roads",
    priority: "high",
    safety_level: "none",
    disposition: "standard_routing",
    confidence: 0.7,
    address: "12 Ring Rd",
    issue_text: "Pothole causing damage.",
    structured_facts: { summary: "Pothole summary" },
    routing: {},
    flags: [],
    created_at: "2026-01-01T10:00:00Z",
    state_version: 1,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response;
}

// jsdom's window.location.assign isn't configurable enough for vi.spyOn in
// this environment, so swap the whole location object for one with a mock.
function stubLocationAssign() {
  const assign = vi.fn();
  const original = window.location;
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...original, assign },
  });
  return assign;
}

function restoreLocation(original: Location) {
  Object.defineProperty(window, "location", { configurable: true, value: original });
}

function seedSession() {
  sessionStorage.setItem(TOKEN_KEY, "tok");
  sessionStorage.setItem(PROFILE_KEY, JSON.stringify({ name: "Alex", role: "reviewer", jurisdiction_id: "j1" }));
}

function renderConsole() {
  return renderWithProviders(
    <Routes>
      <Route path="/official" element={<OfficialConsole />} />
      <Route path="/official/login" element={<div>Official Login Screen</div>} />
    </Routes>,
    { route: "/official" },
  );
}

describe("OfficialConsole", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    sessionStorage.clear();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    restoreLocation(originalLocation);
  });

  it("redirects to /official/login when there is no token", async () => {
    renderConsole();
    expect(await screen.findByText("Official Login Screen")).toBeInTheDocument();
  });

  it("loads the queue and metrics, shows a case, and enables actions after typing a reason", async () => {
    seedSession();
    const metrics = { total_visible: 5, pending_review: 2, immediate_safety: 0, failed_ai: 0, failed_dispatch: 0 };
    const queue = [queueItem()];
    vi.mocked(fetch).mockImplementation((url: string | URL | Request) => {
      const href = String(url);
      if (href.includes("/api/official/queue")) return Promise.resolve(jsonResponse(queue));
      if (href.includes("/api/official/metrics")) return Promise.resolve(jsonResponse(metrics));
      return Promise.resolve(jsonResponse({}));
    });
    const user = userEvent.setup();
    renderConsole();

    expect(await screen.findByText("5")).toBeInTheDocument();
    expect(screen.getByText("JS-4001")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /JS-4001/ }));
    expect(await screen.findByText("Pothole summary")).toBeInTheDocument();

    const approveButton = screen.getByRole("button", { name: "Approve route" });
    expect(approveButton).toBeDisabled();

    await user.type(screen.getByPlaceholderText(/Explain evidence/), "Looks valid");
    expect(approveButton).not.toBeDisabled();

    vi.mocked(fetch).mockClear();
    vi.mocked(fetch).mockImplementation((url: string | URL | Request) => {
      const href = String(url);
      if (href.includes("/actions")) return Promise.resolve(jsonResponse(queueItem({ review_status: "approved" })));
      if (href.includes("/api/official/queue")) return Promise.resolve(jsonResponse(queue));
      if (href.includes("/api/official/metrics")) return Promise.resolve(jsonResponse(metrics));
      return Promise.resolve(jsonResponse({}));
    });
    await user.click(approveButton);

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/official/grievances/g1/actions"),
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "approve", reason: "Looks valid" }) }),
    );
  });

  it("clears the token and redirects on a 401 response", async () => {
    seedSession();
    const assign = stubLocationAssign();
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}, 401));
    renderConsole();
    await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/official/login"));
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("polls every 10 seconds", async () => {
    vi.useFakeTimers();
    seedSession();
    const metrics = { total_visible: 1, pending_review: 0, immediate_safety: 0, failed_ai: 0, failed_dispatch: 0 };
    vi.mocked(fetch).mockImplementation((url: string | URL | Request) => {
      const href = String(url);
      if (href.includes("/api/official/queue")) return Promise.resolve(jsonResponse([]));
      if (href.includes("/api/official/metrics")) return Promise.resolve(jsonResponse(metrics));
      return Promise.resolve(jsonResponse({}));
    });
    renderConsole();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    const initialCalls = vi.mocked(fetch).mock.calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(initialCalls);
  });

  it("sign out clears sessionStorage and redirects", async () => {
    seedSession();
    const assign = stubLocationAssign();
    vi.mocked(fetch).mockResolvedValue(jsonResponse([]));
    const user = userEvent.setup();
    renderConsole();
    await screen.findByText("Civic triage desk");
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(sessionStorage.getItem(PROFILE_KEY)).toBeNull();
    expect(assign).toHaveBeenCalledWith("/official/login");
  });
});
