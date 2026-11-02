# Decision log (frozen 28 Oct 2026)

## Scoring

- D-02 Unit = rule; any-fail per site; n-of-m kept as evidence
- D-03 Tier weights Critical 3 / Major 2 / Minor 1, pre-registered, never tuned; equal-weight score also reported
- D-04 Risk band: High if any Critical fails; Moderate if only Major; Low otherwise
- D-05/D-35 Blocked scan (403/429/challenge/tiny HAR) = "Blocked", no score. Unable to Determine excluded; coverage = determined weight / 50; hide score if < 70%
- D-06 Score card + radar + overlays + bars + Fix-first list
- D-07/D-33 Consent rules (CN-01..07, SB-02) are N/A only if no non-essential cookies/storage/trackers in ANY run; otherwise missing banner = Non-Compliant
- D-34 Policy not found after exhaustive discovery: PP-01 fails, PP-02..06 Non-Compliant "root cause: PP-01". Uncertain discovery: Unable to Determine

## Capture

- D-08 Three runs (No-action / Accept / Reject), fresh context each
- D-30 One monotonic clock per run (ms since navigation start)
- D-09 CDP script attribution (spike-gated; fallback "unattributed")
- D-10 Cookies + localStorage + sessionStorage + IndexedDB; key names and hashes only
- D-16 Policy discovery: common paths + two clicks
- D-18 Mobile: one extra No-action pass; desktop is the scored baseline
- D-19 Evaluation scans from Nigeria
- Blocked sites: realistic capture first (real Chrome, UA/locale, pacing); always show Blocked; replace sites only as last resort; report final block rate

## Rules and registries

- D-11 Rulebook v2 = YAML + Python check functions
- D-12 27 rules (26 scored); new CN-08, PP-07, PP-08; SB-01 (script loaded) split from SB-03 (beacon)
- D-14 CN-04 computed (click depth, area ratio < 0.5, reject contrast < 3:1)
- D-15 CK-04 threshold 6 months (GAID Art 49(3) reference)
- D-13 Tracker matching: registrable domain + blocklist URL rules
- D-29 DuckDuckGo tracker blocklist only (EasyPrivacy dropped) + small vendors_extra.yaml
- D-17 Cross-border map: observed recipients + apparent jurisdiction; only PP-07 scored

## Platform

- D-01 Targeted rebuild; port rule logic, tests, config
- D-20 FastAPI, sqlite3, Jinja2, HTMX, Alpine, Tailwind CLI, SSE, Chart.js (vendored)
- D-21/D-22 SQLite + Pydantic; JSON/evidence canonical; never store raw payloads
- D-23 Thin security: SSRF guard, autoescape, non-root container, timeouts
- D-24 SHA-256 hash-chained manifest + verify.py (no RFC 3161)
- D-27 Demo = pre-seeded scans + one live scan; Docker; no hosted deployment
- D-31/D-32 Events in SQLite by (run_id, t_ms); one scan = one subprocess

## Evaluation

- D-25 Blind annotation, 72-hour freeze, second annotator on ~10 stratified sites
- D-26 P/R/F1 per site-rule; Cookiescanner on overlapping rules only
- D-28 LLM = advisor only (Should), never scorer

## Scope

Must: Rulebook v2, 3-run capture, attribution, storage, scoring v2, remediation engine, PP-08, dashboard/report, timeline, evaluation harness, fixtures + CI, repo hygiene, policy discovery, tracker registry, bot-block detection
Should: CNAME cloaking, dark-pattern metrics, thin security, history/diff, data-flow map, mobile, evidence integrity, frozen corpus + Docker, LLM advisor, CMP fix hints
Could: .ng crawl (200-300), threat model/CSP/rate limits
Won't: geo-gated test, server-side analytics, accounts/alerts, ML scorer, hosted deployment
Cut order if behind: crawl -> evidence integrity -> CNAME -> mobile -> dark patterns -> CMP hints -> LLM -> data-flow

## Update 29 Oct 2026 (after Rulebook v2 PDF)

- Rulebook v2 PDF is the source of truth: 18 rules (17 scored + TR-01). Annotation starts from scratch.
- R8: annotators and tool both use the frozen DuckDuckGo blocklist snapshot (version + hash). Annotators use an Excel lookup.
- R3 / D-15: CK-01 threshold = 12 months, methodological, not statutory.
- R10 / D-12: SB-01 "active" = transmitting or storing. SB-01, SB-02, SB-03 and CN-02 all kept.
- Overlap rule (pending OK): CN-02+SB-02 share 3 points; SB-01+SB-03 share 3 points. Total weight 28. Risk band unchanged.
