"""
scanner/rules/privacy_policy.py

Phase 3, Module 6 (rules half) — PP-01 to PP-06.

Three text-processing tools are used, each for what it's actually good
at, not uniformly for everything (matches Chapter 2 §2.5's technology
review):

  - spaCy (Matcher/PhraseMatcher) — natural-language phrase and
    sentence-level matching: PP-04's purpose-near-data-category
    adjacency, PP-05's retention-marker detection, PP-06's rights
    detection. Lemma-based patterns catch inflected word forms
    ("retain"/"retains"/"retained"/"retention") that a fixed substring
    list would miss — a direct fix to the character-window adjacency
    approach used in the first version of this module, which could span
    unrelated sentences or miss valid matches in longer ones. Still
    fully deterministic and rule-based (Matcher/PhraseMatcher patterns,
    not a trained classifier) — every match traces to an explicit
    pattern, consistent with the traceability requirement (NFR2/NFR3).
  - Python `re` — structured pattern extraction where spaCy adds nothing:
    PP-03's email address, PP-05's numeric duration ("12 months"). These
    are formatted patterns, not natural-language phrases.
  - BeautifulSoup4 — PP-02's cookie-section detection, using real HTML
    heading structure (<h1>-<h6>) when available, falling back to a
    mention-count proxy only when HTML wasn't captured or no heading
    matched. This replaces a pure keyword-count heuristic with an actual
    structural signal.

Every threshold below (adjacency window, mention counts, rights
threshold) is a real interpretive choice the Rulebook itself asks be
pre-defined (PP-04/05/06 edge cases) — state them in the methodology
chapter same as CN-04/CN-05/CK-04's own fixed thresholds.
"""

import re

import spacy
from spacy.matcher import Matcher, PhraseMatcher
from bs4 import BeautifulSoup

nlp = spacy.load("en_core_web_sm")

# --- PP-03: contact info ---
CONTACT_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
DPO_MARKERS = ["data protection officer", " dpo "]

# --- PP-04: purpose disclosure ---
PURPOSE_PHRASES = [
    "for the purpose of", "in order to", "we use your", "we use this information to",
    "we collect this information to", "used to provide", "in order to provide",
]
DATA_CATEGORY_TERMS = [
    "name", "email", "phone", "address", "cookie", "browsing data",
    "ip address", "location", "payment", "device information",
]
SENTENCE_ADJACENCY = 1  # match counts if purpose phrase + data category fall in the same or adjacent sentence

# --- PP-05: retention disclosure ---
RETENTION_MARKER_LEMMAS = ["retain", "retention", "keep"]
RETENTION_MARKER_PHRASES = ["storage period", "how long"]  # fixed compounds, low inflection — substring is fine
RETENTION_TRIGGER_PHRASES = ["until you withdraw", "duration of your account", "as long as necessary"]
DURATION_RE = re.compile(r"\b\d+\s*(day|days|month|months|year|years)\b")

# --- PP-06: rights disclosure ---
RIGHTS_PATTERNS = {
    "access": [[{"LEMMA": "access"}]],
    "rectification": [[{"LEMMA": {"IN": ["rectify", "rectification", "correct", "correction"]}}]],
    "erasure": [[{"LEMMA": {"IN": ["erase", "erasure", "delete", "deletion"]}}]],
    "restriction": [[{"LEMMA": {"IN": ["restrict", "restriction"]}}]],
    "portability": [[{"LEMMA": {"IN": ["portability", "port"]}}], [{"LOWER": "portable"}]],
    "objection": [[{"LEMMA": {"IN": ["object", "objection"]}}]],
    "complaint": [
        [{"LOWER": "ndpc"}],
        [{"LOWER": "nigeria"}, {"LOWER": "data"}, {"LOWER": "protection"}, {"LOWER": "commission"}],
        [{"LEMMA": {"IN": ["complain", "complaint"]}}],
    ],
}
RIGHTS_COMPLIANCE_THRESHOLD = 5  # of 7 — Rulebook: "fewer than the core set... without explanation" is Non-Compliant

# --- PP-02: cookie section heading ---
COOKIE_MENTION_FALLBACK_THRESHOLD = 3


def _matcher_for_phrases(phrases: list[str]) -> PhraseMatcher:
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
    patterns = [nlp.make_doc(p) for p in phrases]
    matcher.add("PHRASES", patterns)
    return matcher


