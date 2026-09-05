// Single source for every file served out of `public/`.
// Paths are built from Vite's BASE_URL (always ends in "/") so they stay correct
// when the app is served below a prefix via VITE_ASSET_BASE, matching the
// basename already given to BrowserRouter in main.tsx.
const base = import.meta.env.BASE_URL;

export const assets = {
  logo: `${base}jan-setu-logo.svg`,
  logoDark: `${base}jan-setu-logo-dark.svg`,
  civicHero: `${base}civic-hero.webp`,
  civicHero2x: `${base}civic-hero@2x.webp`,
} as const;
