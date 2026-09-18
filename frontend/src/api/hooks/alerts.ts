import { useQuery } from "@tanstack/react-query"
import { api, unwrap } from "@/api/client"
import type { components } from "@/api/schema.d.ts"

export type AlertsSummary = components["schemas"]["AlertsSummary"]

export const alertsSummaryQueryKey = ["alerts", "summary"] as const

export function useAlertsSummary() {
  return useQuery({
    queryKey: alertsSummaryQueryKey,
    queryFn: async (): Promise<AlertsSummary> => {
      return unwrap(await api.GET("/api/alerts/summary"), "Failed to load alerts summary")
    },
  })
}
