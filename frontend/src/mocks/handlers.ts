import { HttpResponse, http } from "msw";
import {
  type ApiResponse,
  type ChatEvent,
  type Conversation,
  type CreateTripBody,
  GROUP_TYPES,
  type Message,
  type RequestDraft,
  TRAVEL_STYLES,
  type Trip,
  type User,
} from "../api/api.types.ts";
import { apiUrl } from "../api/client.ts";
import { addDays, todayInVietnam, tripDays } from "../format/dates.ts";
import { COUNTRY_CURRENCY } from "../format/money.ts";
import { scriptReply } from "./chatScript.ts";
import { PLACES } from "./fixtures.ts";
import { type MockMessage, type MockTrip, mockDb, REPLAN_HEAD_START_MS } from "./mockDb.ts";

const MAX_NAME = 50;
const MAX_TRIP_DAYS = 30;
const MAX_TRAVELERS = 50;
const MAX_NOTES = 2000;
const MAX_MESSAGE = 4000;
const MAX_TITLE = 80;
const MAX_PLACES = 10;
const TITLE_LENGTH = 80;
const DEFAULT_LIMIT = 50;
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

// Every route of spec "API" except /health and /ready
export const handlers = [
  // POST /users - Claim a name, or return the user who has it
  http.post(apiUrl("/users"), async ({ request }) => {
    const { name } = (await request.json()) as { name?: unknown };
    const clean = typeof name === "string" ? name.normalize("NFC").trim() : "";
    if (clean.length < 1 || clean.length > MAX_NAME) return fail(422, "invalid_request", "Name must be 1 to 50 characters");

    const existing = mockDb.users.find((u) => nameKey(u.name) === nameKey(clean));
    if (existing) return ok(withTripCount(existing));
    const user: User = { id: crypto.randomUUID(), name: clean, created_at: mockDb.now().toISOString(), trip_count: 0 };
    mockDb.users.push(user);
    return ok(user, 201);
  }),

  // GET /users/:userId - User and trip count
  http.get(apiUrl("/users/:userId"), ({ params }) => {
    const user = mockDb.users.find((u) => u.id === params.userId);
    return user ? ok(withTripCount(user)) : notFound();
  }),

  // GET /users/:userId/trips - Trips, newest first, paged
  http.get(apiUrl("/users/:userId/trips"), ({ params, request }) => {
    if (!mockDb.users.some((u) => u.id === params.userId)) return notFound();
    const trips = mockDb.trips
      .filter((t) => t.user_id === params.userId)
      .map((t) => mockDb.advance(t))
      .toSorted((a, b) => b.created_at.localeCompare(a.created_at))
      .map(({ plan: _p, notes: _n, origin: _o, sources: _s, job_started_at: _j, ...summary }) => summary);
    return page(trips, request);
  }),

  // GET /users/:userId/conversations - Conversations, newest first
  http.get(apiUrl("/users/:userId/conversations"), ({ params, request }) => {
    if (!mockDb.users.some((u) => u.id === params.userId)) return notFound();
    const rows = mockDb.conversations
      .filter((c) => c.user_id === params.userId)
      .toSorted((a, b) => b.updated_at.localeCompare(a.updated_at));
    return page(rows, request);
  }),

  // POST /conversations - Start a conversation, optionally with the form's draft
  http.post(apiUrl("/conversations"), async ({ request }) => {
    const body = (await request.json()) as { user_id?: string; draft?: RequestDraft | null };
    const user = mockDb.users.find((u) => u.id === body.user_id);
    if (!user) return notFound();
    const iso = mockDb.now().toISOString();
    const conversation: Conversation = {
      id: crypto.randomUUID(),
      user_id: user.id,
      title: null,
      request_draft: body.draft ?? null,
      created_at: iso,
      updated_at: iso,
    };
    mockDb.conversations.push(conversation);
    return ok(conversation, 201);
  }),

  // GET /conversations/:conversationId - Conversation, draft and messages
  http.get(apiUrl("/conversations/:conversationId"), ({ params }) => {
    const conversation = mockDb.conversations.find((c) => c.id === params.conversationId);
    if (!conversation) return notFound();
    const messages = mockDb.messages
      .filter((m) => m.conversation_id === conversation.id)
      .map(({ conversation_id: _c, ...m }) => m);
    return ok({ ...conversation, messages });
  }),

  // PATCH /conversations/:conversationId - Rename; updated_at stays, so the list order does not change
  http.patch(apiUrl("/conversations/:conversationId"), async ({ params, request }) => {
    const conversation = mockDb.conversations.find((c) => c.id === params.conversationId);
    if (!conversation) return notFound();
    const body = (await request.json()) as { title?: unknown };
    const title = typeof body.title === "string" ? body.title.normalize("NFC").trim() : "";
    if (title.length < 1 || title.length > MAX_TITLE) return fail(422, "invalid_request", "Title must be 1 to 80 characters");
    conversation.title = title;
    return ok(conversation);
  }),

  // DELETE /conversations/:conversationId - Delete with its messages; trips made from it stay
  http.delete(apiUrl("/conversations/:conversationId"), ({ params }) => {
    const conversation = mockDb.conversations.find((c) => c.id === params.conversationId);
    if (!conversation) return notFound();
    mockDb.conversations = mockDb.conversations.filter((c) => c.id !== conversation.id);
    mockDb.messages = mockDb.messages.filter((m) => m.conversation_id !== conversation.id);
    for (const trip of mockDb.trips) if (trip.conversation_id === conversation.id) trip.conversation_id = null;
    return new HttpResponse(null, { status: 204 });
  }),

  // POST /conversations/:conversationId/messages - Send a message; the reply is an SSE stream
  http.post(apiUrl("/conversations/:conversationId/messages"), async ({ params, request }) => {
    const conversation = mockDb.conversations.find((c) => c.id === params.conversationId);
    if (!conversation) return notFound();
    const body = (await request.json()) as { content?: string; trip_id?: string | null; plan_revision?: number | null };
    const content = (body.content ?? "").trim();
    if (content.length < 1 || content.length > MAX_MESSAGE) return fail(422, "invalid_request", "Message must be 1 to 4000 characters");

    // The trip on screen must be the user's, have a plan, and be at the revision the client saw
    let trip: MockTrip | null = null;
    if (body.trip_id) {
      const found = mockDb.trips.find((t) => t.id === body.trip_id && t.user_id === conversation.user_id);
      if (!found) return notFound();
      trip = mockDb.advance(found);
      if (trip.plan === null) return fail(409, "conflict", "The trip has no plan yet");
      if (body.plan_revision != null && body.plan_revision !== trip.plan_revision) return fail(409, "conflict", "The plan changed");
    }
    const blocked = quotaBlocked();
    if (blocked) return blocked;

    // Save the user message; the first one names the conversation
    const iso = mockDb.now().toISOString();
    mockDb.messages.push(row(conversation.id, "user", content, null, null, iso));
    conversation.title ??= content.slice(0, TITLE_LENGTH);
    conversation.updated_at = iso;

    // Apply the reply's trip change before streaming, like the backend does
    const reply = scriptReply({ content, trip, conversation });
    if (trip && reply.updatedTrip) {
      Object.assign(trip, reply.updatedTrip);
      if (reply.updatedTrip.status === "researching") mockDb.startJob(trip, REPLAN_HEAD_START_MS);
    }
    if (reply.intent === "suggest") conversation.request_draft = discoveryDraft(conversation.request_draft);

    return new HttpResponse(sse(conversation.id, reply.events, reply.intent, request.signal), {
      headers: { "Content-Type": "text/event-stream" },
    });
  }),

  // GET /places - Destination search, ignoring case and accents
  http.get(apiUrl("/places"), ({ request }) => {
    const q = fold(new URL(request.url).searchParams.get("q") ?? "");
    if (q.length < 2) return fail(422, "invalid_request", "Type at least 2 characters");
    return ok(PLACES.filter((p) => fold(p.name).startsWith(q)).slice(0, MAX_PLACES));
  }),

  // POST /trips - Create a trip and queue its generation
  http.post(apiUrl("/trips"), async ({ request }) => {
    const body = (await request.json()) as CreateTripBody;
    if (!mockDb.users.some((u) => u.id === body.user_id)) return notFound();
    const blocked = quotaBlocked();
    if (blocked) return blocked;
    const problem = firstBrokenRule(body);
    if (problem) return fail(422, "invalid_request", problem);

    const iso = mockDb.now().toISOString();
    const country = body.destination.country_code;
    const trip: MockTrip = {
      id: crypto.randomUUID(),
      user_id: body.user_id,
      conversation_id: body.conversation_id,
      destination_name: body.destination.name,
      destination_country: country,
      destination_lat: body.destination.lat,
      destination_lon: body.destination.lon,
      origin: body.origin.trim(),
      start_date: body.start_date,
      end_date: body.end_date,
      travelers: body.travelers,
      group_type: body.group_type,
      travel_styles: body.travel_styles,
      transport_modes: body.transport_modes,
      budget_amount: Number(body.budget_amount).toFixed(2),
      budget_scope: body.budget_scope,
      local_currency: country === "VN" ? null : (COUNTRY_CURRENCY[country] ?? null),
      language: body.language,
      notes: body.notes,
      status: "queued",
      stage: null,
      failure_reason: null,
      plan: null,
      total_cost_vnd: null,
      over_budget: null,
      plan_revision: 0,
      sources: {},
      created_at: iso,
      updated_at: iso,
      job_started_at: null,
    };
    mockDb.trips.push(trip);
    mockDb.startJob(trip);
    return ok(publicTrip(trip), 202);
  }),

  // GET /trips/:tripId - Trip, status, stage and current plan
  http.get(apiUrl("/trips/:tripId"), ({ params }) => {
    const trip = mockDb.trips.find((t) => t.id === params.tripId);
    return trip ? ok(publicTrip(mockDb.advance(trip))) : notFound();
  }),

  // POST /trips/:tripId/retry - Queue generation again after a failure
  http.post(apiUrl("/trips/:tripId/retry"), ({ params }) => {
    const trip = mockDb.trips.find((t) => t.id === params.tripId);
    if (!trip) return notFound();
    if (mockDb.advance(trip).status !== "failed") return fail(409, "conflict", "A job is already running");
    const blocked = quotaBlocked();
    if (blocked) return blocked;
    mockDb.startJob(trip);
    return ok(publicTrip(trip), 202);
  }),

  // DELETE /trips/:tripId - Delete a trip
  http.delete(apiUrl("/trips/:tripId"), ({ params }) => {
    const count = mockDb.trips.length;
    mockDb.trips = mockDb.trips.filter((t) => t.id !== params.tripId);
    return mockDb.trips.length === count ? notFound() : new HttpResponse(null, { status: 204 });
  }),

  // GET /trips/:tripId/export.xlsx - Download the current plan (a placeholder file here)
  http.get(apiUrl("/trips/:tripId/export.xlsx"), ({ params }) => {
    const trip = mockDb.trips.find((t) => t.id === params.tripId);
    if (!trip) return notFound();
    if (mockDb.advance(trip).plan === null) return fail(409, "conflict", "The trip has no plan yet");
    const filename = fold(trip.destination_name).replace(/[^a-z0-9 _-]/g, "").trim() || "trip";
    return new HttpResponse(new Blob([`Mock export: ${trip.destination_name}`], { type: XLSX }), {
      headers: { "Content-Type": XLSX, "Content-Disposition": `attachment; filename="${filename}.xlsx"` },
    });
  }),
];

