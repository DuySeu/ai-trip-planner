import { CircleX } from "lucide-react";
import type { RequestDraft } from "../api/api.types.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { CARD, TITLE } from "../styles/recipes.ts";
import { TripFacts } from "./TripFacts.tsx";

// A trip form the visitor canceled: what it held, marked canceled
export function ChatTripCanceled({ form }: { form: RequestDraft }) {
  const t = useT();
  const destination = form.destination?.name ?? null;

  return (
    <section className={`${CARD} flex w-full flex-col gap-3`}>
      <h3 className={TITLE.card}>{destination ?? t("chat.tripForm.newTrip")}</h3>
      <TripFacts
        origin={form.origin}
        destination={destination}
        startDate={form.start_date}
        endDate={form.end_date}
        lengthDays={form.length_days}
        travelers={form.travelers}
        styles={form.travel_styles}
        budgetAmount={form.budget_amount}
        budgetScope={form.budget_scope}
      />
      <p className="flex items-center gap-2 border-t border-border pt-3 text-sm text-muted-foreground">
        <CircleX size={16} strokeWidth={1.75} aria-hidden="true" />
        {t("chat.tripForm.canceled")}
      </p>
    </section>
  );
}
