import { ChevronLeft, ChevronRight } from "lucide-react";
import { useRef } from "react";
import type { HotelCard as Hotel } from "../api/api.types.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON } from "../styles/recipes.ts";
import { HotelCard } from "./HotelCard.tsx";

// Hotel cards in one row that scrolls sideways and snaps to a card; arrows from 640px up
export function HotelSlider({ cards }: { cards: Hotel[] | null }) {
  const t = useT();
  const listRef = useRef<HTMLUListElement>(null);
  if (!cards || cards.length === 0) return null;

  // Move by most of the visible width; jump instead of gliding when the visitor asks for less motion
  const scroll = (direction: 1 | -1) => {
    const list = listRef.current;
    if (!list) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    list.scrollBy({ left: direction * list.clientWidth * 0.8, behavior: reduce ? "auto" : "smooth" });
  };

  return (
    <section className="flex min-w-0 flex-col gap-2" aria-label={t("hotels.title")}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-medium text-muted-foreground">{t("hotels.title")}</h3>
        <div className="hidden gap-1 sm:flex">
          <button type="button" className={BUTTON.icon} aria-label={t("hotels.previous")} onClick={() => scroll(-1)}>
            <ChevronLeft size={20} strokeWidth={1.75} aria-hidden="true" />
          </button>
          <button type="button" className={BUTTON.icon} aria-label={t("hotels.next")} onClick={() => scroll(1)}>
            <ChevronRight size={20} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </div>
      <ul ref={listRef} className="flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2">
        {cards.map((hotel) => (
          <li key={`${hotel.source_id}-${hotel.name}`} className="w-72 max-w-[85%] shrink-0 snap-start">
            <HotelCard hotel={hotel} />
          </li>
        ))}
      </ul>
    </section>
  );
}
