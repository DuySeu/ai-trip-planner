import { HttpResponse, http } from "msw";
import {
  type ApiResponse,
  type ChatEvent,
  type Conversation,
  type CreateTripBody,
  type FlightDates,
  type HotelDates,
  type Message,
  type RequestDraft,
  TRAVEL_STYLES,
  type Trip,
  type TripCreated,
  type TripFormMeta,
  type TripSummary,
  type User,
} from "../api/api.types.ts";
import { apiUrl } from "../api/client.ts";
import { IP_LOCATION_URL } from "../api/location.ts";
import { addDays, todayInVietnam, tripDays } from "../format/dates.ts";
import { COUNTRY_CURRENCY } from "../format/money.ts";
import { type ScriptFollowUp, scriptReply } from "./chatScript.ts";
import { CURRENT_LOCATION, HEALTH_STATS, MODELS, PLACES, usageStats } from "./fixtures.ts";
import { type MockMessage, type MockTrip, mockDb, REPLAN_HEAD_START_MS } from "./mockDb.ts";

const MAX_NAME = 50;
const MAX_TRIP_DAYS = 30;
const MAX_TRAVELERS = 50;
const MAX_NOTES = 2000;
const MAX_MESSAGE = 4000;
const MAX_TITLE = 80;
const MAX_PLACES = 10;
const MAX_PLACE = 200;
// The origin when the visitor's location is unknown (src/domain/questionnaire.py DEFAULT_ORIGIN)
const DEFAULT_ORIGIN = "Hà Nội";
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
      .map((t): TripSummary => ({
        id: t.id,
        destination: t.destination,
        start_date: t.start_date,
        end_date: t.end_date,
        travelers: t.travelers,
        status: t.status,
        total_cost_vnd: t.total_cost_vnd,
        over_budget: t.over_budget,
        created_at: t.created_at,
        updated_at: t.updated_at,
      }));
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
    const body = (await request.json()) as { user_id?: string; draft?: RequestDraft | null; chat_model?: string | null };
    const chatModel = body.chat_model ?? null;
    if (!isChatModel(chatModel)) return fail(422, "invalid_request", "Unknown chat model");
    const user = mockDb.users.find((u) => u.id === body.user_id);
    if (!user) return notFound();
    const iso = mockDb.now().toISOString();
    const conversation: Conversation = {
      id: crypto.randomUUID(),
      user_id: user.id,
      title: null,
      request_draft: body.draft ?? null,
      chat_model: chatModel,
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

  // PATCH /conversations/:conversationId - Rename and/or pick the chat model; updated_at stays, so the list order
  // does not change
  http.patch(apiUrl("/conversations/:conversationId"), async ({ params, request }) => {
    const conversation = mockDb.conversations.find((c) => c.id === params.conversationId);
    if (!conversation) return notFound();
    const body = (await request.json()) as { title?: unknown; chat_model?: unknown };
    const hasTitle = "title" in body;
    const hasModel = "chat_model" in body;
    if (!hasTitle && !hasModel) return fail(422, "invalid_request", "Send title or chat_model");
    const title = typeof body.title === "string" ? body.title.normalize("NFC").trim() : "";
    if (hasTitle && (title.length < 1 || title.length > MAX_TITLE)) {
      return fail(422, "invalid_request", "Title must be 1 to 80 characters");
    }
    const chatModel = typeof body.chat_model === "string" ? body.chat_model : null;
    if (hasModel && !isChatModel(chatModel)) return fail(422, "invalid_request", "Unknown chat model");
    if (hasTitle) conversation.title = title;
    if (hasModel) conversation.chat_model = chatModel;
    return ok(conversation);
  }),

  // GET /models - The chat models of the provider in use
  http.get(apiUrl("/models"), () => ok(MODELS)),

  // PATCH /conversations/:conversationId/messages/:messageId - Cancel an open trip form, or answer a questionnaire step
  http.patch(apiUrl("/conversations/:conversationId/messages/:messageId"), async ({ params, request }) => {
    const message = mockDb.messages.find((m) => m.id === params.messageId && m.conversation_id === params.conversationId);
    if (!message) return notFound();
    const body = (await request.json()) as { status?: unknown; step?: unknown; choice?: unknown; answers?: unknown };
    if (typeof body.step === "number") {
      if (!Number.isInteger(body.step) || body.step < 1 || body.step > 6) return fail(422, "invalid_request", "step must be 1 to 6");
      const card = message.metadata;
      if (!card || !("kind" in card) || card.kind !== "questionnaire" || card.status !== "open") {
        return fail(409, "conflict", "This questionnaire is closed");
      }
      // The mock keeps typed values only; the server also turns button ids into draft values
      const typed = (body.answers ?? {}) as RequestDraft;
      const conversation = mockDb.conversations.find((c) => c.id === message.conversation_id);
      if (conversation) conversation.request_draft = { ...conversation.request_draft, ...typed };
      message.metadata = {
        ...card,
        step: Math.max(card.step, body.step),
        answers: { ...card.answers, ...typed },
        choices: { ...card.choices, [String(body.step)]: (body.choice ?? null) as string | string[] | null },
      };
      const { conversation_id: _c, ...saved } = message;
      return ok(saved);
    }
    if (body.status !== "canceled") return fail(422, "invalid_request", "Unknown body");
    const form = openForm(message);
    if (!form) return fail(409, "conflict", "This form was already used");
    message.metadata = { ...form, status: "canceled" };
    const { conversation_id: _c, ...saved } = message;
    return ok(saved);
  }),

  // DELETE /conversations/:conversationId - Delete with its messages; trips made from it stay
  http.delete(apiUrl("/conversations/:conversationId"), ({ params }) => {
    const conversation = mockDb.conversations.find((c) => c.id === params.conversationId);
    if (!conversation) return notFound();
    mockDb.conversations = mockDb.conversations.filter((c) => c.id !== conversation.id);
    mockDb.messages = mockDb.messages.filter((m) => m.conversation_id !== conversation.id);
    return new HttpResponse(null, { status: 204 });
  }),

  // POST /chat - Send a message to the conversation in the body; the reply is an SSE stream
  http.post(apiUrl("/chat"), async ({ request }) => {
    const body = (await request.json()) as {
      conversation_id?: string;
      content?: string;
      trip_id?: string | null;
      plan_revision?: number | null;
      discover_message_id?: string;
      booking_message_id?: string;
      dates?: Partial<HotelDates & FlightDates>;
      origin?: string;
      default_origin?: string;
    };
    if (!body.conversation_id) return fail(422, "invalid_request", "conversation_id is required");
    const conversation = mockDb.conversations.find((c) => c.id === body.conversation_id);
    if (!conversation) return notFound();
    const content = (body.content ?? "").trim();
    if (content.length < 1 || content.length > MAX_MESSAGE) return fail(422, "invalid_request", "Message must be 1 to 4000 characters");
    const defaultOrigin = body.default_origin === undefined ? DEFAULT_ORIGIN : body.default_origin.trim();
    if (defaultOrigin.length < 1 || defaultOrigin.length > MAX_PLACE) return fail(422, "invalid_request", "default_origin must be 1 to 200 characters");

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

    // A message from a card must name an open card of this conversation and, for a search, good dates
    const followUp = checkFollowUp(conversation, body);
    if (followUp instanceof HttpResponse) return followUp;

    // Save the user message; the first one names the conversation
    const iso = mockDb.now().toISOString();
    mockDb.messages.push(row(conversation.id, "user", content, null, null, iso));
    conversation.title ??= content.slice(0, TITLE_LENGTH);
    conversation.updated_at = iso;

    // Apply the reply's trip change before streaming, like the backend does
    const reply = scriptReply({ content, trip, conversation, followUp, defaultOrigin });
    if (trip && reply.updatedTrip) {
      Object.assign(trip, reply.updatedTrip);
      if (reply.updatedTrip.status === "researching") mockDb.startJob(trip, REPLAN_HEAD_START_MS);
    }
    if (reply.intent === "discover") conversation.request_draft = discoveryDraft(conversation.request_draft);

    // A card with an id is saved with its text before its event is sent, like the backend does
    const card = reply.events.find((e): e is Extract<ChatEvent, { type: "metadata" }> => e.type === "metadata");
    if (card?.data.message_id) {
      if ("draft" in card.data.metadata) {
        // The form shows the default origin; the saved draft keeps only an origin it already had
        const { origin, ...rest } = card.data.metadata.draft;
        conversation.request_draft = conversation.request_draft?.origin || origin !== defaultOrigin ? card.data.metadata.draft : rest;
      }
      const text = reply.events.map((e) => (e.type === "token" ? e.data.text : "")).join("").trim();
      mockDb.messages.push({
        ...row(conversation.id, "assistant", text, reply.intent, card.data.metadata, iso),
        id: card.data.message_id,
      });
    }

    return new HttpResponse(sse(conversation.id, reply.events, reply.intent, request.signal), {
      headers: { "Content-Type": "text/event-stream" },
    });
  }),

  // GET /stats/health - Dashboard health numbers
  http.get(apiUrl("/stats/health"), () => ok(HEALTH_STATS)),

  // GET /stats/usage - Dashboard usage numbers for 7, 30 or 90 days
  http.get(apiUrl("/stats/usage"), ({ request }) => {
    const days = Number(new URL(request.url).searchParams.get("days") ?? "30");
    if (days !== 7 && days !== 30 && days !== 90) return fail(422, "invalid_request", "query.days: Input should be 7, 30 or 90");
    return ok(usageStats(days, todayInVietnam(mockDb.now())));
  }),

  // GET /places - Destination search, ignoring case and accents
  http.get(apiUrl("/places"), ({ request }) => {
    const q = fold(new URL(request.url).searchParams.get("q") ?? "");
    if (q.length < 2) return fail(422, "invalid_request", "Type at least 2 characters");
    return ok(PLACES.filter((p) => fold(p.name).startsWith(q)).slice(0, MAX_PLACES));
  }),

  // The IP lookup the browser makes itself; a test IP sits in a private range, so it has no position
  http.get(IP_LOCATION_URL, () => HttpResponse.json({ success: false, message: "Reserved range" })),

  // GET /weather/current - The visitor's city and its weather now; any valid point is Hồ Chí Minh City
  http.get(apiUrl("/weather/current"), ({ request }) => {
    const params = new URL(request.url).searchParams;
    const lat = Number(params.get("lat") ?? NaN);
    const lon = Number(params.get("lon") ?? NaN);
    if (!(Math.abs(lat) <= 90 && Math.abs(lon) <= 180)) return fail(422, "invalid_request", "lat and lon are required");
    return ok(CURRENT_LOCATION);
  }),

  // POST /trips - Create a trip and queue its generation
  http.post(apiUrl("/trips"), async ({ request }) => {
    const { message_id: messageId, ...body } = (await request.json()) as CreateTripBody;
    if (!mockDb.users.some((u) => u.id === body.user_id)) return notFound();
    const blocked = quotaBlocked();
    if (blocked) return blocked;
    const problem = firstBrokenRule(body);
    if (problem) return fail(422, "invalid_request", problem);

    // A trip made from a chat form must come from that user's open form
    const form = messageId ? mockDb.messages.find((m) => m.id === messageId) : undefined;
    const owner = form ? mockDb.conversations.find((c) => c.id === form.conversation_id) : undefined;
    if (messageId && (!form || owner?.user_id !== body.user_id)) return notFound();
    if (form && !openForm(form)) return fail(409, "conflict", "This form was already used");

    const iso = mockDb.now().toISOString();
    const country = body.destination.country_code;
    const trip: MockTrip = {
      id: crypto.randomUUID(),
      user_id: body.user_id,
      destination: body.destination,
      origin: body.origin.trim(),
      start_date: body.start_date,
      end_date: body.end_date,
      travelers: body.travelers,
      travel_styles: body.travel_styles,
      budget_amount: body.budget_amount === null ? null : Number(body.budget_amount).toFixed(2),
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
      created_at: iso,
      updated_at: iso,
      job_started_at: null,
    };
    mockDb.trips.push(trip);
    mockDb.startJob(trip);
    if (form && owner) {
      const { user_id: _u, ...request } = body;
      form.metadata = { status: "created", draft: request, trip_id: trip.id };
      owner.request_draft = null;
    }
    return ok({ id: trip.id, status: trip.status } satisfies TripCreated, 202);
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
    return ok({ id: trip.id, status: "queued" } satisfies TripCreated, 202);
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
    const filename = fold(trip.destination.name).replace(/[^a-z0-9 _-]/g, "").trim() || "trip";
    return new HttpResponse(new Blob([`Mock export: ${trip.destination.name}`], { type: XLSX }), {
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

// Null ("Auto") or one of the mocked provider's models
function isChatModel(chatModel: string | null) {
  return chatModel === null || MODELS.models.some((m) => m.id === chatModel);
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
function publicTrip({ job_started_at: _j, user_id: _u, ...trip }: MockTrip): Trip {
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
  if (body.travel_styles.length === 0 || !body.travel_styles.every((s) => TRAVEL_STYLES.includes(s))) {
    return "Pick at least one travel style";
  }
  if ((body.budget_amount === null) !== (body.budget_scope === null)) return "budget_amount and budget_scope are given together";
  if (body.budget_amount !== null && !(Number(body.budget_amount) > 0)) return "The budget must be above 0";
  if (body.language !== "en" && body.language !== "vi") return "Unknown language";
  if ((body.notes ?? "").length > MAX_NOTES) return "Notes can be at most 2000 characters";
  return null;
}

// What a discovery chat has gathered so far, kept on the conversation
function discoveryDraft(draft: RequestDraft | null): RequestDraft {
  return {
    origin: "Hồ Chí Minh",
    travelers: 4,
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
  metadata: Message["metadata"],
  createdAt: string,
): MockMessage {
  return { id: crypto.randomUUID(), conversation_id: conversationId, role, content, intent, metadata, created_at: createdAt };
}

// The follow-up a chat body asks for after checking its card and dates (as POST /chat does); an error response when
// the card is not this conversation's (404), not open (409), or the dates break a rule (422). Closes the card
function checkFollowUp(
  conversation: Conversation,
  body: { discover_message_id?: string; booking_message_id?: string; dates?: Partial<HotelDates & FlightDates>; origin?: string },
): ScriptFollowUp | ReturnType<typeof fail> | null {
  const id = body.discover_message_id ?? body.booking_message_id;
  if (!id) return null;
  if (body.discover_message_id && body.booking_message_id) return fail(422, "invalid_request", "Send one card id");
  if (body.booking_message_id && !body.dates) return fail(422, "invalid_request", "dates are required");
  const card = mockDb.messages.find((m) => m.id === id);
  if (!card || card.conversation_id !== conversation.id) return notFound();
  const meta = card.metadata;
  if (!meta || !("kind" in meta)) return fail(409, "conflict", "This card is closed");

  if (body.discover_message_id) {
    if (meta.kind !== "questionnaire" || meta.status !== "open") return fail(409, "conflict", "This card is closed");
    card.metadata = { ...meta, status: "done" };
    return { kind: "discover" };
  }
  if ((meta.kind !== "hotel" && meta.kind !== "flight") || meta.status !== "need_dates") return fail(409, "conflict", "This card is closed");
  const today = todayInVietnam(mockDb.now());
  const dates = body.dates ?? {};
  const start = meta.kind === "hotel" ? dates.check_in : dates.depart;
  const end = meta.kind === "hotel" ? dates.check_out : dates.return;
  if (!start || start < today) return fail(422, "invalid_request", "Dates cannot be in the past");
  if (meta.kind === "hotel" && (!end || end <= start || tripDays(start, end) - 1 > MAX_TRIP_DAYS)) {
    return fail(422, "invalid_request", "Check-out must be after check-in, at most 30 nights");
  }
  if (meta.kind === "flight" && end && end < start) return fail(422, "invalid_request", "The return is before the departure");
  const draft = conversation.request_draft ?? {};
  card.metadata = { ...meta, status: "done" };
  conversation.request_draft = {
    ...draft,
    ...(draft.start_date ? {} : { start_date: start, ...(end ? { end_date: end } : {}) }),
    ...(draft.origin || !body.origin ? {} : { origin: body.origin }),
  };
  return meta.kind === "hotel"
    ? { kind: "hotel", query: meta.query, dates: { check_in: start, check_out: end as string } }
    : { kind: "flight", query: meta.query, dates: { depart: start, return: end ?? null } };
}

// The metadata of an open trip form; null for any other message
function openForm(message: MockMessage): TripFormMeta | null {
  const meta = message.metadata;
  return message.intent === "create_trip" && meta !== null && "draft" in meta && meta.status === "open" ? meta : null;
}

// Write the events as SSE frames with a gap between tokens; save the assistant message on done unless it was saved first
function sse(conversationId: string, events: ChatEvent[], intent: Message["intent"], signal: AbortSignal) {
  const encoder = new TextEncoder();
  let isCancelled = false;
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      let text = "";
      let metadata: Message["metadata"] = null;
      let isSaved = false;
      for (const event of events) {
        if (event.type === "token") {
          text += event.data.text;
          if (mockDb.tokenGapMs > 0) await new Promise((resolve) => setTimeout(resolve, mockDb.tokenGapMs));
        }
        if (isCancelled || signal.aborted) return;
        if (event.type === "metadata") {
          metadata = event.data.metadata;
          isSaved = event.data.message_id !== null;
        }
        if (event.type === "done" && !isSaved) {
          mockDb.messages.push(row(conversationId, "assistant", text.trim(), intent, metadata, mockDb.now().toISOString()));
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
