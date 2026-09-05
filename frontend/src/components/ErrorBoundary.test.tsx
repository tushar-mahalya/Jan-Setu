import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import ErrorBoundary from "./ErrorBoundary";
import { en } from "../i18n/messages/en";

function Bomb(): never {
  throw new Error("boom");
}

describe("ErrorBoundary", () => {
  it("renders children when nothing throws", () => {
    renderWithProviders(
      <ErrorBoundary>
        <p>All good</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("All good")).toBeInTheDocument();
  });

  describe("when a child throws", () => {
    let consoleSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    });

    afterEach(() => {
      consoleSpy.mockRestore();
    });

    it("renders the fallback UI", () => {
      renderWithProviders(
        <ErrorBoundary>
          <Bomb />
        </ErrorBoundary>,
      );
      expect(screen.getByRole("alert")).toBeInTheDocument();
      expect(screen.getByText(en.errorTitle)).toBeInTheDocument();
      expect(screen.getByText(en.errorBody)).toBeInTheDocument();
    });

    it("reloads the page when the retry button is clicked", async () => {
      // jsdom's window.location.reload is a non-configurable own property, so
      // vi.spyOn can't redefine it directly — swap the whole location object.
      const originalLocation = window.location;
      const reload = vi.fn();
      Object.defineProperty(window, "location", {
        configurable: true,
        writable: true,
        value: { ...originalLocation, reload },
      });

      const user = userEvent.setup();
      renderWithProviders(
        <ErrorBoundary>
          <Bomb />
        </ErrorBoundary>,
      );
      await user.click(screen.getByRole("button", { name: en.retry }));
      expect(reload).toHaveBeenCalledTimes(1);

      Object.defineProperty(window, "location", {
        configurable: true,
        writable: true,
        value: originalLocation,
      });
    });
  });
});
