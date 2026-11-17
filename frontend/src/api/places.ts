import { useQuery } from "@tanstack/react-query";
import type { Place } from "./api.types.ts";
import { apiRequest } from "./client.ts";

const MIN_QUERY = 2;
const STALE_MS = 5 * 60_000;

// GET /places - destination search; Vietnam results first since Vietnam is the default country
export function usePlaceSearch(query: string) {
  const q = query.trim();
  return useQuery({
    queryKey: ["places", q.toLowerCase()],
    queryFn: async ({ signal }) => {
      const places = (await apiRequest<Place[]>(`/places?q=${encodeURIComponent(q)}`, { signal })).data;
      return places.toSorted((a, b) => Number(b.country_code === "VN") - Number(a.country_code === "VN"));
    },
    enabled: q.length >= MIN_QUERY,
    staleTime: STALE_MS,
  });
}
