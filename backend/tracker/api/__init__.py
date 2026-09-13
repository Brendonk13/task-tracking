from ninja import NinjaAPI

from tracker.api.sessions import router as sessions_router
from tracker.api.statuses import router as statuses_router
from tracker.api.tickets import router as tickets_router

api = NinjaAPI(title="Task Tracking")

api.add_router("/tickets", tickets_router)
api.add_router("/sessions", sessions_router)
api.add_router("/statuses", statuses_router)
