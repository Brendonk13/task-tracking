import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
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

export type CommentIn = components["schemas"]["CommentIn"]
export type StatusChangeIn = components["schemas"]["StatusChangeIn"]
export type NeedsHumanEyesIn = components["schemas"]["NeedsHumanEyesIn"]

const HUMAN = "human"

type ApiResult = { data?: TicketDetail; error?: unknown }

/**
 * A human-actor mutation on one ticket. Every mutating endpoint returns the updated
 * `TicketDetail` (A3), which replaces the cached detail so the page re-renders at once.
 */
function useTicketMutation<TVars>(
  id: number,
  request: (vars: TVars) => Promise<ApiResult>,
  failureMessage: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: TVars): Promise<TicketDetail> => {
      const { data, error } = await request(vars)
      if (error !== undefined || data === undefined) {
        throw new Error(failureMessage)
      }
      return data
    },
    onSuccess: (detail) => {
      queryClient.setQueryData(ticketDetailQueryKey(id), detail)
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
    "Failed to post comment",
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
    "Failed to change status",
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
    "Failed to update needs human eyes",
  )
}
