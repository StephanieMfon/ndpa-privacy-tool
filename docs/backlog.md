# Backlog (not blockers: look at these after the task outline is finished)

## Rules and text analysis
- B-01 PP-06 objection wording: Punch says "right to ask us not to process your personal data for marketing" and the word list misses it. Calibrate in the pilot, then freeze.
- B-02 Re-check MTN's outcomes after the collapsed-text fix. Dashboard shows privacy policy 90% (4 of 5 content checks pass; retention missing): confirm against the policy page.
- B-03 PP-02/PP-04/PP-05 word lists: calibrate against annotators in the pilot, then freeze.
- B-04 PP-03 does not detect contact forms (Minor rule).
- B-05 Policy discovery limits: PDF policies, lazily loaded footers, cross-domain policy (parent company) not decided.
- B-06 R2 (own subsidiaries count as first-party) is not applied automatically in CK-02 and TR-02.
- B-07 CN-01 timing clause ("banner before cookies") is evidence only; revisit with annotators.
- B-08 R5: report CN-02 under both Close readings (strict and implied).
- B-09 Reject run opens one panel level only; "toggle off, then Save" flows are reported as no reject control.
- B-10 R1 necessary-cookie list: confirm in the pilot (TS... F5 pattern is UNVERIFIED).
- B-11 CK-01: Chrome's 400-day cookie cap is UNVERIFIED (from memory).

## Capture and evidence
- B-12 CDP script attribution (reduces unattributed cookie sets; helps SB-02).
- B-13 gtbank ERR_EMPTY_RESPONSE was intermittent: decide how to count failed versus blocked in the block rate.
- B-14 Block rate: bundled headless Chromium was blocked on 2 of 5 sites, real headed Chrome on 0. Report this in Ch4/5 (Ch3's "no anti-bot" claim is false).
- B-15 Google consent-mode "cookieless pings" after Reject (MTN: "still contacted Google Ads" after Reject; jumia): separate in error analysis using query key names (UNVERIFIED).
- B-16 gtbank: 62 third-party requests but no tracker matches earlier; review its domains against the tracker list.

## Dashboard
- B-17 Cancel a running scan.
- B-18 Sector-median overlay on the radar (needs the larger crawl).
- B-19 /method page (read-only rulebook with citations).
- B-20 PDF export and a separate plain-language report.
- B-21 Update Ch3/Ch4 tool list: plain CSS and server-drawn SVG instead of Tailwind/HTMX/Alpine/Chart.js (see decisions D-36).
- B-27 Show scan duration instead of "started / finished" on the Evidence tab.
- B-28 Check the print layout by printing to PDF on real data (only checked in emulated print mode so far).
- B-30 Safari and Firefox were not checked (Chrome engine only).

## Repository
- B-22 DONE 6 Nov 2026: CI (GitHub Actions), ruff configuration, old scanner retired (kept in git under the tag pre-cleanup-2026-11-06). Remaining: delete any old venv/ folder by hand; more fixture sites if the evaluation needs them.
- B-31 Process: for big code deliveries, send smaller pieces plus a file check (a zip snapshot of the project works well).
- B-32 data/lists/ (the frozen tracker list), data/reports/ and eval outputs are not in git. Commit data/lists/ so the frozen list is versioned with the code.
- B-33 Move tests/unit/web_seed.py into a shared tests/support folder when more suites need it.

## Evaluation and writing
- B-23 Evaluation harness: blind annotation import, P/R/F1 per rule and category, Cookiescanner on overlapping rules, error analysis, weighted-versus-equal sensitivity, agreement report.
- B-24 You: rulebook pilot with the second annotator, freeze, annotate 30 sites; update PDF Appendix A/B.
- B-25 Chapters: patch 1-3 (18 rules, scoring model, SQLite, MacBook environment, block rate), write 4-6, regenerate figures, abstract, demo rehearsal.
- B-26 "Should" items by cut order: crawl, evidence integrity extras, CNAME, mobile, dark patterns, CMP hints, LLM advisor, data-flow map, Docker.

## Added 5 Nov 2026 (after the first real use of the dashboard)
- B-34 Real-browser tests now cover the form, Back button, filters, fix-first links, Scan again and compare. Still untested in a browser: the Copy button, Print, and a scan through real Google Chrome on macOS.
- B-35 Bringing earlier scans into a new project folder: copy data/ndpa.db and data/evidence/ across (or start with --db pointing at the old database). A command-line helper could do this.

## Added 6 Nov 2026
- B-36 FUTURE TASK, after the task outline is finished: a technical build book. A very detailed breakdown of the approach and plan for each part of the project (capture, script and cookie attribution, tracker detection, the rules, the text analysis behind the policy rules, scoring, evidence integrity, storage, orchestration, the dashboard, security, evaluation), the reason behind each choice, the considerations, the alternatives that were rejected and why, and what could go wrong, written by the builder (Claude) with as much technical depth as possible. It is the source material for Chapters 3 to 5 and for preparing the defence. Delivered in chat, as always.
- B-38 Re-assessed B-12 with the real scans: MTN has 0 of 13 script-set cookies without an attributed script; punchng has 27 of 107, but they are only two cookie names, FCCDCF and FCNEC (they look like Google Funding Choices consent cookies; what they store is UNVERIFIED). So the CDP attribution upgrade would fix very little. Recommend keeping it low in the cut order. Instead, check at the pilot whether FCCDCF and FCNEC belong on the R1 necessary-cookie list (they are currently counted as non-necessary).
- B-37 CI uses actions/checkout@v6 and actions/setup-python@v6. Newer major versions may exist (UNVERIFIED); update when GitHub warns, or turn on Dependabot for actions.
- B-39 My test sandbox runs older browsers (Playwright 1.56, Chromium 141) than the project's own machine (Chrome 156). Rule: before delivering, state the versions I tested with. A CI job that tests against the newest Playwright would catch these differences earlier.
