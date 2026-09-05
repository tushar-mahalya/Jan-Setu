import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LanguagePicker from "./LanguagePicker";
import { I18nProvider, LOCALES } from "./I18nContext";

describe("LanguagePicker", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("renders all six locale options with their native names", () => {
    render(
      <I18nProvider>
        <LanguagePicker />
      </I18nProvider>,
    );
    const select = screen.getByRole("combobox", { name: "Language" });
    const options = Array.from(select.querySelectorAll("option"));
    expect(options).toHaveLength(6);
    expect(options.map((o) => o.value)).toEqual(LOCALES.map((l) => l.code));
    LOCALES.forEach((entry) => {
      expect(screen.getByRole("option", { name: entry.native })).toBeInTheDocument();
    });
  });

  it("changing the select updates the locale, document lang, and native-name display", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <LanguagePicker />
      </I18nProvider>,
    );
    const select = screen.getByRole("combobox", { name: "Language" }) as HTMLSelectElement;
    expect(select.value).toBe("en");

    await user.selectOptions(select, "hi");

    expect(select.value).toBe("hi");
    expect(document.documentElement.lang).toBe("hi-IN");
  });

  it("applies the default class with no inverse modifier", () => {
    render(
      <I18nProvider>
        <LanguagePicker />
      </I18nProvider>,
    );
    const select = screen.getByRole("combobox", { name: "Language" });
    expect(select).toHaveClass("language-picker");
    expect(select).not.toHaveClass("language-picker--inverse");
  });

  it("variant='inverse' applies the extra class", () => {
    render(
      <I18nProvider>
        <LanguagePicker variant="inverse" />
      </I18nProvider>,
    );
    const select = screen.getByRole("combobox", { name: "Language" });
    expect(select).toHaveClass("language-picker");
    expect(select).toHaveClass("language-picker--inverse");
  });
});
