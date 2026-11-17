import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { Plan, Trip } from "../api/api.types.ts";
import { apiUrl } from "../api/client.ts";
import { ABROAD_TRIP_ID, DOMESTIC_TRIP_ID } from "../mocks/fixtures.ts";
import { mockDb } from "../mocks/mockDb.ts";
import { server } from "../mocks/server.ts";
import { renderApp } from "../test/renderApp.tsx";
import { renderWithProviders } from "../test/renderWithProviders.tsx";
import { PlanView } from "./PlanView.tsx";

// A seeded trip with its plan
function seeded(id: string): Trip & { plan: Plan } {
  const { job_started_at: _j, ...trip } = mockDb.trips.find((t) => t.id === id) as (typeof mockDb.trips)[number];
  return trip as Trip & { plan: Plan };
}

describe("PlanView", () => {
  it("renders_one_card_per_day_with_items_in_time_order", () => {
    const trip = seeded(DOMESTIC_TRIP_ID);
    const shuffled = { ...trip, plan: { ...trip.plan, days: trip.plan.days.map((d) => ({ ...d, items: d.items.toReversed() })) } };
    renderWithProviders(<PlanView trip={shuffled} />);
    const days = within(screen.getByRole("region", { name: "Day by day" })).getAllByRole("heading", { level: 3 });
    expect(days).toHaveLength(4);
    const firstDay = days[0]?.closest("li") as HTMLElement;
    const times = within(firstDay).getAllByText(/^\d\d:\d\d - \d\d:\d\d$/).map((el) => el.textContent);
    expect(times).toEqual(["06:30 - 13:00", "14:00 - 15:00", "18:00 - 19:30"]);
  });

  it("typical_weather_day_shows_typical_badge", () => {
    renderWithProviders(<PlanView trip={seeded(DOMESTIC_TRIP_ID)} />);
    const badges = screen.getAllByText("Typical");
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveAttribute("title", "Based on the same dates last year");
  });

  it("over_budget_warning_states_the_amount", () => {
    const trip = seeded(ABROAD_TRIP_ID);
    renderWithProviders(<PlanView trip={trip} />);
    const over = Number(trip.total_cost_vnd) - 10_000_000;
    const amount = new Intl.NumberFormat("en-US", { style: "currency", currency: "VND", maximumFractionDigits: 0 }).format(over);
    expect(screen.getByText(`Over budget by ${amount}`)).toBeInTheDocument();
  });

  it("abroad_trip_shows_rate_line", () => {
    renderWithProviders(<PlanView trip={seeded(ABROAD_TRIP_ID)} />);
    expect(screen.getByText("1 THB = 720.5 VND (2026-11-16)")).toBeInTheDocument();
  });

  it("domestic_trip_has_no_rate_line", () => {
    renderWithProviders(<PlanView trip={seeded(DOMESTIC_TRIP_ID)} />);
    expect(screen.queryByText(/^1 [A-Z]{3} = /)).toBeNull();
  });

  it("transport_options_group_by_leg_and_mark_the_chosen_one", () => {
    renderWithProviders(<PlanView trip={seeded(DOMESTIC_TRIP_ID)} />);
    const outbound = screen.getByRole("region", { name: "Getting there" });
    const options = within(outbound).getAllByRole("listitem");
    expect(options).toHaveLength(2);
    expect(within(options[0] as HTMLElement).getByText("Chosen")).toBeInTheDocument();
    expect(within(options[1] as HTMLElement).queryByText("Chosen")).toBeNull();
    expect(within(outbound).getByText("Ask in the chat to switch")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Getting back" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Getting around" })).toBeInTheDocument();
  });

  it("export_button_downloads_from_the_export_route_when_plan_exists", async () => {
    const requested: string[] = [];
    server.use(
      http.get(apiUrl("/trips/:tripId/export.xlsx"), ({ request }) => {
        requested.push(new URL(request.url).pathname);
        return new HttpResponse(new Blob(["x"]), { headers: { "Content-Disposition": 'attachment; filename="da lat.xlsx"' } });
      }),
    );
    URL.createObjectURL = () => "blob:mock";
    URL.revokeObjectURL = () => undefined;
    const { user } = renderApp(`/trips/${DOMESTIC_TRIP_ID}`);
    await user.click(await screen.findByRole("button", { name: "Export to Excel" }));
    await expect.poll(() => requested).toEqual([`/trips/${DOMESTIC_TRIP_ID}/export.xlsx`]);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
