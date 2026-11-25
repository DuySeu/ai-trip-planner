import { useQuery } from "@tanstack/react-query";
import type { MessageKey } from "../i18n/LanguageProvider.tsx";
import { useLanguage } from "../i18n/LanguageProvider.tsx";
import type { CurrentLocation } from "./api.types.ts";
import { apiRequest } from "./client.ts";

// Approximate position of the visitor's IP, called from the browser so it sees the visitor's own
// IP; no key, no permission prompt. Free tier: 1,000 lookups a day counted per calling site.
export const IP_LOCATION_URL = "https://ipwho.is/";
const POSITION_TIMEOUT_MS = 10_000;
// How long a looked-up position is reused across page loads, so a refresh spends no lookup
const POSITION_MAX_AGE_MS = 6 * 60 * 60_000;
const POSITION_STORAGE_KEY = "tripPlanner.ipPosition";

interface Position {
  latitude: number;
  longitude: number;
}
// WMO weather codes grouped into the few words the banner shows, upper bound inclusive
const WEATHER_GROUPS: readonly [number, MessageKey][] = [
  [1, "weather.clear"],
  [2, "weather.partly"],
  [3, "weather.cloudy"],
  [48, "weather.fog"],
  [57, "weather.drizzle"],
  [67, "weather.rain"],
  [77, "weather.snow"],
  [82, "weather.rain"],
  [86, "weather.snow"],
  [99, "weather.storm"],
];

// The visitor's city and weather: an approximate position from the visitor's IP (kept for a few
// hours, see ipPosition), then the backend names the city and reads the weather once per page load
// and language. null when the lookup fails or the backend cannot name the city; kept as a result
// (not an error) so other components do not ask again.
export function useCurrentLocation() {
  const { lang } = useLanguage();
  const position = useQuery({ queryKey: ["ipPosition"], queryFn: ipPosition, staleTime: Infinity, retry: false });
  const place = position.data;
  return useQuery({
    queryKey: ["currentLocation", place?.latitude, place?.longitude, lang],
    queryFn: async ({ signal }): Promise<CurrentLocation | null> => {
      if (!place) return null;
      try {
        const params = new URLSearchParams({ lat: String(place.latitude), lon: String(place.longitude), language: lang });
        return (await apiRequest<CurrentLocation>(`/weather/current?${params}`, { signal })).data;
      } catch {
        return null;
      }
    },
    enabled: position.isSuccess,
    staleTime: Infinity,
    retry: false,
  });
}

// The i18n key of a WMO weather code; unknown codes read as cloudy
export function weatherKey(code: number): MessageKey {
  return WEATHER_GROUPS.find(([upTo]) => code <= upTo)?.[1] ?? "weather.cloudy";
}

// The position of the visitor's IP, from storage when it was looked up less than 6 hours ago;
// null when the lookup fails, is too slow or answers no position
async function ipPosition(): Promise<Position | null> {
  const stored = storedPosition();
  if (stored) return stored;
  try {
    const response = await fetch(`${IP_LOCATION_URL}?fields=success,latitude,longitude`, {
      signal: AbortSignal.timeout(POSITION_TIMEOUT_MS),
    });
    const body: unknown = await response.json();
    if (typeof body !== "object" || body === null) return null;
    const { success, latitude, longitude } = body as Record<string, unknown>;
    if (success !== true || !isCoordinate(latitude, 90) || !isCoordinate(longitude, 180)) return null;
    storePosition({ latitude, longitude });
    return { latitude, longitude };
  } catch {
    return null;
  }
}

// A position stored by an earlier page load, if it is still fresh and well formed
function storedPosition(): Position | null {
  try {
    const raw = localStorage.getItem(POSITION_STORAGE_KEY);
    if (!raw) return null;
    const { latitude, longitude, savedAt } = JSON.parse(raw) as Record<string, unknown>;
    const age = Date.now() - Number(savedAt);
    if (!(age >= 0 && age < POSITION_MAX_AGE_MS)) return null;
    return isCoordinate(latitude, 90) && isCoordinate(longitude, 180) ? { latitude, longitude } : null;
  } catch {
    return null;
  }
}

function storePosition(position: Position): void {
  try {
    localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify({ ...position, savedAt: Date.now() }));
  } catch {
    // Storage blocked: the next page load looks the position up again
  }
}

function isCoordinate(value: unknown, limit: number): value is number {
  return typeof value === "number" && Math.abs(value) <= limit;
}
