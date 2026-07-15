import { getAccessToken, setAccessToken } from "../auth/AuthContext";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = await response.clone().json();
    if (typeof body?.detail === "string") return body.detail;
    if (typeof body?.message === "string") return body.message;
  } catch {
    // response body wasn't JSON — fall through to status text
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

function buildHeaders(extra?: HeadersInit, includeAuth = true): Headers {
  const headers = new Headers(extra);
  if (includeAuth) {
    const token = getAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  return headers;
}

/**
 * Attempts to refresh the access token using the httpOnly refresh cookie.
 * Returns the new token on success, or null if the refresh failed.
 */
async function refreshAccessToken(): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    });
    if (!response.ok) return null;
    const data = (await response.json()) as { access_token: string };
    setAccessToken(data.access_token);
    return data.access_token;
  } catch {
    return null;
  }
}

/**
 * Attempts to silently restore a session from the httpOnly refresh cookie on
 * app boot. The access token only ever lives in memory, so a hard page
 * reload always starts with none — without this, a refresh would otherwise
 * bounce a still-logged-in citizen back to /login.
 */
export async function restoreSession(): Promise<string | null> {
  return refreshAccessToken();
}

function redirectToLogin(): void {
  setAccessToken(null);
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

interface RequestOptions extends RequestInit {
  /** Attach the in-memory access token as a Bearer header. Defaults to true. */
  auth?: boolean;
  /** Internal flag — prevents infinite refresh retry loops. */
  _isRetry?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { auth = true, _isRetry = false, headers, ...rest } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      credentials: "include",
      headers: buildHeaders(headers, auth),
    });
  } catch {
    throw new ApiError(0, "We couldn’t reach Jan Setu. Check your connection and try again.");
  }

  if (response.status === 401 && auth && !_isRetry) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      return request<T>(path, { ...options, _isRetry: true });
    }
    redirectToLogin();
    throw new ApiError(401, "Session expired. Please log in again.");
  }

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function apiGet<T>(path: string, options?: RequestOptions): Promise<T> {
  return request<T>(path, { ...options, method: "GET" });
}

export function apiPostJson<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
  return request<T>(path, {
    ...options,
    method: "POST",
    body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
  });
}

export function apiPostForm<T>(path: string, formData: FormData, options?: RequestOptions): Promise<T> {
  // Do not set Content-Type manually — the browser must add the multipart boundary.
  return request<T>(path, { ...options, method: "POST", body: formData });
}

export function apiPatchForm<T>(path: string, formData: FormData, options?: RequestOptions): Promise<T> {
  return request<T>(path, { ...options, method: "PATCH", body: formData });
}

export function apiPostEmpty<T>(path: string, options?: RequestOptions): Promise<T> {
  return request<T>(path, { ...options, method: "POST" });
}

/**
 * Fetches a binary resource (e.g. a grievance PDF) with the Authorization header
 * attached, since plain <a href> downloads cannot carry custom headers.
 * Triggers a browser download via a temporary object-URL anchor.
 */
export async function downloadWithAuth(path: string, filename: string): Promise<void> {
  const url = /^https?:\/\//i.test(path) ? path : `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      credentials: "include",
      headers: buildHeaders(undefined, true),
    });
  } catch {
    throw new ApiError(0, "We couldn’t download the receipt. Check your connection and try again.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorMessage(response));
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}
