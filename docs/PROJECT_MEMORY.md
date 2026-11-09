# Project memory: read this first in any new conversation

Last updated: 9 Nov 2026. If this file and the code disagree, the code wins. Full detail: `decisions.md`, `backlog.md`, `thesis/THESIS_STATE.md`.

## 1. The project
- Student: Okpo-Mfon Stephanie Crispin, MIT (Master of Information Technology), MIVA Open University. Supervisor: Dr Abdulfatai Dare Adekale.
- Title: "Development of a Privacy Tool for Assessing Nigeria Data Protection Act (NDPA) Compliance". Applied professional project, six-chapter report (structure and marking: `thesis/SCHOOL_STRUCTURE.md`).
- The tool: a rule-based assessor of Nigerian websites against the NDPA 2023 and the GAID 2025. It visits a site three times in real Chrome (no interaction, Reject, Accept), records cookies, requests and script activity on one clock, applies 17 scored rules (plus TR-01, a descriptive tracker inventory), and shows the result in a local dashboard. No LLM is used (D-53).
- Her setup: MacBook Pro, macOS (zsh), Python 3.11, real Chrome (156 at the last scan), Port Harcourt, Nigeria. Repo `ndpa-privacy-tool`, branch `fix-corrections`. Hardware details (chip, memory, macOS version) are still to be filled in for Chapter 3.6.1.

## 2. How to work with her (standing agreements)
- Explain simply and briefly. Friendly tone. Analogies help. Ask a clarifying question before a detailed answer when it matters.
- Code is delivered as ONE Python block to paste into `script.py` and run with `python script.py`. It must be safe to run twice, must check its own result, and must not use shell heredocs or several terminal blocks.
- Every response ends with numbered "Your steps". Every step explains its aim and why in one sentence, lists considerations, and has "Decisions I made (tell me only if you disagree)". Mark facts that are not verified as UNVERIFIED. Be decisive. Do not reopen approved decisions.
- Explain every code (B-n, D-n, R-n) in brackets the first time it appears in a response.
- Do not make a new zip for every problem. Match the size of the delivery to the size of the fix, batch fixes, and test the way she will really use it (real Chrome, a real form). Say what differs in her environment and what could not be tested. A fix gets one pass. If it fails, it goes to the backlog.
- Chapters 1 to 3 are mostly approved by the supervisor: change only what is strictly necessary and leave sections that still hold. Chapters 4 to 6 are written afresh from what we built.
- Anything not needed to finish the outline goes to `backlog.md` and waits.

## 3. Where the truth lives
- Rules: `rulebook/rules.v2.yaml` (18 rules, registers R1 to R13), `rulebook/necessary_cookies.yaml`, `data/lists/tds-snapshot.json` (frozen DuckDuckGo blocklist), `rulebook/FREEZE.json` (hashes, made at the freeze).
- Code: `src/ndpa/` (capture, rules, scoring, evidence, storage, web, evaluation). Tests: `tests/unit`, `tests/integration`. CI: `.github/workflows/ci.yml`.
- Annotation: `eval/pilot/` (pilot), `eval/annotations/` (real), made by `python -m ndpa.evaluation.workbook`.
- Rulebook PDF (the human-readable source of truth): `Annotation_Rulebook_v2_0_no_interpretive_extensions.pdf`.
- Thesis: her Word chapters (she keeps these), `thesis/THESIS_STATE.md`, `thesis/SCHOOL_STRUCTURE.md`.

