import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl } from "../api/client.ts";
import { MINH_ID } from "../mocks/fixtures.ts";
import { server } from "../mocks/server.ts";
import { fakeIpLocation } from "../test/ipLocation.ts";
import { renderApp } from "../test/renderApp.tsx";

// The trip cards, in screen order
async function tripCards() {
  await screen.findByRole("link", { name: "Bangkok" });
  return screen.getAllByRole("listitem").filter((li) => within(li).queryByRole("button", { name: /delete trip/i }));
}

describe("HomePage", () => {
  it("location_chip_sits_in_the_page_header_not_the_sidebar", async () => {
    fakeIpLocation("allow");
    renderApp("/");
    const header = screen.getByRole("heading", { level: 1 }).closest("header") as HTMLElement;
    expect(await within(header).findByRole("status", { name: "Your location" })).toHaveTextContent("Thành phố Hồ Chí Minh");
    expect(within(screen.getByRole("complementary")).queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows_seeded_trips_newest_first_with_status_badges", async () => {
    renderApp("/");
    const cards = await tripCards();
    expect(cards.map((c) => within(c).getByRole("heading").textContent)).toEqual(["Bangkok", "Đà Lạt", "Hội An"]);
    expect(within(cards[0] as HTMLElement).getByText("Ready")).toBeInTheDocument();
    expect(within(cards[2] as HTMLElement).getByText("Failed")).toBeInTheDocument();
  });

  it("over_budget_trip_shows_warning_badge", async () => {
    renderApp("/");
    const [bangkok, dalat] = await tripCards();
    expect(within(bangkok as HTMLElement).getByText("Over budget")).toBeInTheDocument();
    expect(within(dalat as HTMLElement).queryByText("Over budget")).toBeNull();
  });

  it("empty_user_sees_empty_state_with_new_trip_button", async () => {
    server.use(
      http.get(apiUrl(`/users/${MINH_ID}/trips`), () =>
        HttpResponse.json({ success: true, data: [], error: null, meta: { total: 0, limit: 50, offset: 0 } }),
      ),
    );
    renderApp("/");
    expect(await within(screen.getByRole("main")).findByText("No trips yet. Plan your first one.")).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByRole("button", { name: "New trip" })).toBeInTheDocument();
  });

  it("new_trip_opens_the_form_in_a_dialog_with_origin_ha_noi", async () => {
    const { user } = renderApp("/");
    await tripCards();
    await user.click(screen.getByRole("button", { name: "New trip" }));
    const dialog = screen.getByRole("dialog", { name: "Plan a new trip" });
    expect(within(dialog).getByLabelText("Starting from")).toHaveValue("Hà Nội");
    expect(screen.getByRole("heading", { name: "My trips" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "Plan a new trip" })).toBeNull();
  });

  it("delete_asks_for_confirmation_then_removes_the_card", async () => {
    const { user } = renderApp("/");
    await tripCards();
    const trigger = screen.getByRole("button", { name: "Delete trip to Hội An" });
    await user.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Delete the trip to Hội An?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete trip" }));
    expect(await screen.findByRole("link", { name: "Bangkok" })).toBeInTheDocument();
    await expect.poll(() => screen.queryByRole("link", { name: "Hội An" })).toBeNull();
    expect(trigger).not.toBeInTheDocument();
  });

  it("cancel_delete_keeps_the_card_and_returns_focus", async () => {
    const { user } = renderApp("/");
    await tripCards();
    const trigger = screen.getByRole("button", { name: "Delete trip to Đà Lạt" });
    await user.click(trigger);
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("link", { name: "Đà Lạt" })).toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("list_error_shows_message_and_retry", async () => {
    server.use(
      http.get(apiUrl(`/users/${MINH_ID}/trips`), () =>
        HttpResponse.json(
          { success: false, data: null, error: { code: "rate_limited", message: "slow down" }, meta: null },
          { status: 429 },
        ),
      ),
    );
    const { user } = renderApp("/");
    const main = screen.getByRole("main");
    expect(await within(main).findByText(/too many requests/i)).toBeInTheDocument();
    server.resetHandlers();
    await user.click(within(main).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "Bangkok" })).toBeInTheDocument();
  });
});
