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
