import { Gauge, Languages, LogOut, Moon, Settings, Sun } from "lucide-react";
import { useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON } from "../styles/recipes.ts";
import { applyTheme, initialTheme, type Theme } from "../theme/theme.ts";
import { MENU_ITEM, useAnchoredMenu } from "./useAnchoredMenu.ts";

interface Props {
  // After following a link in the menu (closes the mobile drawer)
  onNavigate(): void;
  onSwitchName(): void;
}

// The gear at the right of the sidebar footer: a menu with the dashboard, the language, the theme and
// switch name. Language and theme keep the menu open so the visitor sees the change.
export function SettingsMenu({ onNavigate, onSwitchName }: Props) {
  const t = useT();
  const { lang, setLang } = useLanguage();
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const { isOpen, setIsOpen, position, triggerRef, menuRef } = useAnchoredMenu();
  const other = lang === "en" ? "vi" : "en";

  // Flip the theme and keep the explicit choice
  const handleThemeToggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`${BUTTON.icon} ${isOpen ? "bg-accent" : ""}`}
        aria-label={t("nav.settings")}
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
      >
        <Settings size={20} strokeWidth={1.75} aria-hidden="true" />
      </button>
      {isOpen &&
        createPortal(
          <div
            ref={menuRef}
            className={`fixed z-50 flex origin-bottom-left animate-pop-in flex-col rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-raised ${position ? "" : "invisible"}`}
            style={position ?? undefined}
          >
            <Link
              to="/dashboard"
              className={`${MENU_ITEM} text-foreground no-underline`}
              onClick={() => {
                setIsOpen(false);
                onNavigate();
              }}
            >
              <Gauge size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("nav.dashboard")}
            </Link>
            <button type="button" className={`${MENU_ITEM} text-foreground`} lang={other} onClick={() => setLang(other)}>
              <Languages size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("nav.language")}
            </button>
            <button type="button" className={`${MENU_ITEM} text-foreground`} onClick={handleThemeToggle}>
              {theme === "dark" ? (
                <Sun size={16} strokeWidth={1.75} aria-hidden="true" />
              ) : (
                <Moon size={16} strokeWidth={1.75} aria-hidden="true" />
              )}
              {theme === "dark" ? t("nav.light") : t("nav.dark")}
            </button>
            <button
              type="button"
              className={`${MENU_ITEM} text-foreground`}
              onClick={() => {
                setIsOpen(false);
                onSwitchName();
              }}
            >
              <LogOut size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("nav.switchName")}
            </button>
          </div>,
          document.body,
        )}
    </>
  );
}
