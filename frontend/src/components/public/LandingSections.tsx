import { Link } from "react-router-dom";
import { useI18n } from "../../i18n/I18nContext";

const categories = ["roads", "lighting", "sanitation", "drainage", "water", "garbage", "animals", "parks", "encroachment", "electricity", "other"];
const categoryIcons = ["⌁", "◉", "✦", "≈", "◌", "▣", "♡", "♧", "▤", "ϟ", "?"];

function CivicHeroIllustration() {
  return <div className="civic-hero-art" aria-label="Example of a citizen sending a location and voice note, then receiving a tracked complaint ticket">
    <svg viewBox="0 0 520 430" role="img" aria-label="Citizen sends a location and voice note and receives a tracked complaint ticket">
      <path className="civic-hero-art__road" d="M24 353c110-56 239-48 472 11" />
      <path className="civic-hero-art__city" d="M42 309V188h85v121M63 214h18v18H63zM94 214h18v18H94zM63 250h18v18H63zM94 250h18v18H94zM400 310V151h76v159M416 178h15v16h-15zM445 178h15v16h-15zM416 214h15v16h-15zM445 214h15v16h-15z" />
      <circle className="civic-hero-art__sun" cx="429" cy="79" r="36" />
      <g className="civic-hero-art__citizen"><circle cx="102" cy="287" r="25" /><path d="M59 386c5-54 21-77 43-77s38 23 43 77" /><path d="m136 335 61 31" /></g>
      <g className="civic-hero-art__phone"><rect x="181" y="74" width="151" height="285" rx="30" /><rect x="196" y="101" width="121" height="211" rx="12" /><path d="M237 335h39" /></g>
      <g className="civic-hero-art__chat"><path d="M215 127h73a10 10 0 0 1 10 10v32a10 10 0 0 1-10 10h-37l-13 13v-13h-23a10 10 0 0 1-10-10v-32a10 10 0 0 1 10-10z" /><circle cx="233" cy="152" r="4" /><circle cx="251" cy="152" r="4" /><circle cx="269" cy="152" r="4" /></g>
      <g className="civic-hero-art__pin"><path d="M255 203c19 0 33 14 33 32 0 23-33 50-33 50s-33-27-33-50c0-18 14-32 33-32z" /><circle cx="255" cy="235" r="10" /></g>
      <g className="civic-hero-art__waves"><path d="M212 292v-18M224 298v-30M236 293v-20M248 301v-36M260 294v-22M272 298v-30M284 291v-16" /></g>
      <path className="civic-hero-art__connection" d="M330 229c46-15 71-3 90 24" />
      <g className="civic-hero-art__ticket"><rect x="354" y="249" width="137" height="82" rx="16" /><path d="M373 272h59M373 289h43" /><circle cx="466" cy="288" r="12" /><path d="m460 288 5 5 8-10" /></g>
    </svg>
    <span className="civic-hero-art__label">WhatsApp → routed ticket → visible updates</span>
  </div>;
}

export function Hero() {
  const { t } = useI18n();
  return <><section className="parity-hero"><div className="parity-container parity-hero-grid"><div><h1>{t.heroTitle}</h1><p className="parity-lead">{t.heroSub}</p><div className="parity-actions"><Link className="parity-btn parity-orange" to="/login">{t.ctaPrimary} →</Link><a className="parity-btn parity-outline" href="#how">{t.ctaSecondary}</a></div><div className="parity-chips"><span>{t.chip1}</span><span>{t.chip2}</span><span>{t.chip3}</span></div></div><CivicHeroIllustration /></div></section><div className="parity-proof"><span>Location, voice, text & photo</span><span>WhatsApp verification</span><span>Tracked complaint history</span><span>{t.chip4}</span></div></>;
}

export function Process() {
  const { t } = useI18n();
  const steps = [[t.step1H, t.step1B], [t.step2H, t.step2B], [t.step3H, t.step3B], [t.step4H, t.step4B]];
  return <section id="how" className="parity-section"><div className="parity-container"><div className="parity-heading"><h2>{t.howTitle}</h2><p>Four visible steps. No unexplained municipal process.</p></div><ol className="parity-workflow">{steps.map(([heading, body], index) => <li key={heading}><i>{index + 1}</i><h3>{heading}</h3><p>{body}</p></li>)}</ol></div></section>;
}

export function Categories() {
  const { t } = useI18n();
  return <section id="categories" className="parity-section parity-soft"><div className="parity-container"><div className="parity-heading"><h2>{t.categoriesTitle}</h2><p>{t.categoriesIntro}</p></div><div className="parity-categories">{categories.map((category, index) => <article key={category}><span aria-hidden="true">{categoryIcons[index]}</span><div><h3>{t[`${category}Label`]}</h3><p>{t[`${category}Dept`]}</p>{category === "animals" && <em>{t.priorityBadge}</em>}</div></article>)}</div></div></section>;
}

export function Features() {
  const { t } = useI18n();
  return <section className="parity-section"><div className="parity-container"><div className="parity-heading"><h2>{t.featuresTitle}</h2></div><div className="parity-features">{[[t.feature1H, t.feature1B, "✓"], [t.feature2H, t.feature2B, "EN/हिं"], [t.feature3H, t.feature3B, "↗"]].map(([heading, body, icon]) => <article key={heading}><span>{icon}</span><h3>{heading}</h3><p>{body}</p></article>)}</div></div></section>;
}

export function CallToAction() {
  const { t } = useI18n();
  return <section className="parity-cta"><div><span className="parity-cta__artifact" aria-hidden="true">⌖</span><h2>{t.ctaTitle}</h2><p>{t.ctaSub}</p><Link className="parity-btn parity-orange" to="/login">{t.ctaButton}</Link></div></section>;
}
