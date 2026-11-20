import { Clock, ExternalLink } from "lucide-react";
import { createElement } from "react";
import type { FlightCard as Flight } from "../api/api.types.ts";
import { siteOf } from "../format/siteOf.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BADGE, CARD, TITLE } from "../styles/recipes.ts";
import { categoryIcon } from "./categoryIcon.ts";
import { Price } from "./Price.tsx";

const HOME_ONLY = { home: "VND", local: null, local_to_home_rate: null, rate_date: null } as const;
const META = "flex items-center gap-2 text-sm text-muted-foreground [&>svg]:shrink-0";

// One ticket option from a travel site: carrier, route, a guide price and a link to its page
export function FlightCard({ flight }: { flight: Flight }) {
  const t = useT();
  return (
    <article className={`${CARD} flex h-full flex-col gap-3`}>
      <h3 className={`${TITLE.card} wrap-anywhere`}>{flight.carrier}</h3>
      <div className="flex flex-col gap-1">
        <p className={META}>
          {createElement(categoryIcon("transport", flight.mode), { size: 16, strokeWidth: 1.75, "aria-hidden": true })}
          {flight.route}
        </p>
        {flight.duration_text && (
          <p className={META}>
            <Clock size={16} strokeWidth={1.75} aria-hidden="true" />
            {flight.duration_text}
          </p>
        )}
      </div>
      {flight.price_from !== null ? (
        <div className="flex flex-col gap-1">
          <span className="text-sm text-muted-foreground">{t("flights.from")}</span>
          <Price amount={String(flight.price_from)} currency={flight.price_currency} basis="estimate" sourceUrl={null} currencies={HOME_ONLY} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("flights.noPrice")}</p>
      )}
      {flight.highlights.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {flight.highlights.map((highlight) => (
            <li key={highlight} className={BADGE.muted}>
              {highlight}
            </li>
          ))}
        </ul>
      )}
      <a
        className="mt-auto inline-flex items-center gap-1 self-start text-sm font-medium text-primary underline underline-offset-3"
        href={flight.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t("hotels.viewOn", { site: siteOf(flight.url) })}
        <ExternalLink size={14} strokeWidth={1.75} aria-hidden="true" />
      </a>
    </article>
  );
}
