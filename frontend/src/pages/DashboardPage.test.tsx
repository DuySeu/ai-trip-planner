import { screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { apiUrl } from "../api/client.ts";
import { HEALTH_STATS } from "../mocks/fixtures.ts";
import { server } from "../mocks/server.ts";
import { renderApp } from "../test/renderApp.tsx";

const RETRY_WAIT = { timeout: 5000 };

// Serve a health response with some fields replaced
function serveHealth(overrides: Partial<typeof HEALTH_STATS>) {
  server.use(http.get(apiUrl("/stats/health"), () => HttpResponse.json({ success: true, data: { ...HEALTH_STATS, ...overrides } })));
}

describe("DashboardPage", () => {
  it("shows_health_and_usage_from_the_api", async () => {
    renderApp("/dashboard");
    const llm = await screen.findByRole("group", { name: "LLM calls today" });
    expect(within(llm).getByText("412")).toBeInTheDocument();
    expect(await screen.findByText("Đà Lạt")).toBeInTheDocument();
    expect(screen.getByText(/does not count trips that users deleted/i)).toBeInTheDocument();
  });

  it("marks_llm_tile_warning_near_the_ceiling", async () => {
    serveHealth({ llm_today: { ...HEALTH_STATS.llm_today, calls: 700, ceiling_new_trips: 800 } });
    renderApp("/dashboard");
    const llm = await screen.findByRole("group", { name: "LLM calls today" });
    expect(llm).toHaveAttribute("data-tone", "warning");
  });

  it("marks_blocked_provider_danger", async () => {
    serveHealth({ blocks: [{ service: "openrouter", blocked_until: "2026-11-25T00:00:00Z" }] });
    renderApp("/dashboard");
    const blocks = await screen.findByRole("group", { name: "Blocked providers" });
    expect(blocks).toHaveAttribute("data-tone", "danger");
    expect(within(blocks).getByText("openrouter")).toBeInTheDocument();
  });

  it("switching_range_requests_usage_with_new_days", async () => {
    const { user } = renderApp("/dashboard");
    const chart = await screen.findByRole("img", { name: /trips per day/i });
    expect(chart.querySelectorAll("rect")).toHaveLength(30);

    await user.click(screen.getByRole("button", { name: "7 days" }));

    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
    await screen.findByRole("img", { name: /trips per day, last 7 days/i });
    expect(screen.getByRole("img", { name: /trips per day/i }).querySelectorAll("rect")).toHaveLength(7);
  });

  it("opens_with_the_range_from_the_url", async () => {
    renderApp("/dashboard?days=90");
    expect(await screen.findByRole("img", { name: /last 90 days/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "90 days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("usage_error_keeps_health_visible", async () => {
    server.use(
      http.get(apiUrl("/stats/usage"), () =>
        HttpResponse.json({ success: false, error: { code: "internal_error", message: "boom" } }, { status: 500 }),
      ),
    );
    renderApp("/dashboard");
    expect(await screen.findByRole("group", { name: "LLM calls today" })).toBeInTheDocument();
    const alert = await screen.findByRole("alert", {}, RETRY_WAIT);
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  }, 10_000);

  it("shows_dash_for_missing_percentiles", async () => {
    serveHealth({ llm_last_hour: { ...HEALTH_STATS.llm_last_hour, p50_latency_ms: null, p95_latency_ms: null } });
    renderApp("/dashboard");
    const latency = await screen.findByRole("group", { name: "LLM latency, last hour" });
    expect(within(latency).getByText("- / -")).toBeInTheDocument();
  });

  it("sidebar_settings_menu_links_to_dashboard", async () => {
    const { user } = renderApp("/");
    await user.click(screen.getByRole("button", { name: "Settings" }));
    await user.click(screen.getByRole("link", { name: "Dashboard" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
  });
});