// Success envelope
function ok<T>(data: T, status = 200) {
  return HttpResponse.json({ success: true, data, error: null, meta: null } satisfies ApiResponse<T>, { status });
}

// Error envelope
function fail(status: number, code: string, message: string, blockedUntil?: string) {
  const error = blockedUntil ? { code, message, blocked_until: blockedUntil } : { code, message };
  return HttpResponse.json({ success: false, data: null, error, meta: null } satisfies ApiResponse<never>, { status });
}

// 404 envelope
function notFound() {
  return fail(404, "not_found", "Not found");
}

// One page of a list, with meta
function page<T>(rows: T[], request: Request) {
  const params = new URL(request.url).searchParams;
  const limit = Number(params.get("limit") ?? DEFAULT_LIMIT);
  const offset = Number(params.get("offset") ?? 0);
  return HttpResponse.json({
    success: true,
    data: rows.slice(offset, offset + limit),
    error: null,
    meta: { total: rows.length, limit, offset },
  } satisfies ApiResponse<T[]>);
}

// 429 quota_exhausted while the free AI quota is blocked
function quotaBlocked() {
  const until = mockDb.quotaBlockedUntil;
  if (until === null || Date.parse(until) <= mockDb.now().getTime()) return null;
  return fail(429, "quota_exhausted", `Free AI quota is used up until ${until}`, until);
}

