import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api/client.ts";

const MAX_RETRIES = 2;

// One query client per app: no retry on a 4xx, no refetch on window focus
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < MAX_RETRIES,
        refetchOnWindowFocus: false,
      },
    },
  });
}
