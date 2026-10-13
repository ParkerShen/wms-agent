from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_homepage_serves_chat_interface() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "云仓运营助手" in response.text
    assert 'id="chat-form"' in response.text
    assert 'id="message-input"' in response.text
    assert 'fetch("/chat"' in response.text
    assert "message.textContent = text" in response.text
    assert "订单自然语言查询尚未接入" in response.text


def test_homepage_is_excluded_from_api_schema() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/" not in response.json()["paths"]
    assert "/chat" in response.json()["paths"]
