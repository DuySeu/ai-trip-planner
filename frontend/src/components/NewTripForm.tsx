import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import type { Place } from "../api/api.types.ts";
import { ApiError } from "../api/client.ts";
import { createConversation, useConversation } from "../api/conversations.ts";
import { useCreateTrip } from "../api/trips.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { useSession } from "../session/session.ts";
import { BANNER, SKELETON } from "../styles/recipes.ts";
import { TripForm } from "./TripForm.tsx";
import { fromDraft, toCreateTripBody, toDraft, type TripFormValues } from "./validateTripForm.ts";

interface Props {
  conversationId: string | null;
  place: Place | null;
  isMissingPlace: boolean;
  isBare?: boolean;
}

// The new-trip form, prefilled from a conversation's draft and a suggestion card's place; submitting opens the trip
export function NewTripForm({ conversationId, place, isMissingPlace, isBare = false }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const session = useSession();
  const navigate = useNavigate();
  const conversation = useConversation(conversationId);
  const createTrip = useCreateTrip();
  const getIdeas = useMutation({ mutationFn: createConversation });

  // Create the trip and follow its progress
  const handleSubmit = (values: TripFormValues) => {
    if (!session) return;
    createTrip.mutate(toCreateTripBody(values, session.userId, lang), {
      onSuccess: (trip) => navigate(`/trips/${trip.id}`),
    });
  };

  // Carry what is filled in so far into a new ideas chat
  const handleGetIdeas = (values: TripFormValues) => {
    if (!session) return;
    getIdeas.mutate(
      { user_id: session.userId, draft: toDraft(values) },
      { onSuccess: (created) => navigate(`/chat/${created.id}`) },
    );
  };

  if (conversationId !== null && conversation.isPending) {
    return <div className={`${SKELETON} h-[640px]`} aria-label={t("home.loading")} />;
  }

  const submitError = createTrip.error ?? getIdeas.error;
  return (
    <>
      {conversation.isError && (
        <p className={BANNER.error} role="alert">
          {t(errorKey(conversation.error))}
        </p>
      )}
      <TripForm
        initialValues={fromDraft(conversation.data?.request_draft ?? null, place)}
        initialErrors={isMissingPlace ? { destination: "form.errors.destination" } : {}}
        isBare={isBare}
        submit={{
          isPending: createTrip.isPending || getIdeas.isPending,
          error: submitError instanceof ApiError ? submitError : null,
        }}
        onSubmit={handleSubmit}
        onGetIdeas={handleGetIdeas}
      />
    </>
  );
}
