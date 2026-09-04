"""Ticket 18: the `python -m app.evaluation` artifact the dashboard serves."""

import json

import pytest

from app import evaluation
from app.evaluation import _main, report_to_dict, run_evaluation, write_report
from app.simulator.generator import generate_population

pytestmark = pytest.mark.usefixtures("isolated_estimator")


def _tiny_report():
    cases = generate_population(1, 12)
    return run_evaluation(cases, run_seed=1, n_bootstrap_resamples=200)


def test_report_to_dict_has_the_shape_the_dashboard_reads():
    payload = report_to_dict(_tiny_report())

    assert set(payload) >= {"arms", "baselines", "pct_of_offline_optimal", "calibration"}
    assert set(payload["arms"]) == {"no_intervention", "fixed_rule", "offline_optimal", "ai_treatment"}
    for arm in payload["arms"].values():
        assert set(arm) == {"total_nrr", "case_count", "recovered_count"}
    assert [b["baseline_name"] for b in payload["baselines"]] == ["no_intervention", "fixed_rule"]
    for b in payload["baselines"]:
        assert b["ci_lower"] <= b["incremental_nrr"] <= b["ci_upper"]
    for bucket in payload["calibration"]:
        assert 0.0 <= bucket["mean_predicted"] <= 1.0
        assert 0.0 <= bucket["observed_rate"] <= 1.0


def test_report_to_dict_is_json_serializable():
    json.dumps(report_to_dict(_tiny_report()))


def test_write_report_and_main_write_a_parseable_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "_split_cases", lambda split, seed, **sizes: generate_population(seed, 12))
    out = tmp_path / "report.json"

    _main(["--split", "dev", "--out", str(out), "--bootstrap-resamples", "200"])

    payload = json.loads(out.read_text())
    assert payload["split"] == "dev"
    assert payload["arms"]["ai_treatment"]["case_count"] == 12


def test_write_report_returns_the_path(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "_split_cases", lambda split, seed, **sizes: generate_population(seed, 8))
    out = tmp_path / "r.json"
    assert write_report(split="dev", out_path=out, n_bootstrap_resamples=100) == out