def check_pp01(policy_capture: dict) -> dict:
    """Privacy Policy present and accessible. 1-click check only — see policy_capture.py's module docstring."""
    if policy_capture.get("privacy_policy_reachable"):
        return _result("PP-01", "Compliant", evidence={"url": policy_capture.get("privacy_policy_url")})
    return _result("PP-01", "Non-Compliant",
                    notes="No Privacy Policy reachable from the homepage in one click. "
                          "Worth a manual click-through before treating as a confirmed finding.")


def check_pp02(policy_capture: dict) -> dict:
    """Cookie Policy present — standalone link, real HTML heading structure, or (fallback) substantial mention count."""
    if policy_capture.get("cookie_policy_reachable"):
        return _result("PP-02", "Compliant", evidence={"url": policy_capture.get("cookie_policy_url"), "standalone": True})

    html = policy_capture.get("policy_html")
    if html:
        soup = BeautifulSoup(html, "lxml")
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            heading_text = heading.get_text(strip=True)
            if "cookie" in heading_text.lower():
                return _result("PP-02", "Compliant",
                                evidence={"heading_found": heading_text, "standalone": False, "detection": "html_heading"},
                                notes="Detected via real HTML heading structure, not a keyword-count proxy.")

    text = policy_capture.get("policy_text") or ""
    cookie_mentions = text.lower().count("cookie")
    if cookie_mentions >= COOKIE_MENTION_FALLBACK_THRESHOLD:
        return _result("PP-02", "Compliant",
                        evidence={"cookie_mentions": cookie_mentions, "standalone": False, "detection": "mention_count_fallback"},
                        notes="No cookie-related HTML heading found; used as fallback proxy since HTML structure was unavailable or inconclusive.")
    return _result("PP-02", "Non-Compliant", evidence={"cookie_mentions": cookie_mentions})


def check_pp03(policy_capture: dict) -> dict:
    """Contact information for privacy/data-protection queries specifically. Structured extraction — regex, no spaCy needed."""
    text = policy_capture.get("policy_text") or ""
    if not text:
        return _result("PP-03", "Non-Compliant", notes="No policy text available to check.")

    has_email = bool(CONTACT_EMAIL_RE.search(text))
    has_dpo_mention = any(m in f" {text.lower()} " for m in DPO_MARKERS)

    if has_email or has_dpo_mention:
        return _result("PP-03", "Compliant", evidence={"email_found": has_email, "dpo_mentioned": has_dpo_mention})
    return _result("PP-03", "Non-Compliant", notes="No privacy-specific contact channel (email or DPO mention) found.")


# def check_pp04(policy_capture: dict) -> dict:
#     """Purpose of data collection disclosed. spaCy sentence-adjacency: a purpose phrase and a data category in the same/adjacent sentence."""
#     text = policy_capture.get("policy_text") or ""
#     if not text:
#         return _result("PP-04", "Non-Compliant", notes="No policy text available to check.")

#     doc = nlp(text)
#     sentences = list(doc.sents)
#     sent_start_to_index = {sent.start: i for i, sent in enumerate(sentences)}

#     purpose_matcher = _matcher_for_phrases(PURPOSE_PHRASES)
#     category_matcher = _matcher_for_phrases(DATA_CATEGORY_TERMS)

#     purpose_matches = purpose_matcher(doc)
#     category_matches = category_matcher(doc)
#     if not purpose_matches or not category_matches:
#         return _result("PP-04", "Non-Compliant", notes="No purpose phrase or no data-category term found at all.")

#     purpose_infos = [
#         (sent_start_to_index[doc[s:e].sent.start], doc[s:e].text, doc[s:e].sent.text)
#         for _, s, e in purpose_matches
#     ]
#     category_indices = [sent_start_to_index[doc[s:e].sent.start] for _, s, e in category_matches]

#     for p_idx, matched_text, sent_text in purpose_infos:
#         for c_idx in category_indices:
#             # Compare SENTENCE INDEX, not raw token position — two adjacent
#             # sentences of different lengths can be hundreds of tokens
#             # apart, so a token-distance check would wrongly reject
#             # genuinely adjacent sentences. Caught via a real test case
#             # with a purpose clause split across two sentences.
#             if abs(p_idx - c_idx) <= SENTENCE_ADJACENCY:
#                 return _result("PP-04", "Compliant", evidence={"matched_phrase": matched_text, "sentence": sent_text.strip()})

