import type {
  Category,
  CurrentLocation,
  FlightCard,
  HealthStats,
  HotelCard,
  ItemStatus,
  ModelsInfo,
  Place,
  Plan,
  PlanDay,
  PriceBasis,
  SuggestionCard,
  TransportMode,
  UsageDays,
  UsageStats,
} from "../api/api.types.ts";
import { addDays } from "../format/dates.ts";

export const MINH_ID = "6f1c2b9e-0d4a-4c1e-9a51-3b7e2f0a1c01";
export const DOMESTIC_TRIP_ID = "1b8e4c2a-7d3f-4a9b-8e21-5c6d7e8f9a02";
export const ABROAD_TRIP_ID = "2c9f5d3b-8e4a-4b0c-9f32-6d7e8f9a0b03";
export const FAILED_TRIP_ID = "3d0a6e4c-9f5b-4c1d-a043-7e8f9a0b1c04";
export const SEED_CONVERSATION_ID = "4e1b7f5d-a06c-4d2e-b154-8f9a0b1c2d05";
export const THB_RATE = 720.5;
export const RATE_DATE = "2026-11-16";

export const CURRENT_LOCATION: CurrentLocation = {
  city: "Thành phố Hồ Chí Minh",
  country_code: "VN",
  weather: { temperature_c: 28.4, weather_code: 1, summary: "Mainly clear" },
};

export const PLACES: Place[] = [
  { name: "Hà Nội", country_code: "VN", admin1: "Hà Nội", lat: 21.0245, lon: 105.8412 },
  { name: "Hồ Chí Minh", country_code: "VN", admin1: "Hồ Chí Minh", lat: 10.8231, lon: 106.6297 },
  { name: "Đà Nẵng", country_code: "VN", admin1: "Đà Nẵng", lat: 16.0678, lon: 108.2208 },
  { name: "Đà Lạt", country_code: "VN", admin1: "Lâm Đồng", lat: 11.9404, lon: 108.4583 },
  { name: "Hội An", country_code: "VN", admin1: "Quảng Nam", lat: 15.8801, lon: 108.338 },
  { name: "Phú Quốc", country_code: "VN", admin1: "Kiên Giang", lat: 10.2899, lon: 103.984 },
  { name: "Sa Pa", country_code: "VN", admin1: "Lào Cai", lat: 22.3364, lon: 103.8438 },
  { name: "Bangkok", country_code: "TH", admin1: "Bangkok", lat: 13.7563, lon: 100.5018 },
  { name: "Chiang Mai", country_code: "TH", admin1: "Chiang Mai", lat: 18.7883, lon: 98.9853 },
  { name: "Singapore", country_code: "SG", admin1: null, lat: 1.2897, lon: 103.8501 },
  { name: "Tokyo", country_code: "JP", admin1: "Tokyo", lat: 35.6895, lon: 139.6917 },
  { name: "Seoul", country_code: "KR", admin1: "Seoul", lat: 37.5665, lon: 126.978 },
  { name: "Paris", country_code: "FR", admin1: "Île-de-France", lat: 48.8534, lon: 2.3488 },
];

export const HOTEL_CARDS: HotelCard[] = [
  {
    name: "Mercure Hai Phong",
    area: "Ngô Quyền",
    stars: 4,
    price_per_night: 1450000,
    price_currency: "VND",
    highlights: ["Outdoor pool", "Near Vincom"],
    source_id: 101,
    url: "https://www.booking.com/hotel/vn/mercure-hai-phong.html",
  },
  {
    name: "The Light Hotel",
    area: "Lê Hồng Phong",
    stars: 4,
    price_per_night: null,
    price_currency: "VND",
    highlights: ["Rooftop bar"],
    source_id: 102,
    url: "https://www.agoda.com/the-light-hotel/hotel/haiphong-vn.html",
  },
];

export const FLIGHT_CARDS: FlightCard[] = [
  {
    carrier: "Vietnam Airlines",
    mode: "flight",
    route: "Hà Nội - Đà Nẵng",
    duration_text: "1h 20m",
    price_from: 1290000,
    price_currency: "VND",
    highlights: ["Daily flights"],
    source_id: 201,
    url: "https://www.traveloka.com/vi-vn/flight/han-dad",
  },
  {
    carrier: "Vietnam Railways",
    mode: "train",
    route: "Hà Nội - Đà Nẵng",
    duration_text: "",
    price_from: null,
    price_currency: "VND",
    highlights: [],
    source_id: 202,
    url: "https://dsvn.vn/",
  },
];

