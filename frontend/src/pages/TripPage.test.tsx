import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { addDays, todayInVietnam } from "../format/dates.ts";
import { DOMESTIC_TRIP_ID, FAILED_TRIP_ID, MINH_ID, SEED_CONVERSATION_ID } from "../mocks/fixtures.ts";
import { type MockTrip, mockDb, REPLAN_HEAD_START_MS } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";
import { renderApp } from "../test/renderApp.tsx";

// A fresh queued trip whose job starts now
function queuedTrip(notes: string | null = null): MockTrip {
  const start = addDays(todayInVietnam(), 7);
  const trip: MockTrip = {
    ...(mockDb.trips.find((t) => t.id === DOMESTIC_TRIP_ID) as MockTrip),
    id: crypto.randomUUID(),
    user_id: MINH_ID,
    start_date: start,
    end_date: addDays(start, 2),
    notes,
    status: "queued",
    plan: null,
    total_cost_vnd: null,
    over_budget: null,
    plan_revision: 0,
  };
  mockDb.trips.push(trip);
  mockDb.startJob(trip);
  return trip;
}

// Count GET requests for one trip
function countTripGets(tripId: string) {
  const counter = { value: 0 };
  server.events.on("request:start", ({ request }) => {
    if (request.method === "GET" && new URL(request.url).pathname === `/trips/${tripId}`) counter.value += 1;
  });
  return counter;
}

// Let the fake clock run, flushing the requests it triggers
async function wait(ms: number) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}

describe("TripPage", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    server.events.removeAllListeners();
  });

  const user = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

  it("polls_every_2s_until_ready_then_stops", async () => {
    const trip = queuedTrip();
    const gets = countTripGets(trip.id);
    renderApp(`/trips/${trip.id}`, { user: user() });
    expect(await screen.findByText("Making your plan")).toBeInTheDocument();
    for (let i = 0; i < 6; i += 1) await wait(2000);
    expect(await screen.findByRole("heading", { level: 1, name: /Đà Lạt in 3 days/ })).toBeInTheDocument();
    const atReady = gets.value;
    expect(atReady).toBeGreaterThanOrEqual(5);
    await wait(10_000);
    expect(gets.value).toBe(atReady);
  });

  it("shows_researching_then_planning_steps", async () => {
    const trip = queuedTrip();
    renderApp(`/trips/${trip.id}`, { user: user() });
    await screen.findByText("Making your plan");
    await wait(4000);
    expect(screen.getByText("Researching").closest("li")).toHaveAttribute("aria-current", "step");
    await wait(4000);
    expect(screen.getByText("Planning").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("failed_trip_shows_reason_and_retry_restarts_progress", async () => {
    const trip = queuedTrip("#fail please");
    const u = user();
    renderApp(`/trips/${trip.id}`, { user: u });
    await screen.findByText("Making your plan");
    for (let i = 0; i < 6; i += 1) await wait(2000);
    expect(await screen.findByText("The AI could not produce a valid plan this time.")).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Making your plan")).toBeInTheDocument();
    expect(screen.getByText("Queued").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("quota_failed_trip_shows_try_again_tomorrow", async () => {
    renderApp(`/trips/${FAILED_TRIP_ID}`, { user: user() });
    expect(await screen.findByRole("alert")).toHaveTextContent("We've hit today's free AI limit. Please try again tomorrow.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("replan_keeps_plan_visible_with_progress_card_above_it", async () => {
    const trip = mockDb.trips.find((t) => t.id === DOMESTIC_TRIP_ID) as MockTrip;
    mockDb.startJob(trip, REPLAN_HEAD_START_MS);
    const gets = countTripGets(trip.id);
    renderApp(`/trips/${trip.id}`, { user: user() });
    const progress = await screen.findByText("Updating your plan");
    const title = screen.getByRole("heading", { level: 1, name: /Đà Lạt in 4 days/ });
    expect(progress.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: "Export to Excel" })).toBeEnabled();
    await wait(2000);
    expect(gets.value).toBeGreaterThanOrEqual(2);
    for (let i = 0; i < 4; i += 1) await wait(2000);
    expect(screen.queryByText("Updating your plan")).toBeNull();
  });

  it("unmount_during_polling_makes_no_more_requests", async () => {
    const trip = queuedTrip();
    const gets = countTripGets(trip.id);
    const { unmount } = renderApp(`/trips/${trip.id}`, { user: user() });
    await screen.findByText("Making your plan");
    await wait(2000);
    unmount();
    const atUnmount = gets.value;
    await wait(10_000);
    expect(gets.value).toBe(atUnmount);
  });

  it("unknown_trip_shows_not_found", async () => {
    renderApp("/trips/00000000-0000-0000-0000-000000000000", { user: user() });
    expect(await screen.findByRole("heading", { name: "Trip not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to my trips" })).toBeInTheDocument();
  });
});

describe("TripPage chat", () => {
  afterEach(() => {
    server.events.removeAllListeners();
    Reflect.deleteProperty(window, "matchMedia");
  });

  it("trip_chat_sends_trip_id_and_plan_revision", async () => {
    const bodies: unknown[] = [];
    server.events.on("request:start", async ({ request }) => {
      if (new URL(request.url).pathname.endsWith("/chat")) bodies.push(await request.clone().json());
    });
    const { user } = renderApp(`/trips/${DOMESTIC_TRIP_ID}`);
    await screen.findByRole("heading", { level: 1, name: /Đà Lạt in 4 days/ });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "Is it cold at night?{Enter}");
    await expect.poll(() => bodies).toEqual([
      { conversation_id: SEED_CONVERSATION_ID, content: "Is it cold at night?", trip_id: DOMESTIC_TRIP_ID, plan_revision: 1 },
    ]);
  });

  it("trip_chat_is_disabled_until_first_plan_is_ready", async () => {
    const trip = queuedTrip();
    renderApp(`/trips/${trip.id}`);
    await screen.findByText("Making your plan");
    expect(screen.getByRole("textbox", { name: "Message" })).toBeDisabled();
    expect(screen.getByText("The chat opens when the plan is ready")).toBeInTheDocument();
  });

  it("trip_chat_stays_open_during_replan", async () => {
    const trip = mockDb.trips.find((t) => t.id === DOMESTIC_TRIP_ID) as MockTrip;
    mockDb.startJob(trip, REPLAN_HEAD_START_MS);
    renderApp(`/trips/${trip.id}`);
    await screen.findByText("Updating your plan");
    expect(screen.getByRole("textbox", { name: "Message" })).toBeEnabled();
  });

  it("empty_trip_chat_offers_example_prompts", async () => {
    mockDb.conversations = [];
    const { user } = renderApp(`/trips/${DOMESTIC_TRIP_ID}`);
    await user.click(await screen.findByRole("button", { name: "Is the weather OK for day 2?" }));
    expect(await screen.findByText(/^Good question\./)).toBeInTheDocument();
    expect(mockDb.conversations).toHaveLength(1);
  });

  it("small_screen_opens_chat_sheet_from_button", async () => {
    window.matchMedia = ((query: string) => ({
      matches: query === "(max-width: 1279px)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
    const { user } = renderApp(`/trips/${DOMESTIC_TRIP_ID}`);
    const opener = await screen.findByRole("button", { name: "Ask about this plan" });
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(opener);
    const sheet = screen.getByRole("dialog", { name: "Ask about this plan" });
    expect(sheet).toHaveAttribute("open");
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    expect(sheet).not.toHaveAttribute("open");
    expect(opener).toHaveFocus();
  });
});
