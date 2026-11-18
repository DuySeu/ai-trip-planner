import { CalendarDays, CircleCheck, Circle, CloudSun, MapPin, TriangleExclamationPoint, Users } from "lucide-react";
import type { Plan, Trip } from "../api/api.types.ts";
import { formatDateRange, formatDay, tripDays } from "../format/dates.ts";
import { formatMoney } from "../format/money.ts";
import { useLanguage, useT } from "../i18n/LanguageProvider.tsx";
import { categoryIcon } from "./categoryIcon.ts";
import { Price } from "./Price.tsx";
import { BADGE, BANNER, CARD, SURFACE, TITLE } from "../styles/recipes.ts";
import { TransportOptions } from "./TransportOptions.tsx";

const SECTION = "flex flex-col gap-4";
const LIST = `${SURFACE} px-5 divide-y divide-border`;
const ROW = "flex min-h-14 flex-wrap items-start gap-x-3 gap-y-1 py-3 sm:flex-nowrap [&>svg]:mt-0.5 [&>svg]:shrink-0";
const BODY = "flex min-w-0 flex-1 flex-col gap-0.5 wrap-anywhere";
const ITEM_TITLE = "flex flex-wrap items-center gap-2 font-medium";
const PRICE_COL = "flex flex-col max-sm:basis-full max-sm:items-start sm:items-end sm:text-right [&>span]:max-sm:items-start";
const MUTED_SMALL = "text-sm text-muted-foreground";

interface Props {
  trip: Trip & { plan: Plan };
}

