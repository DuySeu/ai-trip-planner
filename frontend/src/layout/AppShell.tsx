import { Map as MapIcon, Menu } from "lucide-react";
import { type ReactNode, useState } from "react";
import { Link, useMatch } from "react-router";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON } from "../styles/recipes.ts";
import { Preferences } from "./Preferences.tsx";
import { Sidebar } from "./Sidebar.tsx";

const TOPBAR = "sticky top-0 z-20 flex h-(--shell-topbar) items-center gap-2 border-b border-border bg-background px-4";
const LOGO = "inline-flex items-center gap-2 font-bold tracking-tight no-underline";

interface Props {
  children: ReactNode;
  hasNav: boolean;
}

// Sidebar on the left (a drawer below 1024px) and the page on the right, edge to edge for a chat; without nav, a plain top bar
export function AppShell({ children, hasNav }: Props) {
  const t = useT();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const isChat = useMatch("/chat/:conversationId?") !== null;
  const tripMatch = useMatch("/trips/:tripId");
  const isTrip = tripMatch !== null && tripMatch.params.tripId !== "new";

  if (!hasNav) {
    return (
      <div className="flex min-h-dvh flex-col">
        <header className={TOPBAR}>
          <Link to="/" className={LOGO}>
            <MapIcon size={20} strokeWidth={1.75} aria-hidden="true" className="text-primary" />
            {t("app.name")}
          </Link>
          <div className="ml-auto">
            <Preferences />
          </div>
        </header>
        <main className="flex-1 px-4 py-6 sm:px-6 sm:py-8">{children}</main>
      </div>
    );
  }

  return (
    <div className="flex min-h-dvh">
      {isMenuOpen && (
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-foreground/40 lg:hidden"
          onClick={() => setIsMenuOpen(false)}
        />
      )}
      <aside
        id="sidebar"
        className={`fixed inset-y-0 left-0 z-40 w-72 border-r border-border bg-card lg:sticky lg:top-0 lg:z-auto lg:block lg:h-dvh lg:shrink-0 lg:animate-none ${
          isMenuOpen ? "block animate-drawer-in" : "hidden"
        }`}
      >
        <Sidebar onClose={() => setIsMenuOpen(false)} />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className={`${TOPBAR} lg:hidden`}>
          <button
            type="button"
            className={BUTTON.icon}
            aria-expanded={isMenuOpen}
            aria-controls="sidebar"
            aria-label={t("nav.menu")}
            onClick={() => setIsMenuOpen(true)}
          >
            <Menu size={20} strokeWidth={1.75} />
          </button>
          <Link to="/" className={LOGO}>
            <MapIcon size={20} strokeWidth={1.75} aria-hidden="true" className="text-primary" />
            {t("app.name")}
          </Link>
        </header>
        <main
          className={
            isChat
              ? "min-w-0 flex-1"
              : `mx-auto w-full max-w-(--shell-content) flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8 ${isTrip ? "xl:max-w-(--shell-trip)" : ""}`
          }
        >
          {children}
        </main>
      </div>
    </div>
  );
}
