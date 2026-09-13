import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { components } from "@/api/schema.d.ts"

export type TicketsSummary = components["schemas"]["TicketsSummary"]

export const ticketsSummaryQueryKey = ["tickets", "summary"] as const

export function useTicketsSummary() {
  return useQuery({
    queryKey: ticketsSummaryQueryKey,
    queryFn: async (): Promise<TicketsSummary> => {
      const { data, error } = await api.GET("/api/tickets/summary")
      if (error !== undefined || data === undefined) {
        throw new Error("Failed to load tickets summary")
      }
      return data
    },
  })
}
