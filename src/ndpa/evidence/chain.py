"""Evidence manifest with a hash chain, and its verifier. Standard library only, so this one file can be copied
next to the evidence and run by anyone:

    python verify.py [folder] [--expect HASH]

Each file's SHA-256 is chained to the one before it: chain = sha256(previous chain | path | file hash). Changing,
removing or adding any file, or editing the manifest, breaks the chain. manifest.json and verify.py are not part of
the chain. Record the final hash somewhere else (the database does) to detect a rewritten manifest.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST = "manifest.json"
VERIFIER = "verify.py"
GENESIS = "0" * 64
EXCLUDED = {MANIFEST, VERIFIER}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _chain(previous: str, path: str, file_hash: str) -> str:
    return hashlib.sha256(f"{previous}|{path}|{file_hash}".encode("utf-8")).hexdigest()


def _files(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                  if p.is_file() and p.name not in EXCLUDED)


def build_manifest(folder: Path) -> dict:
    folder = Path(folder)
    entries, previous = [], GENESIS
    for rel in _files(folder):
        file_hash = sha256_file(folder / rel)
        previous = _chain(previous, rel, file_hash)
        entries.append({"path": rel, "sha256": file_hash, "bytes": (folder / rel).stat().st_size, "chain": previous})
    manifest = {"version": 1, "algorithm": "sha256", "entries": entries, "final": previous}
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def verify(folder: Path, expect: str | None = None) -> tuple[list[str], str | None]:
    """Returns (problems, final hash). An empty problem list means the evidence is exactly as sealed."""
    folder = Path(folder)
    manifest_path = folder / MANIFEST
    if not manifest_path.exists():
        return [f"{MANIFEST} is missing"], None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems, previous, listed = [], GENESIS, set()
    for entry in manifest["entries"]:
        rel = entry["path"]
        listed.add(rel)
        path = folder / rel
        if not path.exists():
            problems.append(f"missing file: {rel}")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"file changed: {rel}")
        elif path.stat().st_size != entry["bytes"]:
            problems.append(f"file size changed: {rel}")
        previous = _chain(previous, rel, entry["sha256"])
        if entry["chain"] != previous:
            problems.append(f"chain broken at: {rel}")
    for rel in _files(folder):
        if rel not in listed:
            problems.append(f"file not in the manifest: {rel}")
    if manifest.get("final") != previous:
        problems.append("the final hash in the manifest does not match the chain")
    if expect is not None and previous != expect:
        problems.append("the final hash is not the expected one")
    return problems, previous


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify an evidence folder against its manifest.")
    ap.add_argument("folder", nargs="?", default=".")
    ap.add_argument("--expect", help="the final hash you recorded when the scan was made")
    args = ap.parse_args(argv)
    problems, final = verify(Path(args.folder), args.expect)
    if problems:
        print("EVIDENCE DOES NOT MATCH ITS MANIFEST")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: every file matches. Final hash: {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
