import { screen, waitFor } from "@testing-library/react";
import type userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { Place } from "../api/api.types.ts";
import { apiUrl } from "../api/client.ts";
import { addDays, todayInVietnam } from "../format/dates.ts";
import { PLACES, SEED_CONVERSATION_ID } from "../mocks/fixtures.ts";
import { mockDb } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";
import { renderApp } from "../test/renderApp.tsx";

const BANGKOK = PLACES.find((p) => p.name === "Bangkok") as Place;

// Type into the destination combobox and pick the option with that name
async function pickPlace(user: ReturnType<typeof userEvent.setup>, typed: string, name: RegExp) {
  await user.type(screen.getByRole("combobox", { name: "Destination" }), typed);
  await user.click(await screen.findByRole("option", { name }, { timeout: 2000 }));
}

// Fill every required field except the destination
async function fillRequired(user: ReturnType<typeof userEvent.setup>) {
  const start = addDays(todayInVietnam(), 7);
  await user.type(screen.getByLabelText("Start date"), start);
  await user.type(screen.getByLabelText("End date"), addDays(start, 3));
  await user.click(screen.getByRole("checkbox", { name: "Nature" }));
  await user.type(screen.getByLabelText("Budget (VND)"), "5000000");
}

describe("NewTripPage", () => {
  it("typing_then_picking_a_place_and_submitting_opens_the_trip_page", async () => {
    const { user } = renderApp("/trips/new");
    await pickPlace(user, "da la", /Đà Lạt/);
    await fillRequired(user);
    expect(screen.getByLabelText("Budget (VND)")).toHaveValue("5,000,000");
    await user.click(screen.getByRole("button", { name: "Plan this trip" }));
    await waitFor(() => expect(mockDb.trips.some((t) => t.destination_name === "Đà Lạt" && t.status === "queued")).toBe(true));
    const created = mockDb.trips.at(-1);
    expect(created).toMatchObject({ budget_amount: "5000000.00", travel_styles: ["nature"], transport_modes: [], language: "en" });
  });

  it("typing_after_picking_clears_the_destination", async () => {
    const { user } = renderApp("/trips/new");
    await pickPlace(user, "da la", /Đà Lạt/);
    await user.type(screen.getByRole("combobox", { name: "Destination" }), "x");
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Plan this trip" }));
    expect(await screen.findByText("Pick the destination from the search.")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Destination" })).toHaveFocus();
  });

  it("keyboard_picks_a_place_with_arrow_and_enter", async () => {
    const { user } = renderApp("/trips/new");
    const box = screen.getByRole("combobox", { name: "Destination" });
    await user.type(box, "ba");
    await screen.findByRole("option", { name: /Bangkok/ }, { timeout: 2000 });
    await user.keyboard("{ArrowDown}{Enter}");
    expect(box).toHaveValue("Bangkok");
    expect(box).toHaveAttribute("aria-expanded", "false");
  });

  it("prefills_from_conversation_draft_and_card_place", async () => {
    mockDb.conversations[0] = {
      ...(mockDb.conversations[0] as (typeof mockDb.conversations)[number]),
      request_draft: { travelers: 4, start_date: "2027-01-10", length_days: 4, travel_styles: ["food"] },
    };
    renderApp({ pathname: "/trips/new", search: `?conversation=${SEED_CONVERSATION_ID}`, state: { place: BANGKOK } });
    expect(await screen.findByLabelText("Travelers")).toHaveValue(4);
    expect(screen.getByLabelText("End date")).toHaveValue("2027-01-13");
    expect(screen.getByRole("checkbox", { name: "Food" })).toBeChecked();
    expect(screen.getByRole("combobox", { name: "Destination" })).toHaveValue("Bangkok");
  });

  it("get_ideas_creates_conversation_with_current_values", async () => {
    const { user } = renderApp("/trips/new");
    await user.type(screen.getByLabelText("Starting from"), "Hà Nội");
    await user.click(screen.getByRole("button", { name: "Not sure where? Get ideas" }));
    await waitFor(() => expect(mockDb.conversations).toHaveLength(2));
    expect(mockDb.conversations.at(-1)?.request_draft).toMatchObject({ origin: "Hà Nội", travelers: 2 });
  });

  it("quota_429_shows_try_again_tomorrow", async () => {
    mockDb.setQuotaBlockedUntil(new Date(Date.now() + 3_600_000).toISOString());
    const { user } = renderApp("/trips/new");
    await pickPlace(user, "da la", /Đà Lạt/);
    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Plan this trip" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("We've hit today's free AI limit. Please try again tomorrow.");
  });

  it("abroad_destination_shows_two_currency_hint", async () => {
    const { user } = renderApp("/trips/new");
    await pickPlace(user, "bang", new RegExp(BANGKOK.name));
    expect(screen.getByText("Prices will show in VND and THB")).toBeInTheDocument();
  });

  it("places_error_shows_in_the_list", async () => {
    server.use(
      http.get(apiUrl("/places"), () =>
        HttpResponse.json({ success: false, data: null, error: { code: "rate_limited", message: "x" }, meta: null }, { status: 429 }),
      ),
    );
    const { user } = renderApp("/trips/new");
    await user.type(screen.getByRole("combobox", { name: "Destination" }), "da");
    expect(await screen.findByText(/too many requests/i, {}, { timeout: 2000 })).toBeInTheDocument();
  });
});
