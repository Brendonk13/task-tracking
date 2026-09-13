from django.urls import path

from tracker.api import api

urlpatterns = [
    path("api/", api.urls),
]
