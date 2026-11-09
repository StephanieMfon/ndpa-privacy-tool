"""Builds the annotator workbook (an Excel file), generated from the rulebook so the guide can never drift from the rules.

    python -m ndpa.evaluation.workbook                 annotator1.xlsx (every site) and annotator2.xlsx (the second annotator's share)
    python -m ndpa.evaluation.workbook --pilot --sites eval/pilot_sites.txt --out eval/pilot     one workbook each, for the pilot

The finished workbook is read back directly by ndpa.evaluation.labels and ndpa.evaluation.report (the 'Labels' sheet).
"""
import argparse
import json
import random
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.properties import PageSetupProperties

from ndpa.evaluation.corpus import read_sites
from ndpa.evaluation.labels import normalise_site
from ndpa.scoring.score import load_rulebook

LABEL_CHOICES = ["Compliant", "Non-Compliant", "Not Applicable"]
SEED = 20261106

# The sector of each corpus site, so the second annotator's share is spread across sectors instead of drawn at random.
SECTORS = {
    "gtbank.com": "Banks and fintech", "accessbankplc.com": "Banks and fintech", "zenithbank.com": "Banks and fintech",
    "flutterwave.com": "Banks and fintech", "paystack.com": "Banks and fintech", "kuda.com": "Banks and fintech",
    "mtn.ng": "Telecoms", "airtel.com.ng": "Telecoms", "gloworld.com": "Telecoms", "9mobile.com.ng": "Telecoms", "ntel.com.ng": "Telecoms",
    "jumia.com.ng": "Online shops", "konga.com": "Online shops", "jiji.ng": "Online shops", "kara.com.ng": "Online shops", "csigrocery.com": "Online shops",
    "nimc.gov.ng": "Government", "nass.gov.ng": "Government", "jamb.gov.ng": "Government", "ndpc.gov.ng": "Government", "fedcivilservice.gov.ng": "Government",
    "punchng.com": "News", "thenationonlineng.net": "News", "dailytrust.com": "News", "premiumtimesng.com": "News", "channelstv.com": "News",
    "luth.org.ng": "Health", "duchessinternationalhospital.com": "Health", "evercare.ng": "Health", "meridianhospital.com.ng": "Health",
}
QUOTAS = {"Banks and fintech": 2, "Telecoms": 2, "Online shops": 2, "Government": 1, "News": 2, "Health": 1}  # 10 sites

REGISTER_PLAIN = {
    "R1": "Which cookies count as strictly necessary. Use the 'Necessary cookies' sheet. A cookie that is not on it and has no documented purpose counts as non-necessary: write 'purpose unknown' in the notes.",
    "R2": "Two companies count as the same 'first party' if the site's own disclosures, or a public company record, show they have the same owner.",
    "R3": "The cookie lifespan limit used for rule CK-01: 12 months (365 days). A working rule we chose, not a number in the law.",
    "R4": "The banner size test for rule CN-01 (the 3 by 3 grid). Take a screenshot of the first screen and cut it into a 3 by 3 grid of 9 equal cells. The banner counts as significantly obstructing if its own box covers at least 1 of the 9 cells AND is not entirely inside the bottom row. Measure the banner box, not any dimmed background behind it. Record its position: bottom, top, centre_modal, left, right or full_screen.",
    "R5": "How to treat the Close (x) button, for rule CN-02. A close icon is not Reject. See the special cases on the 'Read me first' sheet.",
    "R6": "The conditions to view every site under: Chrome (stable), a normal desktop window 1366 by 768, a fresh named profile, no extensions, NOT Incognito, connected from Nigeria, browser language English (Nigeria). Write the Chrome version and the date on the 'Site context' sheet.",
    "R7": "The timing: wait 10 seconds after the page finishes loading, touching nothing. After you click Accept or Reject, wait the same 10 seconds.",
    "R8": "What counts as a tracker (rule TR-01). A request to another company's domain is a tracker if that domain is on the 'Tracker lookup' sheet AND the list's default for it is 'block' (or the request address matches one of that domain's special address rules; a matching rule marked 'ignore' means it is NOT a tracker). To apply the address rules exactly, run: python eval/is_tracker.py your_recording.har",
    "R9": "To count as 'named' (rule TR-02), a policy must name the vendor or product (for example 'Google Analytics'). Naming only a category (for example 'analytics providers') does not count.",
    "R10": "What 'active' means for rule SB-01: the script sends a request to another company's tracker, or writes a cookie or local-storage value. A script that is loaded but does nothing is 'dormant': the rule is Not Applicable (write 'dormant' as the reason).",
    "R11": "A privacy policy that sits inside the Terms page counts, if it has its own heading about privacy or personal data (rules PP-01 and PP-02).",
    "R12": "A generic contact form does not count as a privacy contact (rule PP-03) unless the form says it covers privacy matters.",
    "R13": "A stated purpose (rule PP-04) must name the kind of data AND the specific use. Example that counts: 'email address: to send order confirmations'. 'To improve our services' alone does not.",
}
USED_BY_PLAIN = {"0.2": "rulebook section 0.2 (definitions)", "0.4": "rulebook section 0.4 (capture conditions)"}
NECESSARY_GROUPS = {"consent_state": "Remembers the visitor's cookie choice (these are necessary)", "security": "Security and bot protection",
                    "load_balancing": "Keeps a visitor on the same server", "session": "Keeps a visitor logged in or a basket together during one visit"}
