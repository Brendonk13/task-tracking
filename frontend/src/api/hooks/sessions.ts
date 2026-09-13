import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { components } from "@/api/schema.d.ts"

export type Session = components["schemas"]["Session"]

export const sessionsQueryKey = ["sessions", "list"] as const

export function useSessions() {
  return useQuery({
    queryKey: sessionsQueryKey,
    queryFn: async (): Promise<Session[]> => {
      const { data, error } = await api.GET("/api/sessions")
      if (error !== undefined || data === undefined) {
        throw new Error("Failed to load sessions")
      }
      return data
    },
  })
}
