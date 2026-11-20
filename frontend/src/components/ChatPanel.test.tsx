import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl } from "../api/client.ts";
import { DOMESTIC_TRIP_ID, SEED_CONVERSATION_ID } from "../mocks/fixtures.ts";
import { mockDb } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";
import { renderApp } from "../test/renderApp.tsx";

const composer = () => screen.getByRole("textbox", { name: "Message" });

// Ask the chat to plan a trip and wait for the form it answers with
async function askToPlan(user: ReturnType<typeof renderApp>["user"]) {
  await screen.findByText(/three places that fit a cool/);
  await user.type(composer(), "tạo plan trip cho tôi{Enter}");
  await screen.findByRole("combobox", { name: "Destination" });
}

// Add a saved assistant message to the seeded conversation
function addMessage(intent: "trip_form" | "created_trip" | "canceled_trip", content: string) {
  mockDb.messages.push({
    id: crypto.randomUUID(),
    conversation_id: SEED_CONVERSATION_ID,
    role: "assistant",
    content,
    intent,
    suggestions: null,
    created_at: new Date().toISOString(),
  });
}

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
    expect(mockDb.messages.at(-1)).toMatchObject({ role: "assistant", intent: "travel_advice" });
  });

  it("message_over_4000_chars_cannot_be_sent", async () => {
    const { user } = renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    await screen.findByText(/three places that fit a cool/);
    await user.click(composer());
    await user.paste("a".repeat(4001));
    expect(screen.getByText("Messages can be at most 4000 characters (4001 now).")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("empty_chat_shows_welcome_and_example_sends_it", async () => {
    const { user } = renderApp("/chat");
    expect(await screen.findByRole("heading", { name: "Where would you like to go?" })).toBeInTheDocument();
    expect(screen.getByText(/Results are for reference only/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "A long weekend near Hồ Chí Minh City with kids" }));
    await waitFor(() => expect(mockDb.messages.some((m) => m.content === "A long weekend near Hồ Chí Minh City with kids")).toBe(true));
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
    expect(mockDb.messages.at(-1)).toMatchObject({ role: "assistant", intent: "trip_form" });
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
    expect(mockDb.messages.at(-1)?.intent).toBe("canceled_trip");

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
    addMessage("canceled_trip", JSON.stringify({ travelers: 1 }));
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
    expect(mockDb.messages.at(-1)).toMatchObject({ intent: "created_trip" });
    expect(JSON.parse(mockDb.messages.at(-1)?.content ?? "{}")).toMatchObject({ trip_id: created?.id });

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
    addMessage("created_trip", JSON.stringify({ trip_id: DOMESTIC_TRIP_ID }));
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
    expect(mockDb.messages.at(-1)).toMatchObject({ intent: "hotel_options" });

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

  it("broken_form_content_shows_error_line_and_keeps_thread", async () => {
    addMessage("trip_form", "not json");
    addMessage("canceled_trip", "[1]");
    renderApp(`/chat/${SEED_CONVERSATION_ID}`);
    expect(await screen.findAllByText("This trip form could not be shown.")).toHaveLength(2);
    expect(screen.getByText(/three places that fit a cool/)).toBeInTheDocument();
  });
});
