import { describe, expect, it } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/test-utils";
import { AppShell, ErrorState, Header, LoadingState } from "./AppShell";
import { en } from "../i18n/messages/en";

describe("Header", () => {
  it("toggles the mobile menu open and closed, reflecting aria-expanded", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Header />);
    const toggle = screen.getByRole("button", { name: /open navigation/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /close navigation/i })).toBe(toggle);

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the menu on Escape and returns focus to the toggle button", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Header />);
    const toggle = screen.getByRole("button", { name: /open navigation/i });

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
  });

  it("stays open when a non-Escape key is pressed", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Header />);
    const toggle = screen.getByRole("button", { name: /open navigation/i });

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("a");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });

  it("closes the menu on a mousedown outside the menu container", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Header />);
    const toggle = screen.getByRole("button", { name: /open navigation/i });

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    act(() => {
      document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});

describe("AppShell", () => {
  it("renders header, footer, and children", () => {
    renderWithProviders(
      <AppShell>
        <p>Page content</p>
      </AppShell>,
    );
    expect(screen.getByText("Page content")).toBeInTheDocument();
    expect(screen.getByText(en.skipToContent)).toBeInTheDocument();
    expect(screen.getByText(en.footerNote)).toBeInTheDocument();
    expect(screen.getAllByText(en.brand).length).toBeGreaterThan(0);
  });
});

describe("LoadingState", () => {
  it("renders the loading message", () => {
    renderWithProviders(<LoadingState />);
    expect(screen.getByText(en.loading)).toBeInTheDocument();
  });
});

describe("ErrorState", () => {
  it("renders the error title and body", () => {
    renderWithProviders(<ErrorState />);
    expect(screen.getByText(en.errorTitle)).toBeInTheDocument();
    expect(screen.getByText(en.errorBody)).toBeInTheDocument();
  });
});
