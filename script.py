"""Project memory files, the pilot results, and a loader fix. Paste this whole file into script.py and run:  python script.py
(running it twice is harmless; files that already exist are kept, so your own edits are never overwritten)

1. Writes docs/PROJECT_MEMORY.md, docs/thesis/SCHOOL_STRUCTURE.md, docs/thesis/THESIS_STATE.md and docs/pilot/PILOT_RESULTS.md.
2. The annotation loader now reads .xlsm files too (Excel saved the pilot workbooks that way), with a test.
3. Records the decisions and backlog items from the pilot.
"""
import pathlib

DOCS = {
    "docs/PROJECT_MEMORY.md": r'''# Project memory: read this first in any new conversation

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
''',
    "docs/thesis/SCHOOL_STRUCTURE.md": r'''# School structure for the report (MIVA Open University, Professional Master's Project)

Source: the school's template and guide, and the project brief. The report has front matter, six chapters, references and appendices.

## Front matter
Title page, declaration, certification and approval page, dedication, acknowledgements, abstract (300 to 500 words), table of contents, list of figures, list of tables, list of abbreviations.

## Chapter One: Introduction (sets the professional and technical context)
1.1 Background to the Project: industry context; technology gap or problem space; relevance to Nigeria and Africa.
1.2 Statement of the Problem: a clear, practical problem; organisational, sectoral or societal impact.
1.3 Aim and Objectives: one broad aim; 4 to 5 specific, measurable objectives.
1.4 Scope of the Project: what is covered; what is excluded.
1.5 Significance of the Project: to industry, organisations, policy or society, and professional practice.

## Chapter Two: Literature Review and Technology Context (applied and technical, not theory-heavy)
2.1 Conceptual Review: core IT concepts related to the project.
2.2 Review of Existing Systems or Solutions: local and international; strengths and weaknesses.
2.3 Review of Relevant Technologies, Tools and Frameworks: languages, platforms, architectures, standards (ISO, IEEE, ITIL, COBIT if relevant).
2.4 Gap Analysis: what existing solutions fail to address; justification for the proposed solution.
(Her approved draft numbers these differently: 2.1 Introduction, 2.2 Conceptual Review, 2.3 Review of Related Work, 2.4 Gap Analysis, 2.5 Technologies. The supervisor approved it, so the numbering stays.)

## Chapter Three: Methodology and System Design (professional and implementation-focused)
3.1 Project Methodology: Agile, Waterfall, Hybrid, DevOps, Design Thinking, and so on; justification for the choice.
3.2 Requirements Analysis: functional and non-functional requirements.
3.3 System Architecture: high-level architecture diagram; description of components.
3.4 System Design: database design (ER diagrams); UML diagrams (use-case, sequence, class); workflow diagrams.
3.5 Tools and Technologies Used: hardware, software, frameworks, programming languages.

## Chapter Four: System Implementation (this is where professional depth shows)
4.1 Development Environment: tools, platforms, configurations.
4.2 Implementation Details: core modules; key algorithms or logic; code structure (high level, not a full code dump).
4.3 Security, Performance and Scalability Considerations: authentication; data protection; optimisation.
4.4 Challenges Encountered: technical challenges; resource limitations; mitigation strategies.

## Chapter Five: Testing, Results and Evaluation (compulsory; may continue from Chapter 4 if the supervisor wishes)
5.1 Testing Strategy: unit testing; integration testing; user acceptance testing.
5.2 Test Results: tables or screenshots; performance metrics.
5.3 Evaluation of Objectives: objective-versus-outcome table; evidence of achievement.
5.4 Discussion of Results: what worked; what did not; comparison with existing systems.

## Chapter Six: Summary, Conclusion and Recommendations (professional reflection)
6.1 Summary of the Project. 6.2 Conclusion. 6.3 Professional Contributions (to industry practice, IT implementation, digital transformation). 6.4 Recommendations for Future Work (system enhancement, further research, policy or organisational adoption).

## References and appendices
References: APA or IEEE style; at least 30 to 50 quality sources: journals, industry reports, standards, technical documentation.
Appendices: screenshots, sample code snippets, user manuals, questionnaires (if any).

## Marking (Table 7.1 of the brief): proposal 40 marks, defence 60 marks
- Problem definition and relevance: clarity of background and problem statement 4+4; relevance to industry, society, Nigeria 4+4; justification of project choice 2+2.
- Aim, objectives and scope (proposal only): clear and achievable aim 3; well-stated, measurable objectives 3; defined scope and limitations 2.
- Literature review and technology context: understanding of concepts and technologies 4+4; review of existing systems and gap analysis 4+4.
- Methodology and system design: appropriateness of methodology 4+4; quality of architecture and design models 4+6.
- Implementation and technical depth (defence only): quality of implementation 6; appropriate use of tools and technologies 4; security, performance or scalability considerations 2.
- Testing, results and evaluation (defence only): adequacy of testing strategy 4; evaluation of objectives and system performance 4.
- Presentation and oral defence (defence only): clarity of presentation 3; ability to respond to questions 4.
- Professionalism and documentation: quality of documentation 3+3; ethical compliance and referencing 3+2.
''',
    "docs/thesis/THESIS_STATE.md": r'''# Thesis state (9 Nov 2026)

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
''',
    "docs/pilot/PILOT_RESULTS.md": r'''# Pilot annotation results (9 Nov 2026)

Purpose: test whether the rulebook wording is clear before it is frozen. Sites (all outside the 30-site corpus): oxymon.co, tekedia.com, slot.ng. Annotators: Stephanie (annotator 1) and Monalisa (annotator 2). Both used the pilot workbook (17 rules per site, 51 labels each). Capture date on the sheet: 8 Nov 2026.

## Result
- Both labelled all 51 items. Identical labels on all 51 (Cohen's kappa 1.0; Wilson 95% interval for 51 of 51: 0.930 to 1.000). Their notes and evidence references were written separately (no identical notes).
- Label counts for each annotator: 24 Non-Compliant, 14 Not Applicable, 13 Compliant.

| Rule | oxymon.co | slot.ng | tekedia.com |
|---|---|---|---|
| CK-01 | NA | NC | NC |
| CK-02 | NA | NA | NC |
| CN-01 | NA | NC | NC |
| CN-02 | NA | NC | NC |
| CN-03 | NA | NC | NC |
| CN-04 | NA | C | NA |
| CN-05 | NA | NC | NA |
| TR-02 | NA | NC | NC |
| SB-01 | NA | NC | NC |
| SB-02 | NA | NC | NC |
| SB-03 | NA | NC | NC |
| PP-01 | C | C | C |
| PP-02 | C | C | C |
| PP-03 | C | C | NC |
| PP-04 | C | C | C |
| PP-05 | NC | NC | C |
| PP-06 | NC | NC | NC |

(C Compliant, NC Non-Compliant, NA Not Applicable.)

## What the three sites were
- oxymon.co: no banner, no cookies and no tracker, so no consent trigger. The consent and script rules are Not Applicable.
- slot.ng: a bottom banner with an Accept button only. A consent flag was already set to true before any click, and Meta and Google measurement cookies were present before the click. Both annotators judged CN-02 Non-Compliant ("a pre-existing consent=true cannot substitute for affirmative action") and CN-04 Compliant.
- tekedia.com: no banner and no settings, with Google advertising trackers contacted before any choice.

## What it does and does not show
- No disagreement, so the pilot did not expose unclear rule wording. No rule text is changed because of it.
- Three sites and 51 items are few. The lower bound of agreement is 0.93, not 1.0.
- None of the three sites had a Reject button or a Close-only banner, so the wording for the Reject run, the Close reading and CN-05 withdrawal is untested. A fourth pilot site with a full banner (Accept, Reject, settings) is planned (B-53).
- Chrome version was not recorded on any site and the capture date is missing for oxymon.co. Register R6 requires both (B-52).
- Notes and Site context show the annotators used the frozen lists (R8, R10 and R1 are cited in their notes).

## Next
Run the tool on the three pilot sites and compare with these labels. That is a dry run of the whole evaluation and will show the first real tool-versus-human differences before the freeze.
''',
}

