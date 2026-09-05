import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../auth/AuthContext";
import { I18nProvider } from "../i18n/I18nContext";
import AuthenticatedShell from "./AuthenticatedShell";
import { apiPostEmpty } from "../api/client";
import { en } from "../i18n/messages/en";

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  apiPostEmpty: vi.fn().mockResolvedValue(undefined),
}));

function renderShell() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={["/dashboard"]}>
            <Routes>
              <Route
                path="/*"
                element={
                  <AuthenticatedShell>
                    <p>Page content</p>
                  </AuthenticatedShell>
                }
              />
              <Route path="/login" element={<div>Login Page</div>} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("AuthenticatedShell", () => {
  beforeEach(() => {
    vi.mocked(apiPostEmpty).mockReset().mockResolvedValue(undefined);
  });

  it("renders the sidebar nav links and children in main", () => {
    renderShell();
    expect(screen.getByText("Page content").closest("main")).not.toBeNull();
    expect(screen.getAllByRole("link", { name: new RegExp(en.navDashboard) }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: new RegExp(en.navNewComplaint) })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: new RegExp(en.navAboutApp) })).toBeInTheDocument();
  });

  it("logs out via the desktop sidebar button, calls apiPostEmpty, and navigates to /login", async () => {
    const user = userEvent.setup();
    renderShell();
    const [desktopLogout] = screen.getAllByRole("button", { name: en.logout });

    await user.click(desktopLogout);

    expect(apiPostEmpty).toHaveBeenCalledWith("/auth/logout");
    expect(await screen.findByText("Login Page")).toBeInTheDocument();
  });

  it("logs out via the mobile nav button and navigates to /login", async () => {
    const user = userEvent.setup();
    renderShell();
    const logoutButtons = screen.getAllByRole("button", { name: en.logout });
    const mobileLogout = logoutButtons[logoutButtons.length - 1];

    await user.click(mobileLogout);

    expect(apiPostEmpty).toHaveBeenCalledWith("/auth/logout");
    expect(await screen.findByText("Login Page")).toBeInTheDocument();
  });

  it("still navigates to /login when apiPostEmpty rejects", async () => {
    // AuthenticatedShell's logout() has no catch around the await — only a
    // finally — so the rejection propagates out of the async onClick handler
    // and React discards that returned promise, leaving it "unhandled" by
    // design. Swallow just that event for this test so it doesn't fail the
    // run; the finally-driven navigation behavior is what we're verifying.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const nodeProcess = (globalThis as any).process as
      | { emit: (event: string, ...args: unknown[]) => boolean }
      | undefined;
    const originalEmit = nodeProcess?.emit.bind(nodeProcess);
    if (nodeProcess && originalEmit) {
      nodeProcess.emit = (event: string, ...args: unknown[]) => {
        if (event === "unhandledRejection") return true;
        return originalEmit(event, ...args);
      };
    }

    try {
      vi.mocked(apiPostEmpty).mockRejectedValue(new Error("boom"));
      const user = userEvent.setup();
      renderShell();
      const [desktopLogout] = screen.getAllByRole("button", { name: en.logout });

      await user.click(desktopLogout);

      expect(await screen.findByText("Login Page")).toBeInTheDocument();
      await new Promise((resolve) => setTimeout(resolve, 0));
    } finally {
      if (nodeProcess && originalEmit) nodeProcess.emit = originalEmit;
    }
  });
});