export const SUGGESTION_CARDS: SuggestionCard[] = [
  {
    name: "Đà Lạt",
    country_code: "VN",
    why: "Cool weather in December, pine hills and a lively night market, one overnight bus from Saigon.",
    length_days: 4,
    est_cost_per_person_vnd: "3500000",
    best_months: ["December", "January", "February", "March"],
    highlights: ["Langbiang", "Night market", "Coffee farms"],
    source_ids: [1, 2],
  },
  {
    name: "Phú Quốc",
    country_code: "VN",
    why: "The dry season starts in November, the west coast sea is calm and seafood is cheap.",
    length_days: 5,
    est_cost_per_person_vnd: "6000000",
    best_months: ["November", "December", "January", "February"],
    highlights: ["Sao beach", "Night market", "Hòn Thơm cable car"],
    source_ids: [],
  },
  {
    name: "Chiang Mai",
    country_code: "TH",
    why: "Temples, mountain day trips and street food, with cool dry mornings in December.",
    length_days: 5,
    est_cost_per_person_vnd: "9000000",
    best_months: ["November", "December", "January"],
    highlights: ["Doi Suthep", "Old City temples", "Sunday walking street"],
    source_ids: [],
  },
];

// [start, end, title, location, category, price, currency, basis, extras]
type Row = [
  string,
  string,
  string,
  string,
  Category,
  number,
  string,
  PriceBasis,
  { mode?: TransportMode; sourceId?: number; status?: ItemStatus; note?: string; optionId?: string }?,
];

interface Recipe {
  arrival: Row[];
  middle: Row[][];
  departure: Row[];
  themes: { arrival: string; middle: string[]; departure: string };
  weather: { summary: string; min: number; max: number; precip: number };
}

const DALAT: Recipe = {
  arrival: [
    ["06:30", "13:00", "Sleeper bus Sài Gòn to Đà Lạt", "Miền Đông bus station", "transport", 300000, "VND", "source", { mode: "bus", sourceId: 1, status: "booked", optionId: "tr_1" }],
    ["14:00", "15:00", "Check in at Dalat Wonder Resort", "Tuyền Lâm lake", "accommodation", 0, "VND", "estimate"],
    ["18:00", "19:30", "Dinner at the night market", "Chợ đêm Đà Lạt", "food", 150000, "VND", "estimate", { note: "It drops to 14 °C after dark; bring a jacket." }],
  ],
  middle: [
    [
      ["08:00", "11:00", "Langbiang mountain by jeep", "Lạc Dương", "sightseeing", 150000, "VND", "source", { sourceId: 3 }],
      ["12:00", "13:00", "Lunch: bánh căn at Nhà Chung", "Nhà Chung street", "food", 60000, "VND", "estimate"],
      ["15:00", "17:30", "Coffee at a hillside farm", "Cầu Đất", "food", 80000, "VND", "estimate"],
    ],
    [
      ["07:30", "10:30", "Datanla waterfall and alpine coaster", "Đèo Prenn", "sightseeing", 250000, "VND", "estimate"],
      ["12:00", "13:00", "Lunch: lẩu gà lá é", "Tao Ngộ", "food", 120000, "VND", "estimate"],
      ["16:00", "18:00", "Strawberry farm and local market", "Trại Mát", "shopping", 100000, "VND", "estimate"],
    ],
  ],
  departure: [
    ["09:00", "11:00", "Souvenirs at Đà Lạt market", "Chợ Đà Lạt", "shopping", 200000, "VND", "estimate"],
    ["13:00", "19:30", "Sleeper bus Đà Lạt to Sài Gòn", "Đà Lạt bus station", "transport", 300000, "VND", "source", { mode: "bus", sourceId: 1, status: "paid", optionId: "tr_3" }],
  ],
  themes: { arrival: "Arrival and the night market", middle: ["Mountains and coffee", "Waterfalls and farms"], departure: "Market morning, bus home" },
  weather: { summary: "Sunny spells", min: 14, max: 23, precip: 2 },
};

