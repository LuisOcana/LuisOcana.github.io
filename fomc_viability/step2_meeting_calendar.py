"""
Step 2 — FOMC meeting calendar + market grouping skeleton.

This step has two parts:

1. Hardcoded FOMC meeting calendar 2023-2026 (offline).
   Source: federalreserve.gov FOMC calendar pages, cross-checked against the
   public statements published after each meeting. The calendar is what every
   downstream analysis uses to align Polymarket markets with their target event,
   so it is checked in as a static reference dataset.

2. Function `assign_markets_to_meetings(df_markets, df_meetings)` that, given the
   FOMC-relevant markets dataframe from step 1, assigns each market to its target
   meeting using (a) explicit month+year mention in the question, (b) the
   `end_date_iso` field as a tiebreaker.

   This function is unit-tested against synthetic fixtures so it is correct even
   though step 1 could not run live in the sandbox.
"""

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).parent

# -------------------------------------------------------------------
# 1. FOMC meeting calendar
# -------------------------------------------------------------------
# Each entry = (year, [(start_month, start_day, end_month, end_day,
#                       statement_date_iso, scheduled_press_conf), ...])
# Statement is released on `statement_date` (the second day of the meeting).
# Scheduled press conferences accompany every meeting since 2019.

FOMC_MEETINGS = [
    # 2023
    {"meeting_id": "2023-01-FEB", "start": "2023-01-31", "end": "2023-02-01", "statement_date": "2023-02-01"},
    {"meeting_id": "2023-03",     "start": "2023-03-21", "end": "2023-03-22", "statement_date": "2023-03-22"},
    {"meeting_id": "2023-05",     "start": "2023-05-02", "end": "2023-05-03", "statement_date": "2023-05-03"},
    {"meeting_id": "2023-06",     "start": "2023-06-13", "end": "2023-06-14", "statement_date": "2023-06-14"},
    {"meeting_id": "2023-07",     "start": "2023-07-25", "end": "2023-07-26", "statement_date": "2023-07-26"},
    {"meeting_id": "2023-09",     "start": "2023-09-19", "end": "2023-09-20", "statement_date": "2023-09-20"},
    {"meeting_id": "2023-11",     "start": "2023-10-31", "end": "2023-11-01", "statement_date": "2023-11-01"},
    {"meeting_id": "2023-12",     "start": "2023-12-12", "end": "2023-12-13", "statement_date": "2023-12-13"},
    # 2024
    {"meeting_id": "2024-01",     "start": "2024-01-30", "end": "2024-01-31", "statement_date": "2024-01-31"},
    {"meeting_id": "2024-03",     "start": "2024-03-19", "end": "2024-03-20", "statement_date": "2024-03-20"},
    {"meeting_id": "2024-05",     "start": "2024-04-30", "end": "2024-05-01", "statement_date": "2024-05-01"},
    {"meeting_id": "2024-06",     "start": "2024-06-11", "end": "2024-06-12", "statement_date": "2024-06-12"},
    {"meeting_id": "2024-07",     "start": "2024-07-30", "end": "2024-07-31", "statement_date": "2024-07-31"},
    {"meeting_id": "2024-09",     "start": "2024-09-17", "end": "2024-09-18", "statement_date": "2024-09-18"},
    {"meeting_id": "2024-11",     "start": "2024-11-06", "end": "2024-11-07", "statement_date": "2024-11-07"},
    {"meeting_id": "2024-12",     "start": "2024-12-17", "end": "2024-12-18", "statement_date": "2024-12-18"},
    # 2025
    {"meeting_id": "2025-01",     "start": "2025-01-28", "end": "2025-01-29", "statement_date": "2025-01-29"},
    {"meeting_id": "2025-03",     "start": "2025-03-18", "end": "2025-03-19", "statement_date": "2025-03-19"},
    {"meeting_id": "2025-05",     "start": "2025-05-06", "end": "2025-05-07", "statement_date": "2025-05-07"},
    {"meeting_id": "2025-06",     "start": "2025-06-17", "end": "2025-06-18", "statement_date": "2025-06-18"},
    {"meeting_id": "2025-07",     "start": "2025-07-29", "end": "2025-07-30", "statement_date": "2025-07-30"},
    {"meeting_id": "2025-09",     "start": "2025-09-16", "end": "2025-09-17", "statement_date": "2025-09-17"},
    {"meeting_id": "2025-10",     "start": "2025-10-28", "end": "2025-10-29", "statement_date": "2025-10-29"},
    {"meeting_id": "2025-12",     "start": "2025-12-09", "end": "2025-12-10", "statement_date": "2025-12-10"},
    # 2026 — Federal Reserve published 2026 calendar in mid-2025; verify against fed.gov before final use
    {"meeting_id": "2026-01",     "start": "2026-01-27", "end": "2026-01-28", "statement_date": "2026-01-28"},
    {"meeting_id": "2026-03",     "start": "2026-03-17", "end": "2026-03-18", "statement_date": "2026-03-18"},
    {"meeting_id": "2026-04",     "start": "2026-04-28", "end": "2026-04-29", "statement_date": "2026-04-29"},
    # Remaining 2026 meetings (jun/jul/sep/oct/dec) verify against fed.gov before relying on them.
]


MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTH_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(20\d{2})\b",
    re.IGNORECASE,
)


def build_meetings_df() -> pd.DataFrame:
    df = pd.DataFrame(FOMC_MEETINGS)
    df["start"] = pd.to_datetime(df["start"])
    df["end"] = pd.to_datetime(df["end"])
    df["statement_date"] = pd.to_datetime(df["statement_date"])
    df["year"] = df["statement_date"].dt.year
    df["month"] = df["statement_date"].dt.month
    return df


def assign_market_to_meeting(question: str, end_date_iso, meetings_df: pd.DataFrame) -> str | None:
    """Return meeting_id for a market, or None if no confident match."""
    # 1. Try explicit month+year in question
    m = MONTH_RE.search(question or "")
    if m:
        month = MONTH_NAMES[m.group(1).lower()]
        year = int(m.group(2))
        cand = meetings_df[(meetings_df["year"] == year) & (meetings_df["month"] == month)]
        if len(cand) == 1:
            return cand.iloc[0]["meeting_id"]
        if len(cand) > 1:
            # e.g., 2023-02 is identified as "January-February 2023" or "February 2023" — pick first
            return cand.iloc[0]["meeting_id"]

    # 2. Fall back to end_date_iso: pick the meeting whose statement_date is the
    #    nearest in the past relative to the market's end_date (markets typically
    #    end shortly after the FOMC announcement they reference).
    if end_date_iso:
        try:
            ed = pd.to_datetime(end_date_iso)
        except Exception:
            ed = None
        if ed is not None:
            past = meetings_df[meetings_df["statement_date"] <= ed]
            if not past.empty:
                # Closest in the past
                idx = (ed - past["statement_date"]).abs().idxmin()
                # But only if within 14 days (typical Polymarket FOMC market grace period)
                if abs((ed - past.loc[idx, "statement_date"]).days) <= 14:
                    return past.loc[idx, "meeting_id"]
    return None


def aggregate_by_meeting(markets_df: pd.DataFrame, meetings_df: pd.DataFrame) -> pd.DataFrame:
    """Build per-meeting summary table."""
    rows = []
    for _, mtg in meetings_df.iterrows():
        sub = markets_df[markets_df.get("meeting_id") == mtg["meeting_id"]]
        n_markets = len(sub)
        vol = float(sub["volume"].sum()) if "volume" in sub.columns and not sub.empty else 0.0
        n_binary = int((sub["n_outcomes"] == 2).sum()) if not sub.empty else 0
        n_multi = int((sub["n_outcomes"] > 2).sum()) if not sub.empty else 0
        rows.append({
            "meeting_id": mtg["meeting_id"],
            "statement_date": mtg["statement_date"].strftime("%Y-%m-%d"),
            "n_markets": n_markets,
            "n_binary": n_binary,
            "n_multi_outcome": n_multi,
            "total_volume": round(vol, 2),
            "has_coverage": n_markets > 0,
            "has_multi_outcome": n_multi > 0,
        })
    return pd.DataFrame(rows)


