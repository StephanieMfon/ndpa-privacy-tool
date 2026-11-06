"""Spike 0.5a - offline check on baseline HAR files.

Compares three ways of recognising trackers on the same requests:
  A) the current 10-vendor signature list  (config/tracker_signatures.json)
  B) DuckDuckGo tracker blocklist (derived from Tracker Radar)   --tds
  C) EasyPrivacy domain rules (optional)                          --easyprivacy
and, if a DB-IP country file is given (--geo), the apparent country of each server IP.

Run from the repo root with the venv active:
  python spikes/spike_05a_lists.py --evidence ../ndpa-baseline-evidence --tds tds.json \
      --easyprivacy easyprivacy.txt --geo dbip-country-lite.mmdb
"""
import argparse
import glob
import json
import os
import re
from collections import defaultdict
from urllib.parse import urlparse

import tldextract

_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())  # offline: bundled suffix list


def reg_domain(host):
    e = _EXTRACT(host)
    return getattr(e, "top_domain_under_public_suffix", None) or e.registered_domain or host


def suffixes(host):
    """a.b.c.com -> a.b.c.com, b.c.com, c.com (stops before the bare TLD)."""
    parts = host.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def load_signatures(path):
    vendors = json.load(open(path))["vendors"]
    return [(v["name"], v["signatures"]) for v in vendors]


def match_signatures(url, vendors):
    for name, sigs in vendors:
        if any(s in url for s in sigs):
            return name
    return None


def load_tds(path):
    return json.load(open(path)).get("trackers", {})


def match_tds(host, url, tds):
    """Domain lookup, then (for 'ignore'-by-default domains) the tracker's own URL regex rules."""
    for sfx in suffixes(host):
        t = tds.get(sfx)
        if not t:
            continue
        hit = t.get("default") != "ignore"
        if not hit:
            for rule in t.get("rules", []):
                try:
                    if re.search(rule.get("rule", ""), url):
                        hit = True
                        break
                except re.error:
                    continue
        if hit:
            owner = (t.get("owner") or {}).get("displayName") or (t.get("owner") or {}).get("name") or "?"
            return f"{owner} | {','.join(t.get('categories', [])) or 'no-category'} | fp={t.get('fingerprinting', '?')}"
    return None


_EP_DOMAIN_RULE = re.compile(r"^\|\|([a-z0-9][a-z0-9.-]*\.[a-z]{2,})\^(\$[a-z,\-]*)?$")


def load_easyprivacy(path):
    """Keep ONLY plain '||domain^' rules (optionally '$third-party/$script/...'). Ignore everything else."""
    domains = set()
    skipped = 0
    for line in open(path, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line.startswith("||"):
            continue
        m = _EP_DOMAIN_RULE.match(line)
        if m:
            domains.add(m.group(1))
        else:
            skipped += 1
    print(f"EasyPrivacy: {len(domains)} domain rules kept, {skipped} other '||' rules ignored")
    return domains


def match_ep(host, ep):
    return any(s in ep for s in suffixes(host))


def open_geo(path):
    if not path:
        return None
    import maxminddb
    return maxminddb.open_database(path)


def country(geo, ip):
    if not geo or not ip:
        return "-"
    try:
        rec = geo.get(ip.strip("[]"))
        return (rec or {}).get("country", {}).get("iso_code", "??")
    except Exception:
        return "??"


def latest_hars(evidence_dir):
    """One HAR per host folder: the newest timestamp folder."""
    out = {}
    for har in sorted(glob.glob(os.path.join(evidence_dir, "*", "*", "network.har"))):
        host = har.split(os.sep)[-3]
        out[host] = har  # sorted ascending, so the last one wins
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--tds", required=True)
    ap.add_argument("--easyprivacy")
    ap.add_argument("--geo")
    ap.add_argument("--signatures", default="config/tracker_signatures.json")
    ap.add_argument("--hosts", nargs="*", help="only these evidence folder names (default: all)")
    a = ap.parse_args()

    vendors = load_signatures(a.signatures)
    tds = load_tds(a.tds)
    ep = load_easyprivacy(a.easyprivacy) if a.easyprivacy else set()
    geo = open_geo(a.geo)
    print(f"TDS trackers loaded: {len(tds)}")

    results = {}
    totals = defaultdict(int)
    ep_only, tds_only = set(), set()

    for host, har in latest_hars(a.evidence).items():
        if a.hosts and host not in a.hosts:
            continue
        first_party = reg_domain(host)
        entries = json.load(open(har))["log"]["entries"]
        rows = {}
        for e in entries:
            url = e["request"]["url"]
            h = urlparse(url).hostname or ""
            d = reg_domain(h)
            if not h or d == first_party:
                continue
            r = rows.setdefault(d, {"reqs": 0, "ip": None, "hosts": set(), "A": None, "B": None, "C": False})
            r["reqs"] += 1
            r["hosts"].add(h)
            r["ip"] = r["ip"] or e.get("serverIPAddress")
            r["A"] = r["A"] or match_signatures(url, vendors)
            r["B"] = r["B"] or match_tds(h, url, tds)
            r["C"] = r["C"] or (match_ep(h, ep) if ep else False)

        print(f"\n=== {host}  (third-party domains: {len(rows)}) ===")
        print(f"{'domain':32} {'reqs':>4} {'ctry':4} {'A:current':16} {'B:TDS (owner | categories | fp)':60} C:EP")
        for d, r in sorted(rows.items(), key=lambda kv: -kv[1]["reqs"]):
            if not (r["A"] or r["B"] or r["C"]):
                continue
            print(f"{d[:32]:32} {r['reqs']:>4} {country(geo, r['ip']):4} {(r['A'] or '-')[:16]:16} {(r['B'] or '-')[:60]:60} {'yes' if r['C'] else '-'}")
            if r["C"] and not r["B"]:
                ep_only.add(d)
            if r["B"] and not r["A"]:
                tds_only.add(d)
        n = lambda k: sum(1 for r in rows.values() if r[k])
        flagged = {k: n(k) for k in "ABC"}
        union = sum(1 for r in rows.values() if r["A"] or r["B"] or r["C"])
        print(f"flagged -> current: {flagged['A']}  TDS: {flagged['B']}  EasyPrivacy: {flagged['C']}  any: {union}")
        results[host] = {"third_party": len(rows), "flagged": flagged, "any": union,
                         "countries": sorted({country(geo, r['ip']) for r in rows.values() if r["ip"]})}
        for k, v in flagged.items():
            totals[k] += v

    print("\n=== SUMMARY ===")
    print(f"Total flagged: current={totals['A']}  TDS={totals['B']}  EasyPrivacy={totals['C']}")
    print(f"Found by TDS but NOT by current list: {len(tds_only)}")
    if ep:
        print(f"Found by EasyPrivacy but NOT by TDS ({len(ep_only)}) - review these by hand:")
        for d in sorted(ep_only):
            print("   ", d)
    json.dump({"sites": results, "ep_only": sorted(ep_only), "tds_only": sorted(tds_only)},
              open("spike_05a_results.json", "w"), indent=2)
    print("\nSaved spike_05a_results.json")


if __name__ == "__main__":
    main()