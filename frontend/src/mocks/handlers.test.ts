import { describe, expect, it } from "vitest";
import type { ChatEvent, Conversation, Place, Trip, User } from "../api/api.types.ts";
import { apiRequest, apiUrl } from "../api/client.ts";
import { parseSse } from "../api/parseSse.ts";
import { addDays, todayInVietnam } from "../format/dates.ts";
import { DOMESTIC_TRIP_ID, MINH_ID, PLACES } from "./fixtures.ts";
import { mockDb } from "./mockDb.ts";

const BASE_TIME = Date.parse("2026-11-16T03:00:00Z");

// A JSON POST
function post(body: unknown): RequestInit {
  return { method: "POST", body: JSON.stringify(body) };
}

// A valid trip body to Đà Lạt starting a week after the mock's today
function validBody() {
  const dalat = PLACES.find((p) => p.name === "Đà Lạt") as Place;
  const start = addDays(todayInVietnam(mockDb.now()), 7);
  return {
    user_id: MINH_ID,
    destination: { name: dalat.name, country_code: dalat.country_code, lat: dalat.lat, lon: dalat.lon },
    origin: "Hà Nội",
    start_date: start,
    end_date: addDays(start, 3),
    travelers: 2,
    travel_styles: ["nature"],
    budget_amount: "5000000",
    budget_scope: "per_person",
    language: "en",
    notes: null,
  };
}

// Read a trip
async function getTrip(id: string): Promise<Trip> {
  return (await apiRequest<Trip>(`/trips/${id}`)).data;
}

// A new conversation for Minh
async function newConversation(): Promise<Conversation> {
  return (await apiRequest<Conversation>("/conversations", post({ user_id: MINH_ID }))).data;
}

// Send a chat message and read the whole reply
async function chat(conversationId: string, body: Record<string, unknown>) {
  const response = await fetch(apiUrl("/chat"), post({ conversation_id: conversationId, ...body }));
  const events: ChatEvent[] = [];
  if (response.ok && response.body) {
    for await (const event of parseSse(response.body, new AbortController().signal)) events.push(event);
  }
  return { response, events };
}

describe("mock backend", () => {
  it("claim_user_ignores_case_spaces_and_unicode_form", async () => {
    const a = await apiRequest<User>("/users", post({ name: " Đức " }));
    const b = await apiRequest<User>("/users", post({ name: "ĐỨC".normalize("NFD") }));
    expect(b.data.id).toBe(a.data.id);
  });

  it("created_trip_moves_from_queued_to_ready_with_the_clock", async () => {
    let t = 0;
    mockDb.setNow(() => new Date(BASE_TIME + t));
    const { data } = await apiRequest<Trip>("/trips", post(validBody()));
    expect((await getTrip(data.id)).status).toBe("queued");
    t = 3000;
    expect((await getTrip(data.id)).status).toBe("researching");
    t = 11000;
    expect(await getTrip(data.id)).toMatchObject({ status: "ready", plan_revision: 1 });
  });

  it("create_trip_rejects_31_day_trip_with_422", async () => {
    const body = validBody();
    await expect(apiRequest("/trips", post({ ...body, end_date: addDays(body.start_date, 30) }))).rejects.toMatchObject({
      status: 422,
      code: "invalid_request",
    });
  });

  it("create_trip_returns_429_quota_exhausted_while_blocked", async () => {
    mockDb.setQuotaBlockedUntil(new Date(Date.now() + 3_600_000).toISOString());
    await expect(apiRequest("/trips", post(validBody()))).rejects.toMatchObject({ status: 429, code: "quota_exhausted" });
  });

  it("message_with_stale_plan_revision_returns_409_json", async () => {
    const conversation = await newConversation();
    const trip = await getTrip(DOMESTIC_TRIP_ID);
    mockDb.bumpRevision(DOMESTIC_TRIP_ID);
    const { response } = await chat(conversation.id, { content: "Switch to the flight", trip_id: trip.id, plan_revision: trip.plan_revision });
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ error: { code: "conflict" } });
  });

  it("edit_message_streams_plan_event_before_tokens_and_bumps_revision", async () => {
    const conversation = await newConversation();
    const before = await getTrip(DOMESTIC_TRIP_ID);
    const { events } = await chat(conversation.id, { content: "Switch to the flight", trip_id: before.id, plan_revision: before.plan_revision });
    expect(events.map((e) => e.type).slice(0, 2)).toEqual(["plan", "token"]);
    expect(events.at(-1)?.type).toBe("done");
    const after = await getTrip(DOMESTIC_TRIP_ID);
    expect(after.plan_revision).toBe(before.plan_revision + 1);
    expect(after.plan?.transport_options.find((o) => o.leg === "outbound" && o.chosen)?.mode).toBe("flight");
  });

  it("date_change_replans_and_keeps_the_old_plan", async () => {
    const conversation = await newConversation();
    const before = await getTrip(DOMESTIC_TRIP_ID);
    await chat(conversation.id, { content: "Move the dates one week later", trip_id: before.id, plan_revision: before.plan_revision });
    const after = await getTrip(DOMESTIC_TRIP_ID);
    expect(after.status).toBe("researching");
    expect(after.plan).not.toBeNull();
  });

  it("plan_trip_message_saves_a_trip_form_and_the_form_can_be_used_once", async () => {
    const conversation = await newConversation();
    const { events } = await chat(conversation.id, { content: "plan trip for me" });
    const form = events.find((e) => e.type === "trip_form");
    expect(form?.type === "trip_form" && form.data.draft.destination?.name).toBe("Hải Phòng");
    const messageId = form?.type === "trip_form" ? form.data.message_id : "";
    expect(mockDb.messages.at(-1)).toMatchObject({ id: messageId, intent: "trip_form" });

    const created = await apiRequest<{ id: string }>("/trips", post({ ...validBody(), message_id: messageId }));
    expect(mockDb.messages.at(-1)).toMatchObject({ id: messageId, intent: "created_trip" });
    expect(JSON.parse(mockDb.messages.at(-1)?.content ?? "{}")).toMatchObject({ trip_id: created.data.id });
    await expect(apiRequest("/trips", post({ ...validBody(), message_id: messageId }))).rejects.toMatchObject({ status: 409 });
    await expect(
      apiRequest(`/conversations/${conversation.id}/messages/${messageId}`, { method: "PATCH", body: JSON.stringify({ intent: "canceled_trip" }) }),
    ).rejects.toMatchObject({ status: 409 });
  });

  it("places_search_matches_without_accents", async () => {
    expect((await apiRequest<Place[]>("/places?q=da lat")).data[0]?.name).toBe("Đà Lạt");
  });
});
