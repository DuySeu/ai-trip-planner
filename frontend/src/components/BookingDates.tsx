import { CalendarCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import type { BookingKind, FlightDates, HotelDates } from "../api/api.types.ts";
import { addDays, todayInVietnam, tripDays } from "../format/dates.ts";
import { type MessageKey, useT } from "../i18n/LanguageProvider.tsx";
import { BUTTON, FIELD, FIELD_ERROR, INPUT, LABEL } from "../styles/recipes.ts";

const MAX_NIGHTS = 30;
const PAIR = "grid grid-cols-1 gap-4 sm:grid-cols-2";

interface Props {
  messageId: string;
  kind: BookingKind;
  isOpen: boolean;
  isBusy: boolean;
  // Shown until the visitor edits the field; an unedited origin is not sent, so the server keeps
  // its own order (open trip, draft, current city, Hà Nội)
  defaultOrigin: string | null;
  onSearch(dates: HotelDates | FlightDates, origin: string | null): void;
}

// The dates a hotel or ticket search waits for; checked here first so a bad pick never reaches the server
export function BookingDates({ messageId, kind, isOpen, isBusy, defaultOrigin, onSearch }: Props) {
  const t = useT();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  // null until the visitor types: the field then follows defaultOrigin as it changes
  const [origin, setOrigin] = useState<string | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  const today = todayInVietnam();
  const isHotel = kind === "hotel";
  const id = (name: string) => `booking-${messageId}-${name}`;

  // What is wrong with the picked dates, by the same rules as the server
  const problem = (): MessageKey | null => {
    if (!start || (isHotel && !end)) return "booking.errorRequired";
    if (start < today) return "booking.errorPast";
    if (isHotel && end <= start) return "booking.errorOrder";
    if (isHotel && tripDays(start, end) - 1 > MAX_NIGHTS) return "booking.errorTooLong";
    if (!isHotel && end && end < start) return "booking.errorReturn";
    return null;
  };

  // Send the dates, or show why they cannot be sent
  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const found = problem();
    setError(found);
    if (found) return;
    const dates = isHotel ? { check_in: start, check_out: end } : { depart: start, return: end || null };
    onSearch(dates, isHotel || origin === null ? null : origin.trim() || null);
  };

  if (!isOpen) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <CalendarCheck size={16} strokeWidth={1.75} aria-hidden="true" />
        {t("booking.done")}
      </p>
    );
  }

  return (
    <form className="flex w-full flex-col gap-4 rounded-md border border-border bg-card p-4" noValidate onSubmit={handleSubmit}>
      <div className={PAIR}>
        <div className={FIELD}>
          <label className={LABEL} htmlFor={id("start")}>
            {t(isHotel ? "booking.checkIn" : "booking.depart")}
          </label>
          <input
            id={id("start")}
            type="date"
            className={`${INPUT} tabular-nums`}
            min={today}
            value={start}
            aria-invalid={error !== null}
            onChange={(event) => setStart(event.target.value)}
          />
        </div>
        <div className={FIELD}>
          <label className={LABEL} htmlFor={id("end")}>
            {t(isHotel ? "booking.checkOut" : "booking.return")}
          </label>
          <input
            id={id("end")}
            type="date"
            className={`${INPUT} tabular-nums`}
            min={start || today}
            max={isHotel && start ? addDays(start, MAX_NIGHTS) : undefined}
            value={end}
            aria-invalid={error !== null}
            onChange={(event) => setEnd(event.target.value)}
          />
        </div>
      </div>
      {!isHotel && (
        <div className={FIELD}>
          <label className={LABEL} htmlFor={id("origin")}>
            {t("booking.origin")}
          </label>
          <input id={id("origin")} className={INPUT} value={origin ?? defaultOrigin ?? ""} onChange={(event) => setOrigin(event.target.value)} />
        </div>
      )}
      {error && (
        <p className={FIELD_ERROR} role="alert">
          {t(error)}
        </p>
      )}
      <button type="submit" className={`${BUTTON.primary} self-start`} disabled={isBusy}>
        {t("booking.search")}
      </button>
    </form>
  );
}