const BANGKOK: Recipe = {
  arrival: [
    ["07:00", "08:30", "Flight SGN to BKK", "Tân Sơn Nhất airport", "transport", 2400000, "VND", "source", { mode: "flight", sourceId: 4, status: "paid", optionId: "tr_11" }],
    ["11:00", "12:00", "Check in at Sukhumvit 11 Boutique Hotel", "Sukhumvit Soi 11", "accommodation", 0, "THB", "estimate"],
    ["18:30", "20:30", "Street food in Yaowarat", "Chinatown", "food", 400, "THB", "estimate"],
  ],
  middle: [
    [
      ["08:30", "11:30", "Grand Palace and Wat Phra Kaew", "Phra Nakhon", "sightseeing", 500, "THB", "source", { sourceId: 5 }],
      ["12:00", "13:00", "Lunch: boat noodles", "Victory Monument", "food", 120, "THB", "estimate"],
      ["17:00", "18:30", "Thai massage", "Sukhumvit Soi 11", "service", 350, "THB", "source", { sourceId: 6 }],
    ],
    [
      ["09:00", "13:00", "Chatuchak weekend market", "Chatuchak", "shopping", 300, "THB", "estimate"],
      ["16:00", "18:00", "Wat Arun at sunset", "Bangkok Yai", "sightseeing", 200, "THB", "estimate"],
      ["19:00", "20:30", "Dinner cruise on the Chao Phraya", "Asiatique pier", "food", 1500, "THB", "estimate"],
    ],
  ],
  departure: [
    ["09:00", "11:00", "Last coffee and packing", "Sukhumvit", "food", 150, "THB", "estimate"],
    ["15:00", "16:30", "Flight BKK to SGN", "Suvarnabhumi airport", "transport", 2300000, "VND", "source", { mode: "flight", sourceId: 4, optionId: "tr_13" }],
  ],
  themes: { arrival: "Arrival and Chinatown", middle: ["Old town temples", "Markets and the river"], departure: "Fly home" },
  weather: { summary: "Hot and dry", min: 24, max: 32, precip: 0 },
};

// A Đà Lạt plan, all in VND
export function planDomestic(start: string, days: number): Plan {
  const last = addDays(start, days - 1);
  return {
    title: `Đà Lạt in ${days} days with friends`,
    summary: "Cool mountain air, pine forests and night-market food. A sleeper bus both ways keeps the cost down.",
    currencies: { home: "VND", local: null, local_to_home_rate: null, rate_date: null },
    days: layOut(start, days, DALAT),
    transport_options: [
      { id: "tr_1", leg: "outbound", mode: "bus", summary: "Phương Trang sleeper bus, Sài Gòn to Đà Lạt", depart: `${start}T06:30`, duration_minutes: 390, price_per_person: 300000, price_currency: "VND", price_basis: "source", source_id: 1, pros: "Cheapest; stops in the city centre", cons: "Six and a half hours of mountain road", chosen: true },
      { id: "tr_2", leg: "outbound", mode: "flight", summary: "Vietjet SGN to DLI", depart: `${start}T07:15`, duration_minutes: 55, price_per_person: 1500000, price_currency: "VND", price_basis: "estimate", source_id: null, pros: "Under an hour in the air", cons: "Five times the bus fare; the airport is 30 km out", chosen: false },
      { id: "tr_3", leg: "return", mode: "bus", summary: "Phương Trang sleeper bus, Đà Lạt to Sài Gòn", depart: `${last}T13:00`, duration_minutes: 390, price_per_person: 300000, price_currency: "VND", price_basis: "source", source_id: 1, pros: "Cheapest", cons: "A long ride after a long trip", chosen: true },
      { id: "tr_4", leg: "return", mode: "flight", summary: "Vietjet DLI to SGN", depart: `${last}T17:40`, duration_minutes: 55, price_per_person: 1400000, price_currency: "VND", price_basis: "estimate", source_id: null, pros: "An extra afternoon in Đà Lạt", cons: "Costs more", chosen: false },
      { id: "tr_5", leg: "local", mode: "motorbike", summary: "Rent motorbikes in town", depart: null, duration_minutes: null, price_per_person: 120000, price_currency: "VND", price_basis: "estimate", source_id: null, pros: "Go anywhere on your own time", cons: "Steep roads and cold mornings", chosen: true },
    ],
    accommodation: [
      { id: "ac_1", name: "Dalat Wonder Resort", area: "Tuyền Lâm lake", check_in: start, check_out: last, price_per_night: 1200000, price_currency: "VND", rooms: 2, price_basis: "source", source_id: 2, chosen: true },
      { id: "ac_2", name: "Pine Hill Homestay", area: "Phường 3", check_in: start, check_out: last, price_per_night: 600000, price_currency: "VND", rooms: 2, price_basis: "estimate", source_id: null, chosen: false },
    ],
    checklist: [
      { id: "ck_1", label: "Book the sleeper bus seats", category: "transport", price_per_person: 0, price_currency: "VND", done: true },
      { id: "ck_2", label: "Rent motorbikes for 2 days", category: "transport", price_per_person: 120000, price_currency: "VND", done: false },
      { id: "ck_3", label: "Pack a warm jacket", category: "service", price_per_person: 0, price_currency: "VND", done: false },
    ],
    warnings: [],
  };
}

