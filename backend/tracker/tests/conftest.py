import pytest
from ninja.testing import TestClient

from tracker.api import api


@pytest.fixture
def client() -> TestClient:
    return TestClient(api)
