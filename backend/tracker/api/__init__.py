from ninja import NinjaAPI

from tracker.api.alerts import router as alerts_router
from tracker.api.crons import router as crons_router
from tracker.api.pull_requests import router as pull_requests_router
from tracker.api.sessions import router as sessions_router
from tracker.api.statuses import router as statuses_router
from tracker.api.tasks import router as tasks_router
from tracker.api.tickets import router as tickets_router

api = NinjaAPI(title="Task Tracking")

api.add_router("/tickets", tickets_router)
api.add_router("/sessions", sessions_router)
api.add_router("/statuses", statuses_router)
api.add_router("/tasks", tasks_router)
api.add_router("/crons", crons_router)
api.add_router("/alerts", alerts_router)
api.add_router("/pull-requests", pull_requests_router)
