import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ACTIVE_STATUSES, type CreateTripBody, type Trip, type TripCreated, type TripSummary } from "./api.types.ts";
import { apiRequest } from "./client.ts";

const LIST_LIMIT = 50;
const POLL_MS = 2000;

export const tripKeys = {
  all: ["trips"] as const,
  list: (userId: string) => ["trips", "list", userId] as const,
  detail: (tripId: string) => ["trips", "detail", tripId] as const,
};

// GET /users/{id}/trips - the visitor's trips, newest first
export function useUserTrips(userId: string) {
  return useQuery({
    queryKey: tripKeys.list(userId),
    queryFn: async ({ signal }) =>
      (await apiRequest<TripSummary[]>(`/users/${userId}/trips?limit=${LIST_LIMIT}`, { signal })).data,
  });
}

// DELETE /trips/{id} - then drop the trip from every cached list
export function useDeleteTrip() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (tripId: string) => {
      await apiRequest<null>(`/trips/${tripId}`, { method: "DELETE" });
      return tripId;
    },
    onSuccess: (tripId) => {
      queryClient.setQueriesData<TripSummary[]>({ queryKey: [...tripKeys.all, "list"] }, (trips) =>
        trips?.filter((trip) => trip.id !== tripId),
      );
      queryClient.removeQueries({ queryKey: tripKeys.detail(tripId) });
    },
  });
}

// POST /trips - create a trip; generation starts in the background and the trip page polls it
export function useCreateTrip() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateTripBody) =>
      (await apiRequest<TripCreated>("/trips", { method: "POST", body: JSON.stringify(body) })).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [...tripKeys.all, "list"] }),
  });
}

// GET /trips/{id} - polled every 2 s while the job runs, not at all otherwise
export function useTrip(tripId: string) {
  return useQuery({
    queryKey: tripKeys.detail(tripId),
    queryFn: async ({ signal }) => (await apiRequest<Trip>(`/trips/${tripId}`, { signal })).data,
    refetchInterval: (query) =>
      (ACTIVE_STATUSES as readonly string[]).includes(query.state.data?.status ?? "") ? POLL_MS : false,
  });
}

// POST /trips/{id}/retry - queue generation again after a failure
export function useRetryTrip() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (tripId: string) =>
      (await apiRequest<TripCreated>(`/trips/${tripId}/retry`, { method: "POST" })).data,
    // The reply holds only the new status; refetch the trip so polling starts, and the lists for their badge
    onSuccess: ({ id }) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: tripKeys.detail(id) }),
        queryClient.invalidateQueries({ queryKey: [...tripKeys.all, "list"] }),
      ]),
  });
}
