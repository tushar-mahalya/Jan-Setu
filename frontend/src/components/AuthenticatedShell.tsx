import { type ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { apiPostEmpty } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { useI18n } from "../i18n/I18nContext";
import LanguagePicker from "../i18n/LanguagePicker";

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
  const { bcp47, t } = useI18n();
  const logout = async () => {
    try {
      await apiPostEmpty("/auth/logout");
    } finally {
      auth.logout();
      navigate("/login", { replace: true });
    }
  };

  return <div className="authenticated-shell" lang={bcp47}>
    <a className="skip-link" href="#app-content">{t.skipToContent}</a>
    <aside className="app-sidebar">
      <NavLink className="app-brand" to="/dashboard"><img src="/jan-setu-logo-dark.svg" alt="" aria-hidden="true" />{t.brand}</NavLink>
      <p className="app-sidebar__descriptor">{t.shellDescriptor}</p>
      <nav className="app-nav" aria-label={t.appNavAria}>
        <NavLink to="/dashboard"><NavIcon name="dashboard" /><span>{t.navDashboard}</span></NavLink>
        <NavLink to="/complaints/new"><NavIcon name="new" /><span>{t.navNewComplaint}</span></NavLink>
        <NavLink to="/about"><NavIcon name="about" /><span>{t.navAboutApp}</span></NavLink>
      </nav>
      <div className="app-sidebar__footer">
        <LanguagePicker variant="inverse" />
        <button type="button" className="app-logout" onClick={logout}><NavIcon name="logout" /><span>{t.logout}</span></button>
      </div>
    </aside>
    <header className="app-mobilebar">
      <NavLink className="app-brand" to="/dashboard"><img src="/jan-setu-logo-dark.svg" alt="" aria-hidden="true" />{t.brand}</NavLink>
      <div className="app-language--mobile">
        <LanguagePicker variant="inverse" />
      </div>
    </header>
    <main className="app-content" id="app-content">{children}</main>
    <nav className="app-mobile-nav" aria-label={t.appNavAria}>
      <NavLink to="/dashboard"><NavIcon name="dashboard" /><span>{t.navHome}</span></NavLink>
      <NavLink className="app-mobile-nav__primary" to="/complaints/new"><NavIcon name="new" /><span>{t.navNew}</span></NavLink>
      <NavLink to="/about"><NavIcon name="about" /><span>{t.about}</span></NavLink>
      <button type="button" onClick={logout}><NavIcon name="logout" /><span>{t.logout}</span></button>
    </nav>
  </div>;
}
