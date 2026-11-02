"""Show tracker requests (register R8). Same code the tool uses.
  python eval/is_tracker.py path/to/network.har
  python eval/is_tracker.py "https://example.com/some/url"
"""
import json
import sys
from datetime import datetime

sys.path.insert(0, "src")
from ndpa.analyse.trackers import TrackerList, is_third_party  # noqa: E402


def show(label, m):
    cats = ", ".join(m.categories) or "no-category"
    print(f"{label:>9}  {m.domain:<28} {m.owner:<24} {cats:<32} {m.reason}")


def main(arg):
    tl = TrackerList()
    if not arg.endswith(".har"):
        m = tl.match(arg)
        print("TRACKER" if m else "not a tracker")
        if m:
            show("", m)
        return
    entries = json.load(open(arg))["log"]["entries"]
    if not entries:
        print("HAR has no entries")
        return
    t0 = datetime.fromisoformat(entries[0]["startedDateTime"])
    site = entries[0]["request"]["url"]
    hits = third = 0
    for e in entries:
        url = e["request"]["url"]
        if not is_third_party(url, site):
            continue
        third += 1
        m = tl.match(url)
        if m:
            hits += 1
            ms = int((datetime.fromisoformat(e["startedDateTime"]) - t0).total_seconds() * 1000)
            show(f"+{ms}ms", m)
    print(f"\n{hits} tracker requests out of {third} third-party requests ({len(entries)} total)")


main(sys.argv[1])
