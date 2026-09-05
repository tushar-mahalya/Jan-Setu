import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { Routes, Route } from "react-router-dom";
import { renderWithProviders, screen } from "../test/test-utils";
import Login from "./Login";
import { ApiError } from "../api/client";
import { en } from "../i18n/messages/en";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal()),
  apiGet: vi.fn(),
  apiPostJson: vi.fn(),
}));

import { apiGet, apiPostJson } from "../api/client";

function renderLogin() {
  return renderWithProviders(
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/dashboard" element={<div>Dashboard Screen</div>} />
    </Routes>,
    { route: "/login" },
  );
}

async function fillPhone(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(en.loginPhoneLabel), "9876543210");
  await user.click(screen.getByRole("button", { name: en.loginSubmit }));
}

describe("Login", () => {
  beforeEach(() => {
    vi.mocked(apiPostJson).mockReset();
    vi.mocked(apiGet).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the request-code error when apiPostJson rejects", async () => {
    const user = userEvent.setup();
    vi.mocked(apiPostJson).mockRejectedValueOnce(new ApiError(400, "Bad phone number"));
    renderLogin();
    await fillPhone(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("Bad phone number");
  });

  it("shows the whatsapp approval panel then navigates to /dashboard once verified", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });
    vi.mocked(apiPostJson).mockImplementation((path: string) => {
      if (path === "/auth/request-code") {
        return Promise.resolve({
          verification_id: "v1",
          method: "whatsapp_approval",
          browser_label: "Chrome on macOS",
          expires_at: null,
        });
      }
      if (path === "/auth/approval-status") {
        const call = vi.mocked(apiPostJson).mock.calls.filter((c) => c[0] === "/auth/approval-status").length;
        if (call <= 1) return Promise.resolve({ status: "pending" });
        return Promise.resolve({ status: "verified", access_token: "tok" });
      }
      return Promise.reject(new Error("unexpected path " + path));
    });
    renderLogin();
    await fillPhone(user);
    expect(await screen.findByText(en.approvalTitle)).toBeInTheDocument();
    expect(screen.getByText("Chrome on macOS")).toBeInTheDocument();
    expect(screen.getByText(en.approvalWaiting)).toBeInTheDocument();

    await vi.advanceTimersByTimeAsync(2500);
    await vi.advanceTimersByTimeAsync(2500);

    expect(await screen.findByText("Dashboard Screen")).toBeInTheDocument();
  });

  it("shows the reverse-code panel with code and wa_link", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });
    vi.mocked(apiPostJson).mockResolvedValueOnce({
      verification_id: "v2",
      method: "reverse_code",
      code: "123456",
      wa_link: "https://wa.me/xyz",
    });
    vi.mocked(apiGet).mockResolvedValue({ status: "pending" });
    renderLogin();
    await fillPhone(user);
    expect(await screen.findByText(en.codeTitle)).toBeInTheDocument();
    expect(screen.getByText("123456")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.codeOpen })).toHaveAttribute("href", "https://wa.me/xyz");
  });

  it("shows the denied panel with a working reset button", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });
    vi.mocked(apiPostJson).mockImplementation((path: string) => {
      if (path === "/auth/request-code") {
        return Promise.resolve({ verification_id: "v3", method: "whatsapp_approval" });
      }
      return Promise.resolve({ status: "denied" });
    });
    renderLogin();
    await fillPhone(user);
    expect(await screen.findByText(en.deniedTitle)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en.retry }));
    expect(await screen.findByLabelText(en.loginPhoneLabel)).toBeInTheDocument();
  });

  it("shows the expired panel with a working reset button", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ delay: null });
    vi.mocked(apiPostJson).mockImplementation((path: string) => {
      if (path === "/auth/request-code") {
        return Promise.resolve({ verification_id: "v4", method: "whatsapp_approval" });
      }
      return Promise.resolve({ status: "expired" });
    });
    renderLogin();
    await fillPhone(user);
    expect(await screen.findByText(en.expiredTitle)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: en.expiredCta }));
    expect(await screen.findByLabelText(en.loginPhoneLabel)).toBeInTheDocument();
  });
});