CODES = [
    ("CK", "Rule group: Cookies (how cookies are set and how long they last)."), ("CN", "Rule group: Consent (the cookie banner and the choices it offers)."),
    ("TR", "Rule group: Trackers (companies that follow visitors from site to site). TR-01 is not labelled; it produces the tracker list."),
    ("SB", "Rule group: Script behaviour (what a site's code does BEFORE the visitor agrees)."), ("PP", "Rule group: Privacy policy."),
    ("CN-02 and similar", "A rule code: the second rule in the Consent group. Every rule is described on the 'Rules guide' sheet."),
    ("Compliant / Non-Compliant / Not Applicable", "The three labels you use. Not Applicable always needs a reason in the na_reason column."),
    ("Critical / Major / Minor", "How serious a rule is. Critical: processing happened without or against consent. Major: a consent or transparency feature is missing or broken. Minor: tidiness and completeness. This only affects the score, not how you label."),
    ("R1 to R13", "The rulebook's 'decide in advance' rules (registers): fixed answers to questions that could otherwise be argued either way. All are explained on the 'Registers' sheet."),
    ("Run 1, Run 2, Run 3", "Run 1: open the site and touch nothing. Run 2: open it fresh and click Reject (only if a Reject control exists). Run 3: open it fresh and click Accept."),
    ("NDPA", "Nigeria Data Protection Act 2023, the law."), ("GAID", "General Application and Implementation Directive 2025, the regulator's detailed rules under the NDPA."),
    ("NDPC", "Nigeria Data Protection Commission, the regulator."), ("CMP", "Consent management platform: the software that shows the cookie banner and remembers the choice."),
    ("First party / third party", "First party: the site you are visiting (and companies it is shown to own, R2). Third party: any other company whose address shows up in what the page loads."),
    ("Non-necessary cookie", "A cookie the site does not strictly need to work (for example analytics or advertising). Strictly necessary ones are listed on the 'Necessary cookies' sheet (R1)."),
    ("Consent trigger", "The point where consent becomes relevant: at least one non-necessary cookie is set, or one TR-01 tracker loads, in any run. No trigger means the consent rules do not apply."),
    ("Banner", "The cookie notice (a bar, a box or a full-screen window). A settings panel reached from it counts as part of it."),
    ("Close (x)", "A small x or 'dismiss' control. It is NOT Reject, and in the strict reading it is NOT consent either."),
    ("Root cause PP-01", "When no privacy policy exists, every rule that needs policy text fails because of that one missing policy. Write 'root cause: PP-01' in the notes."),
    ("Purpose unknown", "A cookie that is not on the necessary list and whose purpose you cannot find. It counts as non-necessary; say 'purpose unknown' in the notes."),
    ("DevTools", "Chrome's built-in inspector. Open it with F12, or Cmd+Option+I on a Mac. Application tab: cookies and storage. Network tab: everything the page loads."),
    ("HAR file", "A recording of everything the page loaded. In DevTools, Network tab, use 'Save all as HAR with content'. Used with eval/is_tracker.py."),
    ("Evidence reference", "A note of where you saw something, so someone else can check: a screenshot file name, a page address, a time. Put it in the evidence_ref column."),
]
SECTION_FILL = PatternFill("solid", fgColor="1F3A68")
HEADER_FONT = Font(bold=True, color="FFFFFF")
HELP_FILL = PatternFill("solid", fgColor="EEF1F7")
WRAP = Alignment(wrap_text=True, vertical="top")
THIN = Side(style="thin", color="B8C0D0")