// A Bangkok plan: flights in VND, everything on the ground in THB
export function planAbroad(start: string, days: number): Plan {
  const last = addDays(start, days - 1);
  return {
    title: `Bangkok in ${days} days`,
    summary: "Temples in the morning, markets and street food at night. Flights are priced in VND, the rest in baht.",
    currencies: { home: "VND", local: "THB", local_to_home_rate: THB_RATE, rate_date: RATE_DATE },
    days: layOut(start, days, BANGKOK),
    transport_options: [
      { id: "tr_11", leg: "outbound", mode: "flight", summary: "Vietjet SGN to BKK", depart: `${start}T07:00`, duration_minutes: 90, price_per_person: 2400000, price_currency: "VND", price_basis: "source", source_id: 4, pros: "Fast, morning arrival", cons: "Checked bags cost extra", chosen: true },
      { id: "tr_12", leg: "outbound", mode: "bus", summary: "Overland bus through Phnom Penh", depart: `${addDays(start, -1)}T06:00`, duration_minutes: 1500, price_per_person: 1100000, price_currency: "VND", price_basis: "estimate", source_id: null, pros: "Half the price", cons: "A full day and two border crossings", chosen: false },
      { id: "tr_13", leg: "return", mode: "flight", summary: "Vietjet BKK to SGN", depart: `${last}T15:00`, duration_minutes: 90, price_per_person: 2300000, price_currency: "VND", price_basis: "source", source_id: 4, pros: "Afternoon departure", cons: "Rush hour on the way to the airport", chosen: true },
      { id: "tr_14", leg: "return", mode: "bus", summary: "Overland bus through Phnom Penh", depart: `${last}T06:00`, duration_minutes: 1500, price_per_person: 1100000, price_currency: "VND", price_basis: "estimate", source_id: null, pros: "Cheaper", cons: "Very long", chosen: false },
      { id: "tr_15", leg: "local", mode: "train", summary: "BTS Skytrain day passes", depart: null, duration_minutes: null, price_per_person: 150, price_currency: "THB", price_basis: "estimate", source_id: null, pros: "Beats the traffic", cons: "Does not reach the old town", chosen: true },
    ],
    accommodation: [
      { id: "ac_11", name: "Sukhumvit 11 Boutique Hotel", area: "Sukhumvit", check_in: start, check_out: last, price_per_night: 1800, price_currency: "THB", rooms: 1, price_basis: "estimate", source_id: null, chosen: true },
    ],
    checklist: [
      { id: "ck_11", label: "Buy a Rabbit card for the BTS", category: "transport", price_per_person: 200, price_currency: "THB", done: false },
      { id: "ck_12", label: "Travel insurance", category: "service", price_per_person: 350000, price_currency: "VND", done: false },
      { id: "ck_13", label: "Check passports are valid for 6 more months", category: "service", price_per_person: 0, price_currency: "VND", done: true },
    ],
    warnings: [],
  };
}