// A trip as the API returns it
function publicTrip({ job_started_at: _j, ...trip }: MockTrip): Trip {
  return trip;
}

// A user with the number of trips they own
function withTripCount(user: User): User {
  return { ...user, trip_count: mockDb.trips.filter((t) => t.user_id === user.id).length };
}

// The unique-name key: NFC, trimmed, lowercase
function nameKey(name: string): string {
  return name.normalize("NFC").trim().toLowerCase();
}

// Lowercase without accents, for search and file names
function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").replace(/đ/gi, "d").toLowerCase().trim();
}

// The first trip rule the body breaks (spec "Validation rules for a trip request")
function firstBrokenRule(body: CreateTripBody): string | null {
  const today = todayInVietnam(mockDb.now());
  const place = body.destination;
  if (!place?.name || !Number.isFinite(place.lat) || !Number.isFinite(place.lon) || !COUNTRY_CURRENCY[place.country_code]) {
    return "Pick the destination from the search";
  }
  if (!body.start_date || body.start_date < today) return "The trip cannot start in the past";
  if (!body.end_date || body.end_date < body.start_date) return "The end date is before the start date";
  if (tripDays(body.start_date, body.end_date) > MAX_TRIP_DAYS) return "A trip can be at most 30 days";
  if (!Number.isInteger(body.travelers) || body.travelers < 1 || body.travelers > MAX_TRAVELERS) return "Travelers must be 1 to 50";
  if (!GROUP_TYPES.includes(body.group_type)) return "Unknown group type";
  if (body.travel_styles.length === 0 || !body.travel_styles.every((s) => TRAVEL_STYLES.includes(s))) {
    return "Pick at least one travel style";
  }
  if (!(Number(body.budget_amount) > 0)) return "The budget must be above 0";
  if (body.language !== "en" && body.language !== "vi") return "Unknown language";
  if ((body.notes ?? "").length > MAX_NOTES) return "Notes can be at most 2000 characters";
  return null;
}

