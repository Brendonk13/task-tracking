import { useQuery } from "@tanstack/react-query"
import { api } from "@/api/client"
import type { components } from "@/api/schema.d.ts"

export type StatusItem = components["schemas"]["StatusItem"]

export const statusesQueryKey = ["statuses"] as const

export function useStatuses() {
  return useQuery({
    queryKey: statusesQueryKey,
    queryFn: async (): Promise<StatusItem[]> => {
      const { data, error } = await api.GET("/api/statuses")
      if (error !== undefined || data === undefined) {
        throw new Error("Failed to load statuses")
      }
      return data
    },
  })
}
