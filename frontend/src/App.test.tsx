import { screen } from "@testing-library/react"
import App from "./App"
import { renderWithProviders } from "./test/render"

describe("App", () => {
  it("renders the ticket list page at /", () => {
    renderWithProviders(<App />)
    expect(screen.getByText("Tickets")).toBeInTheDocument()
  })
})
