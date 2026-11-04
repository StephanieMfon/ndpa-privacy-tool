"""
scanner/report.py

Phase 3, Module 8 — Report generator.

Produces a JSON report (full machine-readable record, everything needed
for the Chapter 5 stats and appendices) and a self-contained HTML report
(one file, inline CSS, no external dependencies) per site.

Scope choice, stated plainly: no separate PDF pipeline is built here. The
HTML report is self-contained and "print to PDF" from any browser
produces a clean PDF if you need one for the dissertation appendices — a
dedicated automated PDF step (e.g. via weasyprint) is a small addition
later if you decide you want every site's report as a real .pdf file
without the manual print step, not something left unsolved.
"""

import json
from pathlib import Path
from datetime import datetime, timezone

LABEL_COLORS = {"Compliant": "#1a7f37", "Non-Compliant": "#cf222e", "Not Applicable": "#6e7781", "Unable to Determine": "#9a6700"}


def build_report(url: str, rule_results: list[dict], score: dict) -> dict:
    """Assemble the full report structure — the single object both write_json_report and write_html_report consume."""
    return {
        "url": url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "results": rule_results,
    }


def write_json_report(report: dict, output_path: Path) -> None:
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _pct(score_val: float | None) -> str:
    return f"{score_val * 100:.1f}%" if score_val is not None else "N/A"


def _rule_row_html(r: dict) -> str:
    color = LABEL_COLORS.get(r["label"], "#000")
    notes = r.get("notes") or ""
    evidence_preview = ", ".join(f"{k}={v}" for k, v in (r.get("evidence") or {}).items() if k != "pending_policy_crossref")
    return (
        f"<tr><td>{r['rule_id']}</td><td>{r['category']}</td>"
        f"<td style=\"color:{color}; font-weight:600;\">{r['label']}</td>"
        f"<td>{notes}</td><td style=\"font-size:0.8em; color:#57606a;\">{evidence_preview}</td></tr>"
    )


def _category_row_html(cat: str, s: dict) -> str:
    return (
        f"<tr><td>{cat}</td><td>{s['compliant']}</td><td>{s['non_compliant']}</td>"
        f"<td>{s['not_applicable']}</td><td>{_pct(s['score'])}</td></tr>"
    )


def write_html_report(report: dict, output_path: Path) -> None:
    score = report["score"]["overall"]
    score_pct = _pct(score["score"])

    category_rows = "".join(_category_row_html(cat, s) for cat, s in report["score"]["by_category"].items())
    rule_rows = "".join(_rule_row_html(r) for r in report["results"])

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>NDPA Compliance Report — {report['url']}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 40px; color: #1a1a1a; max-width: 960px; }}
  h1 {{ font-size: 1.4em; margin-bottom: 4px; }}
  .meta {{ color: #57606a; font-size: 0.9em; margin-bottom: 20px; }}
  .score {{ font-size: 2.2em; font-weight: 700; margin: 10px 0; }}
  .summary-line {{ color: #57606a; margin-bottom: 24px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0 32px 0; }}
  th, td {{ border: 1px solid #d0d7de; padding: 8px 12px; text-align: left; font-size: 0.88em; vertical-align: top; }}
  th {{ background: #f6f8fa; }}
  h2 {{ font-size: 1.1em; border-bottom: 1px solid #d0d7de; padding-bottom: 6px; }}
</style></head>
<body>
  <h1>NDPA / GAID Privacy Compliance Report</h1>
  <div class="meta">Site: {report['url']}<br>Generated: {report['generated_at']}</div>

  <div class="score">{score_pct}</div>
  <div class="summary-line">{score['compliant']} compliant &nbsp;|&nbsp; {score['non_compliant']} non-compliant &nbsp;|&nbsp; {score['not_applicable']} not applicable</div>

  <h2>By category</h2>
  <table>
    <tr><th>Category</th><th>Compliant</th><th>Non-Compliant</th><th>Not Applicable</th><th>Score</th></tr>
    {category_rows}
  </table>

  <h2>Full rule results</h2>
  <table>
    <tr><th>Rule ID</th><th>Category</th><th>Label</th><th>Notes</th><th>Evidence</th></tr>
    {rule_rows}
  </table>
</body></html>"""

    output_path.write_text(html, encoding="utf-8")