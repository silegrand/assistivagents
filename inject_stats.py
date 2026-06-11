#!/usr/bin/env python3
"""
inject_stats.py — Assistiv Cloud static stat injection
═══════════════════════════════════════════════════════

Bakes the current live data values into the static HTML as fallback text,
between <!--INJECT:key--> ... <!--/INJECT--> markers, so the numbers are
visible to AI crawlers, search engines and anyone with JavaScript disabled.
The page JavaScript still overwrites these values on load, so nothing about
the live behaviour changes.

This script is ADDITIVE to the data pipeline. It does not modify any
data fetcher, any JSON output, or any scoring logic. It reads the latest
committed JSON files via the GitHub API (never the possibly-stale local
checkout) and patches only the marked spans in:

  - index.html            (FEP ticker, top district, high-risk count,
                           RAVI critical count, discharge delay + period)
  - nhs-pressure-map.html (corridor total, HES 65+ admissions,
                           SHMI East Kent, GP 75+ population)

Commits via the GitHub contents API, mirroring daily_refresh.py's pattern,
and only commits when a value has actually changed.

Run from GitHub Actions after any data refresh:
    python inject_stats.py
Requires: GITHUB_TOKEN env var with contents:write on this repo.
"""

import base64
import json
import os
import re
import sys

import requests

GITHUB_REPO  = "silegrand/assistiv_cloud"
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
BRANCH       = "main"

API  = f"https://api.github.com/repos/{GITHUB_REPO}/contents"
HEAD = {"Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"}


# ── GitHub API helpers ───────────────────────────────────────────────

def get_file(path):
    """Fetch latest file content + sha from the repo via the API."""
    r = requests.get(f"{API}/{path}", headers=HEAD, params={"ref": BRANCH})
    if r.status_code != 200:
        print(f"  ✗ could not fetch {path}: {r.status_code}")
        return None, None
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return content, data["sha"]


def put_file(path, content, sha, message):
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": BRANCH,
        "sha": sha,
    }
    r = requests.put(f"{API}/{path}", headers=HEAD, json=payload)
    if r.status_code in (200, 201):
        print(f"  ✓ committed {path}")
        return True
    print(f"  ✗ commit failed {path}: {r.status_code} {r.json().get('message','')}")
    return False


def get_json(path):
    content, _ = get_file(path)
    if content is None:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"  ✗ invalid JSON in {path}: {e}")
        return None


# ── Value derivation (mirrors the page JavaScript exactly) ──────────

def derive_index_values():
    """Values for index.html — mirrors loadLiveData()."""
    vals = {}
    fep = get_json("kent-fep-data.json")
    if fep and fep.get("districts"):
        ds = fep["districts"]
        top = ds[0]
        vals["top_district"] = f"{top['name']} {top['fep']}"
        vals["high_count"] = str(sum(
            1 for d in ds if d.get("risk") in ("high", "critical")))
        ticker = " · ".join(f"{d['name']} {d['fep']}" for d in ds[:3])
        vals["ticker"] = f"Live: {ticker} · Data refreshed daily"

    ravi = get_json("kent-ravi-data.json")
    if ravi and ravi.get("lsoas"):
        vals["ravi_count"] = str(sum(
            1 for l in ravi["lsoas"] if l.get("ravi_band") == "critical"))

    dis = get_json("kent-discharge-data.json")
    if dis:
        ek = dis.get("table2_daily_discharge", {}).get("ekhuft", {})
        remaining = ek.get("avg_remaining_per_day")
        if remaining is not None:
            vals["discharge_count"] = str(round(remaining))
        period = dis.get("meta", {}).get("period_nice")
        if period:
            # "April 2026" → "Apr 2026" to match the existing label style
            parts = period.split()
            vals["discharge_period"] = (
                f"{parts[0][:3]} {parts[1]}" if len(parts) == 2 else period)
    return vals


def derive_pressure_values():
    """Values for nhs-pressure-map.html — mirrors its banner JS."""
    vals = {}
    cor = get_json("kent-corridor-data.json")
    if cor and cor.get("trusts"):
        totals = [t["corridor_total"] for t in cor["trusts"].values()
                  if t.get("corridor_total") is not None]
        if totals:
            vals["corridor_total"] = f"{sum(totals):,.0f}"

    hes = get_json("kent-hes-data.json")
    if hes and hes.get("trusts"):
        sums = [t["total_emerg_65plus"] for t in hes["trusts"].values()
                if t.get("total_emerg_65plus") is not None]
        if sums:
            vals["emerg_65plus"] = f"{sum(sums):,}"

    shmi = get_json("kent-shmi-data.json")
    rvv = (shmi or {}).get("trusts", {}).get("RVV", {})
    if rvv.get("shmi_value") is not None:
        vals["shmi_ek"] = f"{rvv['shmi_value']:.2f}"

    gp = get_json("kent-gp-reg-data.json")
    if gp and gp.get("districts"):
        pops = [d["pop_75plus"] for d in gp["districts"].values()
                if d.get("pop_75plus") is not None]
        if pops:
            vals["pop_75plus"] = f"{sum(pops):,}"
    return vals


# ── HTML patching ────────────────────────────────────────────────────

def patch_html(html, values):
    """Replace content between INJECT markers. Returns (html, changed)."""
    changed = False
    for key, val in values.items():
        pattern = re.compile(
            r"(<!--INJECT:" + re.escape(key) + r"-->)(.*?)(<!--/INJECT-->)",
            re.DOTALL)
        m = pattern.search(html)
        if not m:
            continue
        if m.group(2) != val:
            html = pattern.sub(
                lambda mm: mm.group(1) + val + mm.group(3), html, count=1)
            changed = True
            print(f"    {key}: '{m.group(2).strip()}' → '{val}'")
    return html, changed


def inject(page, values, label):
    if not values:
        print(f"  – no values derived for {page}, skipping")
        return
    html, sha = get_file(page)
    if html is None:
        return
    patched, changed = patch_html(html, values)
    if not changed:
        print(f"  = {page} already current, no commit")
        return
    put_file(page, patched, sha,
             f"Static stat injection — {label} — automated")


def main():
    print("── index.html ──")
    inject("index.html", derive_index_values(), "index fallbacks")
    print("── nhs-pressure-map.html ──")
    inject("nhs-pressure-map.html", derive_pressure_values(),
           "pressure map fallbacks")
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
