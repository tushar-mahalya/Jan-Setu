import { Link } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { Categories, Process } from "../components/public/LandingSections";
import { useI18n } from "../i18n/I18nContext";

export default function About() {
  const { t } = useI18n();
  return <AppShell><main id="main-content">
    <section className="parity-about"><div className="parity-container parity-about__layout"><div><h1>{t.aboutTitle}</h1><p>{t.aboutIntro}</p><Link className="parity-btn parity-orange" to="/login">Open Jan Setu →</Link></div><div className="about-artifact" aria-hidden="true"><span className="about-artifact__phone">•••</span><span className="about-artifact__route" /><span className="about-artifact__ticket">JS<br /><b>✓</b></span></div></div></section>
    <Process />
    <section className="about-principles"><div className="parity-container"><div><h2>Designed around how citizens already communicate</h2><p>No department names to memorize. No password to remember. Describe the issue naturally and Jan Setu structures the report.</p></div><ul><li><span>⌖</span><b>Precise location</b><small>Pin where the issue is happening.</small></li><li><span>▮</span><b>Voice or text</b><small>Explain it in the language and format you prefer.</small></li><li><span>▣</span><b>Optional evidence</b><small>Add a photo when it helps.</small></li><li><span>✓</span><b>Visible progress</b><small>Return to a complete status history.</small></li></ul></div></section>
    <Categories />
    <section className="parity-privacy"><div className="parity-container privacy-layout"><span aria-hidden="true">◉</span><div><h2>{t.privacyTitle}</h2><p>{t.privacyBody}</p></div></div></section>
  </main></AppShell>;
}
