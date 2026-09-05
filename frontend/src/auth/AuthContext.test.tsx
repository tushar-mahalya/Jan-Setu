import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthProvider, getAccessToken, setAccessToken, useAuth } from "./AuthContext";

function Consumer() {
  const { isAuthenticated, token, login, logout } = useAuth();
  return (
    <div>
      <p data-testid="status">{isAuthenticated ? "authenticated" : "anonymous"}</p>
      <p data-testid="token">{token ?? "none"}</p>
      <button onClick={() => login("abc-123")}>Log in</button>
      <button onClick={() => logout()}>Log out</button>
    </div>
  );
}

describe("AuthContext", () => {
  afterEach(() => {
    setAccessToken(null);
  });

  it("useAuth throws when used outside an AuthProvider", () => {
    // Suppress the expected React error boundary console noise.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Consumer />)).toThrow("useAuth must be used within an AuthProvider");
    spy.mockRestore();
  });

  it("starts anonymous when no token is set", () => {
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );
    expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
    expect(screen.getByTestId("token")).toHaveTextContent("none");
  });

  it("login updates isAuthenticated and token, reflected across re-renders", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("token")).toHaveTextContent("abc-123");
    expect(getAccessToken()).toBe("abc-123");
  });

  it("logout clears isAuthenticated and token", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");

    await user.click(screen.getByRole("button", { name: "Log out" }));
    expect(screen.getByTestId("status")).toHaveTextContent("anonymous");
    expect(screen.getByTestId("token")).toHaveTextContent("none");
    expect(getAccessToken()).toBeNull();
  });

  it("AuthProvider seeds its initial state from the module-level token mirror", () => {
    setAccessToken("seeded-tok");
    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );
    expect(screen.getByTestId("status")).toHaveTextContent("authenticated");
    expect(screen.getByTestId("token")).toHaveTextContent("seeded-tok");
  });

  it("getAccessToken/setAccessToken mirror module-level state outside React", () => {
    expect(getAccessToken()).toBeNull();
    setAccessToken("direct-tok");
    expect(getAccessToken()).toBe("direct-tok");
    setAccessToken(null);
    expect(getAccessToken()).toBeNull();
  });
});
