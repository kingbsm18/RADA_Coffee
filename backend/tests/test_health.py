def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