def sector_of(site: str) -> str:
    return SECTORS.get(normalise_site(site), "Other")


def second_annotator_sites(sites: list[str], seed: int = SEED) -> list[str]:
    """About 10 sites spread across the sectors, chosen with a fixed seed so the choice can be explained and repeated."""
    rng = random.Random(seed)
    chosen: set[str] = set()
    for sector, quota in QUOTAS.items():
        pool = sorted(s for s in sites if sector_of(s) == sector)
        chosen.update(rng.sample(pool, min(quota, len(pool))))
    return [s for s in sites if s in chosen]


def plain(text: str) -> str:
    """Rule texts in the rulebook use code words; annotators read plain ones."""
    for code, words in (("max_days", "12 months (365 days, register R3)"), ("non_compliant", "Non-Compliant"), ("not_applicable", "Not Applicable"),
                        ("unable_to_determine", "unable to determine (the tool only)")):
        text = text.replace(code, words)
    return text


def read_me(count: int, rows: int, kind: str) -> list[tuple[str, str]]:
    who = {"main1": "Annotator 1", "main2": "Annotator 2 (you label only the sites listed here: about a third of the corpus)",
           "pilot1": "Pilot, annotator 1", "pilot2": "Pilot, annotator 2"}[kind]
    out = [("title", "NDPA website privacy annotation: annotator workbook"),
           ("p", f"{who}. {count} sites x 17 rules = {rows} labels. Your name: ______________   Dates you worked: ______________"),
           ("h", "What you are doing"),
           ("p", "You will look at real Nigerian websites in an ordinary Chrome browser and decide, for each of 17 rules, whether the site is Compliant, Non-Compliant or Not Applicable. "
                 "The rules come from the Nigeria Data Protection Act 2023 (NDPA) and the General Application and Implementation Directive 2025 (GAID). "
                 "Your labels are the answer key that the software tool is later compared with, so your own careful, independent judgement is the whole point.")]
    if kind.startswith("pilot"):
        out += [("p", "THIS IS THE PILOT. It tests whether the rulebook's wording is clear. It is not part of the final evaluation. "
                      "Write down every place where a rule was unclear or you had to guess, in the notes column: that is exactly what the pilot is for.")]
    out += [("h", "Rules of the study (please follow them)"),
            ("li", "1. Work blind. Do not run the tool, open its dashboard or reports, and do not look at the other annotator's sheet until your labels are final. Otherwise the comparison measures agreement with the tool, not accuracy."),
            ("li", "2. Work alone. You and the other annotator discuss disagreements only afterwards, when the researcher adjudicates (settles) them."),
            ("li", "3. Use the same conditions as the tool (register R6): Chrome (stable), a normal desktop window of 1366 x 768, a fresh named profile, no extensions, NOT Incognito, connected from Nigeria, language English (Nigeria). Write the Chrome version and the date on the 'Site context' sheet."),
            ("li", "4. Use the same timing (register R7): after the page finishes loading, wait 10 seconds and touch nothing, then record what you see. After you click Accept or Reject, wait another 10 seconds."),
            ("li", "5. Stay inside the capture window. The researcher will tell you the dates. The tool scans every site inside one 72-hour window; viewing the sites in the same window means a site cannot change between the tool's visit and yours."),
            ("li", "6. Use the frozen lists, even if you know better: the 'Necessary cookies' sheet (R1) and the 'Tracker lookup' sheet (R8). If you disagree with a list, label by the list and say why in the notes. These disagreements feed the error analysis."),
            ("li", "7. Public pages only. Do not log in, do not fill in forms and do not test for security weaknesses."),
            ("h", "For each site (about 30 to 45 minutes)"),
            ("li", "Step 1, Run 1 (no clicks). Open the site in a fresh profile. Touch nothing. Wait 10 seconds. Is a cookie banner visible? Where, and how big (R4, the 3 by 3 grid test)? Open DevTools (F12, or Cmd+Option+I on a Mac), Application tab, Cookies: list the cookies and use the 'Necessary cookies' sheet to see which are non-necessary. Network tab: look for requests to other companies' domains and check them against the 'Tracker lookup' sheet."),
            ("li", "Step 2, Run 2 (Reject), only if the banner has a Reject control. A settings panel that you reach from the banner counts. Fresh profile, open the site, click Reject, wait 10 seconds. Did any new non-necessary cookie or tracker request appear after the click?"),
            ("li", "Step 3, Run 3 (Accept). Fresh profile, click Accept (or the only consent button), wait 10 seconds, then reload the page. Does the banner stay away (the choice was remembered)? Is there a link or button to change the choice later?"),
            ("li", "Step 4, the privacy policy. Look for it within two clicks of the homepage (footer links first). Read it for: cookies, what data is used and why, how long it is kept, the visitor's rights, and a contact for privacy questions."),
            ("li", "Step 5, record. Fill in one row per rule on the 'Labels' sheet (the 17 rules for this site), and the banner details on the 'Site context' sheet."),
            ("h", "How to fill in the Labels sheet"),
            ("li", "label: pick from the dropdown. Compliant = the rule's requirement is met. Non-Compliant = it is not met. Not Applicable = the rule does not apply to this site."),
            ("li", "na_reason: required whenever you choose Not Applicable. Short, for example 'no cookies', 'no consent trigger', 'dormant'. A missing reason turns the cell orange."),
            ("li", "evidence_ref: where you saw it, so someone else can check (a screenshot file name, a page address, a time)."),
            ("li", "notes: anything uncertain, any rule that was hard to apply, anything the tool might get wrong. Write 'purpose unknown' for a cookie you could not explain."),
            ("li", "There is no 'unable to determine' label for you (that exists only for the tool). Choose the best-supported label and explain the doubt in the notes. If a site will not load at all in an ordinary browser, leave its rows blank and write why on the 'Site context' sheet."),
            ("li", "Read the 'Rules guide' sheet for what makes each rule Compliant, Non-Compliant or Not Applicable, and the 'Registers' sheet (R1 to R13) for the fixed answers to arguable questions."),
            ("h", "Special cases (from the rulebook's conventions)"),
            ("li", "No cookies at all: CK-01 and CK-02 are Not Applicable (reason: 'no cookies')."),
            ("li", "No consent trigger (no non-necessary cookie and no TR-01 tracker in any run): CN-01 to CN-05 and SB-01 to SB-03 are Not Applicable (reason: 'no consent trigger')."),
            ("li", "A consent trigger exists but there is no banner or settings panel: CN-01 is Non-Compliant, CN-03 is Non-Compliant, CN-02 is judged from what happened (the timeline), and CN-04 and CN-05 are Not Applicable."),
            ("li", "No privacy policy after a proper search (footer, the common addresses like /privacy, the Terms page): PP-01 is Non-Compliant. Every rule that needs policy text (CK-01, CK-02, TR-02, PP-02 to PP-06) is also Non-Compliant; write 'root cause: PP-01' in the notes of each. If you could not search properly (the page would not load), say so in the notes."),
            ("li", "The Close (x) button, for CN-02 (register R5). A close icon is not Reject. Label CN-02 under the STRICT reading: closing is not consent, so cookies set after a Close click count as set without consent. Then ALSO write the other reading in the notes, as 'Implied: Compliant' or 'Implied: Non-Compliant'. Under the implied reading, Close counts as consent only if the banner passed the size test (CN-01), and only for the site's own cookies used for site functions or the site's own statistics, never for advertising, cross-site or third-party cookies."),
            ("h", "Before you hand the workbook in"),
            ("li", "Ask the researcher to run the sheet check, or run it yourself if you have the project: python -m ndpa.evaluation.labels eval/annotations/<your file>.xlsx --sites my_site_list.txt. It lists every row with a problem and how many rules are still unlabelled for each site."),
            ("li", "Keep the file as .xlsx and do not rename the sheets or the column headings. Excel or Google Sheets work best; if you use Apple Numbers, check that the dropdowns still appear."),
            ("h", "The sheets in this workbook"),
            ("li", "Labels: where your answers go.   Site context: banner and capture details for each site, with a count of how many rules you have labelled."),
            ("li", "Rules guide: what decides each rule.   Registers: the fixed answers R1 to R13, in plain words.   Codes explained: every abbreviation used here."),
            ("li", "Necessary cookies: the frozen list (R1).   Tracker lookup: the frozen DuckDuckGo list (R8), about 1,000 trackers.")]
    return out