EXPECTED_LINES = {
    "docs/PROJECT_MEMORY.md": 62,
    "docs/thesis/SCHOOL_STRUCTURE.md": 56,
    "docs/thesis/THESIS_STATE.md": 37,
    "docs/pilot/PILOT_RESULTS.md": 44,
}


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def patch(path, old, new):
    s = read(path)
    if new in s and old not in s:
        print("  already applied:", path)
        return
    assert s.count(old) == 1, f"{path}: the expected text was not found exactly once. Paste me the lines around '{old[:40]}'."
    pathlib.Path(path).write_text(s.replace(old, new), encoding="utf-8")
    print("  patched:", path)


def append_once(path, marker, text):
    if marker in read(path):
        print("  already there:", path, "|", marker)
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    print("  added to:", path, "|", marker)


# 1. The memory and thesis files (kept if they already exist)
problems = []
for name, text in DOCS.items():
    target = pathlib.Path(name)
    if target.exists():
        print("  already there (yours is kept):", name)
        continue
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    got = len(read(name).splitlines())
    if got != EXPECTED_LINES[name]:
        problems.append(f"{name}: {got} lines, expected {EXPECTED_LINES[name]}")
    print("  wrote:", name)
assert not problems, "The paste was not complete:\n  " + "\n  ".join(problems) + "\nDelete those files and paste the whole script again."

