import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { delay, HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl } from "../api/client.ts";
import { DOMESTIC_TRIP_ID, SEED_CONVERSATION_ID } from "../mocks/fixtures.ts";
import { mockDb } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";
import { LanguageProvider } from "../i18n/LanguageProvider.tsx";
import { createQueryClient } from "../queryClient.ts";
import { useChatStream } from "./useChatStream.ts";

// Providers for the hook
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={createQueryClient()}>
      <LanguageProvider initialLang="en">{children}</LanguageProvider>
    </QueryClientProvider>
  );
}

describe("useChatStream", () => {
  it("collects_suggestion_cards_while_streaming_then_goes_idle", async () => {
    const { result } = renderHook(
      () => useChatStream(SEED_CONVERSATION_ID, { tripId: null, planRevision: null, ensureConversation: async () => "x" }),
      { wrapper },
    );
    let isSent = false;
    await act(async () => {
      isSent = await result.current.send("Where should we go?");
    });
    expect(isSent).toBe(true);
    expect(result.current.state).toEqual({ kind: "idle", hasUpdatedPlan: false });
    expect(mockDb.messages.at(-1)?.metadata).toMatchObject({ kind: "suggestions", cards: { length: 3 } });
  });

  it("stale_revision_ends_in_conflict_error_with_the_draft", async () => {
    const revision = mockDb.trips.find((t) => t.id === DOMESTIC_TRIP_ID)?.plan_revision ?? 0;
    mockDb.bumpRevision(DOMESTIC_TRIP_ID);
    const { result } = renderHook(
      () =>
        useChatStream(SEED_CONVERSATION_ID, { tripId: DOMESTIC_TRIP_ID, planRevision: revision, ensureConversation: async () => "x" }),
      { wrapper },
    );
    await act(async () => {
      await result.current.send("Switch to the flight");
    });
    await waitFor(() => expect(result.current.state).toEqual({ kind: "error", code: "conflict", draft: "Switch to the flight" }));
  });

  it("metadata_event_keeps_the_message_id_and_value", async () => {
    // A reply that sends the metadata event and then waits, so the streaming state can be seen
    const meta = { status: "open", draft: { length_days: 3 }, trip_id: null };
    const frames = [`event: metadata\ndata: ${JSON.stringify({ message_id: "m1", metadata: meta })}\n\n`, "event: done\ndata: {}\n\n"];
    server.use(
      http.post(apiUrl("/chat"), () => {
        const encoder = new TextEncoder();
        const body = new ReadableStream<Uint8Array>({
          async start(controller) {
            controller.enqueue(encoder.encode(frames[0]));
            await delay(200);
            controller.enqueue(encoder.encode(frames[1]));
            controller.close();
          },
        });
        return new HttpResponse(body, { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    const { result } = renderHook(
      () => useChatStream(SEED_CONVERSATION_ID, { tripId: null, planRevision: null, ensureConversation: async () => "x" }),
      { wrapper },
    );
    let sent: Promise<boolean> = Promise.resolve(false);
    act(() => {
      sent = result.current.send("tạo plan trip cho tôi");
    });
    await waitFor(() => expect(result.current.state).toMatchObject({ kind: "streaming", metadata: { messageId: "m1", value: meta } }));
    await act(async () => {
      await sent;
    });
    expect(result.current.state).toEqual({ kind: "idle", hasUpdatedPlan: false });
  });

  it("creates_the_conversation_on_first_send", async () => {
    let created = 0;
    const { result } = renderHook(
      () =>
        useChatStream(null, {
          tripId: null,
          planRevision: null,
          ensureConversation: async () => {
            created += 1;
            return SEED_CONVERSATION_ID;
          },
        }),
      { wrapper },
    );
    await act(async () => {
      await result.current.send("hello");
    });
    expect(created).toBe(1);
  });
});
