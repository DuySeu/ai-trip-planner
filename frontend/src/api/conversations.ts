import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Conversation, ConversationDetail, RequestDraft } from "./api.types.ts";
import { apiRequest, readEnvelope, send } from "./client.ts";

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

// POST /conversations - start a conversation, optionally carrying the form's fields as a draft
export async function createConversation(body: { user_id: string; draft: RequestDraft | null }): Promise<Conversation> {
  return (await apiRequest<Conversation>("/conversations", { method: "POST", body: JSON.stringify(body) })).data;
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

// POST /conversations/{id}/messages - the reply body as an SSE stream; errors before streaming throw ApiError
export async function sendMessage(
  conversationId: string,
  body: { content: string; trip_id: string | null; plan_revision: number | null },
  signal: AbortSignal,
): Promise<ReadableStream<Uint8Array>> {
  const response = await send(`/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok || response.body === null) {
    await readEnvelope(response);
    throw new Error("The reply has no body");
  }
  return response.body;
}
