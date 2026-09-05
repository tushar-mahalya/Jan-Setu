import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiGet,
  apiPatchForm,
  apiPatchJson,
  apiPostEmpty,
  apiPostForm,
  apiPostJson,
  downloadWithAuth,
  restoreSession,
} from "./client";
import { setAccessToken } from "../auth/AuthContext";

function jsonResponse(body: unknown, init: { status?: number; ok?: boolean; statusText?: string } = {}) {
  const status = init.status ?? 200;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    statusText: init.statusText ?? "",
    clone() {
      return jsonResponse(body, init);
    },
    json: async () => body,
  } as unknown as Response;
}

function noBodyResponse(init: { status?: number; ok?: boolean; statusText?: string } = {}) {
  const status = init.status ?? 204;
  return {
    ok: init.ok ?? (status >= 200 && status < 300),
    status,
    statusText: init.statusText ?? "",
    clone() {
      return noBodyResponse(init);
    },
    json: async () => {
      throw new Error("not json");
    },
  } as unknown as Response;
}

describe("api/client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    setAccessToken(null);
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe("happy paths", () => {
    it("apiGet resolves with parsed JSON", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ hello: "world" }));
      const result = await apiGet<{ hello: string }>("/things");
      expect(result).toEqual({ hello: "world" });
      const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(url).toBe("/things");
      expect(init.method).toBe("GET");
      expect(init.credentials).toBe("include");
    });

    it("apiPostJson sends JSON body with content-type header", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ id: 1 }));
      const result = await apiPostJson<{ id: number }>("/things", { name: "a" });
      expect(result).toEqual({ id: 1 });
      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(init.method).toBe("POST");
      expect(init.body).toBe(JSON.stringify({ name: "a" }));
      expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
    });

    it("apiPostForm sends FormData without setting content-type", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ ok: true }));
      const fd = new FormData();
      fd.append("file", "x");
      const result = await apiPostForm<{ ok: boolean }>("/upload", fd);
      expect(result).toEqual({ ok: true });
      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(init.method).toBe("POST");
      expect(init.body).toBe(fd);
      expect((init.headers as Headers).get("Content-Type")).toBeNull();
    });

    it("apiPatchForm sends FormData via PATCH", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ ok: true }));
      const fd = new FormData();
      const result = await apiPatchForm<{ ok: boolean }>("/things/1", fd);
      expect(result).toEqual({ ok: true });
      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(init.method).toBe("PATCH");
      expect(init.body).toBe(fd);
    });

    it("apiPatchJson sends JSON body via PATCH", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ id: 2 }));
      const result = await apiPatchJson<{ id: number }>("/things/1", { name: "b" });
      expect(result).toEqual({ id: 2 });
      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(init.method).toBe("PATCH");
      expect(init.body).toBe(JSON.stringify({ name: "b" }));
    });

    it("apiPostEmpty sends POST with no body", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ started: true }));
      const result = await apiPostEmpty<{ started: boolean }>("/things/1/start");
      expect(result).toEqual({ started: true });
      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(init.method).toBe("POST");
      expect(init.body).toBeUndefined();
    });

    it("attaches Authorization header when an access token is set", async () => {
      setAccessToken("tok-123");
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse({ ok: true }));
      await apiGet("/things");
      const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      expect((init.headers as Headers).get("Authorization")).toBe("Bearer tok-123");
    });

    it("204 response returns undefined without parsing a body", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(noBodyResponse({ status: 204 }));
      const result = await apiGet("/things/1");
      expect(result).toBeUndefined();
    });
  });

  describe("errors", () => {
    it("throws ApiError with message from `detail` field on non-ok response", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ detail: "Not found" }, { status: 404, ok: false }),
      );
      await expect(apiGet("/missing")).rejects.toMatchObject({
        name: "ApiError",
        status: 404,
        message: "Not found",
      });
    });

    it("throws ApiError with message from `message` field on non-ok response", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ message: "Bad input" }, { status: 400, ok: false }),
      );
      await expect(apiGet("/things")).rejects.toMatchObject({
        status: 400,
        message: "Bad input",
      });
    });

    it("falls back to statusText when body isn't JSON", async () => {
      const response = {
        ok: false,
        status: 500,
        statusText: "Internal Server Error",
        clone() {
          return response;
        },
        json: async () => {
          throw new Error("not json");
        },
      } as unknown as Response;
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(response);
      await expect(apiGet("/things")).rejects.toMatchObject({
        status: 500,
        message: "Internal Server Error",
      });
    });

    it("falls back to a generic status message when body isn't JSON and statusText is empty", async () => {
      const response = {
        ok: false,
        status: 503,
        statusText: "",
        clone() {
          return response;
        },
        json: async () => {
          throw new Error("not json");
        },
      } as unknown as Response;
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(response);
      await expect(apiGet("/things")).rejects.toMatchObject({
        status: 503,
        message: "Request failed with status 503",
      });
    });

    it("wraps a network failure (fetch rejects) in an ApiError with status 0", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new TypeError("network down"));
      await expect(apiGet("/things")).rejects.toMatchObject({
        status: 0,
        name: "ApiError",
      });
    });

    it("ApiError sets name, status, and message", () => {
      const err = new ApiError(418, "teapot");
      expect(err.name).toBe("ApiError");
      expect(err.status).toBe(418);
      expect(err.message).toBe("teapot");
      expect(err).toBeInstanceOf(Error);
    });
  });

  describe("401 handling", () => {
    it("retries once after a successful refresh and returns the retried result", async () => {
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch
        .mockResolvedValueOnce(jsonResponse({}, { status: 401, ok: false })) // initial request
        .mockResolvedValueOnce(jsonResponse({ access_token: "new-tok" })) // refresh
        .mockResolvedValueOnce(jsonResponse({ id: 5 })); // retried request

      const result = await apiGet<{ id: number }>("/things");
      expect(result).toEqual({ id: 5 });
      expect(mockFetch).toHaveBeenCalledTimes(3);
      const refreshCall = mockFetch.mock.calls[1];
      expect(refreshCall[0]).toBe("/auth/refresh");
      const retryCall = mockFetch.mock.calls[2];
      expect((retryCall[1].headers as Headers).get("Authorization")).toBe("Bearer new-tok");
    });

    it("redirects to /login and throws when refresh fails", async () => {
      const original = window.location;
      Object.defineProperty(window, "location", {
        value: { ...original, pathname: "/dashboard", assign: vi.fn() },
        writable: true,
        configurable: true,
      });
      const assignSpy = window.location.assign as ReturnType<typeof vi.fn>;
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch
        .mockResolvedValueOnce(jsonResponse({}, { status: 401, ok: false })) // initial request
        .mockResolvedValueOnce(jsonResponse({}, { status: 401, ok: false })); // refresh fails

      await expect(apiGet("/things")).rejects.toMatchObject({
        status: 401,
        message: "Session expired. Please log in again.",
      });
      expect(assignSpy).toHaveBeenCalledWith("/login");

      Object.defineProperty(window, "location", { value: original, writable: true, configurable: true });
    });

    it("does not redirect when refresh fails but already on /login", async () => {
      const original = window.location;
      Object.defineProperty(window, "location", {
        value: { ...original, pathname: "/login", assign: vi.fn() },
        writable: true,
        configurable: true,
      });
      const assignSpy = window.location.assign as ReturnType<typeof vi.fn>;
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch
        .mockResolvedValueOnce(jsonResponse({}, { status: 401, ok: false }))
        .mockResolvedValueOnce(jsonResponse({}, { status: 401, ok: false }));

      await expect(apiGet("/things")).rejects.toMatchObject({ status: 401 });
      expect(assignSpy).not.toHaveBeenCalled();

      Object.defineProperty(window, "location", { value: original, writable: true, configurable: true });
    });

    it("does not attempt refresh when auth: false", async () => {
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch.mockResolvedValueOnce(jsonResponse({}, { status: 401, ok: false, statusText: "Unauthorized" }));
      await expect(apiGet("/public-ish", { auth: false })).rejects.toMatchObject({ status: 401 });
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  describe("restoreSession", () => {
    it("delegates to the refresh endpoint and returns the new token", async () => {
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch.mockResolvedValueOnce(jsonResponse({ access_token: "restored-tok" }));
      const token = await restoreSession();
      expect(token).toBe("restored-tok");
      expect(mockFetch).toHaveBeenCalledWith(
        "/auth/refresh",
        expect.objectContaining({ method: "POST", credentials: "include" }),
      );
    });

    it("returns null when the refresh request fails", async () => {
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch.mockResolvedValueOnce(jsonResponse({}, { status: 401, ok: false }));
      const token = await restoreSession();
      expect(token).toBeNull();
    });

    it("returns null when the refresh request throws (network failure)", async () => {
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch.mockRejectedValueOnce(new TypeError("offline"));
      const token = await restoreSession();
      expect(token).toBeNull();
    });
  });

  describe("downloadWithAuth", () => {
    let createObjectURL: ReturnType<typeof vi.fn>;
    let revokeObjectURL: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      createObjectURL = vi.fn(() => "blob:mock-url");
      revokeObjectURL = vi.fn();
      vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    });

    it("downloads a blob and triggers an anchor click", async () => {
      const blob = new Blob(["data"]);
      const response = {
        ok: true,
        status: 200,
        statusText: "",
        clone() {
          return response;
        },
        json: async () => ({}),
        blob: async () => blob,
      } as unknown as Response;
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(response);

      const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

      await downloadWithAuth("/receipts/1", "receipt.pdf");

      expect(createObjectURL).toHaveBeenCalledWith(blob);
      expect(clickSpy).toHaveBeenCalled();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
    });

    it("uses the given absolute URL as-is when path is already a full URL", async () => {
      const blob = new Blob(["data"]);
      const response = {
        ok: true,
        status: 200,
        statusText: "",
        clone() {
          return response;
        },
        json: async () => ({}),
        blob: async () => blob,
      } as unknown as Response;
      const mockFetch = fetch as ReturnType<typeof vi.fn>;
      mockFetch.mockResolvedValueOnce(response);
      vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

      await downloadWithAuth("https://files.example.com/r/1", "receipt.pdf");
      expect(mockFetch.mock.calls[0][0]).toBe("https://files.example.com/r/1");
    });

    it("throws ApiError(0) on network failure", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new TypeError("offline"));
      await expect(downloadWithAuth("/receipts/1", "receipt.pdf")).rejects.toMatchObject({ status: 0 });
    });

    it("throws ApiError on non-ok response", async () => {
      (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
        jsonResponse({ detail: "Receipt not found" }, { status: 404, ok: false }),
      );
      await expect(downloadWithAuth("/receipts/1", "receipt.pdf")).rejects.toMatchObject({
        status: 404,
        message: "Receipt not found",
      });
    });
  });
});
