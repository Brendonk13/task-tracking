import { Route, Routes } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { SessionsPage } from "@/pages/SessionsPage"
import { TicketListPage } from "@/pages/TicketListPage"

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<TicketListPage />} />
        <Route path="sessions" element={<SessionsPage />} />
      </Route>
    </Routes>
  )
}
