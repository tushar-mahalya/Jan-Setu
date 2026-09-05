import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/test-utils";
import Landing from "./Landing";
import { en } from "../i18n/messages/en";

describe("Landing", () => {
  it("renders the hero, process, categories, features, and CTA sections", () => {
    renderWithProviders(<Landing />);
    expect(screen.getByRole("heading", { level: 1, name: en.heroTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: en.howTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: en.categoriesTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: en.featuresTitle })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: en.ctaTitle })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `${en.ctaPrimary} →` })).toHaveAttribute("href", "/login");
  });
});
