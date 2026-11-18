import { useLocation, useSearchParams } from "react-router";
import type { Place } from "../api/api.types.ts";
import { NewTripForm } from "../components/NewTripForm.tsx";
import { useT } from "../i18n/LanguageProvider.tsx";
import { READING, TITLE } from "../styles/recipes.ts";

// The new-trip page, opened from a suggestion card or a chat draft
export function NewTripPage() {
  const t = useT();
  const location = useLocation();
  const [params] = useSearchParams();
  const state = location.state as { place?: Place; missingPlace?: boolean } | null;

  return (
    <div className={`${READING} flex flex-col gap-6`}>
      <h1 className={TITLE.page}>{t("form.title")}</h1>
      <NewTripForm
        conversationId={params.get("conversation")}
        place={state?.place ?? null}
        isMissingPlace={state?.missingPlace ?? false}
      />
    </div>
  );
}
