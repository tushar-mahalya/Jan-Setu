import { type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { apiPostEmpty } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/I18nContext";

type IconName = "dashboard" | "new" | "about" | "logout";

function NavIcon({ name }: { name: IconName }) {
  const paths: Record<IconName, ReactNode> = {
    dashboard: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
    new: <><path d="M12 5v14M5 12h14" /><circle cx="12" cy="12" r="9" /></>,
    about: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5h.01" /></>,
    logout: <><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 8l4 4-4 4M8 12h10" /></>,
  };
  return <svg className="app-nav__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export default function AuthenticatedShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const auth = useAuth();
  const { locale, setLocale } = useI18n();
  const logout = async () => {
    try {
      await apiPostEmpty("/auth/logout");
    } finally {
      auth.logout();
      navigate("/login", { replace: true });
    }
  };

  return <div className="authenticated-shell" lang={locale}>
    <a className="skip-link" href="#app-content">Skip to content</a>
    <aside className="app-sidebar">
      <NavLink className="app-brand" to="/dashboard"><span />Jan Setu</NavLink>
      <p className="app-sidebar__descriptor">Citizen grievance portal</p>
      <nav className="app-nav" aria-label="Application navigation">
        <NavLink to="/dashboard"><NavIcon name="dashboard" /><span>Dashboard</span></NavLink>
        <NavLink to="/complaints/new"><NavIcon name="new" /><span>New complaint</span></NavLink>
        <NavLink to="/about"><NavIcon name="about" /><span>About Jan Setu</span></NavLink>
      </nav>
      <div className="app-sidebar__footer">
        <div className="app-language" aria-label="Choose interface language">
          <button type="button" aria-pressed={locale === "en"} className={locale === "en" ? "is-active" : ""} onClick={() => setLocale("en")}>EN</button>
          <button type="button" aria-pressed={locale === "hi"} className={locale === "hi" ? "is-active" : ""} onClick={() => setLocale("hi")}>हिं</button>
        </div>
        <button type="button" className="app-logout" onClick={logout}><NavIcon name="logout" /><span>Log out <span lang="hi">/ लॉग आउट</span></span></button>
      </div>
    </aside>
    <header className="app-mobilebar">
      <NavLink className="app-brand" to="/dashboard"><span />Jan Setu</NavLink>
      <div className="app-language app-language--mobile" aria-label="Choose interface language">
        <button type="button" aria-pressed={locale === "en"} className={locale === "en" ? "is-active" : ""} onClick={() => setLocale("en")}>EN</button>
        <button type="button" aria-pressed={locale === "hi"} className={locale === "hi" ? "is-active" : ""} onClick={() => setLocale("hi")}>हिं</button>
      </div>
    </header>
    <main className="app-content" id="app-content">{children}</main>
    <nav className="app-mobile-nav" aria-label="Mobile application navigation">
      <NavLink to="/dashboard"><NavIcon name="dashboard" /><span>Home</span></NavLink>
      <NavLink className="app-mobile-nav__primary" to="/complaints/new"><NavIcon name="new" /><span>New</span></NavLink>
      <NavLink to="/about"><NavIcon name="about" /><span>About</span></NavLink>
      <button type="button" onClick={logout}><NavIcon name="logout" /><span>Log out</span></button>
    </nav>
  </div>;
}
