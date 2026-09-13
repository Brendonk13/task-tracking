import createClient from "openapi-fetch"
import type { paths } from "./schema.d.ts"

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  // Resolve fetch lazily so interceptors installed after module load (MSW in tests) are honoured.
  fetch: (input) => globalThis.fetch(input),
})
