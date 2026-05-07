"""
Step 3 — Verify Polymarket CLOB price-history availability for a sample.

Picks 5 representative markets across time horizons (recent / 6mo / 1y / 2y / oldest)
and queries the CLOB prices-history endpoint for each. Reports coverage of the
critical 24-72h pre-announcement window.

This is the central viability test: if CLOB does not retain price history for
markets older than ~12 months, longitudinal analysis is bounded.

Endpoint:
  GET https://clob.polymarket.com/prices-history
    ?market={yes_token_id}
    &interval=max
    &fidelity=60   # 60-minute bars

Output:
  fomc_viability/price_history_sample.csv  (one row per (market, hourly bar))
  fomc_viability/step3_summary.json        (per-market coverage summary)
"""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path(__file__).parent
CLOB_HISTORY = "https://clob.polymarket.com/prices-history"

# Buckets to sample. Filled lazily from fomc_meetings.csv if available; otherwise
# the user can override SAMPLE_MARKETS manually with (label, condition_id, yes_token_id, statement_date).
BUCKETS = [
    {"label": "recent_<2mo",   "min_age_days": 0,   "max_age_days": 60},
    {"label": "mid_~6mo",      "min_age_days": 150, "max_age_days": 210},
    {"label": "old_~1y",       "min_age_days": 330, "max_age_days": 400},
    {"label": "very_old_~2y",  "min_age_days": 700, "max_age_days": 800},
    {"label": "oldest_>2y",    "min_age_days": 800, "max_age_days": 9999},
]


def pick_sample(meetings_with_markets: pd.DataFrame, today: datetime) -> list[dict]:
    """For each bucket, pick the meeting with the highest market volume.

    Expects df with at least columns: meeting_id, statement_date, total_volume,
    yes_token_id, condition_id, question.
    """
    chosen = []
    df = meetings_with_markets.copy()
    df["statement_date"] = pd.to_datetime(df["statement_date"])
    df["age_days"] = (today - df["statement_date"]).dt.days

    for b in BUCKETS:
        cand = df[
            (df["age_days"] >= b["min_age_days"]) & (df["age_days"] <= b["max_age_days"])
        ].sort_values("total_volume", ascending=False)
        if cand.empty:
            chosen.append({"bucket": b["label"], "match": None})
        else:
            row = cand.iloc[0].to_dict()
            row["bucket"] = b["label"]
            chosen.append(row)
    return chosen


