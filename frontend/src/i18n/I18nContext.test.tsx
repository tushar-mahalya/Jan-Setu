import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  fill,
  I18nProvider,
  LOCALE_STORAGE_KEY,
  useI18n,
} from "./I18nContext";

function Consumer() {
  const { locale, bcp47, t, setLocale } = useI18n();
  return (
    <div>
      <p data-testid="locale">{locale}</p>
      <p data-testid="bcp47">{bcp47}</p>
      <p data-testid="brand">{t.brand}</p>
      <button onClick={() => setLocale("hi")}>Hindi</button>
      <button onClick={() => setLocale("bn")}>Bengali</button>
    </div>
  );
}

describe("I18nContext", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  it("useI18n throws when used outside an I18nProvider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Consumer />)).toThrow("useI18n must be used within I18nProvider");
    spy.mockRestore();
  });

  it("defaults to locale 'en' when localStorage is empty", () => {
    render(
      <I18nProvider>
        <Consumer />
      </I18nProvider>,
    );
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
    expect(screen.getByTestId("bcp47")).toHaveTextContent("en-IN");
  });

  it("restores a saved locale from localStorage on mount", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "ta");
    render(
      <I18nProvider>
        <Consumer />
      </I18nProvider>,
    );
    expect(screen.getByTestId("locale")).toHaveTextContent("ta");
    expect(screen.getByTestId("bcp47")).toHaveTextContent("ta-IN");
  });

  it("ignores an invalid saved locale and falls back to 'en'", () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "fr");
    render(
      <I18nProvider>
        <Consumer />
      </I18nProvider>,
    );
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
  });

  it("setLocale updates t/bcp47 and writes to localStorage and document.documentElement.lang", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <Consumer />
      </I18nProvider>,
    );

    expect(screen.getByTestId("brand")).toHaveTextContent("Jan Setu");

    await user.click(screen.getByRole("button", { name: "Hindi" }));

    expect(screen.getByTestId("locale")).toHaveTextContent("hi");
    expect(screen.getByTestId("bcp47")).toHaveTextContent("hi-IN");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("hi");
    expect(document.documentElement.lang).toBe("hi-IN");

    await user.click(screen.getByRole("button", { name: "Bengali" }));
    expect(screen.getByTestId("locale")).toHaveTextContent("bn");
    expect(document.documentElement.lang).toBe("bn-IN");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("bn");
  });
});

describe("fill", () => {
  it("substitutes known placeholders", () => {
    expect(fill("Step {current} of {total}", { current: 2, total: 4 })).toBe("Step 2 of 4");
  });

  it("leaves unknown placeholders as-is", () => {
    expect(fill("Hello {name}, code {code}", { name: "Asha" })).toBe("Hello Asha, code {code}");
  });

  it("returns the template unchanged when it has no placeholders", () => {
    expect(fill("no placeholders here", {})).toBe("no placeholders here");
  });
});