# 2. The loader reads .xlsm as well as .xlsx
patch("src/ndpa/evaluation/labels.py", '''    if path.suffix.lower() == ".xlsx":
        return _read_workbook(path)''', '''    if path.suffix.lower() in (".xlsx", ".xlsm"):  # Excel may save the workbook as .xlsm
        return _read_workbook(path)''')
append_once("tests/unit/test_eval_workbook.py", "test_a_workbook_saved_as_xlsm_is_read_too", r'''

def test_a_workbook_saved_as_xlsm_is_read_too(tmp_path):
    path = make(tmp_path)
    fill(path, {("https://mtn.ng", "CN-02"): ("Non-Compliant", None)})
    renamed = path.with_suffix(".xlsm")  # Excel offers this extension; the Labels sheet is the same
    path.rename(renamed)
    ann = load_annotations(renamed, IDS, {normalise_site(s) for s in SITES})
    assert ann.labels[("mtn.ng", "CN-02")].outcome == Outcome.NON_COMPLIANT and ann.blank_rows == 50
''')

# 3. Decisions and backlog
append_once("docs/decisions.md", "D-58", """
## Update 9 Nov 2026 (pilot, chapters)

- D-58 Pilot: two annotators labelled three sites outside the corpus (oxymon.co, tekedia.com, slot.ng). All 51 labels were identical (Cohen's kappa 1.0; Wilson lower bound 0.93), so no rule wording is changed because of the pilot. The pilot had no Reject button and no Close-only banner, so the wording for those cases is untested.
- D-59 The annotation loader reads .xlsm as well as .xlsx, because Excel saved the pilot workbooks as .xlsm.
- D-60 Corpus sites that were scanned during development (gtbank.com, jumia.com.ng, mtn.ng, jamb.gov.ng, punchng.com, kara.com.ng; konga.com to be confirmed) are reported separately in the evaluation, because some rule wording was refined while examining them.
- D-61 Chapters 1 to 3 change only where the text no longer matches the build. The score is described as tier-weighted, with the equal-weight score reported beside it.
""")
append_once("docs/backlog.md", "B-51", """
## Added 9 Nov 2026 (pilot, chapters)
- B-51 Add a sensitivity to the evaluation report: results for all sites and for the sites not seen during development (D-60).
- B-52 Make capture date and Chrome version required: the sheet checker should warn when they are blank (register R6). The pilot left Chrome version blank.
- B-53 A fourth pilot site outside the corpus with a full banner (Accept, Reject and settings), to test the Reject, Close and withdrawal wording before the freeze.
- B-54 Cookiescanner feasibility test: does it install and run on a few sites, and does it check CN-01 and CN-03? Decide B-41 (the Cookiescanner comparison) from the result, before keeping Objective D as written.
- B-55 Run the tool on the three pilot sites and compare with the pilot labels (a dry run of the whole evaluation).
""")
print("\nDone. Now run:  python -m ruff check src tests eval   and   python -m pytest tests/unit -q")