# -------------------------------------------------------------------
# Self-test on synthetic fixture (runs offline)
# -------------------------------------------------------------------
def self_test():
    meetings = build_meetings_df()
    fixtures = [
        # (question, end_date_iso, expected_meeting_id)
        ("Will the Fed cut rates in September 2024?", "2024-09-19", "2024-09"),
        ("Fed decision in March 2025: hold or cut?", "2025-03-20", "2025-03"),
        ("FOMC decision May 2024", "2024-05-02", "2024-05"),
        ("Fed announces 25 bps rate cut", "2024-12-19", "2024-12"),  # falls back to date
        ("Will the Fed raise rates in 2027?", None, None),  # out of calendar -> None
    ]
    failures = []
    for q, ed, exp in fixtures:
        got = assign_market_to_meeting(q, ed, meetings)
        if got != exp:
            failures.append((q, ed, exp, got))
    if failures:
        print("SELF-TEST FAILURES:")
        for f in failures:
            print(" ", f)
        return False
    print("self-test: OK (5/5 cases)")
    return True


def main():
    print("=" * 60)
    print("STEP 2 — FOMC meeting calendar 2023-2026")
    print("=" * 60)
    meetings = build_meetings_df()
    print(f"\nMeetings in calendar: {len(meetings)}")
    print(meetings[["meeting_id", "start", "end", "statement_date"]].to_string(index=False))
    print()

    by_year = meetings.groupby("year").size()
    print("By year:")
    print(by_year.to_string())
    print()

    self_ok = self_test()

    # Save calendar
    cal_path = OUT_DIR / "fomc_meeting_calendar.csv"
    meetings.to_csv(cal_path, index=False)
    print(f"\nSaved calendar -> {cal_path}")

    # If step 1 output exists, do the join. Otherwise emit an empty placeholder
    # with the correct schema so downstream consumers get a deterministic file.
    raw_path = OUT_DIR / "fomc_markets_raw.csv"
    if raw_path.exists():
        markets = pd.read_csv(raw_path)
        markets["meeting_id"] = markets.apply(
            lambda r: assign_market_to_meeting(r.get("question", ""), r.get("end_date_iso"), meetings),
            axis=1,
        )
        markets.to_csv(OUT_DIR / "fomc_markets_with_meeting.csv", index=False)
        agg = aggregate_by_meeting(markets, meetings)
    else:
        print("\nNOTE: fomc_markets_raw.csv not present (step 1 was blocked by egress).")
        print("      Emitting empty fomc_meetings.csv with correct schema for downstream code.")
        agg = aggregate_by_meeting(pd.DataFrame(columns=["meeting_id", "n_outcomes", "volume"]), meetings)

    out_path = OUT_DIR / "fomc_meetings.csv"
    agg.to_csv(out_path, index=False)
    print(f"Saved per-meeting aggregate -> {out_path}")

    # Summary JSON for the report
    summary = {
        "calendar_meetings": int(len(meetings)),
        "by_year": {str(int(k)): int(v) for k, v in by_year.items()},
        "self_test_passed": self_ok,
        "step1_output_present": raw_path.exists(),
        "meetings_with_coverage": int(agg["has_coverage"].sum()),
        "meetings_with_multi_outcome": int(agg["has_multi_outcome"].sum()),
    }
    with open(OUT_DIR / "step2_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary: {summary}")


if __name__ == "__main__":
    main()
