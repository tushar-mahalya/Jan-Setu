import { Link } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { Categories, Process } from "../components/public/LandingSections";
import { useI18n } from "../i18n/I18nContext";

export default function About() {
  const { t } = useI18n();
  return <AppShell><main id="main-content">
    <section className="parity-about"><div className="parity-container parity-about__layout"><div><h1>{t.aboutTitle}</h1><p>{t.aboutIntro}</p><Link className="parity-btn parity-orange" to="/login">{t.aboutOpenCta}</Link></div><div className="about-artifact" aria-hidden="true"><span className="about-artifact__phone">•••</span><span className="about-artifact__route" /><span className="about-artifact__ticket">JS<br /><b>✓</b></span></div></div></section>
    <Process />
    <section className="about-principles"><div className="parity-container"><div><h2>{t.aboutPrinciplesTitle}</h2><p>{t.aboutPrinciplesBody}</p></div><ul><li><span>⌖</span><b>{t.aboutP1H}</b><small>{t.aboutP1B}</small></li><li><span>▮</span><b>{t.aboutP2H}</b><small>{t.aboutP2B}</small></li><li><span>▣</span><b>{t.aboutP3H}</b><small>{t.aboutP3B}</small></li><li><span>✓</span><b>{t.aboutP4H}</b><small>{t.aboutP4B}</small></li></ul></div></section>
    <Categories />
    <section className="parity-privacy"><div className="parity-container privacy-layout"><span aria-hidden="true">◉</span><div><h2>{t.privacyTitle}</h2><p>{t.privacyBody}</p></div></div></section>
  </main></AppShell>;
}
