"""ADR-0015 (hosted demo): the /config flag surface and the DEMO_READONLY
gate on the human-action write endpoints."""

from app.config import settings


def test_config_reports_demo_readonly_false_by_default(client):
    response = client.get("/config")
    assert response.status_code == 200
    assert response.json() == {"demo_readonly": False}


def test_config_reports_demo_readonly_when_set(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_readonly", True)
    assert client.get("/config").json() == {"demo_readonly": True}


def test_write_endpoints_open_when_not_readonly(client):
    # 404 (no such case), not 403 -- the gate is open, the request reaches the body.
    assert client.post("/cases/nope/override", json={"intervention": "payment_retry"}).status_code == 404
    assert client.post("/cases/nope/resolve", json={"outcome": "stopped", "reason": "x"}).status_code == 404


def test_write_endpoints_403_when_readonly(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_readonly", True)
    assert client.post("/cases/any/override", json={"intervention": "payment_retry"}).status_code == 403
    assert client.post("/cases/any/resolve", json={"outcome": "stopped", "reason": "x"}).status_code == 403


def test_readonly_does_not_touch_read_endpoints(client, monkeypatch):
    monkeypatch.setattr(settings, "demo_readonly", True)
    assert client.get("/cases").status_code == 200
    assert client.get("/observability/cases").status_code == 200
