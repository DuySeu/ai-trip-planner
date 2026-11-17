// The API contract the client codes against. If the backend picks other field names,
// only this file and src/mocks/fixtures.ts change.

export const GROUP_TYPES = ["solo", "couple", "family", "friends", "colleagues"] as const;
export const TRAVEL_STYLES = [
  "relax",
  "adventure",
  "culture",
  "food",
  "nature",
  "nightlife",
  "shopping",
  "luxury",
  "budget",
] as const;
export const TRANSPORT_MODES = ["flight", "train", "bus", "car", "motorbike", "boat"] as const;
export const ACTIVE_STATUSES = ["queued", "researching", "planning"] as const;
export const CHAT_EVENT_TYPES = ["token", "plan", "suggestions", "error", "done"] as const;

export type GroupType = (typeof GROUP_TYPES)[number];
export type TravelStyle = (typeof TRAVEL_STYLES)[number];
export type TransportMode = (typeof TRANSPORT_MODES)[number];
export type TripStatus = (typeof ACTIVE_STATUSES)[number] | "ready" | "failed";
export type Category = "transport" | "accommodation" | "food" | "shopping" | "service" | "sightseeing";
export type BudgetScope = "per_person" | "total";
export type Language = "en" | "vi";
export type PriceBasis = "source" | "estimate";
export type ItemStatus = "planned" | "booked" | "paid";
export type WeatherBasis = "forecast" | "typical";
export type Leg = "outbound" | "return" | "local";
export type TripStage = "researching" | "planning" | "validating";
export type MessageIntent =
  | "plan_answer"
  | "plan_editor"
  | "trip_research"
  | "travel_advice"
  | "clarification"
  | "ask"
  | "suggest"
  | "answer";

export interface ErrorBody {
  code: string;
  message: string;
  blocked_until?: string;
}

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ErrorBody | null;
  meta: PageMeta | null;
}

export interface User {
  id: string;
  name: string;
  created_at: string;
  trip_count: number;
}

export interface Place {
  name: string;
  country_code: string;
  country: string;
  admin1: string | null;
  lat: number;
  lon: number;
}

export interface Currencies {
  home: "VND";
  local: string | null;
  local_to_home_rate: number | null;
  rate_date: string | null;
}

export interface Weather {
  summary: string;
  temp_min_c: number;
  temp_max_c: number;
  precip_mm: number;
  basis: WeatherBasis;
}

export interface PlanItem {
  id: string;
  start_time: string | null;
  end_time: string | null;
  title: string;
  description: string | null;
  location: string | null;
  category: Category;
  transport_mode: TransportMode | null;
  price_per_person: number;
  price_currency: string;
  price_basis: PriceBasis;
  source_id: number | null;
  status: ItemStatus;
  note: string | null;
  option_id: string | null;
}

export interface PlanDay {
  date: string;
  theme: string;
  weather: Weather | null;
  items: PlanItem[];
}

export interface TransportOption {
  id: string;
  leg: Leg;
  mode: TransportMode;
  summary: string;
  depart: string | null;
  duration_minutes: number | null;
  price_per_person: number;
  price_currency: string;
  price_basis: PriceBasis;
  source_id: number | null;
  pros: string;
  cons: string;
  chosen: boolean;
}

export interface Accommodation {
  id: string;
  name: string;
  area: string;
  check_in: string;
  check_out: string;
  price_per_night: number;
  price_currency: string;
  rooms: number;
  price_basis: PriceBasis;
  source_id: number | null;
  chosen: boolean;
}

export interface ChecklistItem {
  id: string;
  label: string;
  category: Category;
  price_per_person: number;
  price_currency: string;
  done: boolean;
}

export interface PlanWarning {
  code: string;
  message: string;
}

export interface Plan {
  title: string;
  summary: string;
  currencies: Currencies;
  days: PlanDay[];
  transport_options: TransportOption[];
  accommodation: Accommodation[];
  checklist: ChecklistItem[];
  warnings: PlanWarning[];
}

export interface Source {
  title: string;
  url: string | null;
}

export interface Trip {
  id: string;
  user_id: string;
  conversation_id: string | null;
  destination_name: string;
  destination_country: string;
  destination_lat: number;
  destination_lon: number;
  origin: string;
  start_date: string;
  end_date: string;
  travelers: number;
  group_type: GroupType;
  travel_styles: TravelStyle[];
  transport_modes: TransportMode[];
  budget_amount: string;
  budget_scope: BudgetScope;
  local_currency: string | null;
  language: Language;
  notes: string | null;
  status: TripStatus;
  stage: TripStage | null;
  failure_reason: string | null;
  plan: Plan | null;
  total_cost_vnd: string | null;
  over_budget: boolean | null;
  plan_revision: number;
  sources: Record<string, Source>;
  created_at: string;
  updated_at: string;
}

// Lists leave out the heavy fields; sources only make sense next to a plan
export type TripSummary = Omit<Trip, "plan" | "notes" | "origin" | "sources">;

export interface CreateTripBody {
  user_id: string;
  conversation_id: string | null;
  destination: { name: string; country_code: string; lat: number; lon: number };
  origin: string;
  start_date: string;
  end_date: string;
  travelers: number;
  group_type: GroupType;
  travel_styles: TravelStyle[];
  transport_modes: TransportMode[];
  budget_amount: string;
  budget_scope: BudgetScope;
  language: Language;
  notes: string | null;
}

export type RequestDraft = Partial<Omit<CreateTripBody, "user_id" | "conversation_id">> & {
  month?: string | null;
  length_days?: number | null;
};

export interface SuggestionCard {
  name: string;
  country_code: string;
  why: string;
  length_days: number;
  est_cost_per_person_vnd: string;
  best_months: string[];
  highlights: string[];
  source_ids: number[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent: MessageIntent | null;
  suggestions: SuggestionCard[] | null;
  created_at: string;
}

export interface Conversation {
  id: string;
  user_id: string;
  title: string | null;
  request_draft: RequestDraft | null;
  created_at: string;
  updated_at: string;
}

export type ConversationDetail = Conversation & { messages: Message[] };

export type ChatEvent =
  | { type: "token"; data: { text: string } }
  | { type: "plan"; data: { plan_revision: number } }
  | { type: "suggestions"; data: { cards: SuggestionCard[] } }
  | { type: "error"; data: ErrorBody }
  | { type: "done"; data: Record<string, never> };
