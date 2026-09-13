import type { ReactElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { render, type RenderOptions } from "@testing-library/react"

interface Options extends Omit<RenderOptions, "wrapper"> {
  /** Initial URL for the MemoryRouter. Defaults to "/". */
  route?: string
}

export function renderWithProviders(ui: ReactElement, { route = "/", ...options }: Options = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
      </QueryClientProvider>,
      options,
    ),
  }
}
