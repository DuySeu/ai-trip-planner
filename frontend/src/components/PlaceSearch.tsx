import { MapPin } from "lucide-react";
import { type KeyboardEvent, useEffect, useState } from "react";
import type { Place } from "../api/api.types.ts";
import { usePlaceSearch } from "../api/places.ts";
import { errorKey } from "../i18n/errorKey.ts";
import { useT } from "../i18n/LanguageProvider.tsx";
import { INPUT } from "../styles/recipes.ts";

const DEBOUNCE_MS = 300;
const MIN_QUERY = 2;
const MESSAGE = "flex min-h-12 items-center px-3 text-sm text-muted-foreground";

interface Props {
  inputId: string;
  value: Place | null;
  isInvalid: boolean;
  describedBy: string | undefined;
  onChange(place: Place | null): void;
}

// Combobox over GET /places; typing after a pick clears the value, so free text can never be submitted
export function PlaceSearch({ inputId, value, isInvalid, describedBy, onChange }: Props) {
  const t = useT();
  const [text, setText] = useState(value?.name ?? "");
  const [query, setQuery] = useState("");
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const search = usePlaceSearch(query);

  const listId = `${inputId}-list`;
  const places = search.data ?? [];
  const isSearchable = query.trim().length >= MIN_QUERY;
  const isExpanded = isOpen && isSearchable && value === null && !search.isPending;
  const active = activeIndex >= 0 ? places[activeIndex] : undefined;

  // Take a place and close the list
  const pick = (place: Place) => {
    onChange(place);
    setText(place.name);
    setIsOpen(false);
    setActiveIndex(-1);
  };

  // Up/Down move, Enter picks, Escape closes
  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (places.length === 0) return;
      event.preventDefault();
      setIsOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((index) => (index + step + places.length) % places.length);
    } else if (event.key === "Enter" && isExpanded && active) {
      event.preventDefault();
      pick(active);
    } else if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      setIsOpen(false);
    }
  };

  // Search only once typing pauses
  useEffect(() => {
    const timer = setTimeout(() => setQuery(text), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [text]);

  return (
    <div className="relative">
      <MapPin className="pointer-events-none absolute top-3 left-3 text-muted-foreground" size={20} strokeWidth={1.75} aria-hidden="true" />
      <input
        id={inputId}
        className={`${INPUT} pl-10`}
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={isExpanded}
        aria-controls={listId}
        aria-activedescendant={isExpanded && active ? `${listId}-${activeIndex}` : undefined}
        aria-invalid={isInvalid}
        aria-describedby={describedBy}
        autoComplete="off"
        placeholder={t("form.destinationPlaceholder")}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setIsOpen(true);
          setActiveIndex(-1);
          if (value !== null) onChange(null);
        }}
        onKeyDown={handleKeyDown}
        onFocus={() => setIsOpen(true)}
        onBlur={() => setIsOpen(false)}
      />
      <ul id={listId} role="listbox" className="absolute inset-x-0 top-[calc(100%+4px)] z-10 max-h-[488px] origin-top animate-pop-in overflow-y-auto rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-raised"
        hidden={!isExpanded}>
        {search.isError ? (
          <li className={MESSAGE}>{t(errorKey(search.error))}</li>
        ) : places.length === 0 ? (
          <li className={MESSAGE}>{t("form.noPlaces")}</li>
        ) : (
          places.map((place, index) => (
            <li
              key={`${place.name}-${place.lat}-${place.lon}`}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === activeIndex}
              className="flex min-h-12 cursor-pointer flex-col justify-center rounded-sm px-3 py-1 hover:bg-accent hover:text-accent-foreground aria-selected:bg-accent aria-selected:text-accent-foreground"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(place)}
            >
              <span className="text-base/5">{place.name}</span>
              <span className="text-sm text-muted-foreground">
                {[place.admin1 !== place.name ? place.admin1 : null, place.country].filter(Boolean).join(", ")}
              </span>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
