import { useMutation } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearchParams } from "react-router";
import type { Place } from "../api/api.types.ts";
import { ApiError } from "../api/client.ts";
import { createConversation, useConversation } from "../api/conversations.ts";
import { useCreateTrip } from "../api/trips.ts";
import { TripForm } from "../components/TripForm.tsx";
import { fromDraft, toCreateTripBody, toDraft, type TripFormValues } from "../components/validateTripForm.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { useSession } from "../session/session.ts";
import { BANNER, READING, SKELETON, TITLE } from "../styles/recipes.ts";

// The new-trip form, prefilled from a conversation's draft and a suggestion card's place
export function NewTripPage() {
  const t = useT();
  const { lang } = useLanguage();
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const conversationId = params.get("conversation");
  const state = location.state as { place?: Place; missingPlace?: boolean } | null;
  const conversation = useConversation(conversationId);
  const createTrip = useCreateTrip();
  const getIdeas = useMutation({ mutationFn: createConversation });

  // Create the trip and follow its progress
  const handleSubmit = (values: TripFormValues) => {
    if (!session) return;
    createTrip.mutate(toCreateTripBody(values, session.userId, conversationId, lang), {
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

  const isLoadingDraft = conversationId !== null && conversation.isPending;
  const submitError = createTrip.error ?? getIdeas.error;

  return (
    <div className={`${READING} flex flex-col gap-6`}>
      <h1 className={TITLE.page}>{t("form.title")}</h1>
      {isLoadingDraft ? (
        <div className={`${SKELETON} h-[640px]`} aria-label={t("home.loading")} />
      ) : (
        <>
          {conversation.isError && (
            <p className={BANNER.error} role="alert">
              {t(errorKey(conversation.error))}
            </p>
          )}
          <TripForm
            initialValues={fromDraft(conversation.data?.request_draft ?? null, state?.place ?? null)}
            initialErrors={state?.missingPlace ? { destination: "form.errors.destination" } : {}}
            submit={{
              isPending: createTrip.isPending || getIdeas.isPending,
              error: submitError instanceof ApiError ? submitError : null,
            }}
            onSubmit={handleSubmit}
            onGetIdeas={handleGetIdeas}
          />
        </>
      )}
    </div>
  );
}
