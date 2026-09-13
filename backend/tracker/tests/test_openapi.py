def test_openapi_is_served(client):
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "openapi" in response.json()
