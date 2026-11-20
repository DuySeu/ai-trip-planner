import { useMutation } from "@tanstack/react-query";
import {
  ArrowUp,
  ArrowUpRight,
  BedDouble,
  ChevronDown,
  CloudSun,
  type LucideIcon,
  Maximize2,
  Mic,
  Minimize2,
  Plane,
  Plus,
  Sparkles,
  TrainFront,
  TriangleExclamationPoint,
  Users,
  Waves,
} from "lucide-react";
import { type ChangeEvent, type KeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import type { Message, Place, RequestDraft, SuggestionCard as Card } from "../api/api.types.ts";
import { apiRequest } from "../api/client.ts";
import { createConversation, useConversation } from "../api/conversations.ts";
import { useChatStream } from "../chat/useChatStream.ts";
import { formatDay } from "../format/dates.ts";
import { codeKey, errorKey } from "../i18n/errorKey.ts";
import { type MessageKey, useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { useSession } from "../session/session.ts";
import { ChatTripCanceled } from "./ChatTripCanceled.tsx";
import { ChatTripForm } from "./ChatTripForm.tsx";
import { ChatTripProgress } from "./ChatTripProgress.tsx";
import { BookingDates } from "./BookingDates.tsx";
import { CardSlider } from "./CardSlider.tsx";
import { DiscoverQuestionnaire } from "./DiscoverQuestionnaire.tsx";
import { FlightCard } from "./FlightCard.tsx";
import { HotelCard } from "./HotelCard.tsx";
import { SuggestionCard } from "./SuggestionCard.tsx";
import { BANNER, BUTTON, TITLE } from "../styles/recipes.ts";

const MAX_MESSAGE = 4000;
const NEAR_BOTTOM_PX = 48;
const SINGLE_LINE_PX = 44;
const PILL_SINGLE = "rounded-full [grid-template-areas:'plus_text_model_mic_send']";
const PILL_STACKED = "rounded-lg [grid-template-areas:'text_text_text_text_expand'_'plus_gap_model_mic_send']";
const SOON = "aria-disabled:cursor-not-allowed aria-disabled:opacity-50 aria-disabled:hover:bg-transparent";
const TRIP_EXAMPLES: { key: MessageKey; icon: LucideIcon }[] = [
  { key: "chat.example1", icon: CloudSun },
  { key: "chat.example2", icon: BedDouble },
  { key: "chat.example3", icon: TrainFront },
];
const DISCOVERY_EXAMPLES: { key: MessageKey; icon: LucideIcon }[] = [
  { key: "chat.discoveryExample1", icon: Waves },
  { key: "chat.discoveryExample2", icon: Users },
  { key: "chat.discoveryExample3", icon: Plane },
];
const EXAMPLE_CARD =
  "group/example flex h-full w-full cursor-pointer items-start gap-3 rounded-md border border-border bg-card p-3 text-left text-sm transition duration-120 ease-standard hover:border-input hover:bg-accent active:scale-[0.99]";
const USER_BUBBLE =
  "max-w-[85%] self-end rounded-md rounded-br-[4px] bg-secondary px-4 py-3 whitespace-pre-wrap wrap-anywhere text-secondary-foreground";
const ASSISTANT = "flex max-w-full flex-col gap-3";
const TEXT = "whitespace-pre-wrap wrap-anywhere";
const PLAN_UPDATED = "text-sm font-medium text-primary";

interface Props {
  header?: ReactNode;
  conversationId: string | null;
  trip: { id: string; planRevision: number } | null;
  disabledReason: MessageKey | null;
  onConversationCreated(conversationId: string): void;
}

// The chat thread and composer; streams replies, applies plan changes and turns cards into a prefilled form
export function ChatPanel({ header, conversationId, trip, disabledReason, onConversationCreated }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const session = useSession();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [isMultiline, setIsMultiline] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);
  const isPinnedRef = useRef(true);
  const conversation = useConversation(conversationId);

  // Create the conversation on the first send when there is none yet
  const ensureConversation = async () => {
    const created = await createConversation({ user_id: session?.userId ?? "", draft: null });
    onConversationCreated(created.id);
    return created.id;
  };
  const chat = useChatStream(conversationId, {
    tripId: trip?.id ?? null,
    planRevision: trip?.planRevision ?? null,
    ensureConversation,
  });

  // Resolve a card's place, then open the form prefilled from this conversation
  const planCard = useMutation({
    mutationFn: async (card: Card) => {
      const places = (await apiRequest<Place[]>(`/places?q=${encodeURIComponent(card.name)}`)).data;
      return places.find((p) => p.country_code === card.country_code) ?? null;
    },
    onSettled: (place) => {
      navigate(`/trips/new${conversationId ? `?conversation=${conversationId}` : ""}`, {
        state: place ? { place } : { missingPlace: true },
      });
    },
  });

  const { state } = chat;
  // While a reply streams, the saved copy of the prompt (from a refetch) would show it twice
  const saved = conversation.data?.messages ?? [];
  const messages =
    state.kind === "streaming" && saved.at(-1)?.role === "user" && saved.at(-1)?.content === state.prompt
      ? saved.slice(0, -1)
      : saved;
  const trimmed = text.trim();
  const isTooLong = trimmed.length > MAX_MESSAGE;
  const isQuota = state.kind === "error" && state.code === "quota_exhausted";
  const isStreaming = state.kind === "streaming";
  const isDisabled = disabledReason !== null || isQuota;
  const canSend = !isDisabled && !isStreaming && trimmed.length > 0 && !isTooLong;
  const isLoading = conversationId !== null && conversation.isPending;
  const isEmpty = messages.length === 0 && !isStreaming && !isLoading;
  const lastAssistant = messages.findLast((m) => m.role === "assistant");

  // Send a message; the composer gets the text back if the send failed
  const submit = async (content: string) => {
    const clean = content.trim();
    if (clean.length === 0 || clean.length > MAX_MESSAGE || isDisabled || isStreaming) return;
    isPinnedRef.current = true;
    setText("");
    setIsMultiline(false);
    setIsExpanded(false);
    const isSent = await chat.send(clean);
    if (!isSent) setText((current) => current || clean);
  };

  // Once the text wraps the pill becomes a box with the text above the buttons; it goes back only when the text is
  // cleared, so the wider text area cannot flip it back and forth
  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.target.value;
    setText(value);
    if (value === "") {
      setIsMultiline(false);
      setIsExpanded(false);
    } else if (event.target.scrollHeight > SINGLE_LINE_PX) {
      setIsMultiline(true);
    }
  };

  // Enter sends, Shift+Enter starts a new line
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) void submit(text);
    }
  };

  // Follow new text unless the visitor scrolled up to read
  const streamedText = state.kind === "streaming" ? state.text : "";
  useEffect(() => {
    const thread = threadRef.current;
    if (thread && isPinnedRef.current) thread.scrollTop = thread.scrollHeight;
  }, [messages.length, streamedText]);

  // A trip form by its status; a form whose draft is not an object shows an error line
  const renderTripForm = (message: Message) => {
    const meta = message.metadata;
    const draft: unknown = meta !== null && "draft" in meta ? meta.draft : null;
    if (meta === null || !("draft" in meta) || typeof draft !== "object" || draft === null || Array.isArray(draft)) {
      return <p className={BANNER.error}>{t("chat.tripForm.broken")}</p>;
    }
    if (meta.status === "open") {
      return conversationId === null ? null : <ChatTripForm conversationId={conversationId} messageId={message.id} draft={draft as RequestDraft} />;
    }
    if (meta.status === "canceled") return <ChatTripCanceled form={draft as RequestDraft} />;
    return meta.trip_id ? (
      <ChatTripProgress tripId={meta.trip_id} />
    ) : (
      <p className="text-sm text-muted-foreground">{t("chat.tripForm.deleted")}</p>
    );
  };

  const renderCards = (cards: Card[]) =>
    cards.length > 0 ? (
      <div className="flex flex-col gap-3">
        {cards.map((card) => (
          <SuggestionCard key={`${card.name}-${card.country_code}`} card={card} isBusy={planCard.isPending} onPlan={planCard.mutate} />
        ))}
      </div>
    ) : null;

  // The structured part of an assistant message, the same for a saved message and the streaming one
  const renderMetadata = (message: Message) => {
    if (message.intent === "create_trip") return renderTripForm(message);
    const meta = message.metadata;
    if (meta === null || !("kind" in meta)) return null;
    if (meta.kind === "suggestions") return renderCards(meta.cards);
    if (meta.kind === "questionnaire") {
      return conversationId === null ? null : (
        <DiscoverQuestionnaire
          conversationId={conversationId}
          messageId={message.id}
          meta={meta}
          isBusy={isStreaming}
          onSuggest={() => void chat.send(t("questionnaire.suggestMessage"), { discover_message_id: message.id })}
        />
      );
    }
    if (meta.status !== "results") {
      return (
        <BookingDates
          messageId={message.id}
          kind={meta.kind}
          isOpen={meta.status === "need_dates"}
          isBusy={isStreaming}
          defaultOrigin={conversation.data?.request_draft?.origin ?? null}
          onSearch={(dates, origin) =>
            void chat.send(t("booking.searchMessage"), { booking_message_id: message.id, dates, ...(origin ? { origin } : {}) })
          }
        />
      );
    }
    if (meta.kind === "hotel") {
      const dates = meta.dates;
      return (
        <CardSlider
          labels={{ title: "hotels.title", previous: "hotels.previous", next: "hotels.next" }}
          subtitle={dates && t("booking.hotelDates", { checkIn: formatDay(dates.check_in, lang), checkOut: formatDay(dates.check_out, lang) })}
          items={meta.cards.map((hotel) => ({ key: `${hotel.source_id}-${hotel.name}`, node: <HotelCard hotel={hotel} /> }))}
        />
      );
    }
    const dates = meta.dates;
    return (
      <CardSlider
        labels={{ title: "flights.title", previous: "flights.previous", next: "flights.next" }}
        subtitle={
          dates &&
          (dates.return
            ? t("booking.flightDatesReturn", { depart: formatDay(dates.depart, lang), return: formatDay(dates.return, lang) })
            : t("booking.flightDates", { depart: formatDay(dates.depart, lang) }))
        }
        items={meta.cards.map((flight) => ({ key: `${flight.source_id}-${flight.carrier}-${flight.route}`, node: <FlightCard flight={flight} /> }))}
      />
    );
  };

  // The streaming reply as a message, so renderMetadata draws it like a saved one
  const streamed: Message | null =
    state.kind === "streaming"
      ? {
          id: state.metadata?.messageId ?? "streaming",
          role: "assistant",
          content: state.text,
          intent: state.metadata && "draft" in state.metadata.value ? "create_trip" : null,
          metadata: state.metadata?.value ?? null,
          created_at: "",
        }
      : null;

  return (
    <div
      ref={threadRef}
      className="flex h-full min-h-0 flex-col overflow-y-auto"
      onScroll={(event) => {
        const el = event.currentTarget;
        isPinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
      }}
    >
      {header && (
        <div className="pointer-events-none sticky top-0 z-10 shrink-0">
          <header className="pointer-events-auto flex min-h-16 items-center bg-background px-4 py-3 sm:px-6 lg:px-8">
            {header}
          </header>
          <div className="h-6 bg-linear-to-b from-background to-transparent" />
        </div>
      )}
      <div
        className="relative flex flex-1 flex-col gap-4 p-4"
        role="log"
        aria-live="polite"
        aria-busy={isStreaming}
        aria-label={t("chat.title")}
      >
        {isLoading && <p className="text-sm text-muted-foreground">{t("chat.loading")}</p>}
        {conversation.isError && <p className={BANNER.error}>{t(errorKey(conversation.error))}</p>}

        {isEmpty && disabledReason === null && (
          <section
            className={`m-auto flex w-full animate-pop-in flex-col items-center gap-6 py-6 text-center ${trip === null ? "max-w-3xl" : "max-w-md"}`}
            aria-labelledby="chat-welcome"
          >
            <span className="flex size-14 items-center justify-center rounded-full bg-accent text-accent-foreground ring-8 ring-accent/40">
              <Sparkles size={28} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <div className="flex flex-col gap-2">
              <h2 id="chat-welcome" className={trip === null ? TITLE.page : TITLE.section}>
                {t(trip === null ? "chat.welcomeDiscoveryTitle" : "chat.welcomeTripTitle")}
              </h2>
              <p className="text-muted-foreground">{t(trip === null ? "chat.discoveryPrompt" : "chat.welcomeTripBody")}</p>
            </div>
            <ul className={`grid w-full gap-3 ${trip === null ? "sm:grid-cols-3" : ""}`}>
              {(trip === null ? DISCOVERY_EXAMPLES : TRIP_EXAMPLES).map(({ key, icon: Icon }) => (
                <li key={key}>
                  <button type="button" className={EXAMPLE_CARD} onClick={() => void submit(t(key))}>
                    <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground transition-colors duration-120 ease-standard group-hover/example:bg-card group-hover/example:text-primary">
                      <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
                    </span>
                    <span className="flex-1 self-center">{t(key)}</span>
                    <ArrowUpRight
                      size={16}
                      strokeWidth={1.75}
                      aria-hidden="true"
                      className="mt-0.5 shrink-0 text-muted-foreground opacity-0 transition-opacity duration-120 ease-standard group-hover/example:opacity-100"
                    />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <ol className="flex flex-col gap-4">
          {messages.map((message) =>
            message.role === "user" ? (
              <li key={message.id} className={USER_BUBBLE}>
                <span className="sr-only">{t("chat.you")}: </span>
                {message.content}
              </li>
            ) : (
              <li key={message.id} className={ASSISTANT}>
                <span className="sr-only">{t("chat.assistant")}: </span>
                {message.content && <p className={TEXT}>{message.content}</p>}
                {renderMetadata(message)}
                {message.id === lastAssistant?.id && state.kind === "idle" && state.hasUpdatedPlan && (
                  <p className={PLAN_UPDATED}>{t("chat.planUpdated")}</p>
                )}
              </li>
            ),
          )}
          {state.kind === "streaming" && streamed !== null && (
            <>
              <li className={USER_BUBBLE}>
                <span className="sr-only">{t("chat.you")}: </span>
                {state.prompt}
              </li>
              <li className={ASSISTANT}>
                <span className="sr-only">{t("chat.assistant")}: </span>
                {(state.text || state.metadata === null) && (
                  <p className={TEXT}>
                    {state.text}
                    <span className="ml-0.5 inline-block h-4 w-2 bg-muted-foreground align-[-2px]" aria-hidden="true" />
                  </p>
                )}
                {renderMetadata(streamed)}
                {state.hasUpdatedPlan && <p className={PLAN_UPDATED}>{t("chat.planUpdated")}</p>}
              </li>
            </>
          )}
        </ol>

        {state.kind === "error" && (
          <p className={isQuota ? BANNER.warning : "rounded-md bg-accent px-4 py-3 text-sm text-accent-foreground"} role="alert">
            {isQuota && <TriangleExclamationPoint size={20} strokeWidth={1.75} aria-hidden="true" />}
            {t(codeKey(state.code))}
          </p>
        )}
      </div>

      <form
        className="pointer-events-none sticky bottom-0 z-10 flex shrink-0 flex-col"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSend) void submit(text);
        }}
      >
        <div className={`relative z-10 bg-linear-to-b from-transparent px-4 pt-6 ${trip === null ? "to-background" : "to-card"}`}>
          <div className={`pointer-events-auto @container ${trip === null ? "mx-auto w-full sm:w-1/2" : ""}`}>
            <div
              className={`grid grid-cols-[auto_1fr_auto_auto_auto] items-center gap-1 bg-muted p-1.5 transition duration-120 ease-standard focus-within:ring-3 focus-within:ring-ring/30 ${isMultiline ? PILL_STACKED : PILL_SINGLE} ${isDisabled ? "opacity-60" : ""}`}
            >
              <button
                type="button"
                className={`${BUTTON.icon} [grid-area:plus] ${SOON}`}
                aria-label={t("chat.attach")}
                aria-disabled="true"
                title={t("chat.comingSoon")}
              >
                <Plus size={20} strokeWidth={1.75} aria-hidden="true" />
              </button>
              <label htmlFor="chat-composer" className="sr-only">
                {t("chat.composer")}
              </label>
              <textarea
                id="chat-composer"
                className={`field-sizing-content min-h-10 min-w-0 resize-none overflow-y-auto bg-transparent py-2 [grid-area:text] placeholder:truncate placeholder:text-muted-foreground focus-visible:outline-none ${isMultiline ? "px-3" : "px-1"} ${isExpanded ? "min-h-[40dvh] max-h-[60dvh]" : "max-h-[200px]"}`}
                rows={1}
                value={text}
                disabled={isDisabled}
                placeholder={t("chat.composerPlaceholder")}
                aria-invalid={isTooLong}
                aria-describedby={isTooLong ? "chat-too-long" : undefined}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
              />
              {isMultiline && (
                <button
                  type="button"
                  className={`${BUTTON.icon} self-start [grid-area:expand]`}
                  aria-label={t(isExpanded ? "chat.collapse" : "chat.expand")}
                  aria-pressed={isExpanded}
                  onClick={() => setIsExpanded((expanded) => !expanded)}
                >
                  {isExpanded ? (
                    <Minimize2 size={16} strokeWidth={1.75} aria-hidden="true" />
                  ) : (
                    <Maximize2 size={16} strokeWidth={1.75} aria-hidden="true" />
                  )}
                </button>
              )}
              <div className="hidden [grid-area:model] @md:block">
                <button
                  type="button"
                  className={`${BUTTON.ghost} text-sm ${SOON}`}
                  aria-label={t("chat.model", { model: t("chat.modelAuto") })}
                  aria-disabled="true"
                  title={t("chat.comingSoon")}
                >
                  {t("chat.modelAuto")}
                  <ChevronDown size={16} strokeWidth={1.75} aria-hidden="true" />
                </button>
              </div>
              <button
                type="button"
                className={`${BUTTON.icon} [grid-area:mic] ${SOON}`}
                aria-label={t("chat.voice")}
                aria-disabled="true"
                title={t("chat.comingSoon")}
              >
                <Mic size={20} strokeWidth={1.75} aria-hidden="true" />
              </button>
              <button type="submit" className={`${BUTTON.iconPrimary} [grid-area:send]`} aria-label={t("chat.send")} disabled={!canSend}>
                <ArrowUp size={20} strokeWidth={1.75} aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
        <div className={`pointer-events-auto flex flex-col gap-1 px-4 pt-2 pb-3 text-center ${trip === null ? "bg-background" : "bg-card"}`}>
          {disabledReason !== null && <p className="text-sm text-muted-foreground">{t(disabledReason)}</p>}
          {isTooLong && (
            <p id="chat-too-long" className="text-sm text-destructive">
              {t("chat.tooLong", { count: trimmed.length })}
            </p>
          )}
          <p className="text-xs text-muted-foreground">{t("chat.disclaimer")}</p>
        </div>
      </form>
    </div>
  );
}
