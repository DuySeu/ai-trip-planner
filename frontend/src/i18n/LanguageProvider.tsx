import { createContext, type ReactNode, use, useEffect, useState } from "react";
import type { Language } from "../api/api.types.ts";
import en from "./en.json";
import vi from "./vi.json";

const STORAGE_KEY = "tripPlanner.lang";

export type MessageKey = keyof typeof en;
export type Translate = (key: MessageKey, vars?: Record<string, string | number>) => string;

const MESSAGES: Record<Language, Record<MessageKey, string>> = { en, vi };

interface LanguageState {
  lang: Language;
  setLang(lang: Language): void;
}

const LanguageContext = createContext<LanguageState | null>(null);

// Hold the UI language, keep it in storage and mirror it on <html lang>
export function LanguageProvider({ children, initialLang }: { children: ReactNode; initialLang?: Language }) {
  const [lang, setLangState] = useState<Language>(() => initialLang ?? storedLang());

  // Switch and remember the choice
  const setLang = (next: Language) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Storage blocked: the choice lasts for this page only
    }
  };

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  return <LanguageContext value={{ lang, setLang }}>{children}</LanguageContext>;
}

// The UI language and its setter
export function useLanguage(): LanguageState {
  const state = use(LanguageContext);
  if (state === null) throw new Error("useLanguage needs a LanguageProvider");
  return state;
}

// Translate a key into the UI language, filling {name} placeholders
export function useT(): Translate {
  const { lang } = useLanguage();
  return (key, vars) => MESSAGES[lang][key].replace(/\{(\w+)\}/g, (match, name: string) => String(vars?.[name] ?? match));
}

// The stored language, else English
function storedLang(): Language {
  try {
    return localStorage.getItem(STORAGE_KEY) === "vi" ? "vi" : "en";
  } catch {
    return "en";
  }
}
