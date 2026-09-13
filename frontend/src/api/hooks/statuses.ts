import { useQuery } from "@tanstack/react-query"
import { api, unwrap } from "@/api/client"
import type { components } from "@/api/schema.d.ts"

export type StatusItem = components["schemas"]["StatusItem"]

export const statusesQueryKey = ["statuses"] as const

export function useStatuses() {
  return useQuery({
    queryKey: statusesQueryKey,
    queryFn: async (): Promise<StatusItem[]> => {
      return unwrap(await api.GET("/api/statuses"), "Failed to load statuses")
    },
  })
}
