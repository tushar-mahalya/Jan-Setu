import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Locale = "en" | "hi";
type Messages = Record<string, string>;

const categories = [
  ["roads", "Roads & Potholes", "Public Works Department"],
  ["lighting", "Street Lighting", "Electrical Department"],
  ["sanitation", "Sanitation & Public Toilets", "Sanitation Department"],
  ["drainage", "Drainage & Sewerage", "Public Works Department"],
  ["water", "Water Supply", "Water Works Department"],
  ["garbage", "Garbage Collection", "Sanitation Department"],
  ["animals", "Stray Animal Cruelty & Care", "Animal Welfare Department"],
  ["parks", "Parks & Public Spaces", "Parks & Gardens Department"],
  ["encroachment", "Encroachment", "Town Planning Department"],
  ["electricity", "Electricity", "Electrical Department"],
  ["other", "Other", "General Grievance Cell"],
] as const;

const en: Messages = {
  brand: "Jan Setu",
  tagline: "Citizen grievance portal",
  home: "Home",
  about: "About",
  signIn: "Sign in",
  navHow: "How it works",
  navCategories: "Categories",
  navOpenApp: "Open the app",
  heroTitle: "Report an issue. Watch the city respond.",
  heroSub: "File a complaint here on the web, or send it straight from WhatsApp — same location pin, voice note and photo, same tracked ticket. Jan Setu classifies it and routes it to the right department automatically.",
  ctaPrimary: "Get started",
  ctaSecondary: "See how it works",
  chip1: "11 complaint categories",
  chip2: "8 municipal departments",
  chip3: "Works on web or WhatsApp",
  chip4: "English & Hindi",
  howTitle: "From WhatsApp message to a tracked ticket",
  step1H: "Report on WhatsApp",
  step1B: "Share your location, type or record your concern, and add a photo if it helps.",
  step2H: "AI classifies it",
  step2B: "Speech-to-text and language models match the issue to the right category and department.",
  step3H: "Duplicates are grouped",
  step3B: "Nearby reports about the same issue are grouped, while priority cases skip grouping.",
  step4H: "Sent to the department",
  step4B: "A complete ticket reaches the responsible department and you receive status updates.",
  chatLabel: "Example WhatsApp conversation",
  justNow: "Just now",
  chatGreet: "Also open on WhatsApp — same report, same ticket.",
  chatLocation: "Location shared",
  chatVoice: "Voice note · 0:08",
  chatFiling: "Got it — filing your complaint…",
  chatRegistered: "Registered",
  categoriesTitle: "11 categories, routed to 8 departments",
  categoriesIntro: "Every category maps to a real municipal department — no report goes to a generic inbox.",
  priorityBadge: "Priority — skips grouping",
  featuresTitle: "Built for citizens, accessible however you prefer",
  feature1H: "One phone number, no password",
  feature1B: "Sign in by confirming a one-time code sent to your phone. Nothing to remember.",
  feature2H: "Every channel, the same capability",
  feature2B: "Location, voice notes, photos and text work identically here and on WhatsApp.",
  feature3H: "Track every step",
  feature3B: "A live status timeline keeps every ticket visible from processing to dispatch.",
  ctaTitle: "Ready to report an issue?",
  ctaSub: "It takes less than a minute — on the web or on WhatsApp.",
  ctaButton: "Open Jan Setu",
  footerNote: "A citizen-first grievance pipeline for Indian municipalities.",
  aboutTitle: "File a complaint over WhatsApp. Track it here.",
  aboutIntro: "Jan Setu turns a WhatsApp message into a tracked municipal complaint — no app install, no queue at a government office.",
  privacyTitle: "Verified by WhatsApp, not a password",
  privacyBody: "Signing in sends a one-time code you confirm from your own WhatsApp number — nothing to remember, nothing stored but your phone number and reports.",
  loading: "Loading Jan Setu…",
  errorTitle: "We hit a small roadblock",
  errorBody: "This page could not load.",
  retry: "Try again",
};

for (const [key, label, department] of categories) {
  en[`${key}Label`] = label;
  en[`${key}Dept`] = department;
}

const hi: Messages = {
  ...en,
  brand: "जन सेतु",
  tagline: "नागरिक शिकायत पोर्टल",
  home: "होम",
  about: "जानकारी",
  signIn: "साइन इन",
  navHow: "कैसे काम करता है",
  navCategories: "श्रेणियाँ",
  navOpenApp: "ऐप खोलें",
  heroTitle: "समस्या दर्ज करें। शहर को जवाब देते देखें।",
  heroSub: "वेब पर शिकायत दर्ज करें या WhatsApp से भेजें — वही लोकेशन पिन, वॉइस नोट, फोटो और ट्रैक किया गया टिकट।",
  ctaPrimary: "शुरू करें",
  ctaSecondary: "कैसे काम करता है",
  howTitle: "WhatsApp संदेश से ट्रैक किए गए टिकट तक",
  step1H: "WhatsApp पर रिपोर्ट करें",
  step2H: "AI वर्गीकृत करता है",
  step3H: "मिलती-जुलती रिपोर्ट जोड़ी जाती हैं",
  step4H: "विभाग को भेजा जाता है",
  categoriesTitle: "11 श्रेणियाँ, 8 विभागों तक",
  ctaTitle: "समस्या दर्ज करने के लिए तैयार हैं?",
  ctaButton: "जन सेतु खोलें",
  footerNote: "भारतीय नगरपालिकाओं के लिए नागरिक-प्रथम शिकायत प्रणाली।",
  aboutTitle: "WhatsApp पर शिकायत दर्ज करें। यहाँ ट्रैक करें।",
  privacyTitle: "WhatsApp से सत्यापन, पासवर्ड से नहीं",
  loading: "जन सेतु लोड हो रहा है…",
  errorTitle: "एक छोटी अड़चन आई",
  errorBody: "यह पेज लोड नहीं हो सका।",
  retry: "फिर कोशिश करें",
};

const I18nContext = createContext<{
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Messages;
} | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    const saved = window.localStorage.getItem("jan-setu-locale");
    return saved === "hi" ? "hi" : "en";
  });

  useEffect(() => {
    window.localStorage.setItem("jan-setu-locale", locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(() => ({ locale, setLocale, t: locale === "en" ? en : hi }), [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used within I18nProvider");
  return value;
}
