import { screen } from "@testing-library/react"
import { useLocation } from "react-router-dom"

/**
 * Renders the router's current location as text so tests can assert on navigation
 * and URL search params. Mount it next to the component under test inside
 * `renderWithProviders`, then read it back with `currentLocation()`.
 */
export function LocationProbe() {
  const { pathname, search } = useLocation()
  return (
    <p data-testid="location-probe" hidden>
      {pathname}
      {search}
    </p>
  )
}

/** Current router location as reported by a mounted `<LocationProbe />`. */
export function currentLocation(): { pathname: string; search: string; params: URLSearchParams } {
  const text = screen.getByTestId("location-probe").textContent ?? ""
  const url = new URL(text, "http://localhost")
  return { pathname: url.pathname, search: url.search, params: url.searchParams }
}
