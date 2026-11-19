import type { Leg, Plan, TransportOption } from "../api/api.types.ts";
import { formatDay } from "../format/dates.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { categoryIcon } from "./categoryIcon.ts";
import { Price } from "./Price.tsx";
import { BADGE, TITLE } from "../styles/recipes.ts";

const LEGS: Leg[] = ["outbound", "return", "local"];
const MINUTES_PER_HOUR = 60;

interface Props {
  options: TransportOption[];
  currencies: Plan["currencies"];
}

// The ways there, back and around, grouped by leg; the chosen one is marked, switching happens in chat
export function TransportOptions({ options, currencies }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const byLeg = Object.groupBy(options, (option) => option.leg);

  return (
    <div className="flex flex-col gap-6">
      {LEGS.filter((leg) => byLeg[leg]?.length).map((leg) => (
        <section key={leg} className="flex flex-col gap-3" aria-labelledby={`leg-${leg}`}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 id={`leg-${leg}`} className={TITLE.card}>
              {t(`leg.${leg}`)}
            </h3>
            <p className="text-sm text-muted-foreground">{t("plan.askToSwitch")}</p>
          </div>
          <ul className="flex flex-col gap-3">
            {(byLeg[leg] ?? []).map((option) => {
              const Icon = categoryIcon("transport", option.mode);
              const minutes = option.duration_minutes;
              return (
                <li key={option.id} className={`flex flex-col gap-3 rounded-md bg-card shadow-surface ${option.chosen ? "border-2 border-primary p-[15px]" : "border border-border p-4"}`}>
                  <div className="flex flex-wrap items-start gap-3 sm:flex-nowrap">
                    <Icon size={20} strokeWidth={1.75} aria-hidden="true" className="mt-0.5 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        {option.summary}
                        {option.chosen && <span className={BADGE.primary}>{t("badge.chosen")}</span>}
                      </p>
                      <p className="text-sm text-muted-foreground tabular-nums">
                        {[
                          t(`mode.${option.mode}`),
                          option.depart
                            ? t("plan.departs", {
                                time: `${formatDay(option.depart.slice(0, 10), lang)} ${option.depart.slice(11, 16)}`,
                              })
                            : null,
                          minutes !== null
                            ? t("plan.duration", {
                                hours: Math.floor(minutes / MINUTES_PER_HOUR),
                                minutes: minutes % MINUTES_PER_HOUR,
                              })
                            : null,
                        ]
                          .filter(Boolean)
                          .join(", ")}
                      </p>
                    </div>
                    <div className="flex max-sm:basis-full max-sm:pl-8 [&>span]:max-sm:items-start">
                      <Price
                        amount={String(option.price_per_person)}
                        currency={option.price_currency}
                        basis={option.price_basis}
                        sourceUrl={null}
                        currencies={currencies}
                      />
                    </div>
                  </div>
                  <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2 sm:pl-8 [&_dt]:font-medium [&_dt]:text-muted-foreground">
                    <div>
                      <dt>{t("plan.pros")}</dt>
                      <dd>{option.pros}</dd>
                    </div>
                    <div>
                      <dt>{t("plan.cons")}</dt>
                      <dd>{option.cons}</dd>
                    </div>
                  </dl>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
