import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, setAccessToken } from "./auth/AuthContext";
import { I18nProvider } from "./i18n/I18nContext";
import App from "./App";
import { restoreSession } from "./api/client";
import { en } from "./i18n/messages/en";

vi.mock("./api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./api/client")>()),
  restoreSession: vi.fn(),
}));

const mockedRestoreSession = vi.mocked(restoreSession);

function renderApp(route: string) {
  // App.tsx decides whether to restore a citizen session by reading
  // window.location.pathname directly (not the router's in-memory location),
  // so the real jsdom URL has to match the MemoryRouter's initial entry.
  window.history.pushState({}, "", route);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[route]}>
            <App />
          </MemoryRouter>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("App", () => {
  beforeEach(() => {
    mockedRestoreSession.mockReset();
    // The access token lives in a module-level variable outside React state
    // (see auth/AuthContext.tsx), so a previous test's login() call leaks
    // into the next test's AuthProvider unless explicitly cleared.
    setAccessToken(null);
    window.history.pushState({}, "", "/");
  });

  it("renders Landing at / without restoring a citizen session", async () => {
    renderApp("/");
    expect(await screen.findByRole("heading", { level: 1, name: en.heroTitle })).toBeInTheDocument();
    expect(mockedRestoreSession).not.toHaveBeenCalled();
  });

  it("scrolls to the #how section when the route includes a hash", async () => {
    // jsdom doesn't implement scrollIntoView; App.tsx's ScrollToHash effect
    // calls it unconditionally when a hash is present.
    Element.prototype.scrollIntoView = vi.fn();
    renderApp("/#how");
    expect(await screen.findByRole("heading", { level: 2, name: en.howTitle })).toBeInTheDocument();
    expect(mockedRestoreSession).not.toHaveBeenCalled();
  });

  it("restores the session at /dashboard and redirects to /login when unauthenticated", async () => {
    mockedRestoreSession.mockResolvedValue(null);
    renderApp("/dashboard");
    expect(await screen.findByRole("heading", { level: 1, name: en.loginTitle })).toBeInTheDocument();
    expect(mockedRestoreSession).toHaveBeenCalled();
  });

  it("restores the session at /dashboard and renders the authenticated shell when a token comes back", async () => {
    mockedRestoreSession.mockResolvedValue("tok");
    renderApp("/dashboard");
    expect((await screen.findAllByRole("navigation", { name: en.appNavAria })).length).toBeGreaterThan(0);
    expect(mockedRestoreSession).toHaveBeenCalled();
  });

  it("redirects an unknown route to /", async () => {
    renderApp("/nonexistent");
    expect(await screen.findByRole("heading", { level: 1, name: en.heroTitle })).toBeInTheDocument();
  });
});
