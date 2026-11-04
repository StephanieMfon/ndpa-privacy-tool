"""
tests/test_report.py

Run: pytest tests/test_report.py -v

Note: these test STRUCTURE (does the JSON have the right shape, does the
HTML contain the data it should) — not visual correctness. Open a
generated HTML report in a real browser at least once to confirm it
actually looks right; that's not something a unit test can verify.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scanner import report, scoring


def sample_results():
    return [
        {"rule_id": "CK-01", "category": "cookies", "label": "Compliant", "evidence": {"cookie_name": "_ga"}, "notes": None},
        {"rule_id": "CN-01", "category": "consent", "label": "Non-Compliant", "evidence": {}, "notes": "Banner in bottom 25%."},
        {"rule_id": "CK-04", "category": "cookies", "label": "Not Applicable", "evidence": {}, "notes": "Session cookie."},
    ]


def test_build_report_structure():
    results = sample_results()
    score = scoring.score_results(results)
    r = report.build_report("https://example.com.ng", results, score)
    assert r["url"] == "https://example.com.ng"
    assert "generated_at" in r
    assert r["results"] == results
    assert r["score"] == score


def test_write_json_report_round_trips():
    results = sample_results()
    score = scoring.score_results(results)
    r = report.build_report("https://example.com.ng", results, score)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.json"
        report.write_json_report(r, path)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["url"] == "https://example.com.ng"
        assert len(loaded["results"]) == 3


def test_write_html_report_contains_expected_content():
    results = sample_results()
    score = scoring.score_results(results)
    r = report.build_report("https://example.com.ng", results, score)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.html"
        report.write_html_report(r, path)
        assert path.exists()
        html = path.read_text(encoding="utf-8")

        assert "https://example.com.ng" in html
        assert "CK-01" in html
        assert "CN-01" in html
        assert "Non-Compliant" in html
        assert "<html>" in html and "</html>" in html


def test_write_html_report_handles_none_score_gracefully():
    """All-Not-Applicable case — score is None, HTML generation must not crash."""
    results = [{"rule_id": "CK-04", "category": "cookies", "label": "Not Applicable", "evidence": {}, "notes": None}]
    score = scoring.score_results(results)
    r = report.build_report("https://example.com.ng", results, score)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "report.html"
        report.write_html_report(r, path)  # must not raise
        html = path.read_text(encoding="utf-8")
        assert "N/A" in html