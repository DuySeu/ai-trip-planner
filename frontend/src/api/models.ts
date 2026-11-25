import { useQuery } from "@tanstack/react-query";
import type { ModelsInfo } from "./api.types.ts";
import { apiRequest } from "./client.ts";

// GET /models - the chat models a visitor may pick; fixed while the server runs, so loaded once
export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: async ({ signal }) => (await apiRequest<ModelsInfo>("/models", { signal })).data,
    staleTime: Infinity,
  });
}
