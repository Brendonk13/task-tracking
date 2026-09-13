import random

import pytest
from ninja.testing import TestClient

from tracker.api import api
from tracker.services import names

NAME_RNG_SEED = 4


@pytest.fixture
def client() -> TestClient:
    return TestClient(api)


@pytest.fixture
def seeded_names(monkeypatch) -> random.Random:
    """Make the session name generator deterministic (A11).

    Seed 4 is chosen because, against the current 40x40 word lists, it produces
    repeated adjective-animal pairs within 50 independent draws.
    """
    rng = random.Random(NAME_RNG_SEED)
    monkeypatch.setattr(names, "rng", rng)
    return rng


def register_session(
    client: TestClient,
    session_id: str = "a4c7e1b9-6f2d-4e83-b5a0-9d1c3f7e2b46",
    directory: str = "/home/me/proj",
) -> dict:
    """PUT a session through the API and return the response JSON."""
    response = client.put(f"/sessions/{session_id}", json={"directory": directory})
    assert response.status_code == 200, response.content
    return response.json()
