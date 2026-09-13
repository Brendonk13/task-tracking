import { Route, Routes } from "react-router-dom"
import { TicketListPage } from "@/pages/TicketListPage"

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<TicketListPage />} />
    </Routes>
  )
}
