"""The app is reachable from this machine only.

These use Django's test client (not ninja's TestClient) because ninja's client
calls the view function directly and skips middleware.
"""

import pytest
from django.test import Client

from config.middleware import is_loopback

OPENAPI_URL = "/api/openapi.json"


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "127.0.0.53", "::1", "::ffff:127.0.0.1"]
)
def test_loopback_peer_is_served(address: str) -> None:
    response = Client().get(OPENAPI_URL, REMOTE_ADDR=address)
    assert response.status_code == 200


@pytest.mark.parametrize("address", ["192.168.1.20", "10.0.0.4", "8.8.8.8", "", "nope"])
def test_non_loopback_peer_is_refused(address: str) -> None:
    response = Client().get(OPENAPI_URL, REMOTE_ADDR=address)
    assert response.status_code == 403


def test_forwarded_header_cannot_spoof_the_peer() -> None:
    response = Client().get(
        OPENAPI_URL, REMOTE_ADDR="203.0.113.7", HTTP_X_FORWARDED_FOR="127.0.0.1"
    )
    assert response.status_code == 403


@pytest.mark.parametrize("host", ["evil.example.com", "192.168.1.20:8000"])
def test_non_loopback_host_header_is_refused(host: str) -> None:
    response = Client().get(OPENAPI_URL, REMOTE_ADDR="127.0.0.1", HTTP_HOST=host)
    assert response.status_code == 400


def test_is_loopback_rejects_a_hostname() -> None:
    assert not is_loopback("localhost")


# --- C5.7: the cron and alert endpoints are as private as the rest of the app ---


@pytest.mark.django_db
@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/crons/summary"),
        ("get", "/api/crons/runs"),
        ("get", "/api/alerts"),
        ("post", "/api/crons/run"),
    ],
)
def test_crons_and_alerts_endpoints_refuse_non_loopback_peers(method: str, path: str) -> None:
    response = getattr(Client(), method)(path, REMOTE_ADDR="8.8.8.8")

    assert response.status_code == 403