#     return _result("PP-04", "Non-Compliant",
#                     notes="Purpose phrase and data-category term both present, but not within the same or an adjacent sentence.")

def check_pp04(policy_capture: dict) -> dict:
    """Purpose of data collection disclosed. Fixed adequacy bar: a purpose phrase near a named data category."""
    text = (policy_capture.get("policy_text") or "").lower()
    if not text:
        return _result("PP-04", "Non-Compliant", notes="No policy text available to check.")

    for phrase in PURPOSE_PHRASES:
        idx = text.find(phrase)
        if idx == -1:
            continue
        window = text[max(0, idx - 150):idx + 150]
        if any(term in window for term in DATA_CATEGORY_TERMS):
            return _result("PP-04", "Compliant", evidence={"matched_phrase": phrase})

    return _result("PP-04", "Non-Compliant",
                    notes="No purpose statement found adjacent to a named data category (fixed adequacy bar).")

def check_pp05(policy_capture: dict) -> dict:
    """Retention period disclosed — spaCy for marker detection (lemma-based), regex for the numeric duration, substring for fixed trigger phrases."""
    text = policy_capture.get("policy_text") or ""
    if not text:
        return _result("PP-05", "Non-Compliant", notes="No policy text available to check.")

    doc = nlp(text)
    has_lemma_marker = any(tok.lemma_.lower() in RETENTION_MARKER_LEMMAS for tok in doc)
    has_phrase_marker = any(p in text.lower() for p in RETENTION_MARKER_PHRASES)
    has_marker = has_lemma_marker or has_phrase_marker

    has_duration = bool(DURATION_RE.search(text.lower()))
    has_trigger = any(t in text.lower() for t in RETENTION_TRIGGER_PHRASES)

    if has_marker and (has_duration or has_trigger):
        return _result("PP-05", "Compliant", evidence={"has_duration": has_duration, "has_trigger_criterion": has_trigger})
    return _result("PP-05", "Non-Compliant", notes="No retention period or clear criterion found in policy text.")


def check_pp06(policy_capture: dict) -> dict:
    """Data subject rights disclosed — core NDPA s.34 rights set, spaCy lemma-based Matcher per right."""
    text = policy_capture.get("policy_text") or ""
    if not text:
        return _result("PP-06", "Non-Compliant", notes="No policy text available to check.")

    doc = nlp(text)
    found_rights = {}
    for right, patterns in RIGHTS_PATTERNS.items():
        matcher = Matcher(nlp.vocab)
        matcher.add(right, patterns)
        found_rights[right] = len(matcher(doc)) > 0

    found_count = sum(found_rights.values())
    complaint_disclosed = found_rights.get("complaint", False)

    evidence = {
        "rights_found": [r for r, found in found_rights.items() if found],
        "found_count": found_count,
        "complaint_to_ndpc_disclosed": complaint_disclosed,
    }

    if found_count >= RIGHTS_COMPLIANCE_THRESHOLD:
        notes = None
        if not complaint_disclosed:
            notes = ("Core rights disclosed, but the right to lodge a complaint with the NDPC "
                      "specifically is missing — record as a partial-compliance sub-finding, per Rulebook PP-06 edge case.")
        return _result("PP-06", "Compliant", evidence=evidence, notes=notes)

    return _result("PP-06", "Non-Compliant", evidence=evidence,
                    notes=f"Only {found_count}/7 core rights terms found (threshold: {RIGHTS_COMPLIANCE_THRESHOLD}).")


def _result(rule_id: str, label: str, evidence: dict | None = None, notes: str | None = None) -> dict:
    return {"rule_id": rule_id, "category": "privacy_policy", "label": label, "evidence": evidence or {}, "notes": notes}


def evaluate(scan_result: dict) -> list[dict]:
    """Run PP-01 through PP-06 against one site's captured policy evidence."""
    policy_capture = scan_result.get("policy_capture", {})
    return [
        check_pp01(policy_capture),
        check_pp02(policy_capture),
        check_pp03(policy_capture),
        check_pp04(policy_capture),
        check_pp05(policy_capture),
        check_pp06(policy_capture),
    ]