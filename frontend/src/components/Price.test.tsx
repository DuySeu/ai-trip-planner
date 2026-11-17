import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Currencies } from "../api/api.types.ts";
import { renderWithProviders } from "../test/renderWithProviders.tsx";
import { Price } from "./Price.tsx";

const DOMESTIC: Currencies = { home: "VND", local: null, local_to_home_rate: null, rate_date: null };
const ABROAD: Currencies = { home: "VND", local: "THB", local_to_home_rate: 720.5, rate_date: "2026-11-16" };

describe("Price", () => {
  it("estimate_price_shows_badge_and_no_link", () => {
    renderWithProviders(<Price amount="150000" currency="VND" basis="estimate" sourceUrl={null} currencies={DOMESTIC} />);
    expect(screen.getByText("Estimate")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("source_price_without_url_falls_back_to_estimate_badge", () => {
    renderWithProviders(<Price amount="150000" currency="VND" basis="source" sourceUrl={null} currencies={DOMESTIC} />);
    expect(screen.getByText("Estimate")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("local_price_on_abroad_trip_shows_vnd_line", () => {
    renderWithProviders(<Price amount="350" currency="THB" basis="source" sourceUrl="https://x.test" currencies={ABROAD} />);
    const link = screen.getByRole("link", { name: /THB\s350/ });
    expect(link).toHaveAttribute("href", "https://x.test");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/≈ ₫252,000/)).toBeInTheDocument();
  });

  it("vnd_price_on_abroad_trip_has_no_conversion_line", () => {
    renderWithProviders(<Price amount="2400000" currency="VND" basis="estimate" sourceUrl={null} currencies={ABROAD} />);
    expect(screen.queryByText(/≈/)).toBeNull();
  });
});