def _style_header(ws, widths: list[int], row: int = 1) -> None:
    for col, width in enumerate(widths, start=1):
        cell = ws.cell(row=row, column=col)
        cell.fill, cell.font, cell.alignment = SECTION_FILL, HEADER_FONT, Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[cell.column_letter].width = width
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _table(ws, header: list[str], rows: list[list], widths: list[int]) -> None:
    ws.append(header)
    for row in rows:
        ws.append(row)
    _style_header(ws, widths)
    for r in ws.iter_rows(min_row=2):
        for cell in r:
            cell.alignment = WRAP
    ws.auto_filter.ref = ws.dimensions


def build_workbook(sites: list[str], kind: str, rulebook: dict, necessary_file: Path, tds_file: Path) -> Workbook:
    rules = [r for r in rulebook["rules"] if r.get("tier") != "unscored"]
    ids = [r["id"] for r in rules]
    book = Workbook()
    book.properties.title = "NDPA website privacy annotation workbook"
    book.properties.creator = "NDPA Privacy Check"

    ws = book.active
    ws.title = "Read me first"
    ws.column_dimensions["A"].width = 110
    for style, text in read_me(len(sites), len(sites) * len(ids), kind):
        ws.append([text])
        cell = ws.cell(row=ws.max_row, column=1)
        cell.alignment = WRAP
        if style == "title":
            cell.font = Font(bold=True, size=16, color="1F3A68")
        elif style == "h":
            cell.font, cell.fill = HEADER_FONT, SECTION_FILL
        elif style == "li":
            cell.alignment = Alignment(wrap_text=True, vertical="top", indent=1)

    labels = book.create_sheet("Labels")
    labels.append(["site", "rule_id", "rule", "label", "na_reason", "evidence_ref", "notes"])
    names = {r["id"]: r["name"] for r in rules}
    for site in sites:
        for rule_id in ids:
            labels.append([site, rule_id, names[rule_id], None, None, None, None])
    last = labels.max_row
    _style_header(labels, [34, 9, 44, 18, 30, 36, 60])
    for row in labels.iter_rows(min_row=2, max_row=last):
        for cell in row:
            cell.alignment = WRAP
        for cell in row[:3]:
            cell.fill = HELP_FILL
        if row[1].value == ids[0]:  # a line above the first rule of each site
            for cell in row:
                cell.border = Border(top=THIN)
    check = DataValidation(type="list", formula1='"' + ",".join(LABEL_CHOICES) + '"', allow_blank=True, showErrorMessage=True,
                           errorTitle="Not a label", error="Choose Compliant, Non-Compliant or Not Applicable from the list.")
    labels.add_data_validation(check)
    check.add(f"D2:D{last}")
    for text, colour in (("Compliant", "D7F0DD"), ("Non-Compliant", "F8D3D6"), ("Not Applicable", "E3E6EC")):
        labels.conditional_formatting.add(f"D2:D{last}", CellIsRule(operator="equal", formula=[f'"{text}"'], fill=PatternFill("solid", bgColor=colour)))
    labels.conditional_formatting.add(f"E2:E{last}", FormulaRule(formula=['AND($D2="Not Applicable",TRIM($E2)="")'], fill=PatternFill("solid", bgColor="FFD9A0")))
    labels.auto_filter.ref = f"A1:G{last}"

    context = book.create_sheet("Site context")
    head = ["site", "capture_date", "chrome_version", "banner_position", "covers_1_of_9_cells", "bottom_row_only", "reject_available", "accept_available",
            "close_only_case", "trackers_found (TR-01)", "policy_url", "policy_discovery", "notes", "rules labelled"]
    _table(context, head, [[s] + [None] * 12 + [f'=COUNTIFS(Labels!$A$2:$A${last},$A{i},Labels!$D$2:$D${last},"<>")&" of {len(ids)}"'] for i, s in enumerate(sites, start=2)],
           [34, 14, 16, 16, 14, 12, 12, 12, 12, 26, 36, 18, 44, 14])
    for col, choices in (("D", "none,bottom,top,centre_modal,left,right,full_screen"), ("E", "yes,no"), ("F", "yes,no"), ("G", "yes,no"), ("H", "yes,no"), ("I", "yes,no"),
                         ("L", "found_linked,found_unlinked,not_found,uncertain")):
        dv = DataValidation(type="list", formula1=f'"{choices}"', allow_blank=True)
        context.add_data_validation(dv)
        dv.add(f"{col}2:{col}{len(sites) + 1}")

    guide = book.create_sheet("Rules guide")
    rows = []
    for r in rulebook["rules"]:
        d = r.get("decision", {})
        scored = r.get("tier") != "unscored"
        rows.append([r["id"], r["name"], r["category"].replace("_", " ").title(),
                     f'{r["tier"].title()}: {rulebook["meta"]["tiers"][r["tier"]]}' if scored else "Not labelled (it produces the tracker list)",
                     plain(d.get("non_compliant", d.get("outcome", ""))), plain(d.get("compliant", "")), plain(d.get("not_applicable", "")),
                     plain(" | ".join(str(e) for e in r.get("edge_cases", []))), "; ".join(r.get("legal", []))])
    _table(guide, ["Rule", "Name", "Area", "How serious", "Non-Compliant when", "Compliant when", "Not Applicable when", "Edge cases", "Legal basis"], rows,
           [8, 30, 16, 28, 50, 44, 34, 44, 34])

    registers = book.create_sheet("Registers")
    reg_rows = []
    for code, info in rulebook["registers"].items():
        used = ", ".join(USED_BY_PLAIN.get(u.strip(), u.strip()) for u in info["used_by"].split(","))
        reg_rows.append([code, used, REGISTER_PLAIN[code], plain(info["value"])])
    _table(registers, ["Code", "Used by", "In plain words", "Official wording"], reg_rows, [7, 26, 80, 60])

    cookies = book.create_sheet("Necessary cookies")
    patterns = yaml.safe_load(necessary_file.read_text(encoding="utf-8"))["patterns"]
    _table(cookies, ["Group", "What the group is for", "Cookie name (matching ignores capital letters; * means any characters)"],
           [[group, NECESSARY_GROUPS.get(group, ""), name] for group, names_ in patterns.items() for name in names_], [18, 52, 60])
    cookies.cell(row=cookies.max_row + 2, column=1, value="A cookie that is not here and has no documented purpose counts as NON-necessary (write 'purpose unknown' in the notes).")

    trackers = book.create_sheet("Tracker lookup")
    entries = json.loads(tds_file.read_text(encoding="utf-8"))["trackers"]
    track_rows = []
    for domain, t in sorted(entries.items()):
        owner = t.get("owner") or {}
        track_rows.append([domain, owner.get("displayName") or owner.get("name", ""), "; ".join(t.get("categories") or []) or "no-category", t.get("default", ""),
                           t.get("fingerprinting", ""), t.get("prevalence", ""), "yes" if t.get("rules") else "no"])
    _table(trackers, ["domain", "owner", "categories", "default (block or ignore)", "fingerprinting", "prevalence", "has special address rules"], track_rows, [34, 30, 40, 16, 14, 12, 16])

    codes = book.create_sheet("Codes explained")
    _table(codes, ["Code or term", "What it means"], [[c, m] for c, m in CODES], [38, 120])
    for sheet in book.worksheets:  # printable: landscape, one page wide, the heading row repeated
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
        sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        if sheet.title != "Read me first":
            sheet.print_title_rows = "1:1"
    return book


