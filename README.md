# NDPA Privacy Check

A tool that assesses a website's cookie, tracker and privacy-policy behaviour against the Nigeria Data Protection
Act 2023 and the GAID 2025. It opens the site in a real Chrome window, records what happens before and after a
visitor clicks Accept or Reject on the cookie banner, reads the privacy policy, applies 17 scored rules, and shows
the result in a dashboard with a fix-first list, a timeline, history and re-scan comparison.

It checks what a visitor's browser can observe. It is a technical assessment, not legal advice.

MIT (Master of Information Technology) applied project, MIVA Open University.

## Quick start

You need Python 3.11 or newer and Google Chrome installed.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m ndpa.web --vantage "Port Harcourt, NG"
```

Then open http://127.0.0.1:8000, type a website address and press **Scan website**.

- Run everything from the repository root (the folder that contains `rulebook/` and `data/`).
- A scan takes two to three minutes. A Chrome window opens and closes by itself while it runs: leave it alone.
- `--vantage` records where you are scanning from. It is shown on every result, because results depend on location.
- Results are stored in `data/ndpa.db`, and the evidence for each scan in `data/evidence/<site>/<time>/`. Both stay on your computer.

Useful options: `--headless` (no visible window), `--port 8001`, `--db path/to/other.db`.

## From the command line

```bash
python -m ndpa.scan https://example.com.ng --vantage "Port Harcourt, NG"   # one full scan, stored like the dashboard
python -m ndpa.rules.engine data/evidence/<site>/<time>                    # print the rule results for a scan
python data/evidence/<site>/<time>/verify.py --expect <final hash>        # prove the evidence has not been changed
```

## Tests

```bash
python -m playwright install chromium   # once, for the browser tests
python -m pytest tests/unit -q           # fast, no browser
python -m pytest tests/integration -q    # real browser against local test sites (a few minutes)
```

## Where things are

| Folder | What it holds |
|---|---|
| `src/ndpa/capture/` | the browser: three runs per site (no click, Accept, Reject), banner finder, policy discovery |
| `src/ndpa/rules/` | the 17 rules and the text analysis behind the privacy-policy rules |
| `src/ndpa/scoring/`, `remediation/` | the score, risk band and the fix-first list |
| `src/ndpa/evidence/` | the hash-chained evidence manifest and its stand-alone verifier |
| `src/ndpa/storage/` | the SQLite database |
| `src/ndpa/web/` | the dashboard (FastAPI, Jinja2 templates, server-drawn SVG charts) |
| `rulebook/` | the rulebook (`rules.v2.yaml`) and the list of necessary cookies |
| `data/lists/` | the frozen tracker list (DuckDuckGo tracker blocklist snapshot) |
| `eval/` | tools for the evaluation: annotation templates, tracker lookup, rulebook freeze |
| `docs/` | decisions, backlog, and `spikes/` (the evidence for choosing the tracker list) |
| `.github/workflows/` | continuous integration: lint and every test on each push |
