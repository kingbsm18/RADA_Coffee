import pytest
from starlette.websockets import WebSocketDisconnect

from app.services.notification import hub

URL = "/api/v1/ws/alerts?site_id=cafe-01"


def token_of(client, username="manager-a", password="correct-horse-battery") -> str:
    return client.post("/api/v1/auth/login", json={"username": username, "password": password}).json()["access_token"]


def test_authenticated_client_receives_published_alerts(client, world) -> None:
    with client.websocket_connect(URL) as ws:
        ws.send_json({"token": token_of(client)})
        assert ws.receive_json() == {"type": "ready"}
        hub.publish("cafe-01", {"type": "alert_created", "alert": {"id": "x"}})
        assert ws.receive_json() == {"type": "alert_created", "alert": {"id": "x"}}
        assert hub.subscriber_count("cafe-01") == 1
    assert hub.subscriber_count("cafe-01") == 0  # cleaned up on disconnect


def test_clients_only_receive_their_own_sites_messages(client, world) -> None:
    with client.websocket_connect(URL) as ws:
        ws.send_json({"token": token_of(client)})
        ws.receive_json()
        hub.publish("other-01", {"type": "alert_created", "alert": {"id": "leak"}})
        hub.publish("cafe-01", {"type": "alert_updated", "alert": {"id": "mine"}})
        assert ws.receive_json()["alert"]["id"] == "mine"


@pytest.mark.parametrize("first_message", [{"token": "garbage"}, {"nope": 1}, {"token": 5}])
def test_invalid_first_message_closes_the_socket(client, world, first_message) -> None:
    with client.websocket_connect(URL) as ws:
        ws.send_json(first_message)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1008


def test_a_user_of_another_organization_is_refused(client, world) -> None:
    with client.websocket_connect(URL) as ws:
        ws.send_json({"token": token_of(client, "admin-b")})
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1008


def test_unknown_site_is_refused(client, world) -> None:
    with client.websocket_connect("/api/v1/ws/alerts?site_id=nope") as ws:
        ws.send_json({"token": token_of(client)})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_publish_without_subscribers_is_a_noop() -> None:
    hub.publish("cafe-01", {"type": "x"})  # must not raise
