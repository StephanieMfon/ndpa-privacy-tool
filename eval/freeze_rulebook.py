"""Freeze Rulebook v2.0. Run ONCE, after the pilot: python eval/freeze_rulebook.py"""
import datetime, hashlib, json, os, pathlib

FILES = [
    "rulebook/rules.v2.yaml",
    "rulebook/necessary_cookies.yaml",
    "rulebook/Annotation_Rulebook_v2.0.pdf",
    "data/lists/tds-snapshot.json",
]
missing = [f for f in FILES if not pathlib.Path(f).exists()]
if missing:
    raise SystemExit(f"Missing files: {missing}")

yml = pathlib.Path("rulebook/rules.v2.yaml")
text = yml.read_text()
for old, new in [('version: "2.0.0-draft2"', 'version: "2.0.0"'), ("frozen: false", "frozen: true")]:
    if text.count(old) != 1:
        raise SystemExit(f"Cannot freeze: expected exactly one '{old}'. Already frozen?")
    text = text.replace(old, new)
yml.write_text(text)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

record = {
    "rulebook_version": "2.0.0",
    "frozen_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "files": {f: {"sha256": sha256(f), "bytes": os.path.getsize(f)} for f in FILES},
}
pathlib.Path("rulebook/FREEZE.json").write_text(json.dumps(record, indent=2))
print(json.dumps(record, indent=2))
