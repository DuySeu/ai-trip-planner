import type { Conversation, Message, Plan, Trip, User } from "../api/api.types.ts";
import { addDays, todayInVietnam, tripDays } from "../format/dates.ts";
import {
  ABROAD_TRIP_ID,
  DOMESTIC_TRIP_ID,
  FAILED_TRIP_ID,
  MINH_ID,
  planAbroad,
  planDomestic,
  SEED_CONVERSATION_ID,
  SUGGESTION_CARDS,
} from "./fixtures.ts";

// Job timeline: queued < 2 s, researching < 6 s, planning < 10 s, then done
const STAGES = [
  { status: "queued", until: 2000 },
  { status: "researching", until: 6000 },
  { status: "planning", until: 10000 },
] as const;
const DEFAULT_TOKEN_GAP_MS = 30;

// Head start that puts a re-plan straight into researching
export const REPLAN_HEAD_START_MS = 2000;

// A stored trip plus its owner and the start time of its running job
export interface MockTrip extends Trip {
  user_id: string;
  job_started_at: number | null;
}

export type MockMessage = Message & { conversation_id: string };

// In-memory backend state shared by the browser worker and the test server
export const mockDb = {
  now: (): Date => new Date(),
  quotaBlockedUntil: null as string | null,
  tokenGapMs: DEFAULT_TOKEN_GAP_MS,
  users: [] as User[],
  trips: [] as MockTrip[],
  conversations: [] as Conversation[],
  messages: [] as MockMessage[],

  // Drop everything and seed Minh: a ready domestic trip, a ready abroad trip, a failed trip, one chat
  reset(now: () => Date = () => new Date()) {
    this.now = now;
    this.quotaBlockedUntil = null;
    this.tokenGapMs = DEFAULT_TOKEN_GAP_MS;
    const iso = now().toISOString();
    const ago = (ms: number) => new Date(now().getTime() - ms).toISOString();
    const today = todayInVietnam(now());

    this.users = [{ id: MINH_ID, name: "Minh", created_at: iso, trip_count: 0 }];
    this.conversations = [
      {
        id: SEED_CONVERSATION_ID,
        user_id: MINH_ID,
        title: "Where should we go in December?",
        request_draft: {
          travelers: 4,
          travel_styles: ["nature", "food"],
          month: "2026-12",
          origin: "Hà Nội",
          budget_amount: "3000000",
          budget_scope: "per_person",
          start_date: addDays(today, 30),
          end_date: addDays(today, 33),
        },
        chat_model: null,
        created_at: ago(86_400_000),
        updated_at: ago(86_400_000),
      },
    ];
    this.messages = [
      {
        id: crypto.randomUUID(),
        conversation_id: SEED_CONVERSATION_ID,
        role: "user",
        content: "Where should we go in December? 4 friends, about 5 million each.",
        intent: null,
        metadata: null,
        created_at: ago(86_400_000),
      },
      {
        id: crypto.randomUUID(),
        conversation_id: SEED_CONVERSATION_ID,
        role: "assistant",
        content: "Here are three places that fit a cool, food-heavy December trip for four friends.",
        intent: "discover",
        metadata: { kind: "suggestions", cards: SUGGESTION_CARDS },
        created_at: ago(86_399_000),
      },
    ];

    const seed = {
      user_id: MINH_ID,
      origin: "Hồ Chí Minh",
      language: "en" as const,
      notes: null,
      stage: null,
      failure_reason: null,
      plan: null,
      total_cost_vnd: null,
      over_budget: null,
      plan_revision: 0,
      updated_at: iso,
      job_started_at: null,
    };
    const domesticStart = addDays(today, 14);
    const abroadStart = addDays(today, 40);
    const failedStart = addDays(today, 20);
    this.trips = [
      withPlan(
        {
          ...seed,
          id: DOMESTIC_TRIP_ID,
          destination: { name: "Đà Lạt", country_code: "VN", lat: 11.9404, lon: 108.4583 },
          start_date: domesticStart,
          end_date: addDays(domesticStart, 3),
          travelers: 4,
          travel_styles: ["nature", "food"],
          budget_amount: "4000000.00",
          budget_scope: "per_person",
          local_currency: null,
          status: "ready",
          created_at: ago(3_600_000),
        },
        planDomestic(domesticStart, 4),
      ),
      withPlan(
        {
          ...seed,
          id: ABROAD_TRIP_ID,
          destination: { name: "Bangkok", country_code: "TH", lat: 13.7563, lon: 100.5018 },
          start_date: abroadStart,
          end_date: addDays(abroadStart, 3),
          travelers: 2,
          travel_styles: ["culture", "food", "shopping"],
          budget_amount: "5000000.00",
          budget_scope: "per_person",
          local_currency: "THB",
          status: "ready",
          created_at: iso,
        },
        planAbroad(abroadStart, 4),
      ),
      {
        ...seed,
        id: FAILED_TRIP_ID,
        destination: { name: "Hội An", country_code: "VN", lat: 15.8801, lon: 108.338 },
        start_date: failedStart,
        end_date: addDays(failedStart, 2),
        travelers: 2,
        travel_styles: ["culture"],
        budget_amount: "8000000.00",
        budget_scope: "total",
        local_currency: null,
        status: "failed",
        failure_reason: "quota_exhausted",
        created_at: ago(7_200_000),
      },
    ];
  },

  setNow(now: () => Date) {
    this.now = now;
  },

  setQuotaBlockedUntil(iso: string | null) {
    this.quotaBlockedUntil = iso;
  },

  // Simulate a save from another tab
  bumpRevision(tripId: string) {
    const trip = this.trips.find((t) => t.id === tripId);
    if (trip) trip.plan_revision += 1;
  },

  // Start (or restart) a trip's generation job
  startJob(trip: MockTrip, headStartMs = 0) {
    trip.job_started_at = this.now().getTime() - headStartMs;
    trip.failure_reason = null;
    this.advance(trip);
  },

  // Bring a trip's job up to the clock; status is derived from the elapsed time
  advance(trip: MockTrip): MockTrip {
    if (trip.job_started_at === null) return trip;
    const elapsed = this.now().getTime() - trip.job_started_at;

    const stage = STAGES.find((s) => elapsed < s.until);
    if (stage) {
      trip.status = stage.status;
      trip.stage = stage.status === "queued" ? null : stage.status;
      return trip;
    }

    // The job is over: "#fail" in the notes fails it, otherwise a fresh plan lands
    trip.job_started_at = null;
    trip.stage = null;
    trip.updated_at = this.now().toISOString();
    if (trip.notes?.includes("#fail")) {
      trip.status = "failed";
      trip.failure_reason = "llm_budget_exceeded";
      return trip;
    }
    const days = tripDays(trip.start_date, trip.end_date);
    const plan = trip.destination.country_code === "VN" ? planDomestic(trip.start_date, days) : planAbroad(trip.start_date, days);
    Object.assign(trip, withPlan(trip, plan));
    return trip;
  },
};