def write_workbooks(sites: list[str], out_dir: Path, pilot: bool = False, rulebook: dict | None = None,
                    necessary_file: Path = Path("rulebook/necessary_cookies.yaml"), tds_file: Path = Path("data/lists/tds-snapshot.json")) -> dict[str, list[str]]:
    """Returns {file name: the sites it covers}."""
    rulebook = rulebook or load_rulebook()
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = ({"pilot_annotator1.xlsx": ("pilot1", sites), "pilot_annotator2.xlsx": ("pilot2", sites)} if pilot
            else {"annotator1.xlsx": ("main1", sites), "annotator2.xlsx": ("main2", second_annotator_sites(sites))})
    written = {}
    for name, (kind, covered) in plan.items():
        build_workbook(covered, kind, rulebook, necessary_file, tds_file).save(out_dir / name)
        written[name] = covered
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Make the annotator workbooks from the rulebook.")
    ap.add_argument("--sites", default="my_site_list.txt")
    ap.add_argument("--out", help="default: eval/annotations (eval/pilot with --pilot)")
    ap.add_argument("--pilot", action="store_true", help="one workbook for each annotator, both covering every site in --sites")
    args = ap.parse_args(argv)
    sites = read_sites(Path(args.sites))
    written = write_workbooks(sites, Path(args.out or ("eval/pilot" if args.pilot else "eval/annotations")), pilot=args.pilot)
    for name, covered in written.items():
        print(f"{name}: {len(covered)} sites, {len(covered) * 17} labels")
    if not args.pilot:
        by_sector = {}
        for s in written["annotator2.xlsx"]:
            by_sector.setdefault(sector_of(s), []).append(normalise_site(s))
        print("\nThe second annotator labels these sites (spread across sectors, fixed seed):")
        for sector, names in by_sector.items():
            print(f"  {sector}: {', '.join(names)}")


if __name__ == "__main__":
    main()
