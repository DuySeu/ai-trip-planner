import { useQuery } from "@tanstack/react-query";
import type { HealthStats, UsageDays, UsageStats } from "./api.types.ts";
import { apiRequest } from "./client.ts";

export const HEALTH_REFRESH_MS = 30_000;

// GET /stats/health - refreshed every 30 seconds; a failed refresh keeps the last numbers
export function useHealthStats() {
  return useQuery({
    queryKey: ["stats", "health"],
    queryFn: async ({ signal }) => (await apiRequest<HealthStats>("/stats/health", { signal })).data,
    refetchInterval: HEALTH_REFRESH_MS,
  });
}

// GET /stats/usage?days= - loaded once per range
export function useUsageStats(days: UsageDays) {
  return useQuery({
    queryKey: ["stats", "usage", days],
    queryFn: async ({ signal }) => (await apiRequest<UsageStats>(`/stats/usage?days=${days}`, { signal })).data,
  });
}