// Put a plan on a trip with its totals, the budget check and a new revision
export function withPlan<T extends Trip>(trip: T, plan: Plan): T {
  const total = planTotalVnd(plan, trip.travelers);
  const budget = Number(trip.budget_amount) * (trip.budget_scope === "per_person" ? trip.travelers : 1);
  const isOver = trip.budget_amount !== null && total > budget;
  const warnings = plan.warnings.filter((w) => w.code !== "over_budget");
  return {
    ...trip,
    status: "ready",
    stage: null,
    failure_reason: null,
    plan: {
      ...plan,
      warnings: isOver ? [...warnings, { code: "over_budget", message: "The plan costs more than the budget." }] : warnings,
    },
    total_cost_vnd: total.toFixed(2),
    over_budget: isOver,
    plan_revision: trip.plan_revision + 1,
  };
}

// Group total in VND: items and checklist per person, the chosen stay per room-night
export function planTotalVnd(plan: Plan, travelers: number): number {
  const rate = plan.currencies.local_to_home_rate ?? 1;
  const vnd = (amount: number, currency: string) => (currency === "VND" ? amount : amount * rate);
  const perPerson = [
    ...plan.days.flatMap((d) => d.items).map((i) => vnd(i.price_per_person, i.price_currency)),
    ...plan.checklist.map((c) => vnd(c.price_per_person, c.price_currency)),
  ].reduce((sum, x) => sum + x, 0);
  const stay = plan.accommodation
    .filter((a) => a.chosen)
    .reduce((sum, a) => sum + vnd(a.price_per_night, a.price_currency) * a.rooms * (tripDays(a.check_in, a.check_out) - 1), 0);
  return Math.round(perPerson * travelers + stay);
}
