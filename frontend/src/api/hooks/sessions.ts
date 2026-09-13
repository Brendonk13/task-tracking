import { useQuery } from "@tanstack/react-query"
import { api, unwrap } from "@/api/client"
import type { components } from "@/api/schema.d.ts"

export type Session = components["schemas"]["Session"]

export const sessionsQueryKey = ["sessions", "list"] as const

export function useSessions() {
  return useQuery({
    queryKey: sessionsQueryKey,
    queryFn: async (): Promise<Session[]> => {
      return unwrap(await api.GET("/api/sessions"), "Failed to load sessions")
    },
  })
}
