"""Text analysis for the policy rules: spaCy sentence splitting and rule-based Matcher.

No trained model is used (spacy.blank), so every label traces to a word list in LEXICON below. The word lists are
the tool's operationalisation of the rulebook's 'decide in advance' items (registers R9, R12, R13) and are fixed
before the evaluation scans. An entry ending in * is a prefix (rectif* matches rectify, rectification).
"""
import re
from dataclasses import dataclass
from functools import lru_cache

import spacy
from spacy.matcher import Matcher

LEXICON: dict[str, list[str]] = {
    # PP-06, the seven core rights
    "cue_right": ["right*", "entitled", "request*", "ask", "exercise*"],
    "data_word": ["data", "information", "records", "copy", "copies"],
    "r_access": ["access*"],
    "r_rectify": ["rectif*", "correct*", "amend*", "updat*"],
    "r_erase": ["erase*", "erasure", "delet*", "forgotten", "removal"],
    "r_restrict": ["restrict*"],
    "r_port": ["portab*", "portable", "machine - readable", "machine readable"],
    "r_object": ["object*", "objection", "opt out", "opt - out"],
    "c_verb": ["complain*", "lodge*", "report*"],
    "c_authority": ["ndpc", "nigeria data protection commission", "supervisory authority", "regulator*",
                    "data protection authority", "data protection commission"],
    "limit": ["not apply", "does not apply", "do not apply", "not applicable", "no right", "only applies",
              "only apply", "only where", "only if", "only when"],
    # PP-05, retention
    "ret_cue": ["retain*", "retention", "keep*", "kept", "store", "stored", "storing", "storage", "stores"],
    # PP-04, purpose (register R13: a named data category and a specific use)
    "data_cat": ["name", "names", "email*", "e - mail", "phone*", "telephone", "address", "addresses", "location",
                 "payment", "payments", "card", "device*", "browsing", "cookies", "ip address", "contact details",
                 "transaction*", "purchase*", "account", "accounts", "orders"],
    "purpose_cue": ["to process", "to deliver", "to send", "to contact", "to respond", "to verify", "to comply",
                    "to prevent", "to detect", "to personalise", "to personalize", "to manage", "to create",
                    "to communicate", "to notify", "to authenticate", "to complete", "to fulfil", "to fulfill",
                    "to administer", "to enable", "to identify", "to register", "to arrange", "to charge",
                    "for billing", "for marketing", "for analytics", "for security", "for fraud", "for delivery"],
    # PP-02, cookie text in a banner or panel: it must state that cookies are used and why
    "cookie": ["cookie*"],
    "cookie_purpose": ["improv*", "analy*", "personali*", "advertis*", "perform*", "function*", "experience",
                       "measur*", "market*", "secur*", "track*", "remember*", "preferenc*", "statistic*"],
}

DURATION_RE = re.compile(
    r"\b(?:\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|eighteen|twenty|thirty|sixty|ninety)"
    r"(?:\s*\(\d+\))?[\s-]*(?:calendar\s+)?(?:day|week|month|year)s?\b", re.I)
TRIGGER_RE = re.compile(
    r"until (?:you|the \w+) (?:withdraw|delete|close|request|cancel|terminate|object)|"
    r"for the duration of (?:your|the) (?:account|subscription|relationship|membership|contract|service)|"
    r"while (?:your|the) account (?:is|remains) (?:active|open)|"
    r"as long as you (?:have|maintain|keep|hold) (?:an|your|a) (?:active )?(?:account|subscription)|"
    r"after (?:you )?(?:close|delete|terminate|deactivate|cancel)(?:ing)? (?:your|the) account|"
    r"until your account is (?:closed|deleted)|until consent is withdrawn", re.I)
VAGUE_RETENTION_RE = re.compile(r"as long as (?:necessary|needed|required)|no longer than (?:is )?(?:necessary|needed)", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")
PRIVACY_CUE_RE = re.compile(r"privacy|data protection|\bdpo\b|data subject|personal data", re.I)
PRIVACY_LOCAL_PART_RE = re.compile(r"^(privacy|dpo|dataprotection|data[._-]?protection|gdpr|ndpa)", re.I)


def _token(word: str) -> dict:
    if word.endswith("*"):
        return {"LOWER": {"REGEX": "^" + re.escape(word[:-1])}}
    return {"LOWER": word}


@lru_cache(maxsize=1)
def _pipeline():
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    matcher = Matcher(nlp.vocab)
    for label, entries in LEXICON.items():
        matcher.add(label, [[_token(w) for w in entry.split()] for entry in entries])
    return nlp, matcher


@dataclass
class Sentence:
    text: str
    labels: set[str]


def analyse(text: str) -> list[Sentence]:
    """Split text into sentences (every line starts a new one) and label each with the LEXICON groups it contains."""
    nlp, matcher = _pipeline()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out: list[Sentence] = []
    for doc in nlp.pipe(lines):
        sentence_of = {}
        spans = list(doc.sents)
        for i, span in enumerate(spans):
            for t in range(span.start, span.end):
                sentence_of[t] = i
        labels = [set() for _ in spans]
        for match_id, start, _end in matcher(doc):
            labels[sentence_of[start]].add(nlp.vocab.strings[match_id])
        out += [Sentence(span.text.strip(), lab) for span, lab in zip(spans, labels, strict=True) if span.text.strip()]
    return out


def snippet(text: str, limit: int = 110) -> str:
    """A short identifying phrase, not the whole sentence (rulebook PP-04: do not reproduce policies)."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def vendor_names(vendor: str, domains: set[str]) -> set[str]:
    """Names a policy could use for a tracker: 'Google Ads (Google)' -> google ads, google; plus its domains (R9)."""
    names = {re.sub(r"\s*\(.*?\)", "", vendor).strip().lower()}
    names |= {inner.strip().lower() for inner in re.findall(r"\((.*?)\)", vendor)}
    for name in list(names):
        if "." in name:
            names.add(name.split(".")[0])
    names |= {d.lower() for d in domains}
    names |= {d.split(".")[0].lower() for d in domains}
    return {n for n in names if len(n) >= 3}


def mentions(name: str, text_lower: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", text_lower) is not None
