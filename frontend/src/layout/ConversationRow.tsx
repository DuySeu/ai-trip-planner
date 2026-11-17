import { EllipsisVertical, Pencil, Trash } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { NavLink } from "react-router";
import type { Conversation } from "../api/api.types.ts";
import { formatDateTime } from "../format/dates.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON } from "../styles/recipes.ts";

const MENU_GAP_PX = 4;
const VIEWPORT_MARGIN_PX = 8;
const ROW = "flex min-h-11 min-w-0 items-center rounded-sm py-2 pr-11 pl-3 no-underline group-hover:bg-accent";
const ACTIVE = "bg-accent text-accent-foreground";
const SHOW_ON_HOVER = "opacity-0 transition-opacity duration-120 ease-standard group-hover:opacity-100";
const MENU_ITEM =
  "flex min-h-8 w-full cursor-pointer items-center gap-2 rounded-sm px-2 text-left text-sm font-medium whitespace-nowrap hover:bg-accent";

interface Props {
  conversation: Conversation;
  onNavigate(): void;
  onRename(conversation: Conversation): void;
  onDelete(conversation: Conversation): void;
}

// One sidebar conversation: a one-line title and a menu with the update time, rename and delete
export function ConversationRow({ conversation, onNavigate, onRename, onDelete }: Props) {
  const t = useT();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const title = conversation.title ?? t("home.untitledChat");

  // Place the menu right of the button, top edges aligned; flip left or shift up when the viewport has no room
  // (it lives in body, outside the sidebar's scroll clip)
  useLayoutEffect(() => {
    const trigger = triggerRef.current;
    const menu = menuRef.current;
    if (!isMenuOpen || !trigger || !menu) return;
    const anchor = trigger.getBoundingClientRect();
    const right = anchor.right + MENU_GAP_PX;
    const fitsRight = right + menu.offsetWidth <= window.innerWidth - VIEWPORT_MARGIN_PX;
    setMenuPosition({
      top: Math.max(VIEWPORT_MARGIN_PX, Math.min(anchor.top, window.innerHeight - VIEWPORT_MARGIN_PX - menu.offsetHeight)),
      left: Math.max(VIEWPORT_MARGIN_PX, fitsRight ? right : anchor.left - MENU_GAP_PX - menu.offsetWidth),
    });
  }, [isMenuOpen]);

  // Close the menu on a press outside it, on Escape, or when the page scrolls or resizes under it
  useEffect(() => {
    if (!isMenuOpen) return;
    const close = () => setIsMenuOpen(false);
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) close();
    };
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [isMenuOpen]);

  return (
    <li className="group relative">
      <NavLink
        to={`/chat/${conversation.id}`}
        className={({ isActive }) => `${ROW} ${isActive ? ACTIVE : ""} ${isMenuOpen ? "bg-accent" : ""}`}
        onClick={onNavigate}
      >
        <span className="truncate font-medium" title={title}>
          {title}
        </span>
      </NavLink>

      <button
        ref={triggerRef}
        type="button"
        className={`${BUTTON.icon} absolute top-1/2 right-1 -translate-y-1/2 ${SHOW_ON_HOVER} focus-visible:opacity-100 pointer-coarse:opacity-100 ${isMenuOpen ? "opacity-100" : ""}`}
        aria-label={t("chat.actions", { title })}
        aria-expanded={isMenuOpen}
        onClick={() => setIsMenuOpen((open) => !open)}
      >
        <EllipsisVertical size={20} strokeWidth={1.75} aria-hidden="true" />
      </button>
      {isMenuOpen &&
        createPortal(
          <div
            ref={menuRef}
            className={`fixed z-50 flex origin-top-left animate-pop-in flex-col rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-raised ${menuPosition ? "" : "invisible"}`}
            style={menuPosition ?? undefined}
          >
            <p className="border-b border-border px-2 pt-1 pb-1.5 text-xs text-muted-foreground tabular-nums">
              {formatDateTime(conversation.updated_at)}
            </p>
            <button
              type="button"
              className={`${MENU_ITEM} mt-1 text-foreground`}
              onClick={() => {
                setIsMenuOpen(false);
                onRename(conversation);
              }}
            >
              <Pencil size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("chat.rename")}
            </button>
            <button
              type="button"
              className={`${MENU_ITEM} text-destructive`}
              onClick={() => {
                setIsMenuOpen(false);
                onDelete(conversation);
              }}
            >
              <Trash size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("chat.delete")}
            </button>
          </div>,
          document.body,
        )}

    </li>
  );
}
