import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useI18n } from "../i18n/I18nContext";

export function Brand() {
  const { t } = useI18n();
  return <NavLink className="parity-brand" to="/"><span aria-hidden="true" /><b>{t.brand}</b></NavLink>;
}

export function Header() {
  const { locale, setLocale, t } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuId = useId();
  const menuRef = useRef<HTMLDivElement>(null);
  const menuToggleRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setMenuOpen(false);
      menuToggleRef.current?.focus();
    };
    const closeOnOutside = (event: MouseEvent) => { if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false); };
    document.addEventListener("keydown", closeOnEscape);
    document.addEventListener("mousedown", closeOnOutside);
    return () => { document.removeEventListener("keydown", closeOnEscape); document.removeEventListener("mousedown", closeOnOutside); };
  }, [menuOpen]);
  const closeMenu = () => setMenuOpen(false);
  return <header className="parity-header"><div className="parity-container" ref={menuRef}>
    <Brand />
    <nav className={menuOpen ? "parity-public-nav is-open" : "parity-public-nav"} id={menuId} aria-label="Public navigation">
      <NavLink to="/#how" onClick={closeMenu}>{t.navHow}</NavLink><NavLink to="/#categories" onClick={closeMenu}>{t.navCategories}</NavLink><NavLink to="/about" onClick={closeMenu}>{t.about}</NavLink>
    </nav>
    <button ref={menuToggleRef} type="button" className="parity-menu-toggle" aria-controls={menuId} aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}><span aria-hidden="true">{menuOpen ? "×" : "☰"}</span><span className="visually-hidden">{menuOpen ? "Close navigation" : "Open navigation"}</span></button>
    <button type="button" className="parity-lang" aria-label={locale === "en" ? "Switch interface to Hindi" : "Switch interface to English"} onClick={() => setLocale(locale === "en" ? "hi" : "en")}>{locale === "en" ? "हिं" : "EN"}</button><NavLink className="parity-btn parity-teal" to="/login">{t.navOpenApp}</NavLink>
  </div></header>;
}

export function AppShell({ children }: { children: ReactNode }) {
  const { locale, t } = useI18n();
  return <div className="public-shell" lang={locale}><a className="skip-link" href="#main-content">Skip to content</a><Header />{children}<footer className="parity-footer"><div className="parity-container"><Brand /><p>{t.footerNote}</p><nav aria-label="Footer navigation"><NavLink to="/about">About</NavLink><NavLink to="/login">Citizen sign in</NavLink></nav><small>© {new Date().getFullYear()} Jan Setu</small></div></footer></div>;
}

export function LoadingState() { const { t } = useI18n(); return <main className="state-page state-page--loading" aria-busy="true"><span className="state-page__mark" aria-hidden="true"><i /></span><p>{t.loading}</p></main>; }
export function ErrorState() { const { t } = useI18n(); return <main className="state-page"><span className="state-page__mark" aria-hidden="true">!</span><h1>{t.errorTitle}</h1><p>{t.errorBody}</p></main>; }
