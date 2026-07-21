import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { en, type Catalog } from "./messages/en";
import { hi } from "./messages/hi";
import { bn } from "./messages/bn";
import { mr } from "./messages/mr";
import { te } from "./messages/te";
import { ta } from "./messages/ta";

export type Locale = "en" | "hi" | "bn" | "mr" | "te" | "ta";
export type { Catalog };

export interface LocaleInfo {
  code: Locale;
  /** BCP-47 tag used for <html lang>, Intl formatting, and lang attributes. */
  bcp47: string;
  /** Language name in its own script, shown in the picker. */
  native: string;
}

export const LOCALES: readonly LocaleInfo[] = [
  { code: "en", bcp47: "en-IN", native: "English" },
  { code: "hi", bcp47: "hi-IN", native: "हिन्दी" },
  { code: "bn", bcp47: "bn-IN", native: "বাংলা" },
  { code: "mr", bcp47: "mr-IN", native: "मराठी" },
  { code: "te", bcp47: "te-IN", native: "తెలుగు" },
  { code: "ta", bcp47: "ta-IN", native: "தமிழ்" },
];

const CATALOGS: Record<Locale, Catalog> = { en, hi, bn, mr, te, ta };
export const LOCALE_STORAGE_KEY = "jan-setu-locale";

function isLocale(value: string | null): value is Locale {
  return value !== null && value in CATALOGS;
}

/** Replace {name} placeholders: fill(t.stepCounter, { current: 2, total: 4 }). */
export function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

const I18nContext = createContext<{
  locale: Locale;
  bcp47: string;
  setLocale: (locale: Locale) => void;
  t: Catalog;
} | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    const saved = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return isLocale(saved) ? saved : "en";
  });

  const bcp47 = LOCALES.find((entry) => entry.code === locale)?.bcp47 ?? "en-IN";

  useEffect(() => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    document.documentElement.lang = bcp47;
  }, [locale, bcp47]);

  const value = useMemo(
    () => ({ locale, bcp47, setLocale, t: CATALOGS[locale] }),
    [locale, bcp47],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}
