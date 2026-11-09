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

## Update 5 Nov 2026 (dashboard)

- D-36 Front end simplified (supersedes the front-end part of D-20): hand-written CSS with light and dark colour tokens, charts drawn on the server as inline SVG (radar, gauge, bars, sparkline, timeline), about 100 lines of plain JavaScript. No Tailwind, HTMX, Alpine or Chart.js, so there is nothing third-party to vendor or keep safe, and charts print crisply.
- D-37 Scans run one at a time in a background queue, each in its own process (refines D-32). A scan over 15 minutes is stopped together with everything it started. Scans interrupted by a restart are marked failed. Dashboard scans use the real, visible Chrome by default (matches annotators and R6); `--headless` is optional.
- D-38 Thin security implemented (D-23): addresses on private or local networks are refused, form posts must come from the dashboard itself (checked with the browser's own Sec-Fetch-Site header, falling back to Origin; Referrer-Policy is same-origin, because no-referrer makes browsers send Origin: null and the form was refused), strict Content-Security-Policy (no inline scripts or styles), only a fixed list of evidence files is served and never outside the scan folder, listens on 127.0.0.1 only.
- D-39 Score display: only applicable rules are scored, so the result always shows "based on N of 28 points", with the risk band first. Equal-weight score shown as "if every check counted the same". (User decision, 5 Nov 2026.)
- D-40 Timeline wording follows what happened: when a site shows no cookie banner, the Accept and Reject runs are labelled "Nothing to click" and described as the whole visit, not "before the click".

## Update 6 Nov 2026 (repository hygiene)

- D-41 The old scanner (scanner/, config/, run_scan.py, main.py and its tests) is retired. Nothing in the new code depended on it; the rulebook, the DuckDuckGo tracker list and rulebook/necessary_cookies.yaml replace its inputs. It stays recoverable from git (tags v0-code-snapshot and pre-cleanup-2026-11-06).
- D-42 spike_05a_results.json and its script are kept in docs/spikes/ as the evidence for choosing the DuckDuckGo tracker list over EasyPrivacy.
- D-43 Lint uses ruff with an explicit rule set (E4, E7, E9, F, I, B, C4), line length 120, and B008 ignored (FastAPI idiom). CI runs ruff, the unit tests and the browser tests on every push.

- D-44 (6 Nov 2026) The live-progress stream sends one update per step instead of only the latest picture, so a quick step is never skipped; tests must never depend on timing. Browser tests must not evaluate strings as JavaScript (the Content-Security-Policy forbids it); they use selector waits.

## Update 7 Nov 2026 (evaluation harness)

- D-45 The positive class is non-compliant ("the tool finds a violation"). TP, FP, FN, TN are counted per rule and summed for categories and overall (micro). Macro F1 is shown beside it. Every undefined number is shown as n/a, never as zero.
- D-46 'Unable to determine' exists only in the tool. It is reported as an abstention; recall is shown both ways: without abstentions (lenient) and with each abstention on a gold non-compliant case counted as a miss (strict).
- D-47 Gold = annotator 1, overridden by an adjudicated sheet where one exists. A second annotator gives agreement (percentage and Cohen's kappa) and a disagreements sheet for adjudication. Intervals are 95% Wilson intervals.
- D-48 Blocked and failed scans have no outcomes: they are left out of the comparison and counted in the block rate. Annotators' labels are scored with the tool's own scoring formula, so the score comparison is like for like. Weighted versus equal-weight sensitivity is reported, and the weights are never tuned.
- D-49 The corpus run is resumable, shuffled by a fixed seed, paused between sites, saved after every site, and refuses to run on an unfrozen or changed rulebook (a trial flag overrides this and marks the report as a trial). It records the freeze hashes and the 72-hour window. Sites are matched by host (without www, keeping a non-default port).

## Update 7 Nov 2026 (pre-freeze calibration)

- D-50 PP-06 recognises 'not to process', 'stop processing' and 'prevent such processing' as naming the right to object, as well as 'object', 'objection' and 'opt out'. It still needs a rights cue ('right', 'entitled', 'request', 'ask', 'exercise') and a data word in the same sentence. Found on punchng.com, whose policy offers the right to object to marketing in other words. Annotators decide from the rulebook, not from this word list; any difference is an error-analysis category.
- D-51 FCCDCF (Google Funding Choices consent record) is on the necessary list as a consent-state cookie. FCNEC is not: sources disagree on what it stores (some list it as analytics), so it stays non-necessary until the pilot decides. Annotators use the same list, so tell them.
- D-52 CN-02 applies the strict reading of Close (R5): a Close click is not consent, so cookies set after it count, and the outcome and score are the strict ones. The implied reading is worked out alongside, stated in the note and on each Close row (excused_if_implied, implied_outcome). It excuses a cookie only if the banner passed CN-01 and the site itself plainly set the cookie (no third party, no tracker vendor). A cookie's purpose cannot be read from observation, so first-party is the only test, and the note says so. The SB rules are unchanged: the rulebook defines Close only for CN-02.

## Update 7 Nov 2026 (annotation, scope)

- D-53 The LLM advisor (D-28, an optional 'Should' item) is dropped from the project's scope. Scoring and every explanation are rule-based and deterministic, which the frozen rulebook and the hash-sealed evidence depend on. An LLM would add non-determinism, would need its own evaluation, and would send page text to an outside service, which sits badly in a privacy tool. The brief does not ask for one. It appears only as future work.
- D-54 Annotators use a workbook generated from the rulebook (python -m ndpa.evaluation.workbook): one Labels sheet with dropdowns, plus guides taken from rules.v2.yaml, the registers in plain words, the frozen necessary-cookie and tracker lists, a site-context sheet and a glossary. The loader reads the finished .xlsx directly. Workbooks are made after the freeze, so the guide shows the frozen wording. The second annotator gets about a third of the sites, spread across six sectors with a fixed seed.
- D-55 Close button (resolves B-45): annotators label CN-02 under the strict reading and write the implied reading in the notes as 'Implied: Compliant' or 'Implied: Non-Compliant'.
- D-56 Pilot sites must not be in the corpus (eval/pilot_sites.txt, guarded by a test). kara.com.ng is in the corpus, so it is not a pilot site.
- D-57 The rulebook file's thresholds are corrected (CK-01 max_days 365 under R3; the 1/9 and bottom-row banner thresholds under CN-01 and R4). The code never read them. A test now fails if the file and the code disagree.

## Update 9 Nov 2026 (pilot, chapters)

- D-58 Pilot: two annotators labelled three sites outside the corpus (oxymon.co, tekedia.com, slot.ng). All 51 labels were identical (Cohen's kappa 1.0; Wilson lower bound 0.93), so no rule wording is changed because of the pilot. The pilot had no Reject button and no Close-only banner, so the wording for those cases is untested.
- D-59 The annotation loader reads .xlsm as well as .xlsx, because Excel saved the pilot workbooks as .xlsm.
- D-60 Corpus sites that were scanned during development (gtbank.com, jumia.com.ng, mtn.ng, jamb.gov.ng, punchng.com, kara.com.ng; konga.com to be confirmed) are reported separately in the evaluation, because some rule wording was refined while examining them.
- D-61 Chapters 1 to 3 change only where the text no longer matches the build. The score is described as tier-weighted, with the equal-weight score reported beside it.