// What a discovery chat has gathered so far, kept on the conversation
function discoveryDraft(draft: RequestDraft | null): RequestDraft {
  return {
    origin: "Hồ Chí Minh",
    travelers: 4,
    group_type: "friends",
    travel_styles: ["nature", "food"],
    budget_amount: "5000000",
    budget_scope: "per_person",
    start_date: addDays(todayInVietnam(mockDb.now()), 30),
    length_days: 4,
    ...draft,
  };
}

// A stored message row
function row(
  conversationId: string,
  role: Message["role"],
  content: string,
  intent: Message["intent"],
  suggestions: Message["suggestions"],
  createdAt: string,
): MockMessage {
  return { id: crypto.randomUUID(), conversation_id: conversationId, role, content, intent, suggestions, created_at: createdAt };
}

// Write the events as SSE frames with a gap between tokens; save the assistant message on done
function sse(conversationId: string, events: ChatEvent[], intent: Message["intent"], signal: AbortSignal) {
  const encoder = new TextEncoder();
  let isCancelled = false;
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      let text = "";
      let cards: Message["suggestions"] = null;
      for (const event of events) {
        if (event.type === "token") {
          text += event.data.text;
          if (mockDb.tokenGapMs > 0) await new Promise((resolve) => setTimeout(resolve, mockDb.tokenGapMs));
        }
        if (isCancelled || signal.aborted) return;
        if (event.type === "suggestions") cards = event.data.cards;
        if (event.type === "done") {
          mockDb.messages.push(row(conversationId, "assistant", text.trim(), intent, cards, mockDb.now().toISOString()));
        }
        controller.enqueue(encoder.encode(`event: ${event.type}\ndata: ${JSON.stringify(event.data)}\n\n`));
      }
      controller.close();
    },
    cancel() {
      isCancelled = true;
    },
  });
}
