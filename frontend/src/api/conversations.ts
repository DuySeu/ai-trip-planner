import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Conversation, ConversationDetail, FlightDates, HotelDates, Message, RequestDraft } from "./api.types.ts";
import { ApiError, apiRequest, readEnvelope, send } from "./client.ts";

const LIST_LIMIT = 50;

export const conversationKeys = {
  all: ["conversations"] as const,
  list: (userId: string) => ["conversations", "list", userId] as const,
  detail: (conversationId: string) => ["conversations", "detail", conversationId] as const,
};

// GET /users/{id}/conversations - the visitor's conversations, newest first
export function useUserConversations(userId: string) {
  return useQuery({
    queryKey: conversationKeys.list(userId),
    queryFn: async ({ signal }) =>
      (await apiRequest<Conversation[]>(`/users/${userId}/conversations?limit=${LIST_LIMIT}`, { signal })).data,
  });
}

// POST /conversations - start a conversation, optionally carrying the form's fields as a draft and a picked model
export async function createConversation(body: {
  user_id: string;
  draft: RequestDraft | null;
  chat_model?: string | null;
}): Promise<Conversation> {
  return (await apiRequest<Conversation>("/conversations", { method: "POST", body: JSON.stringify(body) })).data;
}

// PATCH /conversations/{id} - pick the chat model (null is "Auto"), then update every cached copy
export function useSetChatModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conversationId, chatModel }: { conversationId: string; chatModel: string | null }) =>
      (
        await apiRequest<Conversation>(`/conversations/${conversationId}`, {
          method: "PATCH",
          body: JSON.stringify({ chat_model: chatModel }),
        })
      ).data,
    onSuccess: (updated) => {
      queryClient.setQueriesData<Conversation[]>({ queryKey: [...conversationKeys.all, "list"] }, (rows) =>
        rows?.map((row) => (row.id === updated.id ? updated : row)),
      );
      queryClient.setQueryData<ConversationDetail>(conversationKeys.detail(updated.id), (detail) =>
        detail ? { ...detail, chat_model: updated.chat_model } : detail,
      );
    },
    // A 422 means the model is no longer offered (the server's list changed): reload the list
    onError: (error) => {
      if (error instanceof ApiError && error.status === 422) void queryClient.invalidateQueries({ queryKey: ["models"] });
    },
  });
}

// PATCH /conversations/{id} - rename, then update every cached copy; the list order does not change
export function useRenameConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conversationId, title }: { conversationId: string; title: string }) =>
      (
        await apiRequest<Conversation>(`/conversations/${conversationId}`, {
          method: "PATCH",
          body: JSON.stringify({ title }),
        })
      ).data,
    onSuccess: (updated) => {
      queryClient.setQueriesData<Conversation[]>({ queryKey: [...conversationKeys.all, "list"] }, (rows) =>
        rows?.map((row) => (row.id === updated.id ? updated : row)),
      );
      queryClient.setQueryData<ConversationDetail>(conversationKeys.detail(updated.id), (detail) =>
        detail ? { ...detail, title: updated.title } : detail,
      );
    },
  });
}

// PATCH /conversations/{id}/messages/{id} - cancel an open trip form, then reload the thread
export function useCloseTripForm() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conversationId, messageId }: { conversationId: string; messageId: string }) =>
      (
        await apiRequest<Message>(`/conversations/${conversationId}/messages/${messageId}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "canceled" }),
        })
      ).data,
    onSuccess: (_message, { conversationId }) =>
      queryClient.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) }),
  });
}

export interface AnswerBody {
  step: number;
  choice: string | string[] | null;
  answers: Record<string, unknown>;
}

// PATCH /conversations/{id}/messages/{id} - save one step of a questionnaire card, then swap the cached message
export function useAnswerQuestion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conversationId, messageId, body }: { conversationId: string; messageId: string; body: AnswerBody }) =>
      (
        await apiRequest<Message>(`/conversations/${conversationId}/messages/${messageId}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        })
      ).data,
    onSuccess: (updated, { conversationId }) =>
      queryClient.setQueryData<ConversationDetail>(conversationKeys.detail(conversationId), (detail) =>
        detail ? { ...detail, messages: detail.messages.map((m) => (m.id === updated.id ? updated : m)) } : detail,
      ),
    // Closed in another tab: reload the thread so the card shows closed
    onError: (error, { conversationId }) =>
      error instanceof ApiError && error.code === "conflict"
        ? queryClient.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) })
        : undefined,
  });
}

// DELETE /conversations/{id} - then drop it from every cached list
export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (conversationId: string) => {
      await apiRequest<null>(`/conversations/${conversationId}`, { method: "DELETE" });
      return conversationId;
    },
    onSuccess: (conversationId) => {
      queryClient.setQueriesData<Conversation[]>({ queryKey: [...conversationKeys.all, "list"] }, (rows) =>
        rows?.filter((row) => row.id !== conversationId),
      );
      queryClient.removeQueries({ queryKey: conversationKeys.detail(conversationId) });
    },
  });
}

// GET /conversations/{id} - the conversation, its draft and its messages
export function useConversation(conversationId: string | null) {
  return useQuery({
    queryKey: conversationKeys.detail(conversationId ?? ""),
    queryFn: async ({ signal }) => (await apiRequest<ConversationDetail>(`/conversations/${conversationId}`, { signal })).data,
    enabled: conversationId !== null,
  });
}

// POST /chat - the reply body as an SSE stream; errors before streaming throw ApiError
export async function sendMessage(
  conversationId: string,
  body: {
    content: string;
    trip_id: string | null;
    plan_revision: number | null;
    discover_message_id?: string;
    booking_message_id?: string;
    dates?: HotelDates | FlightDates;
    origin?: string;
  },
  signal: AbortSignal,
): Promise<ReadableStream<Uint8Array>> {
  const response = await send("/chat", {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, ...body }),
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || response.body === null) {
    await readEnvelope(response);
    throw new Error("The reply has no body");
  }
  return response.body;
}
