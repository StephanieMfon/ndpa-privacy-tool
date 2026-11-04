"""
run_scan.py

Phase 3 — single entry point tying every module together for one site.
This is the (previously empty) stub already sitting at the repo root.

Runs: harness + consent + fingerprinting + policy capture (all one
session, via full_scan.py) -> every rule module (CK, CN, TR, SB, PP) ->
scoring -> JSON + HTML report.

Usage:
    python run_scan.py https://example.com.ng
    python run_scan.py https://example.com.ng --output-dir data/reports
"""

import argparse
import sys
from pathlib import Path

from scanner.full_scan import run_full_scan
from scanner.rules import cookies, consent, trackers, script_behaviour, privacy_policy
from scanner.scoring import score_results
from scanner.report import build_report, write_json_report, write_html_report


def run(url: str, output_dir: str = "data/reports") -> dict:
    print(f"Scanning {url} ...")
    scan_result = run_full_scan(url)

    policy_text = scan_result.get("policy_capture", {}).get("policy_text")

    all_results = []
    all_results.extend(cookies.evaluate(scan_result, policy_text=policy_text))
    all_results.extend(consent.evaluate(scan_result["consent_capture"], scan_result))
    all_results.extend(trackers.evaluate(scan_result, policy_text=policy_text))
    all_results.extend(script_behaviour.evaluate(scan_result))
    all_results.extend(privacy_policy.evaluate(scan_result))

    score = score_results(all_results)
    report = build_report(url, all_results, score)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_").rstrip("_")
    json_path = out_dir / f"{safe_name}_report.json"
    html_path = out_dir / f"{safe_name}_report.html"

    write_json_report(report, json_path)
    write_html_report(report, html_path)

    overall = score["overall"]
    score_suffix = f"  ({overall['score']*100:.1f}%)" if overall["score"] is not None else "  (no scoreable rules)"
    print(f"\nDone. Overall: {overall['compliant']} compliant / {overall['non_compliant']} non-compliant "
          f"/ {overall['not_applicable']} not applicable{score_suffix}")
    print(f"JSON report: {json_path}")
    print(f"HTML report: {html_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="Run the full NDPA/GAID compliance scan against one site.")
    parser.add_argument("url")
    parser.add_argument("--output-dir", default="data/reports")
    args = parser.parse_args()
    run(args.url, args.output_dir)


if __name__ == "__main__":
    sys.exit(main())