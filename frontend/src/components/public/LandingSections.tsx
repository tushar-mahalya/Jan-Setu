import { Link } from "react-router-dom";
import { useI18n } from "../../i18n/I18nContext";
import { assets } from "../../assets";

const categories = ["roads", "lighting", "sanitation", "drainage", "water", "garbage", "animals", "parks", "encroachment", "electricity", "other"] as const;
const categoryIcons = ["⌁", "◉", "✦", "≈", "◌", "▣", "♡", "♧", "▤", "ϟ", "?"];

function CivicHeroIllustration() {
  const { t } = useI18n();
  return <div className="civic-hero-art">
    <img
      className="civic-hero-art__img"
      src={assets.civicHero}
      srcSet={`${assets.civicHero} 560w, ${assets.civicHero2x} 1120w`}
      sizes="(max-width: 820px) 92vw, 560px"
      width={560}
      height={409}
      alt={t.heroArtAria}
      decoding="async"
    />
    <span className="civic-hero-art__label">{t.heroArtLabel}</span>
  </div>;
}

export function Hero() {
  const { t } = useI18n();
  return <><section className="parity-hero"><div className="parity-container parity-hero-grid"><div><h1>{t.heroTitle}</h1><p className="parity-lead">{t.heroSub}</p><div className="parity-actions"><Link className="parity-btn parity-orange" to="/login">{t.ctaPrimary} →</Link><a className="parity-btn parity-outline" href="#how">{t.ctaSecondary}</a></div><div className="parity-chips"><span>{t.chip1}</span><span>{t.chip2}</span><span>{t.chip3}</span></div></div><CivicHeroIllustration /></div></section><div className="parity-proof"><span>{t.proofLocation}</span><span>{t.proofVerify}</span><span>{t.proofHistory}</span><span>{t.chip4}</span></div></>;
}

export function Process() {
  const { t } = useI18n();
  const steps = [[t.step1H, t.step1B], [t.step2H, t.step2B], [t.step3H, t.step3B], [t.step4H, t.step4B]];
  return <section id="how" className="parity-section"><div className="parity-container"><div className="parity-heading"><h2>{t.howTitle}</h2><p>{t.processSubtitle}</p></div><ol className="parity-workflow">{steps.map(([heading, body], index) => <li key={heading}><i>{index + 1}</i><h3>{heading}</h3><p>{body}</p></li>)}</ol></div></section>;
}

export function Categories() {
  const { t } = useI18n();
  return <section id="categories" className="parity-section parity-soft"><div className="parity-container"><div className="parity-heading"><h2>{t.categoriesTitle}</h2><p>{t.categoriesIntro}</p></div><div className="parity-categories">{categories.map((category, index) => <article key={category}><span aria-hidden="true">{categoryIcons[index]}</span><div><h3>{t[`${category}Label`]}</h3><p>{t[`${category}Dept`]}</p>{category === "animals" && <em>{t.priorityBadge}</em>}</div></article>)}</div></div></section>;
}

export function Features() {
  const { t } = useI18n();
  return <section className="parity-section"><div className="parity-container"><div className="parity-heading"><h2>{t.featuresTitle}</h2></div><div className="parity-features">{[[t.feature1H, t.feature1B, "✓"], [t.feature2H, t.feature2B, "⇄"], [t.feature3H, t.feature3B, "↗"]].map(([heading, body, icon]) => <article key={heading}><span>{icon}</span><h3>{heading}</h3><p>{body}</p></article>)}</div></div></section>;
}

export function CallToAction() {
  const { t } = useI18n();
  return <section className="parity-cta"><div><span className="parity-cta__artifact" aria-hidden="true">⌖</span><h2>{t.ctaTitle}</h2><p>{t.ctaSub}</p><Link className="parity-btn parity-orange" to="/login">{t.ctaButton}</Link></div></section>;
}
