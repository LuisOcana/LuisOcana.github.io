"""
Step 1 — Identify FOMC markets in Polymarket Gamma API.

Strategy: broad keyword search, dedupe by condition_id, filter for FOMC relevance.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path(__file__).parent
GAMMA_URL = "https://gamma-api.polymarket.com/markets"

KEYWORDS = [
    "fed decision",
    "fomc",
    "federal reserve",
    "fed rate",
    "interest rate decision",
    "basis points",
    "fed cut",
    "fed hike",
]

# Patterns to identify FOMC-meeting-specific markets
MONTH_YEAR_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+20(2[3-6])\b",
    re.IGNORECASE,
)
BPS_RE = re.compile(r"\b(\d+)\s*(?:bps|basis\s*points?)\b", re.IGNORECASE)
FED_KEY_RE = re.compile(r"\b(fed|fomc|federal reserve)\b", re.IGNORECASE)
RATE_KEY_RE = re.compile(r"\b(rate|cut|hike|hold|raise|lower|decision)\b", re.IGNORECASE)

# Exclusion patterns (annual aggregates, other central banks, indicators)
EXCLUDE_RE = re.compile(
    r"\b(ecb|bank of england|boe|boj|bank of japan|swiss national|snb|"
    r"inflation|cpi|ppi|unemployment|payroll|jobs report|recession|"
    r"more than|at least|fewer than|by end of|in 202[3-6]\?|throughout|all year)\b",
    re.IGNORECASE,
)


def fetch_keyword(kw: str) -> list[dict]:
    """Fetch up to 500 markets for a keyword via pagination.

    Tries `q=` first; if Gamma returns 0 results, falls back to client-side
    filtering via a global listing (active + closed) so a search-API change
    doesn't silently drop the dataset.
    """
    results = []
    offset = 0
    limit = 100
    while offset < 500:
        try:
            r = requests.get(
                GAMMA_URL,
                params={"q": kw, "limit": limit, "offset": offset},
                timeout=30,
                headers={"User-Agent": "fomc-viability/1.0 (+github actions)"},
            )
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"  ERROR keyword={kw} offset={offset}: {e}")
            break
        if not isinstance(batch, list) or not batch:
            break
        results.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
        time.sleep(0.3)
    return results


def fallback_global_scan(max_pages: int = 30) -> list[dict]:
    """Global scan + client-side keyword filter — used if `q=` returns nothing."""
    out = []
    offset = 0
    limit = 500
    pat = re.compile(r"\b(fed|fomc|federal reserve)\b", re.IGNORECASE)
    for _ in range(max_pages):
        try:
            r = requests.get(
                GAMMA_URL,
                params={"limit": limit, "offset": offset, "closed": "false"},
                timeout=30,
                headers={"User-Agent": "fomc-viability/1.0 (+github actions)"},
            )
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"  fallback ERROR offset={offset}: {e}")
            break
        if not isinstance(batch, list) or not batch:
            break
        for m in batch:
            q = (m.get("question") or "")
            if pat.search(q):
                out.append(m)
        offset += limit
        time.sleep(0.3)
    # Also pull closed/resolved
    offset = 0
    for _ in range(max_pages):
        try:
            r = requests.get(
                GAMMA_URL,
                params={"limit": limit, "offset": offset, "closed": "true"},
                timeout=30,
                headers={"User-Agent": "fomc-viability/1.0 (+github actions)"},
            )
            r.raise_for_status()
            batch = r.json()
        except Exception as e:
            print(f"  fallback(closed) ERROR offset={offset}: {e}")
            break
        if not isinstance(batch, list) or not batch:
            break
        for m in batch:
            q = (m.get("question") or "")
            if pat.search(q):
                out.append(m)
        offset += limit
        time.sleep(0.3)
    return out


def is_fomc_relevant(question: str) -> tuple[bool, str]:
    """Return (is_relevant, reason)."""
    if not question:
        return False, "empty"
    q = question.lower()
    if EXCLUDE_RE.search(q):
        return False, "excluded_pattern"
    has_fed = bool(FED_KEY_RE.search(q))
    has_month_year = bool(MONTH_YEAR_RE.search(q))
    has_bps = bool(BPS_RE.search(q))
    has_rate_word = bool(RATE_KEY_RE.search(q))

    # Must mention Fed/FOMC explicitly
    if not has_fed:
        return False, "no_fed_mention"

    # Must reference a specific meeting (month+year) OR a bps decision OR rate action
    if has_month_year:
        return True, "month_year"
    if has_bps and has_rate_word:
        return True, "bps_rate"
    if has_rate_word and ("decision" in q or "meeting" in q):
        return True, "rate_decision"
    return False, "no_specific_decision"


def normalize_market(m: dict) -> dict:
    """Extract relevant metadata fields, with safe access."""
    # Polymarket schema is heterogeneous; try several names.
    cid = m.get("conditionId") or m.get("condition_id")
    question = m.get("question") or ""
    closed = bool(m.get("closed", False))
    # Resolution status: outcomePrices set after resolution
    outcome_prices = m.get("outcomePrices") or m.get("outcome_prices")
    if isinstance(outcome_prices, str):
        try:
            outcome_prices = json.loads(outcome_prices)
        except Exception:
            pass
    outcomes = m.get("outcomes")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except Exception:
            pass
    tokens = m.get("clobTokenIds") or m.get("tokens")
    if isinstance(tokens, str):
        try:
            tokens = json.loads(tokens)
        except Exception:
            pass
    tags = m.get("tags") or []
    if isinstance(tags, list):
        tag_slugs = [t.get("slug") if isinstance(t, dict) else t for t in tags]
    else:
        tag_slugs = []

    volume = m.get("volumeNum") or m.get("volume") or 0
    try:
        volume = float(volume)
    except (TypeError, ValueError):
        volume = 0.0

    end_date = m.get("endDate") or m.get("end_date_iso") or m.get("endDateIso")
    created = m.get("createdAt") or m.get("created_at")

    resolved = closed and bool(outcome_prices)

    return {
        "condition_id": cid,
        "question": question,
        "closed": closed,
        "resolved": resolved,
        "outcome_prices": json.dumps(outcome_prices) if outcome_prices is not None else None,
        "outcomes": json.dumps(outcomes) if outcomes is not None else None,
        "volume": volume,
        "created_at": created,
        "end_date_iso": end_date,
        "tokens": json.dumps(tokens) if tokens is not None else None,
        "tags": ",".join(tag_slugs) if tag_slugs else "",
        "n_outcomes": len(outcomes) if isinstance(outcomes, list) else None,
    }


def main():
    print("=" * 60)
    print("STEP 1 — Searching Polymarket Gamma API for FOMC markets")
    print("=" * 60)
    all_raw = []
    for kw in KEYWORDS:
        print(f"\n[fetch] keyword={kw!r}")
        batch = fetch_keyword(kw)
        print(f"  got {len(batch)} markets")
        all_raw.extend(batch)

    # Dedupe by condition_id
    seen = {}
    for m in all_raw:
        cid = m.get("conditionId") or m.get("condition_id")
        if cid and cid not in seen:
            seen[cid] = m
    print(f"\nTotal unique markets across keyword search: {len(seen)}")

    # If keyword search returned nothing useful, fall back to a global scan
    if len(seen) < 5:
        print("\n[fallback] keyword search yielded <5 markets, switching to global scan")
        for m in fallback_global_scan():
            cid = m.get("conditionId") or m.get("condition_id")
            if cid and cid not in seen:
                seen[cid] = m
        print(f"  after fallback: {len(seen)} unique markets")

    # Filter for FOMC relevance
    relevant = []
    excluded_reasons = {}
    for cid, m in seen.items():
        norm = normalize_market(m)
        ok, reason = is_fomc_relevant(norm["question"])
        if ok:
            norm["match_reason"] = reason
            relevant.append(norm)
        else:
            excluded_reasons[reason] = excluded_reasons.get(reason, 0) + 1

    print(f"\nRelevant FOMC markets: {len(relevant)}")
    print("Exclusion breakdown:")
    for r, n in sorted(excluded_reasons.items(), key=lambda x: -x[1]):
        print(f"  {r}: {n}")

    # Build dataframe
    df = pd.DataFrame(relevant)
    if df.empty:
        print("\nWARNING: no FOMC markets matched filter. Saving raw dump for inspection.")
        # Save raw sample for manual inspection
        with open(OUT_DIR / "fomc_markets_raw_dump.json", "w") as f:
            json.dump(list(seen.values())[:50], f, indent=2, default=str)
        return

    # Parse dates and add year
    def parse_year(s):
        if not s:
            return None
        try:
            return pd.to_datetime(s).year
        except Exception:
            return None

    df["end_year"] = df["end_date_iso"].apply(parse_year)
    df = df.sort_values(by=["end_date_iso"], na_position="last")

    # Save raw filtered dataset
    out_path = OUT_DIR / "fomc_markets_raw.csv"
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} markets -> {out_path}")

    # Summary
    print("\n=== SUMMARY ===")
    print(f"Total FOMC markets: {len(df)}")
    print(f"Resolved: {df['resolved'].sum()}")
    print(f"Active (not closed): {(~df['closed']).sum()}")
    print(f"Closed but unresolved: {(df['closed'] & ~df['resolved']).sum()}")

    print("\nDistribution by end-date year:")
    year_counts = df["end_year"].value_counts().sort_index()
    print(year_counts.to_string())

    print("\nDistribution by n_outcomes:")
    print(df["n_outcomes"].value_counts(dropna=False).to_string())

    print("\nMatch reason distribution:")
    print(df["match_reason"].value_counts().to_string())

    # Save summary as json for downstream steps
    summary = {
        "total": int(len(df)),
        "resolved": int(df["resolved"].sum()),
        "active": int((~df["closed"]).sum()),
        "by_year": {str(k): int(v) for k, v in year_counts.items()},
        "n_outcomes_dist": {
            str(k): int(v) for k, v in df["n_outcomes"].value_counts(dropna=False).items()
        },
        "exclusion_reasons": excluded_reasons,
        "generated_at": datetime.utcnow().isoformat(),
    }
    with open(OUT_DIR / "step1_summary.json", "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
