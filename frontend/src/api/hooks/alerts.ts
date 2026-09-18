import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
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

export type Alert = components["schemas"]["Alert"]

export const alertsQueryKey = ["alerts", "list"] as const

export function useAlerts() {
  return useQuery({
    queryKey: alertsQueryKey,
    queryFn: async (): Promise<Alert[]> => {
      return unwrap(await api.GET("/api/alerts"), "Failed to load alerts")
    },
  })
}

/**
 * Dismisses one alert. The backend hides dismissed alerts, so the list is refetched
 * rather than filtered here; the summary follows so the sidebar badge stays honest.
 */
export function useDismissAlert() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (alertId: number): Promise<Alert> => {
      return unwrap(
        await api.POST("/api/alerts/{alert_id}/dismiss", {
          params: { path: { alert_id: alertId } },
        }),
        "Failed to dismiss alert",
      )
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: alertsQueryKey })
      void queryClient.invalidateQueries({ queryKey: alertsSummaryQueryKey })
    },
  })
}
