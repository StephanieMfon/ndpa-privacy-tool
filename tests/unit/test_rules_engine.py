import pathlib

import yaml
from builders import NECESSARY, consent, js_cookie, run, scan

from ndpa.models import RunStatus
from ndpa.rules.engine import CHECKS, evaluate


def test_every_implemented_rule_exists_in_the_rulebook():
    path = pathlib.Path(__file__).resolve().parents[2] / "rulebook" / "rules.v2.yaml"
    ids = {r["id"] for r in yaml.safe_load(path.read_text(encoding="utf-8"))["rules"]}
    assert set(CHECKS) <= ids


def test_evaluate_returns_one_result_per_implemented_rule_in_order():
    results = evaluate(scan(run(events=[js_cookie(100, "_ga")], cookies=["_ga"], cons=consent())), NECESSARY)
    assert [r.rule_id for r in results] == list(CHECKS)


def test_blocked_scan_gets_no_outcomes():
    assert evaluate(scan(run(status=RunStatus.BLOCKED)), NECESSARY) == []
    assert evaluate(scan(run(status=RunStatus.FAILED)), NECESSARY) == []


def test_there_is_one_check_for_every_scored_rule():
    path = pathlib.Path(__file__).resolve().parents[2] / "rulebook" / "rules.v2.yaml"
    scored = {r["id"] for r in yaml.safe_load(path.read_text(encoding="utf-8"))["rules"] if r["tier"] != "unscored"}
    assert set(CHECKS) == scored
