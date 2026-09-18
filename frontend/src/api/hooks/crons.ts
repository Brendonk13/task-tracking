import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "@/api/client";
import type { components } from "@/api/schema.d.ts";

export type CronRun = components["schemas"]["CronRun"];
export type CronsSummary = components["schemas"]["CronsSummary"];

export const cronsSummaryQueryKey = ["crons", "summary"] as const;

/** How often the summary is re-read while a pass is in flight. */
const RUNNING_POLL_MS = 5000;

/**
 * The state of the crons. A pass finishes on its own, so while one is running the summary is
 * polled; once nothing is running there is nothing to wait for and the polling stops.
 */
export function useCronsSummary() {
  return useQuery({
    queryKey: cronsSummaryQueryKey,
    queryFn: async (): Promise<CronsSummary> => {
      return unwrap(
        await api.GET("/api/crons/summary"),
        "Failed to load crons summary",
      );
    },
    refetchInterval: (query) =>
      query.state.data?.running === true ? RUNNING_POLL_MS : false,
  });
}

/**
 * Starts a cron pass. The backend refuses a second pass while one is in flight (C5.2), so the
 * summary is invalidated at once rather than waiting for the next poll.
 */
export function useRunCrons() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (): Promise<CronRun> => {
      return unwrap(await api.POST("/api/crons/run"), "Failed to run crons");
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cronsSummaryQueryKey });
    },
  });
}
