import { randomUUID } from "node:crypto"
import { expect, test, type APIRequestContext } from "@playwright/test"

/**
 * PLAN.md task 8.1 - the one critical-path flow, against the real backend.
 *
 * Setup goes through the API exactly as an LLM session would (README "For LLM
 * sessions"); assertions are on what a human sees in the browser.
 */

const API = "/api"

interface Session {
  session_id: string
  name: string
}

interface TicketDetail {
  id: number
  status: string | null
  needs_human_eyes: boolean
}

interface TicketsSummary {
  needs_human_eyes_count: number
}

async function json<T>(response: Awaited<ReturnType<APIRequestContext["get"]>>): Promise<T> {
  expect(response.ok(), `${response.url()} -> ${response.status()} ${await response.text()}`).toBe(true)
  return (await response.json()) as T
}

test("a session posts a blocked ticket and the human sees it in the UI", async ({ page, request }) => {
  const sessionId = randomUUID()
  const runTag = Date.now()
  const title = `E2E smoke ${runTag}`

  // --- 1. Register a session, create a ticket, set it to blocked (all via API) ---
  let sessionName = ""
  let ticketId = 0

  await test.step("register session and create a blocked ticket via the API", async () => {
    const session = await json<Session>(
      await request.put(`${API}/sessions/${sessionId}`, {
        data: {
          directory: "/home/me/code/e2e-smoke",
          last_message: "Running the e2e smoke test",
          last_message_at: new Date().toISOString(),
        },
      }),
    )
    expect(session.session_id).toBe(sessionId)
    expect(session.name).toMatch(/^[a-z]+-[a-z]+$/)
    sessionName = session.name

    const created = await request.post(`${API}/tickets`, {
      data: { title, priority: "high", actor_session_id: sessionId },
    })
    expect(created.status()).toBe(201)
    const ticket = (await created.json()) as TicketDetail
    expect(ticket.status).toBeNull()
    ticketId = ticket.id

    const blocked = await json<TicketDetail>(
      await request.post(`${API}/tickets/${ticketId}/status`, {
        data: { status: "blocked", reason: "waiting on vendor", actor_session_id: sessionId },
      }),
    )
    expect(blocked.status).toBe("blocked")
  })

  // --- 2. The list page shows the ticket with a "blocked" chip ---
  await test.step("ticket list shows the title and a blocked status chip", async () => {
    await page.goto("/")
    await expect(page.getByRole("heading", { level: 1, name: "Tickets" })).toBeVisible()

    const row = page.getByRole("row").filter({ hasText: title })
    await expect(row).toHaveCount(1)
    await expect(row.getByRole("link", { name: title })).toBeVisible()
    await expect(row.getByText("blocked", { exact: true })).toBeVisible()
  })

  // --- 3. Detail page: h1 and the status-change event line with name + reason ---
  await test.step("detail page shows the title and the status change event", async () => {
    await page
      .getByRole("row")
      .filter({ hasText: title })
      .getByRole("link", { name: title })
      .click()

    await expect(page).toHaveURL(new RegExp(`/tickets/${ticketId}$`))
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible()

    const timeline = page.getByRole("list", { name: "Timeline" })
    const statusChange = timeline.locator('li[data-kind="status_change"]')
    await expect(statusChange).toHaveCount(1)
    await expect(statusChange).toContainText(`${sessionName} set status to blocked`)
    await expect(statusChange).toContainText("waiting on vendor")
  })

  // --- 4. Filter the list by "blocked": URL reflects it and the ticket stays listed ---
  await test.step("filtering by blocked updates the URL and keeps the ticket listed", async () => {
    await page.goto("/")
    await page.getByRole("button", { name: "Filter by status" }).click()
    // click() + toBeChecked() rather than check(): the checkbox is controlled by the URL
    // search params, which React Router updates inside a transition, so the checked
    // state lands a render after the click and check()'s synchronous re-read misses it.
    const blockedOption = page.getByRole("checkbox", { name: "blocked", exact: true })
    await blockedOption.click()
    await expect(blockedOption).toBeChecked()

    await expect(page).toHaveURL(/[?&]status=blocked(&|$)/)
    await expect(page.getByRole("row").filter({ hasText: title })).toHaveCount(1)

    // Reload keeps the filter (F2.7) and the ticket.
    await page.reload()
    await expect(page).toHaveURL(/[?&]status=blocked(&|$)/)
    await expect(page.getByRole("row").filter({ hasText: title })).toHaveCount(1)
  })

  // --- 5. Flag needs-human-eyes via API; sidebar badge equals the summary count ---
  await test.step("sidebar badge matches /api/tickets/summary after flagging", async () => {
    const flagged = await json<TicketDetail>(
      await request.post(`${API}/tickets/${ticketId}/needs-human-eyes`, {
        data: { value: true, reason: "decide", actor_session_id: sessionId },
      }),
    )
    expect(flagged.needs_human_eyes).toBe(true)

    const summary = await json<TicketsSummary>(await request.get(`${API}/tickets/summary`))
    expect(summary.needs_human_eyes_count).toBeGreaterThanOrEqual(1)

    await page.goto("/")
    const badge = page.getByRole("status", { name: /tickets? needs? human eyes/ })
    await expect(badge).toHaveText(String(summary.needs_human_eyes_count))
    await expect(badge).toHaveAccessibleName(
      `${summary.needs_human_eyes_count} ${summary.needs_human_eyes_count === 1 ? "ticket needs" : "tickets need"} human eyes`,
    )

    // The flagged row carries the alert marker (F2.4).
    const row = page.getByRole("row").filter({ hasText: title })
    await expect(row).toHaveAttribute("data-needs-human-eyes", "true")
    await expect(row.getByRole("img", { name: "Needs human eyes" })).toBeVisible()
  })
})
