"""Ticket 18: the dashboard's HTTP surface (app/routers/observability.py)."""

import json

import pytest

from tests.conftest import post_signed_webhook, synthetic_payment_failed_payload

pytestmark = pytest.mark.usefixtures("isolated_estimator")


def _open_case(client, payment_id: str) -> dict:
    return post_signed_webhook(
        client,
        "/webhooks/payment-failed",
        synthetic_payment_failed_payload(payment_id=payment_id),
        event_id=f"evt_{payment_id}",
    ).json()


def test_budget_timeline_route_returns_ledger_snapshots(client):
    _open_case(client, "pay_r1")
    _open_case(client, "pay_r2")

    resp = client.get("/budget/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert set(body[0]) == {"timestamp", "case_id", "funded", "reason", "spent", "available", "reserved"}


def test_case_summaries_route_carries_flags(client):
    case = _open_case(client, "pay_r3")

    resp = client.get("/observability/cases")
    assert resp.status_code == 200
    summary = next(c for c in resp.json() if c["id"] == case["id"])
    assert set(summary["flags"]) == {"no_action_recovered", "policy_rejected", "human_overridden", "escalated"}


def test_case_timeline_route(client):
    case = _open_case(client, "pay_r4")

    resp = client.get(f"/observability/cases/{case['id']}/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["case"]["id"] == case["id"]
    assert [s["stage"] for s in body["stages"][:2]] == ["detected", "decision"]


def test_case_timeline_route_404_for_unknown_case(client):
    assert client.get("/observability/cases/nope/timeline").status_code == 404


def test_evaluation_report_404_when_not_generated(client, monkeypatch, tmp_path):
    monkeypatch.setattr("app.routers.observability.DEFAULT_REPORT_PATH", tmp_path / "missing.json")
    resp = client.get("/evaluation/report")
    assert resp.status_code == 404
    assert "app.evaluation" in resp.json()["detail"]


def test_evaluation_report_served_when_present(client, monkeypatch, tmp_path):
    artifact = tmp_path / "report.json"
    artifact.write_text(json.dumps({"arms": {}, "baselines": [], "calibration": [], "pct_of_offline_optimal": 0.5}))
    monkeypatch.setattr("app.routers.observability.DEFAULT_REPORT_PATH", artifact)

    resp = client.get("/evaluation/report")
    assert resp.status_code == 200
    assert resp.json()["pct_of_offline_optimal"] == 0.5
