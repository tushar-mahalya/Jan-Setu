import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders } from "../../test/test-utils";
import { CallToAction, Categories, Features, Hero, Process } from "./LandingSections";
import { en } from "../../i18n/messages/en";

describe("Hero", () => {
  it("renders the headline, CTAs, and proof chips", () => {
    renderWithProviders(<Hero />);
    expect(screen.getByRole("heading", { level: 1, name: en.heroTitle })).toBeInTheDocument();
    expect(screen.getByText(en.heroSub)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: `${en.ctaPrimary} →` })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: en.ctaSecondary })).toHaveAttribute("href", "#how");
    expect(screen.getByText(en.chip1)).toBeInTheDocument();
    expect(screen.getByText(en.proofLocation)).toBeInTheDocument();
  });
});

describe("Process", () => {
  it("renders the four workflow steps in order", () => {
    renderWithProviders(<Process />);
    expect(screen.getByRole("heading", { level: 2, name: en.howTitle })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(screen.getByText(en.step1H)).toBeInTheDocument();
    expect(screen.getByText(en.step4H)).toBeInTheDocument();
  });
});

describe("Categories", () => {
  it("renders every category label and department", () => {
    renderWithProviders(<Categories />);
    expect(screen.getByRole("heading", { level: 2, name: en.categoriesTitle })).toBeInTheDocument();
    const roadsArticle = screen.getByText(en.roadsLabel).closest("article") as HTMLElement;
    expect(within(roadsArticle).getByText(en.roadsDept)).toBeInTheDocument();
    expect(screen.getByText(en.animalsLabel)).toBeInTheDocument();
    expect(screen.getByText(en.otherLabel)).toBeInTheDocument();
  });

  it("shows the priority badge only on the animals category", () => {
    renderWithProviders(<Categories />);
    const badges = screen.getAllByText(en.priorityBadge);
    expect(badges).toHaveLength(1);
    expect(badges[0].tagName).toBe("EM");
    const animalsArticle = screen.getByText(en.animalsLabel).closest("article");
    expect(animalsArticle).toContainElement(badges[0]);

    const roadsArticle = screen.getByText(en.roadsLabel).closest("article");
    expect(roadsArticle?.querySelector("em")).toBeNull();
  });
});

describe("Features", () => {
  it("renders the three feature cards", () => {
    renderWithProviders(<Features />);
    expect(screen.getByRole("heading", { level: 2, name: en.featuresTitle })).toBeInTheDocument();
    expect(screen.getByText(en.feature1H)).toBeInTheDocument();
    expect(screen.getByText(en.feature2H)).toBeInTheDocument();
    expect(screen.getByText(en.feature3H)).toBeInTheDocument();
  });
});

describe("CallToAction", () => {
  it("renders the closing CTA with a link to login", () => {
    renderWithProviders(<CallToAction />);
    expect(screen.getByRole("heading", { level: 2, name: en.ctaTitle })).toBeInTheDocument();
    expect(screen.getByText(en.ctaSub)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: en.ctaButton })).toHaveAttribute("href", "/login");
  });
});
