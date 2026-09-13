import { setupServer } from "msw/node"

// No default handlers. Tests register their own with `server.use(...)`;
// they are reset after every test in ./setup.ts.
export const server = setupServer()
