import { ChevronLeft, ChevronRight } from "lucide-react";
import { type ReactNode, useRef } from "react";
import { type MessageKey, useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON } from "../styles/recipes.ts";

interface Props {
  labels: { title: MessageKey; previous: MessageKey; next: MessageKey };
  // A line under the title, such as the dates searched
  subtitle?: string | null;
  items: { key: string; node: ReactNode }[];
}

// Cards in one row that scrolls sideways and snaps to a card; arrows from 640px up
export function CardSlider({ labels, subtitle, items }: Props) {
  const t = useT();
  const listRef = useRef<HTMLUListElement>(null);
  if (items.length === 0) return null;

  // Move by most of the visible width; jump instead of gliding when the visitor asks for less motion
  const scroll = (direction: 1 | -1) => {
    const list = listRef.current;
    if (!list) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    list.scrollBy({ left: direction * list.clientWidth * 0.8, behavior: reduce ? "auto" : "smooth" });
  };

  return (
    <section className="flex min-w-0 flex-col gap-2" aria-label={t(labels.title)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-col">
          <h3 className="text-sm font-medium text-muted-foreground">{t(labels.title)}</h3>
          {subtitle && <p className="text-sm text-muted-foreground tabular-nums">{subtitle}</p>}
        </div>
        <div className="hidden gap-1 sm:flex">
          <button type="button" className={BUTTON.icon} aria-label={t(labels.previous)} onClick={() => scroll(-1)}>
            <ChevronLeft size={20} strokeWidth={1.75} aria-hidden="true" />
          </button>
          <button type="button" className={BUTTON.icon} aria-label={t(labels.next)} onClick={() => scroll(1)}>
            <ChevronRight size={20} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </div>
      <ul ref={listRef} className="flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2">
        {items.map(({ key, node }) => (
          <li key={key} className="w-72 max-w-[85%] shrink-0 snap-start">
            {node}
          </li>
        ))}
      </ul>
    </section>
  );
}
