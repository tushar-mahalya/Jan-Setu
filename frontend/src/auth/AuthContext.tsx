import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

// The access token lives ONLY in memory (React state + this module-level mirror).
// It is never written to localStorage/sessionStorage so a page refresh always
// requires a fresh /auth/refresh exchange against the httpOnly refresh cookie.
let memoryToken: string | null = null;

/** Read the current access token outside of React (used by api/client.ts). */
export function getAccessToken(): string | null {
  return memoryToken;
}

/** Write the current access token outside of React (used by api/client.ts on refresh). */
export function setAccessToken(token: string | null): void {
  memoryToken = token;
}

interface AuthContextValue {
  token: string | null;
  isAuthenticated: boolean;
  login: (token: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getAccessToken());

  const login = useCallback((newToken: string) => {
    setAccessToken(newToken);
    setToken(newToken);
  }, []);

  const logout = useCallback(() => {
    setAccessToken(null);
    setToken(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ token, isAuthenticated: token !== null, login, logout }),
    [token, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