def fetch_history(token_id: str) -> dict:
    """Fetch full hourly price history for a YES-token. Returns parsed dict or error."""
    try:
        r = requests.get(
            CLOB_HISTORY,
            params={"market": token_id, "interval": "max", "fidelity": 60},
            timeout=60,
        )
        r.raise_for_status()
        return {"ok": True, "data": r.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def evaluate_coverage(history: dict, statement_date: datetime) -> dict:
    """Did the price history cover the 72h pre-announcement window?"""
    if not history.get("ok"):
        return {"n_obs": 0, "covered_72h": False, "first_ts": None, "last_ts": None,
                "error": history.get("error")}
    points = history["data"].get("history") or history["data"].get("points") or []
    if not points:
        return {"n_obs": 0, "covered_72h": False, "first_ts": None, "last_ts": None,
                "error": "empty_history"}
    timestamps = [p["t"] for p in points if "t" in p]
    if not timestamps:
        return {"n_obs": 0, "covered_72h": False, "first_ts": None, "last_ts": None,
                "error": "no_timestamps_in_payload"}
    first = datetime.fromtimestamp(min(timestamps), tz=timezone.utc)
    last = datetime.fromtimestamp(max(timestamps), tz=timezone.utc)
    window_start = statement_date.replace(tzinfo=timezone.utc) - timedelta(hours=72)
    window_end = statement_date.replace(tzinfo=timezone.utc)
    in_window = sum(1 for t in timestamps if window_start.timestamp() <= t <= window_end.timestamp())
    return {
        "n_obs": len(timestamps),
        "covered_72h": in_window >= 24,  # at least one bar per 3 hours during the window
        "n_obs_in_72h_window": in_window,
        "first_ts": first.isoformat(),
        "last_ts": last.isoformat(),
        "error": None,
    }


def extract_yes_token(tokens_field, outcomes_field) -> str | None:
    """Pick the YES-side token id from clobTokenIds, aligned with outcomes array."""
    if not tokens_field or not outcomes_field:
        return None
    try:
        tokens = json.loads(tokens_field) if isinstance(tokens_field, str) else tokens_field
        outcomes = json.loads(outcomes_field) if isinstance(outcomes_field, str) else outcomes_field
    except Exception:
        return None
    if not isinstance(tokens, list) or not isinstance(outcomes, list):
        return None
    for i, o in enumerate(outcomes):
        if isinstance(o, str) and o.strip().lower() == "yes" and i < len(tokens):
            return str(tokens[i])
    # fallback: first token
    return str(tokens[0]) if tokens else None


def main():
    today = datetime.utcnow()
    markets_path = OUT_DIR / "fomc_markets_with_meeting.csv"
    if not markets_path.exists():
        print("STEP 3 BLOCKED: fomc_markets_with_meeting.csv missing.")
        print("  Run step 1 + step 2 first.")
        summary = {
            "status": "blocked",
            "blocker": "missing_input_fomc_markets_with_meeting.csv",
        }
        with open(OUT_DIR / "step3_summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        pd.DataFrame(columns=["bucket", "condition_id", "question", "statement_date",
                              "ts", "p"]
                     ).to_csv(OUT_DIR / "price_history_sample.csv", index=False)
        return

    markets = pd.read_csv(markets_path)
    if markets.empty or "meeting_id" not in markets.columns:
        print("STEP 3 BLOCKED: markets-with-meeting file present but empty or missing meeting_id.")
        with open(OUT_DIR / "step3_summary.json", "w") as f:
            json.dump({"status": "blocked", "blocker": "input_empty"}, f, indent=2)
        return

    # Resolve YES token id and join statement_date from calendar
    cal = pd.read_csv(OUT_DIR / "fomc_meeting_calendar.csv")[["meeting_id", "statement_date"]]
    cal["statement_date"] = pd.to_datetime(cal["statement_date"])
    markets["yes_token_id"] = markets.apply(
        lambda r: extract_yes_token(r.get("tokens"), r.get("outcomes")), axis=1
    )
    markets = markets.dropna(subset=["meeting_id"])
    markets = markets.merge(cal, on="meeting_id", how="left")

    # Most-liquid market per meeting
    per_meeting = (
        markets.sort_values("volume", ascending=False)
        .drop_duplicates(subset=["meeting_id"], keep="first")
        .rename(columns={"volume": "total_volume"})
    )

    sample = pick_sample(per_meeting, today)
    print("Sample picks:")
    for s in sample:
        print(f"  [{s['bucket']}] meeting={s.get('meeting_id')} vol={s.get('total_volume')}")

    rows = []
    coverage_summary = {}
    for s in sample:
        if not s.get("yes_token_id"):
            coverage_summary[s["bucket"]] = {"status": "no_market_in_bucket"}
            continue
        h = fetch_history(s["yes_token_id"])
        cov = evaluate_coverage(h, pd.to_datetime(s["statement_date"]))
        coverage_summary[s["bucket"]] = cov
        # Persist hourly bars for later inspection
        if h.get("ok"):
            for p in h["data"].get("history", []):
                rows.append({
                    "bucket": s["bucket"],
                    "condition_id": s["condition_id"],
                    "question": s["question"],
                    "ts": datetime.fromtimestamp(p["t"], tz=timezone.utc).isoformat(),
                    "p": p.get("p"),
                })
        time.sleep(0.5)

    pd.DataFrame(rows).to_csv(OUT_DIR / "price_history_sample.csv", index=False)
    with open(OUT_DIR / "step3_summary.json", "w") as f:
        json.dump({"status": "ok", "coverage": coverage_summary}, f, indent=2, default=str)
    print(f"\nSaved {len(rows)} price-history rows -> price_history_sample.csv")
    print(json.dumps(coverage_summary, indent=2, default=str))


if __name__ == "__main__":
    main()
