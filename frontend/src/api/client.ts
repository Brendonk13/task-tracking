import createClient from "openapi-fetch"
import type { paths } from "./schema.d.ts"

export const api = createClient<paths>({ baseUrl: window.location.origin })
