/** Turn a backend enum key like "insufficient_information" into "Insufficient information". */
export function humanizeKey(key: string | null | undefined): string | null {
  if (!key) return null;
  const text = key.replace(/_/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : null;
}
