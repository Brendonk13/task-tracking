import { useQuery } from "@tanstack/react-query"
import { api, unwrap } from "@/api/client"
import type { components } from "@/api/schema.d.ts"

export type PullRequest = components["schemas"]["PullRequestItem"]

export const pullRequestsQueryKey = ["pull-requests", "list"] as const

export function usePullRequests() {
  return useQuery({
    queryKey: pullRequestsQueryKey,
    queryFn: async (): Promise<PullRequest[]> => {
      return unwrap(await api.GET("/api/pull-requests"), "Failed to load pull requests")
    },
  })
}
