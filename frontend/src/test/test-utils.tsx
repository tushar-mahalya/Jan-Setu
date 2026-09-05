import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../auth/AuthContext";
import { I18nProvider } from "../i18n/I18nContext";

/**
 * Renders with the same provider stack the app mounts in production:
 * react-query -> i18n -> auth -> router. Use `route` to land on a specific
 * path (needed for pages that read useParams/useLocation).
 */
export function renderWithProviders(
  ui: ReactElement,
  { route = "/", ...options }: RenderOptions & { route?: string } = {},
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <AuthProvider>
            <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
          </AuthProvider>
        </I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(ui, { wrapper: Wrapper, ...options });
}

export * from "@testing-library/react";
