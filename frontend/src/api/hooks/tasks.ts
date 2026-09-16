import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api, unwrap } from "@/api/client"
import type { components } from "@/api/schema.d.ts"
import { ticketDetailQueryKey, ticketsListQueryKey } from "@/api/hooks/tickets"

export type Task = components["schemas"]["Task"]
export type TaskDetail = components["schemas"]["TaskDetail"]
export type TaskState = components["schemas"]["TaskState"]
export type TaskHistoryEntry = components["schemas"]["TaskHistoryEntry"]
export type TaskCreate = components["schemas"]["TaskCreate"]
export type TaskStateIn = components["schemas"]["TaskStateIn"]

/** Every task state, in the order the UI offers them. */
export const TASK_STATES: readonly TaskState[] = ["todo", "in_progress", "done", "cancelled"]

/** Human-readable label for a state (the API value has underscores). */
export const TASK_STATE_LABEL: Record<TaskState, string> = {
  todo: "to do",
  in_progress: "in progress",
  done: "done",
  cancelled: "cancelled",
}

const HUMAN = "human"

export const taskDetailQueryKey = (id: number) => ["tasks", "detail", id] as const

/** One task with its history. Pass `enabled: false` until the history is actually shown. */
export function useTask(id: number, enabled = true) {
  return useQuery({
    queryKey: taskDetailQueryKey(id),
    enabled,
    queryFn: async (): Promise<TaskDetail> => {
      return unwrap(
        await api.GET("/api/tasks/{task_id}", { params: { path: { task_id: id } } }),
        "Failed to load task",
      )
    },
  })
}

/**
 * After any task mutation the ticket's embedded `tasks` (and its `updated_at`) are stale,
 * so the ticket detail and list are refetched; the returned `TaskDetail` seeds its own cache.
 */
function useTaskMutation<TVars>(
  ticketId: number,
  request: (vars: TVars) => Promise<{ data?: TaskDetail; error?: unknown }>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (vars: TVars): Promise<TaskDetail> => {
      return unwrap(await request(vars), "Task update failed")
    },
    onSuccess: (task) => {
      queryClient.setQueryData(taskDetailQueryKey(task.id), task)
      void queryClient.invalidateQueries({ queryKey: ticketDetailQueryKey(ticketId) })
      void queryClient.invalidateQueries({ queryKey: ticketsListQueryKey })
    },
  })
}

export function useCreateTask(ticketId: number) {
  return useTaskMutation(
    ticketId,
    (vars: { title: string; depends_on: number[] }) =>
      api.POST("/api/tickets/{ticket_id}/tasks", {
        params: { path: { ticket_id: ticketId } },
        body: { ...vars, actor_session_id: HUMAN } satisfies TaskCreate,
      }),
  )
}

export function useSetTaskState(taskId: number, ticketId: number) {
  return useTaskMutation(
    ticketId,
    (state: TaskState) =>
      api.POST("/api/tasks/{task_id}/state", {
        params: { path: { task_id: taskId } },
        body: { state, actor_session_id: HUMAN } satisfies TaskStateIn,
      }),
  )
}
