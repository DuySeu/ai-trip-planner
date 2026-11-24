import { Gauge, Lightbulb, Map as MapIcon, UserRound, X } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, useMatch, useNavigate } from "react-router";
import type { Conversation } from "../api/api.types.ts";
import { useDeleteConversation, useRenameConversation, useUserConversations } from "../api/conversations.ts";
import { ConfirmDialog } from "../components/ConfirmDialog.tsx";
import { errorKey } from "../i18n/errorKey.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { clearSession, useSession } from "../session/session.ts";
import { BUTTON, FIELD, FIELD_ERROR, INPUT, LABEL, SKELETON } from "../styles/recipes.ts";
import { ConversationRow } from "./ConversationRow.tsx";
import { Preferences } from "./Preferences.tsx";

const MAX_TITLE = 80;
const ACTIVE = "bg-accent text-accent-foreground";
const NAV_LINK = "flex min-h-9 items-center gap-2 rounded-sm px-3 font-medium no-underline hover:bg-accent";

interface Props {
  onClose(): void;
}

// The left column: Get ideas, My trips, the visitor's conversations, then account and preferences
export function Sidebar({ onClose }: Props) {
  const t = useT();
  const session = useSession();
  const navigate = useNavigate();
  const openChat = useMatch("/chat/:conversationId");
  const conversations = useUserConversations(session?.userId ?? "");
  const deleteConversation = useDeleteConversation();
  const [pendingDelete, setPendingDelete] = useState<Conversation | null>(null);
  const renameConversation = useRenameConversation();
  const [pendingRename, setPendingRename] = useState<Conversation | null>(null);
  const [renameText, setRenameText] = useState("");
  const cleanTitle = renameText.normalize("NFC").trim();

  // Rename after the visitor saves; an unchanged title just closes the dialog
  const handleConfirmRename = () => {
    if (!pendingRename) return;
    if (cleanTitle === pendingRename.title) return setPendingRename(null);
    renameConversation.mutate(
      { conversationId: pendingRename.id, title: cleanTitle },
      { onSuccess: () => setPendingRename(null) },
    );
  };

  // Delete after the visitor confirms; leave the conversation if it is the open one
  const handleConfirmDelete = () => {
    if (!pendingDelete) return;
    const deletedId = pendingDelete.id;
    deleteConversation.mutate(deletedId, {
      onSuccess: () => {
        setPendingDelete(null);
        if (openChat?.params.conversationId === deletedId) navigate("/chat", { replace: true });
      },
    });
  };

  // Forget the name and go back to the name page
  const handleSwitchName = () => {
    clearSession();
    navigate("/start");
  };

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="flex items-center justify-between gap-2 px-2 pt-1">
        <Link to="/" className="inline-flex items-center gap-2 font-bold tracking-tight no-underline" onClick={onClose}>
          <MapIcon size={20} strokeWidth={1.75} aria-hidden="true" className="text-primary" />
          {t("app.name")}
        </Link>
        <button type="button" className={`${BUTTON.icon} lg:hidden`} aria-label={t("common.close")} onClick={onClose}>
          <X size={20} strokeWidth={1.75} />
        </button>
      </div>

      <nav aria-label={t("nav.main")}>
        <ul className="flex flex-col gap-1">
          <li>
            <NavLink to="/chat" end className={`${BUTTON.primary} w-full`} onClick={onClose}>
              <Lightbulb size={20} strokeWidth={1.75} aria-hidden="true" />
              {t("nav.getIdeas")}
            </NavLink>
          </li>
          <li className="mt-2">
            <NavLink to="/" end className={({ isActive }) => `${NAV_LINK} ${isActive ? ACTIVE : ""}`} onClick={onClose}>
              <MapIcon size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("nav.myTrips")}
            </NavLink>
          </li>
          <li>
            <NavLink to="/dashboard" className={({ isActive }) => `${NAV_LINK} ${isActive ? ACTIVE : ""}`} onClick={onClose}>
              <Gauge size={16} strokeWidth={1.75} aria-hidden="true" />
              {t("nav.dashboard")}
            </NavLink>
          </li>
        </ul>
      </nav>

      <section className="flex min-h-0 flex-1 flex-col gap-2 border-t border-border pt-3" aria-labelledby="sidebar-chats">
        <h2 id="sidebar-chats" className="px-3 text-xs font-medium text-muted-foreground">
          {t("home.conversations")}
        </h2>
        <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
          {conversations.isPending ? (
            <div className={`${SKELETON} h-32`} aria-label={t("home.loading")} />
          ) : conversations.isError ? (
            <div className="flex flex-col items-start gap-2 px-3 text-sm text-destructive" role="alert">
              <p>{t(errorKey(conversations.error))}</p>
              <button type="button" className={BUTTON.ghost} onClick={() => conversations.refetch()}>
                {t("common.retry")}
              </button>
            </div>
          ) : conversations.data.length === 0 ? (
            <p className="px-3 text-sm text-muted-foreground">{t("home.emptyChats")}</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {conversations.data.map((conversation) => (
                <ConversationRow
                  key={conversation.id}
                  conversation={conversation}
                  onNavigate={onClose}
                  onRename={(row) => {
                    renameConversation.reset();
                    setRenameText(row.title ?? "");
                    setPendingRename(row);
                  }}
                  onDelete={(row) => {
                    deleteConversation.reset();
                    setPendingDelete(row);
                  }}
                />
              ))}
            </ul>
          )}
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-1 border-t border-border pt-3">
        {session && (
          <details className="relative min-w-0">
            <summary className={`${BUTTON.ghost} max-w-44 list-none [&::-webkit-details-marker]:hidden`}>
              <UserRound size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className="truncate" aria-hidden="true">
                {session.name}
              </span>
              <span className="sr-only">{t("nav.account", { name: session.name })}</span>
            </summary>
            <div className="absolute bottom-[calc(100%+8px)] left-0 z-10 origin-bottom-left animate-pop-in rounded-md border border-border bg-popover p-2 text-popover-foreground shadow-raised">
              <button type="button" className={BUTTON.ghost} onClick={handleSwitchName}>
                {t("nav.switchName")}
              </button>
            </div>
          </details>
        )}
        <Preferences />
      </div>

      <ConfirmDialog
        isOpen={pendingDelete !== null}
        title={t("chat.deleteTitle", { title: pendingDelete?.title ?? t("home.untitledChat") })}
        body={deleteConversation.isError ? t(errorKey(deleteConversation.error)) : t("chat.deleteBody")}
        confirmLabel={t("chat.deleteConfirm")}
        isBusy={deleteConversation.isPending}
        onConfirm={handleConfirmDelete}
        onCancel={() => setPendingDelete(null)}
      />

      <ConfirmDialog
        isOpen={pendingRename !== null}
        title={t("chat.renameTitle")}
        confirmLabel={t("chat.renameConfirm")}
        confirmVariant="primary"
        isBusy={renameConversation.isPending}
        isConfirmDisabled={cleanTitle.length === 0}
        onConfirm={handleConfirmRename}
        onCancel={() => setPendingRename(null)}
      >
        <div className={FIELD}>
          <label htmlFor="rename-conversation" className={LABEL}>
            {t("chat.renameLabel")}
          </label>
          <input
            id="rename-conversation"
            className={INPUT}
            value={renameText}
            placeholder={t("home.untitledChat")}
            maxLength={MAX_TITLE}
            autoFocus
            aria-invalid={renameConversation.isError}
            aria-describedby={renameConversation.isError ? "rename-conversation-error" : undefined}
            onFocus={(event) => event.currentTarget.select()}
            onChange={(event) => setRenameText(event.target.value)}
          />
          {renameConversation.isError && (
            <p id="rename-conversation-error" className={FIELD_ERROR} role="alert">
              {t(errorKey(renameConversation.error))}
            </p>
          )}
        </div>
      </ConfirmDialog>
    </div>
  );
}
