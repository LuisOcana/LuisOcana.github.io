"""
Step 4 — Verify CME FedWatch availability as benchmark + survey alternatives.

CME does not expose FedWatch as a stable, documented public API. The web tool
(cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html) is JS-rendered and
fetches data from internal services that change frequently.

What we attempt here, in order of preference:

  A) https://www.cmegroup.com/services/fed-watch                  (internal endpoint)
  B) https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/FedWatchTool/...
                                                                  (mobile/widget endpoint)
  C) FRED Fed Funds Futures contracts (public API, requires API key):
       - https://api.stlouisfed.org/fred/series?series_id=FEDFUNDS_FUTURE
       - Per-contract series: ZQ {month}{year} (CME 30-Day Federal Funds futures)
       - From these we reconstruct meeting-implied probabilities ourselves using
         the standard FedWatch methodology: subtract month-to-date realized fed
         funds from contract price to back out post-meeting expected rate, then
         allocate probability mass across discrete -50/-25/0/+25/+50 buckets.

  D) Manual scrape of cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html
     (last resort — fragile, ToS may prohibit, requires JS rendering).

The probabilistic reconstruction in (C) is the only fully documented + replicable
path. CME's published methodology is here:
  https://www.cmegroup.com/articles/2023/understanding-the-cme-group-fedwatch-tool-methodology.html

Output:
  fomc_viability/step4_summary.json
"""

import json
from pathlib import Path

import requests

OUT_DIR = Path(__file__).parent

PROBES = [
    ("cme_internal", "https://www.cmegroup.com/services/fed-watch"),
    ("cme_widget",  "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/305/G"),  # ZQ contracts
    ("fred_api",    "https://api.stlouisfed.org/fred/series/observations?series_id=ZQK24&api_key=DEMO&file_type=json"),
    ("fed_calendar","https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
]


def probe(label: str, url: str) -> dict:
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "fomc-viability-probe/1.0"})
        return {"label": label, "url": url, "status": r.status_code,
                "content_type": r.headers.get("Content-Type"), "len": len(r.content)}
    except Exception as e:
        return {"label": label, "url": url, "status": None, "error": str(e)}


def main():
    print("=" * 60)
    print("STEP 4 — CME FedWatch / fed-funds-futures benchmark probe")
    print("=" * 60)
    results = [probe(label, url) for label, url in PROBES]
    for r in results:
        print(f"  {r['label']:14s} -> {r.get('status')} {r.get('error', '')}")

    # Summary + decision tree
    cme_reachable = any(r["label"].startswith("cme") and r.get("status") == 200 for r in results)
    fred_reachable = any(r["label"] == "fred_api" and r.get("status") == 200 for r in results)
    fed_reachable = any(r["label"] == "fed_calendar" and r.get("status") == 200 for r in results)

    summary = {
        "probes": results,
        "cme_direct_reachable": cme_reachable,
        "fred_reachable": fred_reachable,
        "fed_calendar_reachable": fed_reachable,
        "recommendation": None,
        "notes": [],
    }

    if cme_reachable:
        summary["recommendation"] = "Use CME FedWatch directly (best granularity, daily snapshots)."
    elif fred_reachable:
        summary["recommendation"] = (
            "Use FRED Fed Funds Futures (ZQ contracts) and compute meeting-implied "
            "probabilities manually using CME's published methodology."
        )
        summary["notes"].append(
            "FRED free API requires a key (https://fred.stlouisfed.org/docs/api/api_key.html)."
        )
        summary["notes"].append(
            "Methodology reference: https://www.cmegroup.com/articles/2023/understanding-the-cme-group-fedwatch-tool-methodology.html"
        )
    else:
        summary["recommendation"] = (
            "All benchmark sources blocked from this environment. To proceed, "
            "either (a) run from a host with internet egress, (b) request FRED API "
            "key + add api.stlouisfed.org to allowlist, or (c) procure a daily "
            "snapshot dataset (e.g., via Bloomberg WIRP or a vendor)."
        )
        summary["notes"].append(
            "In the sandbox where this script ran first, all hosts returned HTTP 403 "
            "with body 'Host not in allowlist' — the proxy enforces a closed allowlist."
        )

    summary["alternatives"] = [
        {
            "name": "FRED Fed Funds Futures (ZQ contracts)",
            "pros": ["public API", "daily resolution", "free with API key"],
            "cons": ["must implement FedWatch methodology yourself",
                    "discrete probability allocation across rate buckets is non-trivial"],
            "url": "https://fred.stlouisfed.org/docs/api/",
        },
        {
            "name": "Bloomberg WIRP",
            "pros": ["pre-computed probabilities", "intraday"],
            "cons": ["terminal license required (~$25k/yr)"],
            "url": None,
        },
        {
            "name": "Manual scrape of FedWatch HTML/JS",
            "pros": ["no API key"],
            "cons": ["fragile (DOM changes)", "ToS ambiguous", "JS rendering needed (Playwright/Selenium)"],
            "url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html",
        },
        {
            "name": "Daily snapshots from a third party (e.g., academic dataset)",
            "pros": ["already historical"],
            "cons": ["coverage may not include 2025-2026", "licensing"],
            "url": None,
        },
    ]

    with open(OUT_DIR / "step4_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nrecommendation: {summary['recommendation']}")


if __name__ == "__main__":
    main()
