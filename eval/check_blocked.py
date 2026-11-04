"""Run the blocked-scan detector over every evidence folder.
  python eval/check_blocked.py [evidence_root]
"""
import sys
from pathlib import Path

sys.path.insert(0, "src")
from ndpa.capture.blocked import check_evidence_folder  # noqa: E402

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data/evidence")
for folder in sorted(root.glob("*/*")):
    if not (folder / "network.har").exists() or not (folder / "dom_snapshot.html").exists():
        continue
    v = check_evidence_folder(folder)
    print(f"{'BLOCKED' if v.blocked else 'ok':<8} {folder.parent.name:<22} "
          f"{folder.name[:19]}  {'; '.join(v.reasons)}")
