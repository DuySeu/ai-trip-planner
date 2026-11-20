import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { HotelCard, SuggestionCard } from "../api/api.types.ts";
import { ApiError } from "../api/client.ts";
import { conversationKeys, sendMessage } from "../api/conversations.ts";
import { parseSse } from "../api/parseSse.ts";
import { tripKeys } from "../api/trips.ts";

export type ChatState =
  | { kind: "idle"; hasUpdatedPlan: boolean }
  | {
      kind: "streaming";
      prompt: string;
      text: string;
      cards: SuggestionCard[] | null;
      hotels: HotelCard[] | null;
      hasUpdatedPlan: boolean;
      hasTripForm: boolean;
    }
  | { kind: "error"; code: string; draft: string };

interface Options {
  tripId: string | null;
  planRevision: number | null;
  ensureConversation(): Promise<string>;
}

// Send chat messages and follow the streamed reply; shared by the trip page and the chat page
export function useChatStream(conversationId: string | null, { tripId, planRevision, ensureConversation }: Options) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ChatState>({ kind: "idle", hasUpdatedPlan: false });
  const controllerRef = useRef<AbortController | null>(null);

  // Stop the running reply, if any
  const abort = () => controllerRef.current?.abort();

  // Send one message; resolves true when the reply finished without an error
  const send = async (content: string): Promise<boolean> => {
    abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const { signal } = controller;
    const update = (next: ChatState | ((prev: ChatState) => ChatState)) => {
      if (!signal.aborted) setState(next);
    };
    const refreshTrip = () => (tripId ? queryClient.invalidateQueries({ queryKey: tripKeys.detail(tripId) }) : undefined);

    update({ kind: "streaming", prompt: content, text: "", cards: null, hotels: null, hasUpdatedPlan: false, hasTripForm: false });
    try {
      const id = conversationId ?? (await ensureConversation());
      const body = await sendMessage(id, { content, trip_id: tripId, plan_revision: tripId ? planRevision : null }, signal);

      let failure: { code: string } | null = null;
      for await (const event of parseSse(body, signal)) {
        if (event.type === "token") {
          update((prev) => (prev.kind === "streaming" ? { ...prev, text: prev.text + event.data.text } : prev));
        } else if (event.type === "plan") {
          refreshTrip();
          update((prev) => (prev.kind === "streaming" ? { ...prev, hasUpdatedPlan: true } : prev));
        } else if (event.type === "suggestions") {
          update((prev) => (prev.kind === "streaming" ? { ...prev, cards: event.data.cards } : prev));
        } else if (event.type === "hotels") {
          update((prev) => (prev.kind === "streaming" ? { ...prev, hotels: event.data.cards } : prev));
        } else if (event.type === "trip_form") {
          // The form itself arrives with the saved messages, after done
          update((prev) => (prev.kind === "streaming" ? { ...prev, hasTripForm: true } : prev));
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
      if (code === "conflict") await refreshTrip();
      update({ kind: "error", code, draft: content });
      return false;
    }
  };

  // Abort a running reply when the page goes away
  useEffect(() => () => controllerRef.current?.abort(), []);

  return { state, send, abort };
}
