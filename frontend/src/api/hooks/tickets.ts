import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { components, paths } from "@/api/schema.d.ts"

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

export type TicketListItem = components["schemas"]["TicketListItem"]
export type TicketListQuery = NonNullable<
  paths["/api/tickets"]["get"]["parameters"]["query"]
>

export function useTickets(query: TicketListQuery = {}) {
  return useQuery({
    queryKey: ["tickets", "list", query] as const,
    queryFn: async (): Promise<TicketListItem[]> => {
      const { data, error } = await api.GET("/api/tickets", { params: { query } })
      if (error !== undefined || data === undefined) {
        throw new Error("Failed to load tickets")
      }
      return data
    },
  })
}

export type TicketDetail = components["schemas"]["TicketDetail"]
export type TimelineEntry = components["schemas"]["TimelineEntry"]

export const ticketDetailQueryKey = (id: number) => ["tickets", "detail", id] as const

export function useTicket(id: number) {
  return useQuery({
    queryKey: ticketDetailQueryKey(id),
    queryFn: async (): Promise<TicketDetail> => {
      const { data, error } = await api.GET("/api/tickets/{ticket_id}", {
        params: { path: { ticket_id: id } },
      })
      if (error !== undefined || data === undefined) {
        throw new Error("Failed to load ticket")
      }
      return data
    },
  })
}
