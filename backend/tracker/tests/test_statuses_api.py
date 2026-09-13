import pytest

pytestmark = pytest.mark.django_db


def test_built_in_statuses_are_listed(client):
    response = client.get("/statuses")

    assert response.status_code == 200
    assert response.json() == [
        {"name": "blocked", "is_builtin": True},
        {"name": "needs-help", "is_builtin": True},
        {"name": "planning", "is_builtin": True},
        {"name": "implementing-plan", "is_builtin": True},
        {"name": "diagnosing-ticket", "is_builtin": True},
        {"name": "needs-clarification", "is_builtin": True},
        {"name": "ready-for-pr", "is_builtin": True},
        {"name": "merged", "is_builtin": True},
        {"name": "tested-in-cloud", "is_builtin": True},
        {"name": "done", "is_builtin": True},
    ]
