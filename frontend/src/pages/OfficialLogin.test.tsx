import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../auth/AuthContext";
import { I18nProvider } from "../i18n/I18nContext";
import { renderWithProviders } from "../test/test-utils";
import OfficialLogin, { officialToken } from "./OfficialLogin";
import { apiPostJson } from "../api/client";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  apiPostJson: vi.fn(),
}));

const mockedApiPostJson = vi.mocked(apiPostJson);

function renderWithRoutes(route: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[route]}>
            <Routes>
              <Route path="/official/login" element={<OfficialLogin />} />
              <Route path="/official" element={<div>Console</div>} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("OfficialLogin", () => {
  beforeEach(() => {
    sessionStorage.clear();
    mockedApiPostJson.mockReset();
  });

  it("renders the email step when there is no token", () => {
    renderWithProviders(<OfficialLogin />, { route: "/official/login" });
    expect(screen.getByRole("heading", { name: "Official operations" })).toBeInTheDocument();
    expect(screen.getByLabelText("Official email")).toBeInTheDocument();
  });

  it("redirects to /official when a token already exists", () => {
    sessionStorage.setItem("jan-setu-official-token", "existing-token");
    renderWithRoutes("/official/login");
    expect(screen.getByText("Console")).toBeInTheDocument();
    expect(officialToken()).toBe("existing-token");
  });

  it("requests a one-time code without ever revealing it, disabling the button while empty/busy", async () => {
    const user = userEvent.setup();
    let resolveRequest!: (value: { challenge_id: string }) => void;
    mockedApiPostJson.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );
    renderWithProviders(<OfficialLogin />, { route: "/official/login" });

    const emailInput = screen.getByLabelText("Official email");
    await user.clear(emailInput);
    const sendButton = screen.getByRole("button", { name: "Send one-time code" });
    expect(sendButton).toBeDisabled();

    await user.type(emailInput, "official@example.com");
    expect(sendButton).not.toBeDisabled();

    await user.click(sendButton);
    expect(screen.getByRole("button", { name: "Requesting…" })).toBeDisabled();

    resolveRequest({ challenge_id: "c1" });

    await waitFor(() => expect(screen.getByLabelText("One-time code")).toBeInTheDocument());
    // The OTP must never reach the browser: only emailed guidance is shown.
    expect(screen.queryByText(/\d{6}/)).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/emailed a 6-digit code/i);
  });

  it("verifies the code, stores the session, and navigates to /official", async () => {
    const user = userEvent.setup();
    mockedApiPostJson.mockResolvedValueOnce({ challenge_id: "c1" });
    mockedApiPostJson.mockResolvedValueOnce({
      access_token: "tok",
      official: { name: "A", role: "R", jurisdiction_id: "J" },
    });

    renderWithRoutes("/official/login");

    const emailInput = screen.getByLabelText("Official email");
    await user.clear(emailInput);
    await user.type(emailInput, "official@example.com");
    await user.click(screen.getByRole("button", { name: "Send one-time code" }));

    const codeInput = await screen.findByLabelText("One-time code");
    await user.type(codeInput, "654321");
    await user.click(screen.getByRole("button", { name: "Open operations console" }));

    await waitFor(() => expect(screen.getByText("Console")).toBeInTheDocument());
    expect(sessionStorage.getItem("jan-setu-official-token")).toBe("tok");
    expect(sessionStorage.getItem("jan-setu-official-profile")).toBe(
      JSON.stringify({ name: "A", role: "R", jurisdiction_id: "J" }),
    );
  });

  it("shows an error when requesting a code fails", async () => {
    const user = userEvent.setup();
    mockedApiPostJson.mockRejectedValueOnce(new Error("nope"));
    renderWithProviders(<OfficialLogin />, { route: "/official/login" });

    const emailInput = screen.getByLabelText("Official email");
    await user.clear(emailInput);
    await user.type(emailInput, "official@example.com");
    await user.click(screen.getByRole("button", { name: "Send one-time code" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });

  it("shows an error when verifying the code fails", async () => {
    const user = userEvent.setup();
    mockedApiPostJson.mockResolvedValueOnce({ challenge_id: "c1" });
    mockedApiPostJson.mockRejectedValueOnce(new Error("nope"));

    renderWithProviders(<OfficialLogin />, { route: "/official/login" });

    const emailInput = screen.getByLabelText("Official email");
    await user.clear(emailInput);
    await user.type(emailInput, "official@example.com");
    await user.click(screen.getByRole("button", { name: "Send one-time code" }));

    const codeInput = await screen.findByLabelText("One-time code");
    await user.type(codeInput, "654321");
    await user.click(screen.getByRole("button", { name: "Open operations console" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });

  it("resets to the email step when 'Use another email' is clicked", async () => {
    const user = userEvent.setup();
    mockedApiPostJson.mockResolvedValueOnce({ challenge_id: "c1" });
    renderWithProviders(<OfficialLogin />, { route: "/official/login" });

    const emailInput = screen.getByLabelText("Official email");
    await user.clear(emailInput);
    await user.type(emailInput, "official@example.com");
    await user.click(screen.getByRole("button", { name: "Send one-time code" }));

    await screen.findByLabelText("One-time code");
    await user.click(screen.getByRole("button", { name: "Use another email" }));

    expect(screen.getByLabelText("Official email")).toBeInTheDocument();
  });
});
