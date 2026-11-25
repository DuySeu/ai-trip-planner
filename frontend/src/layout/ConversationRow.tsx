import { EllipsisVertical, Pencil, Trash } from "lucide-react";
import { createPortal } from "react-dom";
import { NavLink } from "react-router";
import type { Conversation } from "../api/api.types.ts";
import { formatDateTime } from "../format/dates.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON } from "../styles/recipes.ts";
import { MENU_ITEM, useAnchoredMenu } from "./useAnchoredMenu.ts";

const ROW = "flex min-h-11 min-w-0 items-center rounded-sm py-2 pr-11 pl-3 no-underline group-hover:bg-accent";
const ACTIVE = "bg-accent text-accent-foreground";
const SHOW_ON_HOVER = "opacity-0 transition-opacity duration-120 ease-standard group-hover:opacity-100";

interface Props {
  conversation: Conversation;
  onNavigate(): void;
  onRename(conversation: Conversation): void;
  onDelete(conversation: Conversation): void;
}

// One sidebar conversation: a one-line title and a menu with the update time, rename and delete
export function ConversationRow({ conversation, onNavigate, onRename, onDelete }: Props) {
  const t = useT();
  const { isOpen: isMenuOpen, setIsOpen: setIsMenuOpen, position: menuPosition, triggerRef, menuRef } = useAnchoredMenu();
  const title = conversation.title ?? t("home.untitledChat");

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
