from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_chat_returns_reply() -> None:
    response = client.post("/chat", json={"message": "What is AAPL revenue?", "ticker": "AAPL"})
    assert response.status_code == 200
    data = response.json()
    assert "reply" in data
    assert isinstance(data["reply"], str)
    assert len(data["reply"]) > 0
    assert "sources" in data
