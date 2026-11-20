import { useQueryClient } from "@tanstack/react-query";
import type { Message } from "../api/api.types.ts";
import { ApiError } from "../api/client.ts";
import { conversationKeys, parseTripForm, useCloseTripForm } from "../api/conversations.ts";
import { useCreateTrip } from "../api/trips.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { useSession } from "../session/session.ts";
import { TripForm } from "./TripForm.tsx";
import { fromDraft, toCreateTripBody, type TripFormValues } from "./validateTripForm.ts";

interface Props {
  conversationId: string;
  message: Message;
}

// An open trip form in the thread, prefilled from the chat; creating or canceling it closes the message in place
export function ChatTripForm({ conversationId, message }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const session = useSession();
  const queryClient = useQueryClient();
  const createTrip = useCreateTrip();
  const closeForm = useCloseTripForm();

  // Create the trip from this form; the reloaded message then shows the progress
  const handleSubmit = (values: TripFormValues) => {
    if (!session) return;
    createTrip.mutate(
      { ...toCreateTripBody(values, session.userId, lang), message_id: message.id },
      { onSettled: () => queryClient.invalidateQueries({ queryKey: conversationKeys.detail(conversationId) }) },
    );
  };

  const error = createTrip.error ?? closeForm.error;
  return (
    <div className="flex w-full flex-col gap-4 rounded-md border border-border bg-card p-4">
      <p>{t("chat.tripForm.intro")}</p>
      <TripForm
        initialValues={fromDraft(parseTripForm(message.content), null)}
        isBare
        submit={{ isPending: createTrip.isPending || closeForm.isPending, error: error instanceof ApiError ? error : null }}
        submitLabel="chat.tripForm.create"
        onSubmit={handleSubmit}
        onCancel={() => closeForm.mutate({ conversationId, messageId: message.id })}
      />
    </div>
  );
}
