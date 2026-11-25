import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { useConversation } from "../api/conversations.ts";
import { ChatPanel } from "../components/ChatPanel.tsx";
import { useT } from "../i18n/LanguageProvider.tsx";
import { HeaderLocation } from "../layout/LocationBanner.tsx";
import { TITLE } from "../styles/recipes.ts";

// A conversation filling the whole area right of the sidebar; /chat starts an empty one, created on the first send
export function ChatPage() {
  const t = useT();
  const navigate = useNavigate();
  const { conversationId = null } = useParams();
  const [panelKey, setPanelKey] = useState(0);
  const [shownId, setShownId] = useState(conversationId);
  const conversation = useConversation(conversationId);

  // Going back to /chat (Get ideas) starts over with an empty thread; going from /chat to the new id keeps the stream
  if (conversationId !== shownId) {
    setShownId(conversationId);
    if (conversationId === null) setPanelKey((key) => key + 1);
  }

  return (
    <div className="flex h-[calc(100dvh-var(--shell-topbar))] min-h-[420px] flex-col lg:h-dvh">
      <div className="min-h-0 flex-1">
        <ChatPanel
          key={panelKey}
          header={
            <>
              <h1 className={`${TITLE.section} min-w-0 wrap-anywhere`}>{conversation.data?.title ?? t("chat.pageTitle")}</h1>
              <HeaderLocation className="ml-auto pl-4" />
            </>
          }
          conversationId={conversationId}
          trip={null}
          disabledReason={null}
          onConversationCreated={(id) => navigate(`/chat/${id}`, { replace: true })}
        />
      </div>
    </div>
  );
}