// The whole plan: header, warnings, days, transport, stay, checklist, in that order
export function PlanView({ trip }: Props) {
  const t = useT();
  const { lang } = useLanguage();
  const { plan } = trip;
  const { currencies } = plan;

  const sourceUrl = (id: number | null) => (id === null ? null : (trip.sources[String(id)]?.url ?? null));
  const budgetTotal = Number(trip.budget_amount) * (trip.budget_scope === "per_person" ? trip.travelers : 1);
  const overBy = Number(trip.total_cost_vnd ?? 0) - budgetTotal;
  const stays = plan.accommodation.toSorted((a, b) => Number(b.chosen) - Number(a.chosen));

  return (
    <article className="flex min-w-0 flex-col gap-8">
      <header className="flex flex-col gap-3">
        <h1 className={TITLE.page}>{plan.title}</h1>
        <p className="max-w-[65ch] text-muted-foreground">{plan.summary}</p>
        <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm [&_li]:inline-flex [&_li]:items-center [&_li]:gap-2 [&_svg]:text-muted-foreground">
          <li>
            <MapPin size={16} strokeWidth={1.75} aria-hidden="true" />
            {trip.destination_name}
          </li>
          <li className="tabular-nums">
            <CalendarDays size={16} strokeWidth={1.75} aria-hidden="true" />
            {formatDateRange(trip.start_date, trip.end_date, lang)}
          </li>
          <li>
            <Users size={16} strokeWidth={1.75} aria-hidden="true" />
            {t("common.travelers", { count: trip.travelers })}
          </li>
        </ul>
        <dl className="mt-2 flex flex-wrap gap-6 [&_dd]:text-xl [&_dd]:font-semibold [&_dt]:text-sm [&_dt]:text-muted-foreground">
          <div>
            <dt>{t("plan.total")}</dt>
            <dd className="tabular-nums">{trip.total_cost_vnd === null ? "-" : formatMoney(trip.total_cost_vnd, "VND", lang)}</dd>
          </div>
          <div>
            <dt>{t("plan.budget")}</dt>
            <dd className="tabular-nums">{formatMoney(budgetTotal, "VND", lang)}</dd>
          </div>
        </dl>
        {currencies.local && currencies.local_to_home_rate !== null && (
          <p className={`${MUTED_SMALL} tabular-nums`}>
            {t("plan.rate", {
              currency: currencies.local,
              rate: new Intl.NumberFormat(lang === "vi" ? "vi-VN" : "en-US").format(currencies.local_to_home_rate),
              date: currencies.rate_date ?? "",
            })}
          </p>
        )}
      </header>

      {plan.warnings.length > 0 && (
        <ul className="flex flex-col gap-3">
          {plan.warnings.map((warning) => (
            <li key={warning.code} className={BANNER.warning}>
              <TriangleExclamationPoint size={20} strokeWidth={1.75} aria-hidden="true" />
              <span className="tabular-nums">
                {warning.code === "over_budget" && overBy > 0
                  ? t("plan.overBudget", { amount: formatMoney(overBy, "VND", lang) })
                  : warning.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      <section className={SECTION} aria-labelledby="plan-days">
        <h2 id="plan-days" className={TITLE.section}>
          {t("plan.days")}
        </h2>
        <ol className="flex flex-col gap-4">
          {plan.days.map((day, index) => (
            <li key={day.date} className={`${CARD} pb-2`}>
              <div className="flex flex-wrap items-start justify-between gap-3 pb-4">
                <div>
                  <p className={MUTED_SMALL}>{t("plan.dayLabel", { number: index + 1 })}</p>
                  <h3 className={`${TITLE.section} tabular-nums`}>{formatDay(day.date, lang)}</h3>
                  {day.theme && <p className="mt-1 text-muted-foreground">{day.theme}</p>}
                </div>
                {day.weather && (
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex min-h-7 items-center gap-1 rounded-full bg-muted px-3 text-sm text-foreground tabular-nums">
                      <CloudSun size={16} strokeWidth={1.75} aria-hidden="true" />
                      {day.weather.temp_min_c}-{day.weather.temp_max_c} °C · {day.weather.precip_mm} mm
                    </span>
                    {day.weather.basis === "typical" && (
                      <span className={BADGE.warning} title={t("plan.typicalHint")}>
                        {t("badge.typical")}
                        <span className="sr-only">, {t("plan.typicalHint")}</span>
                      </span>
                    )}
                  </p>
                )}
              </div>
              <ul className="divide-y divide-border border-t border-border">
                {day.items
                  .toSorted((a, b) => (a.start_time ?? "").localeCompare(b.start_time ?? ""))
                  .map((item) => {
                    const Icon = categoryIcon(item.category, item.transport_mode);
                    return (
                      <li key={item.id} className="grid min-h-14 grid-cols-[20px_minmax(0,1fr)] items-start gap-x-3 gap-y-1 py-3 sm:grid-cols-[112px_20px_minmax(0,1fr)_auto] sm:gap-y-0">
                        <span className="col-span-full font-mono text-sm whitespace-nowrap text-muted-foreground sm:col-span-1 sm:pt-0.5">
                          {item.start_time ?? ""}
                          {item.end_time ? ` - ${item.end_time}` : ""}
                        </span>
                        <Icon size={20} strokeWidth={1.75} className="mt-0.5 text-muted-foreground" aria-label={t(`category.${item.category}`)} />
                        <div className={BODY}>
                          <p className={ITEM_TITLE}>
                            {item.title}
                            {item.status !== "planned" && (
                              <span className={item.status === "paid" ? BADGE.accent : BADGE.secondary}>
                                {t(`itemStatus.${item.status}`)}
                              </span>
                            )}
                          </p>
                          {item.location && <p className={MUTED_SMALL}>{item.location}</p>}
                          {item.note && <p className="text-sm">{item.note}</p>}
                        </div>
                        <div className="col-start-2 flex flex-col items-start sm:col-start-auto sm:items-end sm:text-right [&>span]:max-sm:items-start">
                          <Price
                            amount={String(item.price_per_person)}
                            currency={item.price_currency}
                            basis={item.price_basis}
                            sourceUrl={sourceUrl(item.source_id)}
                            currencies={currencies}
                          />
                        </div>
                      </li>
                    );
                  })}
              </ul>
            </li>
          ))}
        </ol>
      </section>

      <section className={SECTION} aria-labelledby="plan-transport">
        <h2 id="plan-transport" className={TITLE.section}>
          {t("plan.transport")}
        </h2>
        <TransportOptions options={plan.transport_options} currencies={currencies} sources={trip.sources} />
      </section>

      {stays.length > 0 && (
        <section className={SECTION} aria-labelledby="plan-stay">
          <h2 id="plan-stay" className={TITLE.section}>
            {t("plan.stay")}
          </h2>
          <ul className={LIST}>
            {stays.map((stay) => (
              <li key={stay.id} className={ROW}>
                <div className={BODY}>
                  <p className={ITEM_TITLE}>
                    {stay.name}
                    {stay.chosen && <span className={BADGE.primary}>{t("badge.chosen")}</span>}
                  </p>
                  <p className={`${MUTED_SMALL} tabular-nums`}>
                    {stay.area}, {t("plan.nights", { nights: tripDays(stay.check_in, stay.check_out) - 1, rooms: stay.rooms })}
                  </p>
                </div>
                <div className={PRICE_COL}>
                  <Price
                    amount={String(stay.price_per_night)}
                    currency={stay.price_currency}
                    basis={stay.price_basis}
                    sourceUrl={sourceUrl(stay.source_id)}
                    currencies={currencies}
                  />
                  <span className={MUTED_SMALL}>{t("plan.perNight")}</span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {plan.checklist.length > 0 && (
        <section className={SECTION} aria-labelledby="plan-checklist">
          <h2 id="plan-checklist" className={TITLE.section}>
            {t("plan.checklist")}
          </h2>
          <p className={MUTED_SMALL}>{t("plan.checklistHint")}</p>
          <ul className={LIST}>
            {plan.checklist.map((entry) => (
              <li key={entry.id} className={ROW}>
                {entry.done ? (
                  <CircleCheck size={20} strokeWidth={1.75} className="text-primary" aria-label={t("plan.done")} />
                ) : (
                  <Circle size={20} strokeWidth={1.75} className="text-muted-foreground" aria-label={t("plan.todo")} />
                )}
                <p className={BODY}>{entry.label}</p>
                {entry.price_per_person > 0 && (
                  <div className={`${PRICE_COL} max-sm:pl-8`}>
                    <Price
                      amount={String(entry.price_per_person)}
                      currency={entry.price_currency}
                      basis="estimate"
                      sourceUrl={null}
                      currencies={currencies}
                    />
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
