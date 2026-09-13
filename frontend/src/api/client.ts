import createClient from "openapi-fetch"
import type { paths } from "./schema.d.ts"

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Resolve fetch lazily so interceptors installed after module load (MSW in tests) are honoured.
  fetch: (input) => globalThis.fetch(input),
})

/** Returns `data` from an openapi-fetch result, or throws `message` on an error/empty body. */
export function unwrap<T>(result: { data?: T; error?: unknown }, message: string): T {
  if (result.error !== undefined || result.data === undefined) {
    throw new Error(message)
  }
  return result.data
}
