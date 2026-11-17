import { Moon, Sun } from "lucide-react";
import { useState } from "react";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON } from "../styles/recipes.ts";
import { applyTheme, initialTheme, type Theme } from "../theme/theme.ts";

// The language and theme switches
export function Preferences() {
  const t = useT();
  const { lang, setLang } = useLanguage();
  const [theme, setTheme] = useState<Theme>(initialTheme);

  // Flip the theme and keep the explicit choice
  const handleThemeToggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  };

  return (
    <div className="flex items-center gap-1">
      <button type="button" className={BUTTON.ghost} lang={lang === "en" ? "vi" : "en"} onClick={() => setLang(lang === "en" ? "vi" : "en")}>
        {t("nav.language")}
      </button>
      <button
        type="button"
        className={BUTTON.icon}
        aria-label={theme === "dark" ? t("nav.themeLight") : t("nav.themeDark")}
        onClick={handleThemeToggle}
      >
        {theme === "dark" ? <Sun size={20} strokeWidth={1.75} /> : <Moon size={20} strokeWidth={1.75} />}
      </button>
    </div>
  );
}
