"""Reads an annotator's label sheet (the CSV made by eval/prepare_annotation.py) and checks it carefully.

A mistake in a label sheet must never silently change a result, so every problem is collected and reported together.
"""
import argparse
import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ndpa.models import Outcome

# What annotators may write. Case, spaces, hyphens and underscores are ignored: "Non-Compliant" = "non_compliant" = "nc".
LABELS = {"compliant": Outcome.COMPLIANT, "c": Outcome.COMPLIANT,
          "noncompliant": Outcome.NON_COMPLIANT, "nc": Outcome.NON_COMPLIANT,
          "notapplicable": Outcome.NOT_APPLICABLE, "na": Outcome.NOT_APPLICABLE, "n/a": Outcome.NOT_APPLICABLE}
REQUIRED_COLUMNS = ("site", "rule_id", "label")


class AnnotationError(ValueError):
    """The sheet has problems. .problems lists every one of them."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        shown = "\n  - ".join(problems[:25])
        more = f"\n  ... and {len(problems) - 25} more" if len(problems) > 25 else ""
        super().__init__(f"{len(problems)} problem(s) in the label sheet:\n  - {shown}{more}")


@dataclass
class Label:
    outcome: Outcome
    na_reason: str = ""
    evidence_ref: str = ""
    notes: str = ""


@dataclass
class Annotations:
    path: str
    labels: dict[tuple[str, str], Label] = field(default_factory=dict)  # (site key, rule id) -> label
    blank_rows: int = 0  # rows the annotator has not labelled yet

    def sites(self) -> set[str]:
        return {site for site, _ in self.labels}


def normalise_site(raw: str) -> str:
    """'https://www.Example.com.ng/path' and 'example.com.ng' are the same site: example.com.ng.
    A port is kept unless it is the usual one for the scheme, so two services on one machine stay apart."""
    raw = (raw or "").strip()
    parts = urlsplit(raw if "://" in raw else "//" + raw)
    host = (parts.hostname or raw).lower().rstrip(".")
    host = host[4:] if host.startswith("www.") else host
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{host}:{port}" if port not in (None, 80, 443) else host


def parse_label(raw: str) -> Outcome | None:
    """None for an empty cell (not labelled yet). KeyError for something that is not a label."""
    cleaned = (raw or "").strip().lower().replace(" ", "").replace("-", "").replace("_", "")
    if not cleaned:
        return None
    return LABELS[cleaned]


def _read_workbook(path: Path) -> list[dict]:
    """The 'Labels' sheet of an annotator workbook (made by ndpa.evaluation.workbook), as rows keyed by the header."""
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    try:
        names = {name.lower(): name for name in book.sheetnames}
        sheet = book[names["labels"]] if "labels" in names else book.active
        lines = sheet.iter_rows(values_only=True)
        header = next(lines, None)
        if header is None:
            return []
        keys = [str(h).strip().lower() if h is not None else "" for h in header]
        return [{key: "" if value is None else str(value) for key, value in zip(keys, values, strict=False)}
                for values in lines if any(v not in (None, "") for v in values)]
    finally:
        book.close()


def _read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):  # Excel may save the workbook as .xlsm
        return _read_workbook(path)
    text = path.read_text(encoding="utf-8-sig")  # spreadsheets often save a byte-order mark
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel  # some locales save with semicolons, which the sniffer handles; otherwise assume commas
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    reader.fieldnames = [(name or "").strip().lower() for name in (reader.fieldnames or [])]
    return list(reader)


def load_annotations(path: str | Path, rule_ids: list[str], site_keys: set[str] | None = None) -> Annotations:
    """Load one label sheet. Raises AnnotationError listing every problem found."""
    path = Path(path)
    rows = _read_rows(path)
    if not rows:
        raise AnnotationError([f"{path.name} has no rows"])
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise AnnotationError([f"{path.name} is missing the column(s): {', '.join(missing)}"])
    problems: list[str] = []
    result = Annotations(path=str(path))
    known_rules = set(rule_ids)
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        site, rule = normalise_site(row.get("site", "")), (row.get("rule_id") or "").strip().upper()
        where = f"row {number} ({row.get('site', '').strip()} {rule})"
        if not site:
            problems.append(f"row {number}: the site is empty")
            continue
        if rule not in known_rules:
            problems.append(f"{where}: '{rule}' is not a scored rule")
            continue
        if site_keys is not None and site not in site_keys:
            problems.append(f"{where}: this site is not in the corpus")
            continue
        try:
            outcome = parse_label(row.get("label", ""))
        except KeyError:
            problems.append(f"{where}: '{row.get('label', '').strip()}' is not a label (use Compliant, Non-Compliant or Not Applicable)")
            continue
        if outcome is None:
            result.blank_rows += 1
            continue
        label = Label(outcome, (row.get("na_reason") or "").strip(), (row.get("evidence_ref") or "").strip(), (row.get("notes") or "").strip())
        if outcome == Outcome.NOT_APPLICABLE and not label.na_reason:
            problems.append(f"{where}: Not Applicable needs a reason in the na_reason column")
        earlier = result.labels.get((site, rule))
        if earlier is not None and earlier.outcome != outcome:
            problems.append(f"{where}: this site and rule appear twice with different labels")
        result.labels[(site, rule)] = label
    if problems:
        raise AnnotationError(problems)
    return result


def complete_sites(annotations: Annotations, rule_ids: list[str]) -> set[str]:
    """Sites where every scored rule has a label."""
    return {site for site in annotations.sites() if all((site, rule) in annotations.labels for rule in rule_ids)}


def main(argv: list[str] | None = None) -> None:
    """python -m ndpa.evaluation.labels eval/annotations/annotator1.csv --sites my_site_list.txt   (annotators: run this before handing in)"""
    from ndpa.evaluation.corpus import read_sites
    from ndpa.scoring.score import load_rulebook

    ap = argparse.ArgumentParser(description="Check a label sheet and say what is still missing.")
    ap.add_argument("sheet")
    ap.add_argument("--sites", help="the site list, so a site that is not in the corpus is caught")
    args = ap.parse_args(argv)
    ids = [r["id"] for r in load_rulebook()["rules"] if r.get("tier") != "unscored"]
    site_keys = {normalise_site(u) for u in read_sites(Path(args.sites))} if args.sites else None
    try:
        annotations = load_annotations(args.sheet, ids, site_keys)
    except AnnotationError as problem:
        raise SystemExit(f"{problem}\n\nFix these and run the check again.") from None
    finished = complete_sites(annotations, ids)
    print(f"OK: {len(annotations.labels)} rows labelled, {annotations.blank_rows} still blank. "
          f"{len(annotations.sites())} site(s) started, {len(finished)} complete.")
    for site in sorted(annotations.sites() - finished):
        print(f"  {site}: {sum(1 for rule in ids if (site, rule) not in annotations.labels)} rule(s) still to label")


if __name__ == "__main__":
    main()
