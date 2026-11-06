
import pathlib
import shutil
import subprocess
import sys

root = pathlib.Path(".")
assert (root / "src" / "ndpa").is_dir() and (root / "pyproject.toml").exists(), "Run this from the project folder (the one that contains src/ and pyproject.toml)."
in_git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode == 0
print("git repository:", "yes" if in_git else "NO (old files will be deleted without a git safety net; your old project folder still has them)")


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


def append_once(path, marker, text):
    p = pathlib.Path(path)
    if marker in p.read_text(encoding="utf-8"):
        print("  already there:", path, marker)
        return
    with open(p, "a", encoding="utf-8") as f:
        f.write(text)
    print("  added to:", path, marker)


def patch(path, old, new):
    p = pathlib.Path(path)
    s = p.read_text(encoding="utf-8")
    if new in s and old not in s:
        print("  already applied:", path)
        return
    assert s.count(old) == 1, f"{path}: the expected text was not found exactly once. Paste me the first 15 lines of this file."
    p.write_text(s.replace(old, new), encoding="utf-8")
    print("  patched:", path)


# 1. safety tag, so the old scanner can always be brought back with: git checkout pre-cleanup-2026-11-06 -- scanner
if in_git:
    git("tag", "-f", "pre-cleanup-2026-11-06")
    print("tagged the current commit as pre-cleanup-2026-11-06")

# 2. keep the evidence for how the tracker list was chosen, then retire the old scanner
spikes = root / "docs" / "spikes"
spikes.mkdir(parents=True, exist_ok=True)
for src in (root / "spikes" / "spike_05a_lists.py", root / "spike_05a_results.json"):
    if src.exists():
        shutil.copy(src, spikes / src.name)
old_things = ["scanner", "config", "spikes", "run_scan.py", "main.py", "notes.md", "spike_05a_results.json",
              "tests/fixtures/fingerprint_test_page.html", *[str(p) for p in sorted(root.glob("tests/test_*.py"))]]
for name in old_things:
    path = root / name
    if in_git:
        git("rm", "-r", "-q", "-f", "--ignore-unmatch", name)
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()
print("removed the old scanner, its config, its tests and the two old entry-point scripts")

# 3. lint configuration (replaces the single line-length setting)
patch("pyproject.toml", "[tool.ruff]\nline-length = 100\n", '''[tool.ruff]
line-length = 120
target-version = "py311"
extend-exclude = ["docs/spikes"]  # kept as evidence of how the tracker list was chosen; not maintained code

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "B", "C4"]
# B008: FastAPI's Depends(...) and Query(...) in a function signature is the framework's own idiom.
ignore = ["B008"]
''')

patch("pyproject.toml", 'dev = ["pytest", "ruff", "httpx"]', 'dev = ["pytest", "ruff>=0.17,<0.18", "httpx"]')

# 4. the six small lint fixes that need a human decision (behaviour is unchanged)
patch("eval/prepare_annotation.py",
      'sites = [l.strip() for l in open("my_site_list.txt") if l.strip() and not l.lstrip().startswith("#")]',
      'sites = [line.strip() for line in open("my_site_list.txt") if line.strip() and not line.lstrip().startswith("#")]')
patch("src/ndpa/rules/checks/policy.py", "    for source, text in d.privacy:\n", "    for _source, text in d.privacy:\n")
patch("src/ndpa/rules/text.py", "zip(spans, labels) if span.text.strip()]", "zip(spans, labels, strict=True) if span.text.strip()]")
patch("src/ndpa/web/charts.py", "    for i, (key, label) in enumerate(LANES):\n        y = top + i * lane_h", "    for i, (_key, label) in enumerate(LANES):\n        y = top + i * lane_h")
patch("tests/unit/test_chain.py", '    a, b = make(tmp_path / "a" if (tmp_path / "a").mkdir() or True else tmp_path), None\n',
      '    first = tmp_path / "first"\n    first.mkdir()\n    make(first)\n')
patch("tests/unit/test_chain.py", 'assert chain.build_manifest(a)["final"] == chain.build_manifest(other)["final"]',
      'assert chain.build_manifest(first)["final"] == chain.build_manifest(other)["final"]')

