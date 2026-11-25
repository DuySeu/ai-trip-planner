import { act, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { IP_LOCATION_URL, weatherKey } from "../api/location.ts";
import { apiUrl } from "../api/client.ts";
import { server } from "../mocks/server.ts";
import { fakeIpLocation } from "../test/ipLocation.ts";
import { useLanguage } from "../i18n/LanguageProvider.tsx";
import { renderWithProviders } from "../test/renderWithProviders.tsx";
import { LocationBanner } from "./LocationBanner.tsx";


describe("LocationBanner", () => {

  it("shows_city_rounded_temperature_and_weather_text", async () => {
    fakeIpLocation("allow");
    renderWithProviders(<LocationBanner />);
    const banner = await screen.findByRole("status", { name: "Your location" });
    expect(banner).toHaveTextContent("Thành phố Hồ Chí Minh · 28 °C · Clear");
  });

  it("asks_the_backend_with_the_position_and_ui_language", async () => {
    fakeIpLocation("allow");
    let asked: URLSearchParams | null = null;
    server.use(
      http.get(apiUrl("/weather/current"), ({ request }) => {
        asked = new URL(request.url).searchParams;
        return HttpResponse.json({ success: true, data: { city: "Thành phố Hồ Chí Minh", country_code: "VN", weather: null } });
      }),
    );
    renderWithProviders(<LocationBanner />, "vi");
    await screen.findByRole("status", { name: "Vị trí của bạn" });
    expect(Object.fromEntries(asked ?? [])).toEqual({ lat: "10.776889", lon: "106.700806", language: "vi" });
  });

  it("renders_nothing_when_the_ip_lookup_answers_no_position", async () => {
    fakeIpLocation("deny");
    const { container } = renderWithProviders(<LocationBanner />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders_nothing_when_the_ip_lookup_fails", async () => {
    server.use(http.get(IP_LOCATION_URL, () => HttpResponse.error()));
    const { container } = renderWithProviders(<LocationBanner />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("renders_nothing_when_the_api_answers_503", async () => {
    fakeIpLocation("allow");
    let calls = 0;
    server.use(
      http.get(apiUrl("/weather/current"), () => {
        calls += 1;
        return HttpResponse.json({ success: false, error: { code: "unavailable", message: "x" } }, { status: 503 });
      }),
    );
    const { container } = renderWithProviders(<LocationBanner />);
    await waitFor(() => expect(calls).toBe(1));
    expect(container).toBeEmptyDOMElement();
  });

  it("shows_only_the_city_when_weather_is_null", async () => {
    fakeIpLocation("allow");
    server.use(
      http.get(apiUrl("/weather/current"), () =>
        HttpResponse.json({ success: true, data: { city: "Sa Pa", country_code: "VN", weather: null } }),
      ),
    );
    renderWithProviders(<LocationBanner />);
    expect(await screen.findByRole("status", { name: "Your location" })).toHaveTextContent(/^Sa Pa$/);
  });

  it("reuses_the_stored_position_on_the_next_page_load", async () => {
    const lookups = fakeIpLocation("allow");
    const first = renderWithProviders(<LocationBanner />);
    await screen.findByRole("status", { name: "Your location" });
    first.unmount();
    renderWithProviders(<LocationBanner />);
    await screen.findByRole("status", { name: "Your location" });
    expect(lookups()).toBe(1);
  });

  it("looks_the_position_up_again_after_six_hours", async () => {
    const savedAt = Date.now() - 6 * 60 * 60_000 - 1;
    localStorage.setItem("tripPlanner.ipPosition", JSON.stringify({ latitude: 21.03, longitude: 105.85, savedAt }));
    const lookups = fakeIpLocation("allow");
    renderWithProviders(<LocationBanner />);
    await screen.findByRole("status", { name: "Your location" });
    expect(lookups()).toBe(1);
  });

  it("ignores_a_malformed_stored_position", async () => {
    localStorage.setItem("tripPlanner.ipPosition", "{not json");
    const lookups = fakeIpLocation("allow");
    renderWithProviders(<LocationBanner />);
    await screen.findByRole("status", { name: "Your location" });
    expect(lookups()).toBe(1);
  });

  it("switching_language_asks_the_backend_again_without_a_new_lookup", async () => {
    const lookups = fakeIpLocation("allow");
    const languages: string[] = [];
    server.use(
      http.get(apiUrl("/weather/current"), ({ request }) => {
        languages.push(new URL(request.url).searchParams.get("language") ?? "");
        return HttpResponse.json({ success: true, data: { city: "Sa Pa", country_code: "VN", weather: null } });
      }),
    );
    let switchLanguage = () => {};
    function Switcher() {
      const { setLang } = useLanguage();
      switchLanguage = () => setLang("vi");
      return null;
    }
    renderWithProviders(
      <>
        <Switcher />
        <LocationBanner />
      </>,
    );
    await screen.findByRole("status", { name: "Your location" });
    act(() => switchLanguage());
    await screen.findByRole("status", { name: "Vị trí của bạn" });
    expect(languages).toEqual(["en", "vi"]);
    expect(lookups()).toBe(1);
  });

  it("weather_key_groups_wmo_codes", () => {
    expect([0, 2, 3, 45, 53, 63, 75, 81, 86, 95].map(weatherKey)).toEqual([
      "weather.clear",
      "weather.partly",
      "weather.cloudy",
      "weather.fog",
      "weather.drizzle",
      "weather.rain",
      "weather.snow",
      "weather.rain",
      "weather.snow",
      "weather.storm",
    ]);
  });
});
