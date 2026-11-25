import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl } from "../api/client.ts";
import type { Message } from "../api/api.types.ts";
import { DOMESTIC_TRIP_ID, HOTEL_CARDS, LIGHTNING_MODEL, SEED_CONVERSATION_ID } from "../mocks/fixtures.ts";
import { mockDb } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";
import { addDays, todayInVietnam } from "../format/dates.ts";
import { fakeIpLocation } from "../test/ipLocation.ts";
import { renderApp } from "../test/renderApp.tsx";

const composer = () => screen.getByRole("textbox", { name: "Message" });
const LIGHTNING = LIGHTNING_MODEL;
// The seeded conversation, as the mock server keeps it
const seeded = () => mockDb.conversations.find((c) => c.id === SEED_CONVERSATION_ID) ?? expect.unreachable("no seeded conversation");

// Ask the chat to plan a trip and wait for the form it answers with
async function askToPlan(user: ReturnType<typeof renderApp>["user"]) {
  await screen.findByText(/three places that fit a cool/);
  await user.type(composer(), "tạo plan trip cho tôi{Enter}");
  await screen.findByRole("combobox", { name: "Destination" });
}

// Add a saved assistant message to the seeded conversation; metadata is unknown so a broken row can be stored
function addMessage(intent: Message["intent"], metadata: unknown, content = "") {
  mockDb.messages.push({
    id: crypto.randomUUID(),
    conversation_id: SEED_CONVERSATION_ID,
    role: "assistant",
    content,
    intent,
    metadata: metadata as Message["metadata"],
    created_at: new Date().toISOString(),
  });
}

// Record the JSON bodies of POST /chat; call stop() at the end of the test
function watchChatBodies() {
  const bodies: Record<string, unknown>[] = [];
  server.events.on("request:start", ({ request }) => {
    if (request.method === "POST" && new URL(request.url).pathname.endsWith("/chat")) {
      void request.clone().json().then((body) => bodies.push(body as Record<string, unknown>));
    }
  });
  return { bodies, stop: () => server.events.removeAllListeners() };
}

// Open a fresh chat, ask for ideas and wait for the questionnaire card at question 1
async function openQuestionnaire(user: ReturnType<typeof renderApp>["user"]) {
  await screen.findByRole("heading", { name: "Where would you like to go?" });
  await user.type(composer(), "Where should I go?{Enter}");
  return screen.findByRole("region", { name: "A few questions about your trip" });
}

// The saved questionnaire card of the newest conversation
const savedCard = () => mockDb.messages.findLast((m) => m.metadata !== null && "kind" in m.metadata && m.metadata.kind === "questionnaire");

