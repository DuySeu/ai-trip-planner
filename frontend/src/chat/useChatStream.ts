import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { FlightDates, HotelDates, MessageMetadata } from "../api/api.types.ts";
import { ApiError } from "../api/client.ts";
import { conversationKeys, sendMessage } from "../api/conversations.ts";
import { useCurrentLocation } from "../api/location.ts";
import { parseSse } from "../api/parseSse.ts";
import { tripKeys } from "../api/trips.ts";

export type ChatState =
  | { kind: "idle"; hasUpdatedPlan: boolean }
  | {
      kind: "streaming";
      prompt: string;
      text: string;
      // The reply's structured part; messageId is set when the message was saved before the event
      metadata: { messageId: string | null; value: MessageMetadata } | null;
      hasUpdatedPlan: boolean;
    }
  | { kind: "error"; code: string; draft: string };

// A message that answers a card skips the router: suggest from a questionnaire, or search with the chosen dates
export type FollowUp =
  | { discover_message_id: string }
  | { booking_message_id: string; dates: HotelDates | FlightDates; origin?: string };

interface Options {
  tripId: string | null;
  planRevision: number | null;
  ensureConversation(): Promise<string>;
}

// Send chat messages and follow the streamed reply; shared by the trip page and the chat page
export function useChatStream(conversationId: string | null, { tripId, planRevision, ensureConversation }: Options) {
  const queryClient = useQueryClient();
  const city = useCurrentLocation().data?.city;
  const [state, setState] = useState<ChatState>({ kind: "idle", hasUpdatedPlan: false });
  const controllerRef = useRef<AbortController | null>(null);

  // Stop the running reply, if any
  const abort = () => controllerRef.current?.abort();

  // Send one message; resolves true when the reply finished without an error
  const send = async (content: string, followUp?: FollowUp): Promise<boolean> => {
    abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const { signal } = controller;
    const update = (next: ChatState | ((prev: ChatState) => ChatState)) => {
      if (!signal.aborted) setState(next);
    };
    const refreshTrip = () => (tripId ? queryClient.invalidateQueries({ queryKey: tripKeys.detail(tripId) }) : undefined);

    update({ kind: "streaming", prompt: content, text: "", metadata: null, hasUpdatedPlan: false });
    let id = conversationId;
    try {
      id ??= await ensureConversation();
      const body = await sendMessage(
        id,
        { content, trip_id: tripId, plan_revision: tripId ? planRevision : null, ...(city ? { default_origin: city } : {}), ...followUp },
        signal,
      );

      let failure: { code: string } | null = null;
      for await (const event of parseSse(body, signal)) {
        if (event.type === "token") {
          update((prev) => (prev.kind === "streaming" ? { ...prev, text: prev.text + event.data.text } : prev));
        } else if (event.type === "plan") {
          refreshTrip();
          update((prev) => (prev.kind === "streaming" ? { ...prev, hasUpdatedPlan: true } : prev));
        } else if (event.type === "metadata") {
          const metadata = { messageId: event.data.message_id, value: event.data.metadata };
          update((prev) => (prev.kind === "streaming" ? { ...prev, metadata } : prev));
        } else if (event.type === "error") {
          failure = { code: event.data.code };
          if (event.data.code === "conflict") refreshTrip();
        }
      }
      if (signal.aborted) return false;

      // Swap the local stream for the saved messages only once they have loaded
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: conversationKeys.detail(id) }),
        queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
        refreshTrip(),
      ]);
      if (failure) {
        update({ kind: "error", code: failure.code, draft: content });
        return false;
      }
      update((prev) => ({ kind: "idle", hasUpdatedPlan: prev.kind === "streaming" && prev.hasUpdatedPlan }));
      return true;
    } catch (err) {
      if (signal.aborted) return false;
      const code = err instanceof ApiError ? err.code : "internal_error";
      // A card pressed here may have been used in another tab: reload the thread so it shows closed
      if (code === "conflict" && followUp && id) await queryClient.invalidateQueries({ queryKey: conversationKeys.detail(id) });
      else if (code === "conflict") await refreshTrip();
      update({ kind: "error", code: code === "conflict" && followUp ? "card_closed" : code, draft: content });
      return false;
    }
  };

  // Abort a running reply when the page goes away
  useEffect(() => () => controllerRef.current?.abort(), []);

  return { state, send, abort };
}
