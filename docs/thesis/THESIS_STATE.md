# Thesis state (9 Nov 2026)

Her Word chapters are the source of truth for wording. This file records their structure, the claims that no longer match the build, and the status of each patch. Chapters 1 to 3 were mostly approved by the supervisor, so only strictly necessary changes are made.

## 1. Structure of the approved drafts
- Chapter 1: 1.1 Background, 1.2 Statement of the Problem, 1.3 Aim and Objectives (A to D), 1.4 Scope, 1.5 Significance.
- Chapter 2: 2.1 Introduction, 2.2 Conceptual Review (2.2.1 to 2.2.7), 2.3 Review of Related Work, 2.4 Gap Analysis, 2.5 Technologies (2.5.1 Python, 2.5.2 Playwright, 2.5.3 BeautifulSoup4, 2.5.4 spaCy, 2.5.5 Tracker and Script Identification, 2.5.6 Performance Metrics, 2.5.6.1 Justification). Tables 2.1 (computational observability) and 2.2 (metrics).
- Chapter 3: 3.1 Introduction, 3.2 Methodology (Agile; the numbered list of steps A to D), 3.3 Requirements (Table 3.1), 3.4 Architecture (Figure 3.1), 3.5 Design (3.5.1 Data, 3.5.2 Browser Automation, 3.5.3 Privacy Assessment, 3.5.4 Policy Analyser, 3.5.5 Rule Evaluation and Scoring with Equation 3.1 and Figures 3.2 and 3.3, 3.5.6 Report Generator, 3.5.7 Evaluation Dataset and Annotation Protocol), 3.6 Tools (hardware, languages, libraries, version control).
- Objectives: A design the rule-based framework; B develop the tool; C develop the reporting component; D evaluate against a manually annotated dataset and Cookiescanner (Gundelach et al., 2023) with precision, recall and F1.

## 2. What the build now says (use these facts)
- 18 rules, 17 scored: CK-01 to CK-02, CN-01 to CN-05, TR-01 (descriptive, not scored) and TR-02, SB-01 to SB-03, PP-01 to PP-06. 13 registers (R1 to R13). No interpretive extensions.
- Score = 100 x (sum of weights of Compliant rules) / (sum of weights of Compliant and Non-Compliant rules). Weights: Critical 1.5 (CN-02, SB-01, SB-02, SB-03), Major 2 (CK-02, CN-01, CN-03, CN-05, TR-02, PP-01, PP-02, PP-04, PP-06), Minor 1 (CK-01, CN-04, PP-03, PP-05). Total 28. Equal-weight score (total 15) shown beside it. Risk band by tier. Coverage under 70% hides the score. Blocked or failed scans get no score.
- Capture: Playwright driving real Chrome, three runs (no interaction, Reject, Accept), each in a fresh context; 10 s observation; viewport 1366 x 768; en-NG; Africa/Lagos. Script attribution by wrapping the cookie and storage setters. Blocked scans are detected and recorded.
- Trackers: frozen DuckDuckGo blocklist snapshot, 1,001 entries (365 block, 636 ignore).
- Policy: found within two clicks; spaCy blank pipeline plus sentence splitter; word-list Matcher; no trained model. The text analyser serves CK-01, CK-02, TR-02 and the PP rules.
- Storage: SQLite, 7 tables (scan, run, event, finding, score, artifact, progress); evidence folder per scan (run.json, DOM snapshot and screenshots per run, policy pages, results.json, manifest.json, verify.py) sealed by a SHA-256 hash chain.
- Application: FastAPI, Jinja2, uvicorn, server-drawn SVG; queue with one scan at a time, one process per scan, 15-minute limit; listens on 127.0.0.1. Pydantic models, PyYAML, tldextract, openpyxl. pytest, ruff, GitHub Actions.
- Evaluation: 30 sites (6 Banking/Fintech, 5 Telecom, 5 E-commerce, 5 Government, 5 News, 4 Health); annotator 1 labels all, annotator 2 labels a sector-balanced 10; Cohen's kappa; adjudication; Wilson 95% intervals; micro and macro F1; abstentions reported separately; block rate reported.
- Not true any more: 24 rules; "equal-weight scoring"; headless Chromium single session; "no anti-bot obstruction"; nine named tracker vendors; fingerprinting (SB-04); BeautifulSoup4, Requests, ReportLab and PhraseMatcher; "no relational database" and plain-dictionary data structures; AMD Ryzen and Ubuntu; deployment on Railway; "sole annotator"; "five sites per sector".

## 3. Patch status (drafted 9 Nov 2026; mark each as applied in Word)
Chapter 1: C1-1 Objective D (decision on Cookiescanner needed); C1-2 Scope.
Chapter 2: C2-1 "24 rules" in 2.4; C2-2 anti-bot sentence in 2.5.2; C2-3 replace 2.5.3; C2-4 PhraseMatcher in 2.5.4; C2-5 replace 2.5.5; C2-6 add 2.5.6.2 and three references; C2-7 Table 2.1 new column and note. Optional: "five sections" should read "four" in 2.1.
Chapter 3: C3-1 and C3-2 methodology paragraphs; C3-3 the numbered list; C3-4 Table 3.1; C3-5 architecture text; C3-6 data design; C3-7 browser automation; C3-8 privacy assessment; C3-9 policy analyser; C3-10 scoring and Equation 3.1; C3-11 report generator; C3-12 dataset and annotation protocol; C3-13 hardware (needs her machine details); C3-14 languages, libraries and version control. Figures 3.1, 3.2 and 3.3 to be redrawn.
New references: Cohen (1960); Landis and Koch (1977); Wilson (1927).

## 4. Open decisions and facts needed
- Cookiescanner comparison (B-41): feasibility test first; Objective D wording depends on it.
- Hardware details for 3.6.1 (chip, memory, macOS version).
- Development-exposed corpus sites: gtbank.com, jumia.com.ng, mtn.ng, jamb.gov.ng, punchng.com and kara.com.ng appear in the project's data; konga.com was scanned by her. To be confirmed. They are reported separately in the evaluation (B-51).
- Tell the supervisor that the score is now tier-weighted (the approved draft said equal weights), with an equal-weight score reported beside it.

## 5. Plan for Chapters 4 to 6 (from the build)
- Ch 4.1 environment (machine, Python, Chrome, Playwright versions, CI). 4.2 core modules (capture, rules, scoring, evidence chain, storage, dashboard, evaluation harness), with key logic: three-run timeline, script attribution, tracker definition (R8), CN-02 windows and the Close reading, the scoring formula, the hash chain. 4.3 security (SSRF guard, same-origin check, CSP, whitelist of evidence files, loopback only), data protection (hashes not raw cookie values), performance (queue, timeouts), scalability. 4.4 challenges (blocked sites, CSP and Origin bug, SQLite threads, race conditions in the live stream, delivery failures, interpretive extensions removed).
- Ch 5.1 testing strategy (unit, integration with controlled fixture sites, browser tests, CI; counts from the latest run). 5.2 results (evaluation report folder). 5.3 objective-versus-outcome table. 5.4 discussion (block rate, error analysis, abstentions, development exposure, limits).
- Ch 6 summary, conclusion, professional contributions, future work (LLM advisor, mobile, crawl, CNAME cloaking, dark patterns, containers, Cookiescanner comparison if not done).
