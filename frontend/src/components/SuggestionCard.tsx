import { CalendarDays } from "lucide-react";
import type { SuggestionCard as Card } from "../api/api.types.ts";
import { locale } from "../format/dates.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { Price } from "./Price.tsx";
import { BADGE, BUTTON, CARD, TITLE } from "../styles/recipes.ts";

const HOME_ONLY = { home: "VND", local: null, local_to_home_rate: null, rate_date: null } as const;

interface Props {
  card: Card;
  isBusy: boolean;
  onPlan(card: Card): void;
}

// One suggested destination: why it fits, length, rough cost per person, best months, and a way to plan it
export function SuggestionCard({ card, isBusy, onPlan }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const country = new Intl.DisplayNames([locale(lang)], { type: "region" }).of(card.country_code) ?? card.country_code;

  return (
    <article className={`${CARD} flex flex-col gap-3`} aria-labelledby={`card-${card.name}`}>
      <header>
        <h3 id={`card-${card.name}`} className={TITLE.section}>
          {card.name}
        </h3>
        <p className="text-sm text-muted-foreground">{country}</p>
      </header>
      <p>{card.why}</p>
      <dl className="flex flex-wrap items-end justify-between gap-4 [&_dd>span]:items-start">
        <div>
          <dt className="sr-only">{t("plan.days")}</dt>
          <dd className="inline-flex items-center gap-2 font-medium">
            <CalendarDays size={16} strokeWidth={1.75} aria-hidden="true" />
            {t("suggestion.days", { count: card.length_days })}
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted-foreground">{t("suggestion.costPerPerson")}</dt>
          <dd>
            <Price amount={card.est_cost_per_person_vnd} currency="VND" basis="estimate" sourceUrl={null} currencies={HOME_ONLY} />
          </dd>
        </div>
      </dl>
      <p className="text-sm text-muted-foreground">{t("suggestion.bestMonths", { months: card.best_months.join(", ") })}</p>
      {card.highlights.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {card.highlights.map((highlight) => (
            <li key={highlight} className={BADGE.muted}>
              {highlight}
            </li>
          ))}
        </ul>
      )}
      <button type="button" className={`${BUTTON.primary} self-start`} disabled={isBusy} onClick={() => onPlan(card)}>
        {t("suggestion.plan")}
      </button>
    </article>
  );
}
