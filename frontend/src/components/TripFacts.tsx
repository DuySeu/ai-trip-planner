import { CalendarDays, MapPin, Users, Wallet } from "lucide-react";
import type { BudgetScope, TravelStyle } from "../api/api.types.ts";
import { formatDateRange, tripDays } from "../format/dates.ts";
import { formatMoney } from "../format/money.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { BADGE } from "../styles/recipes.ts";

interface Props {
  origin?: string | null | undefined;
  destination?: string | null | undefined;
  startDate?: string | null | undefined;
  endDate?: string | null | undefined;
  lengthDays?: number | null | undefined;
  travelers?: number | null | undefined;
  styles?: TravelStyle[] | null | undefined;
  budgetAmount?: string | null | undefined;
  budgetScope?: BudgetScope | null | undefined;
}

const META = "flex items-center gap-2 text-sm text-muted-foreground [&>svg]:shrink-0";

// The basics of a trip or a trip draft, one line each; a fact the draft does not hold is left out
export function TripFacts({ origin, destination, startDate, endDate, lengthDays, travelers, styles, budgetAmount, budgetScope }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const dates = startDate && endDate ? formatDateRange(startDate, endDate, lang) : null;
  const days = startDate && endDate ? tripDays(startDate, endDate) : lengthDays;
  const when = [dates, days ? t("suggestion.days", { count: days }) : null].filter(Boolean).join(" · ");
  const budget = budgetAmount ? formatMoney(budgetAmount, "VND", lang) : null;

  return (
    <div className="flex flex-col gap-2">
      {origin && destination && (
        <p className={META}>
          <MapPin size={16} strokeWidth={1.75} aria-hidden="true" />
          {t("chat.tripForm.route", { origin, destination })}
        </p>
      )}
      {when && (
        <p className={`${META} tabular-nums`}>
          <CalendarDays size={16} strokeWidth={1.75} aria-hidden="true" />
          {when}
        </p>
      )}
      {travelers ? (
        <p className={META}>
          <Users size={16} strokeWidth={1.75} aria-hidden="true" />
          {t("common.travelers", { count: travelers })}
        </p>
      ) : null}
      {budget && (
        <p className={`${META} tabular-nums`}>
          <Wallet size={16} strokeWidth={1.75} aria-hidden="true" />
          {t(budgetScope === "total" ? "chat.tripForm.budgetTotal" : "chat.tripForm.budgetPerPerson", { amount: budget })}
        </p>
      )}
      {styles && styles.length > 0 && (
        <ul className="flex flex-wrap gap-2" aria-label={t("form.styles")}>
          {styles.map((style) => (
            <li key={style} className={BADGE.muted}>
              {t(`style.${style}`)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
