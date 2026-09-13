import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, unwrap } from "@/api/client"
import type { components, paths } from "@/api/schema.d.ts"

export type TicketsSummary = components["schemas"]["TicketsSummary"]

export const ticketsSummaryQueryKey = ["tickets", "summary"] as const

export function useTicketsSummary() {
  return useQuery({
    queryKey: ticketsSummaryQueryKey,
    queryFn: async (): Promise<TicketsSummary> => {
      return unwrap(await api.GET("/api/tickets/summary"), "Failed to load tickets summary")
    },
  })
}

export type TicketListItem = components["schemas"]["TicketListItem"]
export type TicketListQuery = NonNullable<
  paths["/api/tickets"]["get"]["parameters"]["query"]
>

export const ticketsListQueryKey = ["tickets", "list"] as const

export function useTickets(query: TicketListQuery) {
  return useQuery({
    queryKey: [...ticketsListQueryKey, query] as const,
    placeholderData: keepPreviousData,
    queryFn: async (): Promise<TicketListItem[]> => {
      return unwrap(await api.GET("/api/tickets", { params: { query } }), "Failed to load tickets")
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
      return unwrap(await api.GET("/api/tickets/{ticket_id}", {
        params: { path: { ticket_id: id } },
      }), "Failed to load ticket")
    },
  })
}

export type CommentIn = components["schemas"]["CommentIn"]
export type StatusChangeIn = components["schemas"]["StatusChangeIn"]
export type NeedsHumanEyesIn = components["schemas"]["NeedsHumanEyesIn"]

const HUMAN = "human"

type ApiResult = { data?: TicketDetail; error?: unknown }

/**
 * A human-actor mutation on one ticket. Every mutating endpoint returns the updated
 * `TicketDetail` (A3), which replaces the cached detail so the page re-renders at once.
 */
function useTicketMutation<TVars>(id: number, request: (vars: TVars) => Promise<ApiResult>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: TVars): Promise<TicketDetail> => {
      return unwrap(await request(vars), "Ticket update failed")
    },
    onSuccess: (detail) => {
      queryClient.setQueryData(ticketDetailQueryKey(id), detail)
      // The list rows and the sidebar badge derive from the same ticket; refresh them.
      void queryClient.invalidateQueries({ queryKey: ticketsListQueryKey })
      void queryClient.invalidateQueries({ queryKey: ticketsSummaryQueryKey })
    },
  })
}

export function useAddComment(id: number) {
  return useTicketMutation(
    id,
    (body: string) =>
      api.POST("/api/tickets/{ticket_id}/comments", {
        params: { path: { ticket_id: id } },
        body: { body, actor_session_id: HUMAN } satisfies CommentIn,
      }),
  )
}

export function useChangeStatus(id: number) {
  return useTicketMutation(
    id,
    (vars: { status: string; reason: string }) =>
      api.POST("/api/tickets/{ticket_id}/status", {
        params: { path: { ticket_id: id } },
        body: { ...vars, actor_session_id: HUMAN } satisfies StatusChangeIn,
      }),
  )
}

export function useSetNeedsHumanEyes(id: number) {
  return useTicketMutation(
    id,
    (value: boolean) =>
      api.POST("/api/tickets/{ticket_id}/needs-human-eyes", {
        params: { path: { ticket_id: id } },
        body: { value, actor_session_id: HUMAN } satisfies NeedsHumanEyesIn,
      }),
  )
}
