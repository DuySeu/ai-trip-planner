import { MapPinOff, MessageCircle, X } from "lucide-react";
import { useRef, useState, useSyncExternalStore } from "react";
import { Link, useParams } from "react-router";
import { ACTIVE_STATUSES } from "../api/api.types.ts";
import { ApiError } from "../api/client.ts";
import { useUserConversations } from "../api/conversations.ts";
import { useRetryTrip, useTrip } from "../api/trips.ts";
import { ChatPanel } from "../components/ChatPanel.tsx";
import { ExportButton } from "../components/ExportButton.tsx";
import { JobProgress } from "../components/JobProgress.tsx";
import { PlanView } from "../components/PlanView.tsx";
import { errorKey } from "../i18n/errorKey.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { useSession } from "../session/session.ts";
import { BANNER, BUTTON, EMPTY_STATE, SKELETON, TITLE } from "../styles/recipes.ts";

// Below this width the sidebar leaves no room for the chat column, so the chat moves into a sheet
const SMALL_SCREEN = "(max-width: 1279px)";
const CHAT_HEADER = "flex min-h-14 items-center justify-between gap-2 border-b border-border px-4 py-2";

// One trip: job progress while it runs, the plan once there is one, the chat beside it (or in a sheet on narrower screens)
export function TripPage() {
  const t = useT();
  const session = useSession();
  const { tripId = "" } = useParams();
  const [createdConversationId, setCreatedConversationId] = useState<string | null>(null);
  const sheetRef = useRef<HTMLDialogElement>(null);
  const openerRef = useRef<HTMLButtonElement>(null);
  const isSmall = useSyncExternalStore(subscribeSmallScreen, isSmallScreen, () => false);
  const trip = useTrip(tripId);
  const conversations = useUserConversations(session?.userId ?? "");
  const retry = useRetryTrip();

  if (trip.isPending) return <div className={`${SKELETON} h-[480px]`} aria-label={t("home.loading")} />;

  if (trip.isError) {
    const isMissing = trip.error instanceof ApiError && trip.error.status === 404;
    return (
      <section className={EMPTY_STATE}>
        <MapPinOff size={48} strokeWidth={1.75} aria-hidden="true" />
        <h1 className={TITLE.section}>{isMissing ? t("trip.notFound") : t(errorKey(trip.error))}</h1>
        {isMissing ? (
          <>
            <p className="text-muted-foreground">{t("trip.notFoundBody")}</p>
            <Link to="/" className={BUTTON.primary}>
              {t("notFound.home")}
            </Link>
          </>
        ) : (
          <button type="button" className={BUTTON.primary} onClick={() => trip.refetch()}>
            {t("common.retry")}
          </button>
        )}
      </section>
    );
  }

  const data = trip.data;
  const isActive = (ACTIVE_STATUSES as readonly string[]).includes(data.status);
  const hasPlan = data.plan !== null;
  // The conversation created on the first send, else the visitor's latest one
  const conversationId = createdConversationId ?? conversations.data?.[0]?.id ?? null;

  const chat = (
    <ChatPanel
      conversationId={conversationId}
      trip={{ id: data.id, planRevision: data.plan_revision, origin: data.origin }}
      disabledReason={hasPlan ? null : "chat.disabledFirstPlan"}
      onConversationCreated={setCreatedConversationId}
    />
  );

  return (
    <div className="grid grid-cols-1 items-start gap-8 xl:grid-cols-[minmax(0,1fr)_var(--shell-chat-panel)]">
      <div className="mx-auto flex w-full max-w-(--shell-reading) min-w-0 flex-col gap-6 pb-12 xl:pb-0">
        {(isActive || data.status === "failed") && (
          <JobProgress
            status={data.status}
            failureReason={data.failure_reason}
            hasPlan={hasPlan}
            isRetrying={retry.isPending}
            onRetry={() => retry.mutate(data.id)}
          />
        )}
        {retry.isError && (
          <p className={BANNER.warning} role="alert">
            {t(errorKey(retry.error))}
          </p>
        )}
        {data.plan !== null && (
          <>
            <div className="flex justify-end">
              <ExportButton tripId={data.id} isDisabled={false} />
            </div>
            <PlanView trip={{ ...data, plan: data.plan }} />
          </>
        )}
      </div>

      {isSmall ? (
        <>
          <button
            ref={openerRef}
            type="button"
            className={`${BUTTON.primary} fixed right-4 bottom-4 z-[15] min-h-12 rounded-full shadow-raised`}
            onClick={() => sheetRef.current?.showModal()}
          >
            <MessageCircle size={20} strokeWidth={1.75} aria-hidden="true" />
            {t("chat.open")}
          </button>
          <dialog ref={sheetRef} className="mx-0 mt-auto mb-0 h-[85vh] max-h-[85vh] w-full max-w-full flex-col rounded-t-lg border border-b-0 border-border bg-card p-0 text-card-foreground shadow-raised open:flex open:animate-sheet-in" aria-labelledby="chat-title" onClose={() => openerRef.current?.focus()}>
            <header className={CHAT_HEADER}>
              <h2 id="chat-title" className={TITLE.card}>
                {t("chat.title")}
              </h2>
              <button
                type="button"
                className={BUTTON.icon}
                aria-label={t("common.close")}
                onClick={() => sheetRef.current?.close()}
              >
                <X size={20} strokeWidth={1.75} />
              </button>
            </header>
            {chat}
          </dialog>
        </>
      ) : (
        <aside className="sticky top-8 flex h-[calc(100dvh-4rem)] flex-col overflow-hidden rounded-md border border-border bg-card text-card-foreground shadow-surface" aria-labelledby="chat-title">
          <header className={CHAT_HEADER}>
            <h2 id="chat-title" className={TITLE.card}>
              {t("chat.title")}
            </h2>
          </header>
          {chat}
        </aside>
      )}
    </div>
  );
}

// Whether the chat lives in a bottom sheet (below 1024px)
function isSmallScreen(): boolean {
  return window.matchMedia?.(SMALL_SCREEN).matches ?? false;
}

// Follow the breakpoint
function subscribeSmallScreen(onChange: () => void): () => void {
  const query = window.matchMedia?.(SMALL_SCREEN);
  query?.addEventListener("change", onChange);
  return () => query?.removeEventListener("change", onChange);
}
