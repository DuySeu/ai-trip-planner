import { ExternalLink, MapPin, Star } from "lucide-react";
import type { HotelCard as Hotel } from "../api/api.types.ts";
import { siteOf } from "../format/siteOf.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BADGE, CARD, TITLE } from "../styles/recipes.ts";
import { Price } from "./Price.tsx";

const HOME_ONLY = { home: "VND", local: null, local_to_home_rate: null, rate_date: null } as const;
const META = "flex items-center gap-2 text-sm text-muted-foreground [&>svg]:shrink-0";

// One hotel from a booking site: stars, area, a guide price per night and a link to its page
export function HotelCard({ hotel }: { hotel: Hotel }) {
  const t = useT();

  return (
    <article className={`${CARD} flex h-full flex-col gap-3`}>
      <h3 className={`${TITLE.card} wrap-anywhere`}>{hotel.name}</h3>
      <div className="flex flex-col gap-1">
        {hotel.stars !== null && (
          <p className={META}>
            <Star size={16} strokeWidth={1.75} aria-hidden="true" />
            {t("hotels.stars", { count: hotel.stars })}
          </p>
        )}
        {hotel.area && (
          <p className={META}>
            <MapPin size={16} strokeWidth={1.75} aria-hidden="true" />
            {hotel.area}
          </p>
        )}
      </div>
      {hotel.price_per_night !== null ? (
        <div className="flex flex-col gap-1">
          <Price amount={String(hotel.price_per_night)} currency={hotel.price_currency} basis="estimate" sourceUrl={null} currencies={HOME_ONLY} />
          <span className="text-sm text-muted-foreground">{t("hotels.perNight")}</span>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("hotels.noPrice")}</p>
      )}
      {hotel.highlights.length > 0 && (
        <ul className="flex flex-wrap gap-2">
          {hotel.highlights.map((highlight) => (
            <li key={highlight} className={BADGE.muted}>
              {highlight}
            </li>
          ))}
        </ul>
      )}
      <a
        className="mt-auto inline-flex items-center gap-1 self-start text-sm font-medium text-primary underline underline-offset-3"
        href={hotel.url}
        target="_blank"
        rel="noopener noreferrer"
      >
        {t("hotels.viewOn", { site: siteOf(hotel.url) })}
        <ExternalLink size={14} strokeWidth={1.75} aria-hidden="true" />
      </a>
    </article>
  );
}
