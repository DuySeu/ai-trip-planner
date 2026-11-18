import { screen, waitFor, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl } from "../api/client.ts";
import { DOMESTIC_TRIP_ID, SEED_CONVERSATION_ID } from "../mocks/fixtures.ts";
import { mockDb } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";
import { renderApp } from "../test/renderApp.tsx";

const composer = () => screen.getByRole("textbox", { name: "Message" });

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
});