## 4. Decisions that matter most
- Rulebook v2: 17 scored rules plus TR-01; no interpretive extensions (criteria that go beyond what the NDPA or GAID state were removed). Fixed in advance, frozen before the evaluation, never tuned.
- Scoring (D-02 to D-06, D-39): tier-weighted. Critical rules 1.5 points, Major 2, Minor 1, total 28. Overlapping rules share points (CN-02 with SB-02, SB-01 with SB-03). Risk band High/Moderate/Low. Coverage under 70% hides the score. An equal-weight score (total 15) is shown beside it. Blocked or failed scans get no score (D-35).
- Capture: three runs in fresh browser contexts, real headed Chrome by default, viewport 1366 x 768, English (Nigeria), Africa/Lagos time zone, 10 seconds observation (R6, R7).
- Trackers (D-29, R8): the frozen DuckDuckGo blocklist (1,001 entries: 365 default block, 636 default ignore), used by the tool and the annotators alike.
- Text rules: spaCy blank pipeline with a sentence splitter and word-list matching; no trained model. The LLM advisor is dropped (D-53).
- Storage: SQLite (7 tables) plus evidence folders sealed in a SHA-256 hash chain with a stand-alone `verify.py`.
- Dashboard (D-36 to D-38): FastAPI and Jinja2, hand-written CSS, server-drawn SVG, strict CSP, listens on 127.0.0.1. Scans run one at a time from a queue, each in its own process with a 15-minute limit.
- Calibration (D-50 to D-52): PP-06 recognises "not to process" wording; FCCDCF is a necessary cookie; CN-02 treats Close as not consent (strict) and reports the implied reading alongside.
- Annotation (D-54 to D-56): workbook with dropdowns; CN-02 labelled strict with the implied reading in the notes; pilot sites must be outside the corpus.
- Evaluation (D-45 to D-49): Non-Compliant is the positive class; the tool's "unable to determine" is an abstention reported separately; reference labels are annotator 1 overridden by adjudication; blocked and failed sites are left out of the rule metrics and counted in the block rate; weights are never tuned.

## 5. Where we are (9 Nov 2026)
Done: rulebook v2, capture, 17 rules, scoring, evidence chain, SQLite, dashboard (checked on real scans), CI (392 tests), evaluation harness, calibration, annotation workbook, pilot annotation (two annotators, three sites, full agreement).
Next, in this order:
1. Apply the Chapter 1 to 3 patches (drafted 9 Nov; status in `thesis/THESIS_STATE.md`).
2. Decide the Cookiescanner comparison (B-41) after a feasibility test, and fix Objective D accordingly.
3. Compare the tool with the pilot labels (a dry run of the evaluation), add a fourth pilot site that has a full banner (Accept, Reject, settings), and calibrate if needed.
4. Freeze the rulebook, regenerate the workbooks, scan the 30 sites inside one 72-hour window, annotate (annotator 1: 30 sites, annotator 2: 10), adjudicate, run the report.
5. Then write Chapters 4 to 6 and finish Chapters 1 to 3. The build book (B-36) can be written at any time.

## 6. What an assistant may not have seen (known gaps)
- The original handoff document from the first conversation (its decisions are recorded in `decisions.md`, but the original wording is not available).
- The supervisor's "changes file" (a list of requested changes, referred to by item number in earlier notes).
- Her citation-check notes for Table 2.1 (`docs/citation_check.md` is not in the repository).
- The full reference list, the figure files (3.1 to 3.3), the abstract and the front matter.
- Her real `data/` folder (only a snapshot from 5 Nov was seen).

## 7. Starting a new conversation
Upload: the repository zip, this file, `thesis/THESIS_STATE.md`, her current Chapters 1 to 6 (Word), the reference list, the annotated pilot and real workbooks, and the latest evaluation report folder. Then say: "Read docs/PROJECT_MEMORY.md first, then tell me what you understood and what you could not see."

## 8. Reading the codes
- D-n: a decision, written in `decisions.md`.
- B-n: a backlog item (work that waits), in `backlog.md`.
- R1 to R13: the rulebook's "decide in advance" registers (for example R4 is the 3 x 3 grid banner test, R8 is the tracker definition).
- CK, CN, TR, SB, PP: rule groups: Cookies, Consent, Trackers, Script behaviour, Privacy policy. CN-02 is the second rule in the Consent group.
