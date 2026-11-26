import type {
  BudgetScope,
  CreateTripBody,
  Language,
  Place,
  RequestDraft,
  TravelStyle,
} from "../api/api.types.ts";
import { addDays, tripDays } from "../format/dates.ts";
import type { MessageKey } from "../i18n/LanguageProvider.tsx";

const MAX_TRIP_DAYS = 30;
const MAX_TRAVELERS = 50;
const MAX_NOTES = 2000;
const DEFAULT_TRAVELERS = 2;
// The starting point when the draft names none and the visitor's location is unknown (as the backend)
export const DEFAULT_ORIGIN = "Hà Nội";

// The form's own state; destination only ever comes from the place search
export interface TripFormValues {
  destination: Place | null;
  origin: string;
  start_date: string;
  end_date: string;
  travelers: number;
  travel_styles: TravelStyle[];
  budget_amount: string;
  budget_scope: BudgetScope;
  // The visitor lets the AI suggest the budget: amount and scope are not sent
  budget_auto: boolean;
  notes: string;
}

export type TripFormErrors = Partial<Record<keyof TripFormValues, MessageKey>>;

// Mirror the backend's trip rules so the visitor hears about a mistake before a round trip
export function validateTripForm(values: TripFormValues, today: string): TripFormErrors {
  const errors: TripFormErrors = {};
  if (values.destination === null) errors.destination = "form.errors.destination";

  if (!values.start_date) errors.start_date = "form.errors.startRequired";
  else if (values.start_date < today) errors.start_date = "form.errors.startInPast";

  if (!values.end_date) errors.end_date = "form.errors.endRequired";
  else if (values.start_date && values.end_date < values.start_date) errors.end_date = "form.errors.endBeforeStart";
  else if (values.start_date && tripDays(values.start_date, values.end_date) > MAX_TRIP_DAYS) errors.end_date = "form.errors.tooLong";

  if (!Number.isInteger(values.travelers) || values.travelers < 1 || values.travelers > MAX_TRAVELERS) {
    errors.travelers = "form.errors.travelers";
  }
  if (values.travel_styles.length === 0) errors.travel_styles = "form.errors.styles";
  if (!values.budget_auto && !(Number(values.budget_amount) > 0)) errors.budget_amount = "form.errors.budget";
  if (values.notes.length > MAX_NOTES) errors.notes = "form.errors.notes";
  return errors;
}

// The POST /trips body for valid form values
export function toCreateTripBody(
  values: TripFormValues,
  userId: string,
  lang: Language,
): CreateTripBody {
  const place = values.destination as Place;
  const notes = values.notes.trim();
  return {
    user_id: userId,
    destination: { name: place.name, country_code: place.country_code, lat: place.lat, lon: place.lon },
    origin: values.origin.trim(),
    start_date: values.start_date,
    end_date: values.end_date,
    travelers: values.travelers,
    travel_styles: values.travel_styles,
    budget_amount: values.budget_auto ? null : values.budget_amount,
    budget_scope: values.budget_auto ? null : values.budget_scope,
    language: lang,
    notes: notes === "" ? null : notes,
  };
}

// Form values from a conversation's draft plus a picked place; a month alone leaves the dates empty.
// With no origin in the draft the form starts from fallbackOrigin (the visitor's current city)
export function fromDraft(draft: RequestDraft | null, place: Place | null, fallbackOrigin = DEFAULT_ORIGIN): TripFormValues {
  const d = draft ?? {};
  const fromDraftPlace: Place | null = d.destination ? { ...d.destination, admin1: null } : null;
  const start = d.start_date ?? "";
  const end = d.end_date ?? (start && d.length_days ? addDays(start, d.length_days - 1) : "");
  return {
    destination: place ?? fromDraftPlace,
    origin: d.origin ?? fallbackOrigin,
    start_date: start,
    end_date: end,
    travelers: d.travelers ?? DEFAULT_TRAVELERS,
    travel_styles: d.travel_styles ?? [],
    budget_amount: d.budget_amount ? String(Math.round(Number(d.budget_amount))) : "",
    budget_scope: d.budget_scope ?? "per_person",
    budget_auto: false,
    notes: d.notes ?? "",
  };
}

// What the visitor has filled in so far, as a draft for the ideas chat
export function toDraft(values: TripFormValues): RequestDraft {
  const place = values.destination;
  return {
    ...(place ? { destination: { name: place.name, country_code: place.country_code, lat: place.lat, lon: place.lon } } : {}),
    ...(values.origin.trim() ? { origin: values.origin.trim() } : {}),
    ...(values.start_date ? { start_date: values.start_date } : {}),
    ...(values.end_date ? { end_date: values.end_date } : {}),
    travelers: values.travelers,
    travel_styles: values.travel_styles,
    ...(values.budget_amount && !values.budget_auto
      ? { budget_amount: values.budget_amount, budget_scope: values.budget_scope }
      : {}),
    ...(values.notes.trim() ? { notes: values.notes.trim() } : {}),
  };
}