describe("ChatPanel", () => {
  it("streams_tokens_into_one_assistant_message", async () => {
    mockDb.tokenGapMs = 5;
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.type(composer(), "Any tips for packing?{Enter}");
    expect(composer()).toHaveValue("");
    expect(await screen.findByText(/^Good question\./)).toBeInTheDocument();
    expect(await screen.findByText(/Bring a light jacket for the evenings\.$/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("log")).toHaveAttribute("aria-busy", "false"));
    expect(screen.getAllByText(/^Good question\./)).toHaveLength(1);
    expect(mockDb.messages.at(-1)).toMatchObject({ role: "assistant", intent: "advice", metadata: null });
  });

  it("message_over_4000_chars_cannot_be_sent", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.click(composer());
    await user.paste("a".repeat(4001));
    expect(screen.getByText("Messages can be at most 4000 characters (4001 now).")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("empty_discovery_chat_puts_the_composer_above_one_row_per_example", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    const examples = screen.getByRole("list", { name: "Example questions" });
    expect(within(examples).getAllByRole("button")).toHaveLength(5);
    expect(composer().compareDocumentPosition(examples) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await user.type(composer(), "Where should we go in December?{Enter}");
    await waitFor(() => expect(screen.queryByRole("list", { name: "Example questions" })).not.toBeInTheDocument());
  });

  it("shows_thinking_until_the_first_token_arrives", async () => {
    mockDb.tokenGapMs = 200;
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.type(composer(), "Is December cold in Hà Nội?{Enter}");
    expect(await screen.findByText("Thinking...")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Thinking...")).not.toBeInTheDocument(), { timeout: 2000 });
  });

  it("empty_chat_shows_welcome_and_example_sends_it", async () => {
    const { user } = renderApp("/chat");
    expect(await screen.findByRole("heading", { name: "Where would you like to go?" })).toBeInTheDocument();
    expect(screen.getByText(/Results are for reference only/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "How much is a Bà Nà Hills ticket right now?" }));
    await waitFor(() => expect(mockDb.messages.some((m) => m.content === "How much is a Bà Nà Hills ticket right now?")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Where would you like to go?" })).not.toBeInTheDocument());
  });

  it("suggestion_card_plan_this_trip_opens_prefilled_form", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const buttons = await screen.findAllByRole("button", { name: "Plan this trip" });
    await user.click(buttons[2] as HTMLElement);
    expect(await screen.findByRole("heading", { name: "Plan a new trip" })).toBeInTheDocument();
    expect(await screen.findByRole("combobox", { name: "Destination" })).toHaveValue("Chiang Mai");
    expect(screen.getByLabelText("Travelers")).toHaveValue(4);
    expect(screen.getByText("Prices will show in VND and THB")).toBeInTheDocument();
  });

  it("suggestion_card_without_a_place_match_asks_to_pick_from_search", async () => {
    server.use(http.get(apiUrl("/places"), () => HttpResponse.json({ success: true, data: [], error: null, meta: null })));
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const buttons = await screen.findAllByRole("button", { name: "Plan this trip" });
    await user.click(buttons[0] as HTMLElement);
    expect(await screen.findByText("Pick the destination from the search.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Destination" })).toHaveValue("");
  });

  it("edit_reply_invalidates_trip_and_shows_plan_updated", async () => {
    const { user } = renderApp(`/trips/${DOMESTIC_TRIP_ID}`);
    await screen.findByRole("heading", { level: 1, name: /Đà Lạt in 4 days/ });
    await user.type(composer(), "Switch to the flight{Enter}");
    expect(await screen.findByText("Plan updated")).toBeInTheDocument();
    await waitFor(() => {
      const outbound = screen.getByRole("region", { name: "Getting there" });
      const flight = within(outbound).getByText("Vietjet SGN to DLI").closest("li") as HTMLElement;
      expect(within(flight).getByText("Chosen")).toBeInTheDocument();
    });
  });

  it("conflict_409_reloads_trip_shows_notice_and_keeps_draft", async () => {
    const { user } = renderApp(`/trips/${DOMESTIC_TRIP_ID}`);
    await screen.findByRole("heading", { level: 1, name: /Đà Lạt in 4 days/ });
    mockDb.bumpRevision(DOMESTIC_TRIP_ID);
    let tripReads = 0;
    server.events.on("request:start", ({ request }) => {
      if (request.method === "GET" && request.url.endsWith(`/trips/${DOMESTIC_TRIP_ID}`)) tripReads += 1;
    });
    await user.type(composer(), "Switch to the train{Enter}");
    expect(await screen.findByText(/this plan changed/i)).toBeInTheDocument();
    expect(composer()).toHaveValue("Switch to the train");
    expect(tripReads).toBeGreaterThanOrEqual(1);
    server.events.removeAllListeners();
  });

  it("quota_exhausted_disables_composer_with_try_again_tomorrow", async () => {
    mockDb.setQuotaBlockedUntil(new Date(Date.now() + 3_600_000).toISOString());
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.type(composer(), "Where else?{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("We've hit today's free AI limit. Please try again tomorrow.");
    expect(composer()).toBeDisabled();
  });

  it("unmount_mid_stream_aborts_the_request", async () => {
    mockDb.tokenGapMs = 50;
    let aborted = false;
    server.events.on("request:start", ({ request }) => {
      if (new URL(request.url).pathname.endsWith("/chat")) request.signal.addEventListener("abort", () => (aborted = true));
    });
    const { user, unmount } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.type(composer(), "Any tips?{Enter}");
    await screen.findByText(/^Good/);
    const saved = mockDb.messages.length;
    unmount();
    await waitFor(() => expect(aborted).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(mockDb.messages.length).toBe(saved);
    server.events.removeAllListeners();
  });

  it("asking_to_plan_shows_prefilled_form_in_chat", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await askToPlan(user);
    expect(screen.getByRole("combobox", { name: "Destination" })).toHaveValue("Hải Phòng");
    expect(screen.getByLabelText("Starting from")).toHaveValue("Hà Nội");
    expect(screen.getByText(/I filled in this form from our chat/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create plan" })).toBeInTheDocument();
    expect(screen.queryByText(/"destination"/)).not.toBeInTheDocument();
    expect(mockDb.messages.at(-1)).toMatchObject({ role: "assistant", intent: "create_trip", metadata: { status: "open" } });
  });

  it("form_in_chat_has_no_get_ideas_button", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await askToPlan(user);
    expect(screen.queryByRole("button", { name: /Get ideas/ })).not.toBeInTheDocument();
  });

  it("form_cancel_shows_canceled_card_with_trip_facts_after_reload", async () => {
    const { user, unmount } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await askToPlan(user);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByText("Trip form canceled")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Destination" })).not.toBeInTheDocument();
    expect(mockDb.messages.at(-1)?.metadata).toMatchObject({ status: "canceled" });

    unmount();
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const card = (await screen.findByText("Trip form canceled")).closest("section");
    expect(card).not.toBeNull();
    const inCard = within(card as HTMLElement);
    expect(inCard.getByRole("heading", { name: "Hải Phòng" })).toBeInTheDocument();
    expect(inCard.getByText("From Hà Nội to Hải Phòng")).toBeInTheDocument();
    expect(inCard.getByText("4 travelers")).toBeInTheDocument();
    expect(inCard.getByText(/3,000,000 per person$/)).toBeInTheDocument();
  });

  it("canceled_form_without_destination_shows_new_trip_title", async () => {
    addMessage("create_trip", { status: "canceled", draft: { travelers: 1 }, trip_id: null });
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const card = (await screen.findByText("Trip form canceled")).closest("section");
    expect(within(card as HTMLElement).getByRole("heading", { name: "New trip" })).toBeInTheDocument();
    expect(within(card as HTMLElement).queryByText(/^From /)).not.toBeInTheDocument();
  });

  it("form_create_shows_progress_then_open_trip_link", async () => {
    const { user, queryClient } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await askToPlan(user);
    await user.click(screen.getByRole("button", { name: "Create plan" }));
    expect(await screen.findByRole("heading", { name: "Making your plan" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Destination" })).not.toBeInTheDocument();
    const created = mockDb.trips.at(-1);
    expect(mockDb.messages.at(-1)).toMatchObject({ intent: "create_trip", metadata: { status: "created", trip_id: created?.id } });

    // Jump the mock clock past the job, then reload the trip instead of waiting for the poll
    mockDb.now = () => new Date(Date.now() + 60_000);
    await queryClient.invalidateQueries({ queryKey: ["trips"] });
    const link = await screen.findByRole("link", { name: "Open trip" });
    expect(link).toHaveAttribute("href", `/trips/${created?.id}`);
    const card = within(link.closest("section") as HTMLElement);
    expect(card.getByRole("heading", { name: "Hải Phòng" })).toBeInTheDocument();
    expect(card.getByText("From Hà Nội to Hải Phòng")).toBeInTheDocument();
    expect(card.getByText("4 travelers")).toBeInTheDocument();
    expect(card.getByText(/3,000,000 per person$/)).toBeInTheDocument();
    expect(card.getByText("Ready")).toBeInTheDocument();
  });

  it("created_form_for_deleted_trip_says_deleted", async () => {
    addMessage("create_trip", { status: "created", draft: {}, trip_id: DOMESTIC_TRIP_ID });
    mockDb.trips = mockDb.trips.filter((trip) => trip.id !== DOMESTIC_TRIP_ID);
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findByText("This trip was deleted")).toBeInTheDocument();
  });

  it("hotel_question_shows_slider_with_source_links_after_reload", async () => {
    const { user, unmount } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.type(composer(), "How much is a 4-star hotel in Hai Phong?{Enter}");

    const card = within((await screen.findByRole("heading", { name: "Mercure Hai Phong" })).closest("article") as HTMLElement);
    expect(card.getByText("4-star")).toBeInTheDocument();
    expect(card.getByText(/1,450,000/)).toBeInTheDocument();
    const link = card.getByRole("link", { name: "View on booking.com" });
    expect(link).toHaveAttribute("href", "https://www.booking.com/hotel/vn/mercure-hai-phong.html");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("region", { name: "Hotels from booking sites" })).toBeInTheDocument();
    expect(mockDb.messages.at(-1)).toMatchObject({ intent: "booking_search", metadata: { kind: "hotel", status: "results" } });

    unmount();
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findByRole("heading", { name: "Mercure Hai Phong" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View on agoda.com" })).toBeInTheDocument();
  });

  it("hotel_card_without_price_says_no_price", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.type(composer(), "khách sạn ở Hải Phòng bao nhiêu tiền?{Enter}");
    const card = within((await screen.findByRole("heading", { name: "The Light Hotel" })).closest("article") as HTMLElement);
    expect(card.getByText("No price shown")).toBeInTheDocument();
  });

  it("old_hotel_message_from_the_migration_shows_the_slider", async () => {
    addMessage("booking_search", { kind: "hotel", status: "results", query: "", dates: null, cards: HOTEL_CARDS }, "Prices change.");
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findByRole("heading", { name: "Mercure Hai Phong" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Hotels from booking sites" })).toBeInTheDocument();
  });

  it("broken_form_metadata_shows_error_line_and_keeps_thread", async () => {
    addMessage("create_trip", null);
    addMessage("create_trip", { status: "canceled", draft: [1], trip_id: null });
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findAllByText("This trip form could not be shown.")).toHaveLength(2);
    expect(screen.getByText(/three places that fit a cool/)).toBeInTheDocument();
  });
  it("questionnaire_shows_the_first_missing_step_and_saves_a_choice", async () => {
    const { user } = renderApp("/chat");
    const card = within(await openQuestionnaire(user));
    expect(card.getByText("Question 1 of 6")).toBeInTheDocument();
    await user.click(card.getByRole("checkbox", { name: "Food" }));
    await user.click(card.getByRole("button", { name: "Next" }));
    expect(await card.findByRole("heading", { name: "How many people are going?" })).toBeInTheDocument();
    await user.click(card.getByRole("button", { name: "2 people" }));
    expect(await card.findByRole("heading", { name: "About how much per person?" })).toBeInTheDocument();
    expect(savedCard()?.metadata).toMatchObject({ status: "open", step: 2, choices: { "1": ["food"], "2": "2" } });
  });

  it("questionnaire_back_shows_the_previous_answer_selected", async () => {
    const { user } = renderApp("/chat");
    const card = within(await openQuestionnaire(user));
    await user.click(card.getByRole("button", { name: "Skip this question" }));
    await user.click(await card.findByRole("button", { name: "3-4 people" }));
    await card.findByRole("heading", { name: "About how much per person?" });
    await user.click(card.getByRole("button", { name: "Back" }));
    expect(card.getByRole("button", { name: "3-4 people" })).toHaveAttribute("aria-pressed", "true");
    expect(card.getByRole("button", { name: "2 people" })).toHaveAttribute("aria-pressed", "false");
  });

  it("questionnaire_suggest_now_sends_the_card_id_and_shows_destination_cards", async () => {
    const { user } = renderApp("/chat");
    const card = within(await openQuestionnaire(user));
    const watch = watchChatBodies();
    const cardId = savedCard()?.id;
    await user.click(card.getByRole("button", { name: "Suggest now" }));
    expect(await screen.findAllByRole("button", { name: "Plan this trip" })).toHaveLength(3);
    expect(watch.bodies.at(-1)).toMatchObject({ discover_message_id: cardId, content: "Suggest destinations for me" });
    expect(mockDb.messages.find((m) => m.id === cardId)?.metadata).toMatchObject({ status: "done" });
    watch.stop();
  });

  it("done_questionnaire_after_reload_shows_the_chosen_labels", async () => {
    addMessage("discover", {
      kind: "questionnaire",
      status: "done",
      step: 3,
      answers: { travelers: 4, budget_amount: "3000000" },
      choices: { "2": "3_4", "3": "saver" },
    });
    renderApp(`/chat/${SEED_CONVERSATION_ID}`, { lang: "vi" });
    const card = within(await screen.findByRole("region", { name: "Vài câu hỏi về chuyến đi" }));
    expect(card.getByText("Tiết kiệm")).toBeInTheDocument();
    expect(card.getByText("3-4 người")).toBeInTheDocument();
    expect(card.queryByRole("button")).not.toBeInTheDocument();
  });

  it("migrated_ask_message_shows_only_its_text", async () => {
    addMessage("discover", { kind: "questionnaire", status: "done", step: 0, answers: {}, choices: {} }, "Which month suits you?");
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findByText("Which month suits you?")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "A few questions about your trip" })).not.toBeInTheDocument();
  });

  it("answer_on_a_questionnaire_closed_in_another_tab_says_so_and_shows_it_closed", async () => {
    const { user } = renderApp("/chat");
    const card = within(await openQuestionnaire(user));
    const saved = savedCard();
    if (saved?.metadata && "kind" in saved.metadata && saved.metadata.kind === "questionnaire") {
      saved.metadata = { ...saved.metadata, status: "done", choices: { "1": ["food"] } };
    }
    await user.click(card.getByRole("checkbox", { name: "Food" }));
    await user.click(card.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Your answers")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Suggest now" })).not.toBeInTheDocument();
  });

  it("hotel_example_card_asks_for_the_stay_dates", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.click(screen.getByRole("button", { name: /4-star hotel in Hai Phong/ }));
    expect(await screen.findByText("Which dates do you want to stay?")).toBeInTheDocument();
  });

  it("flight_example_asks_for_the_travel_dates", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.click(screen.getByRole("button", { name: /flight from Hà Nội to Đà Nẵng/ }));
    expect(await screen.findByLabelText("Depart")).toBeInTheDocument();
  });

  it("plan_example_opens_the_trip_form_in_the_chat", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.click(screen.getByRole("button", { name: /3-day trip to Đà Lạt/ }));
    expect(await screen.findByRole("button", { name: "Create plan" })).toBeInTheDocument();
  });

  it("open_ended_example_card_opens_the_questionnaire_at_the_first_question", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.click(screen.getByRole("button", { name: /don't know where to go yet/ }));
    expect(await screen.findByText("Question 1 of 6")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How do you want this trip to feel?" })).toBeInTheDocument();
  });

  it("dates_sent_on_a_card_closed_in_another_tab_say_so_and_show_it_closed", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.type(composer(), "How much is a hotel in Hai Phong?{Enter}");
    await screen.findByText("Which dates do you want to stay?");
    const card = mockDb.messages.at(-1);
    if (card?.metadata && "kind" in card.metadata && card.metadata.kind === "hotel") card.metadata = { ...card.metadata, status: "done" };
    const checkIn = addDays(todayInVietnam(), 10);
    await user.type(screen.getByLabelText("Check-in"), checkIn);
    await user.type(screen.getByLabelText("Check-out"), addDays(checkIn, 2));
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This was already used in another tab. The chat now shows the latest state.");
    expect(await screen.findByText("Dates sent")).toBeInTheDocument();
  });

  it("hotel_question_without_dates_shows_date_inputs_then_hotel_cards", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.type(composer(), "How much is a hotel in Hai Phong?{Enter}");
    expect(await screen.findByText("Which dates do you want to stay?")).toBeInTheDocument();
    const checkIn = addDays(todayInVietnam(), 10);
    await user.type(screen.getByLabelText("Check-in"), checkIn);
    await user.type(screen.getByLabelText("Check-out"), addDays(checkIn, 2));
    const watch = watchChatBodies();
    const cardId = mockDb.messages.at(-1)?.id;
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("region", { name: "Hotels from booking sites" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mercure Hai Phong" })).toBeInTheDocument();
    expect(watch.bodies.at(-1)).toMatchObject({
      booking_message_id: cardId,
      dates: { check_in: checkIn, check_out: addDays(checkIn, 2) },
    });
    expect(await screen.findByText("Dates sent")).toBeInTheDocument();
    watch.stop();
  });

  it("booking_dates_with_check_out_before_check_in_shows_an_error_and_sends_nothing", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.type(composer(), "khách sạn ở Hải Phòng{Enter}");
    await screen.findByText("Bạn định nhận phòng và trả phòng ngày nào?");
    const checkIn = addDays(todayInVietnam(), 10);
    await user.type(screen.getByLabelText("Check-in"), checkIn);
    await user.type(screen.getByLabelText("Check-out"), addDays(checkIn, -1));
    const watch = watchChatBodies();
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Check-out must be after check-in.");
    expect(watch.bodies).toHaveLength(0);
    expect(mockDb.messages.at(-1)?.metadata).toMatchObject({ status: "need_dates" });
    watch.stop();
  });

  it("flight_cards_show_route_carrier_price_and_source_link", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.type(composer(), "Flight tickets from Hanoi to Da Nang{Enter}");
    const slider = within(await screen.findByRole("region", { name: "Tickets from travel sites" }));
    const flight = within(slider.getByRole("heading", { name: "Vietnam Airlines" }).closest("article") as HTMLElement);
    expect(flight.getByText("Hà Nội - Đà Nẵng")).toBeInTheDocument();
    expect(flight.getByText(/1,290,000/)).toBeInTheDocument();
    expect(flight.getByText("Estimate")).toBeInTheDocument();
    expect(flight.getByRole("link", { name: "View on traveloka.com" })).toHaveAttribute("href", "https://www.traveloka.com/vi-vn/flight/han-dad");
    const train = within(slider.getByRole("heading", { name: "Vietnam Railways" }).closest("article") as HTMLElement);
    expect(train.getByText("No price shown")).toBeInTheDocument();
    expect(mockDb.messages.at(-1)).toMatchObject({ intent: "booking_search", metadata: { kind: "flight", status: "results" } });
  });

  it("shows_the_stored_model_label_on_the_picker", async () => {
    seeded().chat_model = LIGHTNING.id;
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findByRole("button", { name: `Model: ${LIGHTNING.label}` })).toBeInTheDocument();
  });

  it("shows_auto_for_null_or_unknown_model", async () => {
    seeded().chat_model = "gone/model:free";
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findByRole("button", { name: "Model: Auto" })).not.toHaveAttribute("aria-disabled");
  });

  it("picking_a_model_patches_the_conversation", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await user.click(await screen.findByRole("button", { name: "Model: Auto" }));
    await user.click(screen.getByRole("menuitemradio", { name: LIGHTNING.label }));
    await waitFor(() => expect(seeded().chat_model).toBe(LIGHTNING.id));
    expect(await screen.findByRole("button", { name: `Model: ${LIGHTNING.label}` })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: `Model: ${LIGHTNING.label}` }));
    expect(screen.getByRole("menuitemradio", { name: LIGHTNING.label })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("menuitemradio", { name: "Auto" }));
    await waitFor(() => expect(seeded().chat_model).toBeNull());
  });

  it("a_refused_pick_shows_an_error_and_reloads_the_model_list", async () => {
    server.use(http.patch(apiUrl("/conversations/:conversationId"), () => HttpResponse.json(
      { success: false, data: null, error: { code: "invalid_request", message: "Unknown chat model" }, meta: null },
      { status: 422 },
    )));
    let modelLoads = 0;
    server.events.on("request:start", ({ request }) => {
      if (request.method === "GET" && new URL(request.url).pathname.endsWith("/models")) modelLoads += 1;
    });
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await user.click(await screen.findByRole("button", { name: "Model: Auto" }));
    await user.click(screen.getByRole("menuitemradio", { name: LIGHTNING.label }));
    expect(await screen.findByText("Could not change the model, try again.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Model: Auto" })).toBeInTheDocument();
    await waitFor(() => expect(modelLoads).toBe(2));
    server.events.removeAllListeners();
  });

  it("model_menu_works_from_the_keyboard", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const picker = await screen.findByRole("button", { name: "Model: Auto" });
    picker.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("menuitemradio", { name: "Auto" })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: "Google: Gemma 4 31B (free)" })).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("menuitemradio", { name: LIGHTNING.label })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: "Auto" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(picker).toHaveFocus();
  });

  it("a_pick_before_the_first_message_goes_on_create", async () => {
    const { user } = renderApp("/chat");
    await screen.findByRole("heading", { name: "Where would you like to go?" });
    await user.click(await screen.findByRole("button", { name: "Model: Auto" }));
    await user.click(screen.getByRole("menuitemradio", { name: LIGHTNING.label }));
    await user.type(composer(), "Any tips for packing?{Enter}");
    await waitFor(() => expect(mockDb.conversations.at(-1)?.chat_model).toBe(LIGHTNING.id));
  });

  it("picker_stays_disabled_when_the_list_is_empty", async () => {
    server.use(http.get(apiUrl("/models"), () => HttpResponse.json({ success: true, data: { provider: "openai", default_model: null, models: [] } })));
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const picker = await screen.findByRole("button", { name: "Model: Auto (coming soon)" });
    expect(picker).toHaveAttribute("aria-disabled", "true");
    expect(picker).toHaveAttribute("title", "Coming soon");
    await user.click(picker);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

const CITY = "Thành phố Hồ Chí Minh";

// Take the origin out of the seeded conversation's draft
function dropDraftOrigin() {
  const { origin: _, ...rest } = seeded().request_draft ?? {};
  seeded().request_draft = rest;
}

// Wait until the location chip shows the mock city, so the page knows it
const waitForCity = () => screen.findAllByRole("status", { name: "Your location" });

// Open the questionnaire and skip to question 4, the starting point
async function openOriginStep(user: ReturnType<typeof renderApp>["user"]) {
  const card = within(await openQuestionnaire(user));
  for (const heading of ["How many people are going?", "About how much per person?", "Where are you starting from?"]) {
    await user.click(card.getByRole("button", { name: "Skip this question" }));
    await card.findByRole("heading", { name: heading });
  }
  return card;
}

describe("ChatPanel with the visitor's location", () => {
  it("sends_default_origin_when_the_location_is_known", async () => {
    fakeIpLocation("allow");
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await waitForCity();
    const watch = watchChatBodies();
    await user.type(composer(), "Is December cold?{Enter}");
    await waitFor(() => expect(watch.bodies.at(-1)).toMatchObject({ default_origin: CITY }));
    watch.stop();
  });

  it("omits_default_origin_when_the_location_is_unknown", async () => {
    fakeIpLocation("deny");
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    const watch = watchChatBodies();
    await user.type(composer(), "Is December cold?{Enter}");
    await waitFor(() => expect(watch.bodies).toHaveLength(1));
    expect(watch.bodies[0]).not.toHaveProperty("default_origin");
    watch.stop();
  });

  it("flight_dates_card_prefills_the_draft_origin_over_the_current_city", async () => {
    fakeIpLocation("allow");
    seeded().request_draft = { ...seeded().request_draft, origin: "Cần Thơ" };
    addMessage("booking_search", { kind: "flight", status: "need_dates", query: "flights to Da Nang" }, "When do you want to travel?");
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await waitForCity();
    expect(await screen.findByLabelText("Starting from")).toHaveValue("Cần Thơ");
  });

  it("flight_dates_card_shows_the_city_once_it_arrives_and_sends_no_untouched_origin", async () => {
    fakeIpLocation("allow", 300);
    dropDraftOrigin();
    addMessage("booking_search", { kind: "flight", status: "need_dates", query: "flights to Da Nang" }, "When do you want to travel?");
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const field = await screen.findByLabelText("Starting from");
    expect(field).toHaveValue("Hà Nội");
    await waitForCity();
    expect(field).toHaveValue(CITY);
    await user.type(screen.getByLabelText("Depart"), addDays(todayInVietnam(), 10));
    const watch = watchChatBodies();
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(watch.bodies).toHaveLength(1));
    expect(watch.bodies[0]).not.toHaveProperty("origin");
    expect(watch.bodies[0]).toMatchObject({ default_origin: CITY });
    watch.stop();
  });

  it("flight_dates_card_sends_an_origin_the_visitor_typed", async () => {
    addMessage("booking_search", { kind: "flight", status: "need_dates", query: "flights to Da Nang" }, "When do you want to travel?");
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    const field = await screen.findByLabelText("Starting from");
    await user.clear(field);
    await user.type(field, "Huế");
    await user.type(screen.getByLabelText("Depart"), addDays(todayInVietnam(), 10));
    const watch = watchChatBodies();
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(watch.bodies).toHaveLength(1));
    expect(watch.bodies[0]).toMatchObject({ origin: "Huế" });
    watch.stop();
  });

  it("flight_dates_card_without_draft_origin_prefills_the_current_city", async () => {
    fakeIpLocation("allow");
    dropDraftOrigin();
    addMessage("booking_search", { kind: "flight", status: "need_dates", query: "flights to Da Nang" }, "When do you want to travel?");
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await waitForCity();
    expect(await screen.findByLabelText("Starting from")).toHaveValue(CITY);
  });

  it("flight_dates_card_without_any_origin_prefills_hanoi", async () => {
    dropDraftOrigin();
    addMessage("booking_search", { kind: "flight", status: "need_dates", query: "flights to Da Nang" }, "When do you want to travel?");
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findByLabelText("Starting from")).toHaveValue("Hà Nội");
  });

  it("new_trip_form_opened_before_the_location_shows_the_city_when_it_arrives", async () => {
    fakeIpLocation("allow", 300);
    const { user } = renderApp("/");
    await user.click(await screen.findByRole("button", { name: "New trip" }));
    const field = within(await screen.findByRole("dialog", { name: "Plan a new trip" })).getByLabelText("Starting from");
    expect(field).toHaveValue("Hà Nội");
    await waitFor(() => expect(field).toHaveValue(CITY));
  });

  it("new_trip_form_keeps_an_origin_the_visitor_typed_when_the_city_arrives", async () => {
    fakeIpLocation("allow", 300);
    const { user } = renderApp("/");
    await user.click(await screen.findByRole("button", { name: "New trip" }));
    const field = within(await screen.findByRole("dialog", { name: "Plan a new trip" })).getByLabelText("Starting from");
    await user.clear(field);
    await user.type(field, "Huế");
    await waitForCity();
    expect(field).toHaveValue("Huế");
  });

  it("get_ideas_from_the_new_trip_form_leaves_an_untouched_origin_out_of_the_draft", async () => {
    fakeIpLocation("allow");
    const created: Record<string, unknown>[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.method === "POST" && new URL(request.url).pathname.endsWith("/conversations")) {
        void request.clone().json().then((body) => created.push(body as Record<string, unknown>));
      }
    });
    const { user } = renderApp("/");
    await waitForCity();
    await user.click(screen.getByRole("button", { name: "New trip" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Plan a new trip" }));
    await user.click(dialog.getByRole("button", { name: /Get ideas/ }));
    await waitFor(() => expect(created).toHaveLength(1));
    expect(created[0]?.draft).not.toHaveProperty("origin");
    server.events.removeAllListeners();
  });

  it("asks_for_the_location_once_even_after_a_failure", async () => {
    fakeIpLocation("allow");
    let calls = 0;
    server.use(
      http.get(apiUrl("/weather/current"), () => {
        calls += 1;
        return HttpResponse.json({ success: false, error: { code: "unavailable", message: "x" } }, { status: 503 });
      }),
    );
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.click(screen.getAllByRole("link", { name: "My trips" })[0] as HTMLElement);
    await user.click(await screen.findByRole("button", { name: "New trip" }));
    await screen.findByRole("dialog", { name: "Plan a new trip" });
    expect(calls).toBe(1);
  });

  it("new_trip_form_prefills_the_current_city", async () => {
    fakeIpLocation("allow");
    const { user } = renderApp("/");
    await waitForCity();
    await user.click(screen.getByRole("button", { name: "New trip" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Plan a new trip" }));
    expect(dialog.getByLabelText("Starting from")).toHaveValue(CITY);
  });

  it("questionnaire_origin_step_shows_the_current_city_first_and_selected", async () => {
    fakeIpLocation("allow");
    const { user } = renderApp("/chat");
    await waitForCity();
    const card = await openOriginStep(user);
    const [first] = card.getAllByRole("button", { pressed: true });
    expect(first).toHaveAccessibleName(`${CITY} (where you are)`);
    expect(card.getByRole("button", { name: "Hà Nội" })).toHaveAttribute("aria-pressed", "false");
    await user.click(card.getByRole("button", { name: `${CITY} (where you are)` }));
    await card.findByRole("heading", { name: "When do you want to go?" });
    expect(savedCard()?.metadata).toMatchObject({ answers: { origin: CITY } });
  });

  it("questionnaire_origin_step_selects_hanoi_when_the_location_is_unknown", async () => {
    const { user } = renderApp("/chat");
    const card = await openOriginStep(user);
    expect(card.queryByRole("button", { name: /where you are/ })).not.toBeInTheDocument();
    expect(card.getByRole("button", { name: "Hà Nội" })).toHaveAttribute("aria-pressed", "true");
  });
});
