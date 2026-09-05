import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/test-utils";
import About from "./About";
import { en } from "../i18n/messages/en";

describe("About", () => {
  it("renders the intro, principles, process, and privacy sections", () => {
    renderWithProviders(<About />);
    expect(screen.getByRole("heading", { level: 1, name: en.aboutTitle })).toBeInTheDocument();
    expect(screen.getByText(en.aboutIntro)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.aboutOpenCta })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("heading", { level: 2, name: en.aboutPrinciplesTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: en.howTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: en.categoriesTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: en.privacyTitle })).toBeInTheDocument();
  });
});
