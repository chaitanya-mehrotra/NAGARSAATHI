import { useCallback, useSyncExternalStore } from "react";
import { en, kn, StringKey } from "./strings";

export type Lang = "en" | "kn";
export type { StringKey };

const STORAGE_KEY = "nagarsaathi.lang";
const dictionaries: Record<Lang, Record<StringKey, string>> = { en, kn };

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "kn") return saved;
  } catch {
    // Storage blocked: fall back to English.
  }
  return "en";
}

// A tiny store rather than a context, so any component (and tests without a provider) can read it.
let current: Lang = initialLang();
const listeners = new Set<() => void>();
if (typeof document !== "undefined") document.documentElement.lang = current;

export function setLang(lang: Lang) {
  if (lang === current) return;
  current = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Not persisted; the choice still applies for this visit.
  }
  document.documentElement.lang = lang;
  listeners.forEach((notify) => notify());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Look up a string, filling `{name}` placeholders. Unknown keys fall back to English, then the key. */
export function translate(lang: Lang, key: StringKey | (string & {}), vars?: Record<string, string | number>) {
  const text = dictionaries[lang][key as StringKey] ?? en[key as StringKey] ?? key;
  return vars ? text.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m)) : text;
}

export function useI18n() {
  const lang = useSyncExternalStore(subscribe, () => current, () => current);
  const t = useCallback(
    (key: StringKey | (string & {}), vars?: Record<string, string | number>) => translate(lang, key, vars),
    [lang],
  );
  // Dates follow the chosen language; English keeps the browser's own locale as before.
  const locale = lang === "kn" ? "kn-IN" : undefined;
  return { lang, setLang, t, locale };
}
