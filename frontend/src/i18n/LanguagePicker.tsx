import { LOCALES, useI18n, type Locale } from "./I18nContext";

/** Six-language selector. `variant="inverse"` sits on dark (teal) surfaces. */
export default function LanguagePicker({ variant = "default" }: { variant?: "default" | "inverse" }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <select
      className={`language-picker${variant === "inverse" ? " language-picker--inverse" : ""}`}
      value={locale}
      onChange={(event) => setLocale(event.target.value as Locale)}
      aria-label={t.languageLabel}
    >
      {LOCALES.map((entry) => (
        <option key={entry.code} value={entry.code} lang={entry.bcp47}>
          {entry.native}
        </option>
      ))}
    </select>
  );
}