# 5. continuous integration: lint and every test on each push
ci = root / ".github" / "workflows" / "ci.yml"
ci.parent.mkdir(parents=True, exist_ok=True)
ci.write_text('''name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v6

      - uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: pyproject.toml

      - name: Install the project and its test tools
        run: pip install -e ".[dev]"

      - name: Lint
        run: ruff check src tests eval

      - name: Install the browser the tests use
        run: python -m playwright install --with-deps chromium

      - name: Unit tests (no browser)
        run: python -m pytest tests/unit -q

      - name: Integration tests (real browser against local test sites)
        run: python -m pytest tests/integration -q
''', encoding="utf-8")
print("  wrote:", ci)

# 6. mechanical lint fixes (import order and similar), done by ruff itself
fixed = subprocess.run([sys.executable, "-m", "ruff", "check", "src", "tests", "eval", "--fix"], capture_output=True, text=True)
print("ruff --fix:", (fixed.stdout.strip().splitlines() or ["(no output)"])[-1])

# 7. documentation
patch("README.md", "| `scanner/`, `run_scan.py`, `main.py` | the old scanner, kept until the port is complete (to be removed) |",
      "| `.github/workflows/` | continuous integration: lint and every test on each push |")
patch("README.md", "| `docs/` | decisions, backlog |", "| `docs/` | decisions, backlog, and `spikes/` (the evidence for choosing the tracker list) |")
patch("docs/backlog.md",
      "- B-22 Fixture suite completion, CI (GitHub Actions), ruff configuration (default rules now flag about 69 style findings in older code), docs, retire the old scanner/, run_scan.py, main.py, tests/test_*.py at the top of tests/, and the old venv/ folder.",
      "- B-22 DONE 6 Nov 2026: CI (GitHub Actions), ruff configuration, old scanner retired (kept in git under the tag pre-cleanup-2026-11-06). Remaining: delete any old venv/ folder by hand; more fixture sites if the evaluation needs them.")
append_once("docs/backlog.md", "B-36", """
## Added 6 Nov 2026
- B-36 FUTURE TASK, after the task outline is finished: a technical build book. A very detailed breakdown of the approach and plan for each part of the project (capture, script and cookie attribution, tracker detection, the rules, the text analysis behind the policy rules, scoring, evidence integrity, storage, orchestration, the dashboard, security, evaluation), the reason behind each choice, the considerations, the alternatives that were rejected and why, and what could go wrong, written by the builder (Claude) with as much technical depth as possible. It is the source material for Chapters 3 to 5 and for preparing the defence. Delivered in chat, as always.
- B-38 Re-assessed B-12 with the real scans: MTN has 0 of 13 script-set cookies without an attributed script; punchng has 27 of 107, but they are only two cookie names, FCCDCF and FCNEC (they look like Google Funding Choices consent cookies; what they store is UNVERIFIED). So the CDP attribution upgrade would fix very little. Recommend keeping it low in the cut order. Instead, check at the pilot whether FCCDCF and FCNEC belong on the R1 necessary-cookie list (they are currently counted as non-necessary).
- B-37 CI uses actions/checkout@v6 and actions/setup-python@v6. Newer major versions may exist (UNVERIFIED); update when GitHub warns, or turn on Dependabot for actions.
""")
append_once("docs/decisions.md", "D-41", """
## Update 6 Nov 2026 (repository hygiene)

- D-41 The old scanner (scanner/, config/, run_scan.py, main.py and its tests) is retired. Nothing in the new code depended on it; the rulebook, the DuckDuckGo tracker list and rulebook/necessary_cookies.yaml replace its inputs. It stays recoverable from git (tags v0-code-snapshot and pre-cleanup-2026-11-06).
- D-42 spike_05a_results.json and its script are kept in docs/spikes/ as the evidence for choosing the DuckDuckGo tracker list over EasyPrivacy.
- D-43 Lint uses ruff with an explicit rule set (E4, E7, E9, F, I, B, C4), line length 120, and B008 ignored (FastAPI idiom). CI runs ruff, the unit tests and the browser tests on every push.
""")
print("\nDone. Now run:  python -m ruff check src tests eval   and   python -m pytest -q")