// Spread a recipe over the trip dates: arrival day, rotating middle days, departure day
function layOut(start: string, days: number, recipe: Recipe): PlanDay[] {
  let nextId = 1;
  return Array.from({ length: days }, (_, index) => {
    const isFirst = index === 0;
    const isLast = index === days - 1;
    const middle = recipe.middle[(index - 1) % recipe.middle.length] ?? [];
    const rows = [...(isFirst ? recipe.arrival : []), ...(!isFirst && !isLast ? middle : []), ...(isLast ? recipe.departure : [])];
    const theme = isFirst
      ? recipe.themes.arrival
      : isLast
        ? recipe.themes.departure
        : (recipe.themes.middle[(index - 1) % recipe.themes.middle.length] ?? "");

    return {
      date: addDays(start, index),
      theme,
      weather: {
        summary: recipe.weather.summary,
        temp_min_c: recipe.weather.min + (index % 2),
        temp_max_c: recipe.weather.max - (index % 3),
        precip_mm: recipe.weather.precip + (index % 2),
        // The last day is past the 16-day forecast in the seeds, so it shows typical weather
        basis: isLast && days > 1 ? "typical" : "forecast",
      },
      items: rows.map(([startTime, endTime, title, location, category, price, currency, basis, extra = {}]) => ({
        id: `it_${nextId++}`,
        start_time: startTime,
        end_time: endTime,
        title,
        description: null,
        location,
        category,
        transport_mode: extra.mode ?? null,
        price_per_person: price,
        price_currency: currency,
        price_basis: basis,
        source_id: extra.sourceId ?? null,
        status: extra.status ?? "planned",
        note: extra.note ?? null,
        option_id: extra.optionId ?? null,
      })),
    };
  });
}

// GET /models: two OpenRouter chat models; "Auto" stands for the first
export const LIGHTNING_MODEL = { id: "nvidia/nemotron-3.5-lightning:free", label: "NVIDIA: Nemotron 3.5 Lightning (free)" };
export const MODELS: ModelsInfo = {
  provider: "openrouter",
  default_model: "google/gemma-4-31b-it:free",
  models: [{ id: "google/gemma-4-31b-it:free", label: "Google: Gemma 4 31B (free)" }, LIGHTNING_MODEL],
};

// GET /stats/health: near the new-trip ceiling, a few errors in the last hour, nothing blocked
export const HEALTH_STATS: HealthStats = {
  generated_at: "2026-11-24T12:00:00Z",
  llm_today: { calls: 412, input_tokens: 820_000, output_tokens: 190_000, ceiling_new_trips: 800, ceiling_chat: 950 },
  llm_last_hour: {
    calls: 64,
    errors: 3,
    outcomes: [
      { key: "ok", count: 61 },
      { key: "rate_limited", count: 3 },
    ],
    p50_latency_ms: 2100,
    p95_latency_ms: 8200,
  },
  jobs: { queued: 1, running: 1, oldest_queued_s: 40 },
  plans_last_day: { succeeded: 18, p50_s: 48, p95_s: 110, failed: 1, last_failure: { reason: "generation_failed", finished_at: "2026-11-24T10:20:00Z" } },
  blocks: [],
};

// GET /stats/usage: a daily series of `days` entries ending today
export function usageStats(days: UsageDays, today: string): UsageStats {
  return {
    days,
    users: { total: 310, new: 42, active: 96 },
    trips: {
      created: 118,
      by_status: [
        { key: "ready", count: 107 },
        { key: "failed", count: 7 },
        { key: "planning", count: 4 },
      ],
      domestic: 85,
      abroad: 33,
      avg_days: 4.2,
      avg_travelers: 2.3,
      median_budget_per_person_vnd: 6_000_000,
      with_plan: 107,
      over_budget: 19,
    },
    daily: Array.from({ length: days }, (_, i) => ({ day: addDays(today, i - days + 1), trips: (i * 7) % 9, messages: (i * 13) % 50 })),
    conversations: 204,
    messages: 1204,
    intents: [
      { key: "advice", count: 600 },
      { key: "discover", count: 210 },
      { key: "booking_search", count: 150 },
      { key: "create_trip", count: 90 },
      { key: "edit_plan", count: 60 },
    ],
    trip_forms: [
      { key: "created", count: 30 },
      { key: "open", count: 15 },
      { key: "canceled", count: 6 },
    ],
    destinations: [
      { name: "Đà Lạt", country: "VN", trips: 21 },
      { name: "Bangkok", country: "TH", trips: 14 },
      { name: "Phú Quốc", country: "VN", trips: 9 },
    ],
    styles: [
      { key: "food", count: 72 },
      { key: "nature", count: 52 },
      { key: "culture", count: 45 },
    ],
    models: [
      { model_id: "meta-llama/llama-3.3-70b-instruct:free", calls: 4100, errors: 250 },
      { model_id: "qwen/qwen-2.5-72b-instruct:free", calls: 2300, errors: 260 },
    ],
  };
}
