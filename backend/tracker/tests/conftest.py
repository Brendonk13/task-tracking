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
