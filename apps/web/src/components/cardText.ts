/** Wording helpers for the complaint card. Kept apart from the component so they are easy to test. */

const letters = (text: string) => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");

/**
 * The card's title: the citizen's own words, unless they only repeat the category
 * ("pothole") or are too short to say anything, then "<category> near <area>".
 */
export function cardTitle(
  description: string | null | undefined,
  categoryCode: string,
  categoryName: string,
  area: string | null | undefined,
  fallback: (area: string, category: string) => string,
): string {
  const text = (description ?? "").trim();
  const same = new Set([letters(categoryCode), letters(categoryName)]);
  if (text.length >= 4 && !same.has(letters(text))) return text;
  return area ? fallback(area, categoryName) : categoryName;
}

/** `NS-99D08CD3680C47879D…` becomes `NS-99D08CD3`; the full value stays in a tooltip. */
export function shortReference(reference: string | null | undefined): string {
  if (!reference) return "";
  const match = /^([A-Z]+-)([0-9A-Za-z]+)$/.exec(reference);
  return match && match[2].length > 8 ? match[1] + match[2].slice(0, 8) : reference;
}

/** "today", "yesterday", "3 days ago"; older than 30 days falls back to the plain date. */
export function relativeDay(iso: string, locale?: string, now: Date = new Date()): string {
  const then = new Date(iso);
  const days = Math.round((startOfDay(now) - startOfDay(then)) / 86400000);
  if (days < 0 || days > 30) return then.toLocaleDateString(locale);
  return new Intl.RelativeTimeFormat(locale ?? "en", { numeric: "auto" }).format(-days, "day");
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}
