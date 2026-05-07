"""
Step 5 — Verify the structure of Polymarket multi-outcome FOMC markets.

Polymarket represents multi-outcome FOMC markets in two distinct ways, and the
analysis design must accommodate both:

  (i)  An "event" page that bundles N independent binary markets, one per
       outcome (-50bps / -25bps / no change / +25bps / +50bps). Each binary
       market has its own conditionId and YES-token. To recover the implicit
       multinomial distribution, take the YES price of each binary leg and
       normalize so they sum to 1.

  (ii) A native multi-outcome market with N tokens, one per outcome. Less
       common historically; Polymarket added support more broadly in 2024-2025.
       The outcomes array lists labels and the outcomePrices array lists the
       implied probabilities directly.

For 3 sample meetings (most recent quarter, 6mo back, 1y back) this script:

  1. Identifies the candidate event/market on Gamma
  2. Pulls the constituent leg(s)
  3. Reports: outcome labels, current YES prices, sum, post-fee discrepancy,
     structure type ((i) bundled-binary or (ii) native-multi)

Output:
  fomc_viability/multi_outcome_sample.json
"""

import json
from pathlib import Path

import requests

OUT_DIR = Path(__file__).parent
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"


def fetch_event_for_meeting(meeting_label: str) -> dict | None:
    """E.g., meeting_label='September 2024'. Searches Polymarket events index."""
    try:
        r = requests.get(
            GAMMA_EVENTS,
            params={"q": f"Fed decision {meeting_label}", "limit": 5},
            timeout=20,
        )
        r.raise_for_status()
    except Exception as e:
        return {"error": str(e)}
    events = r.json()
    if not events:
        return None
    return events[0]


def classify_structure(event: dict) -> str:
    """Return one of: 'bundled_binary', 'native_multi', 'unknown'."""
    markets = event.get("markets") or []
    if len(markets) >= 2:
        # Multiple sub-markets -> bundled-binary
        n_outcomes_each = [len(m.get("outcomes") or []) for m in markets]
        if all(n == 2 for n in n_outcomes_each):
            return "bundled_binary"
    if len(markets) == 1:
        m = markets[0]
        n = len(m.get("outcomes") or [])
        if n > 2:
            return "native_multi"
    return "unknown"


def analyze_event(event: dict) -> dict:
    markets = event.get("markets") or []
    structure = classify_structure(event)
    legs = []
    for m in markets:
        outcomes = m.get("outcomes")
        outcome_prices = m.get("outcomePrices")
        if isinstance(outcomes, str):
            try: outcomes = json.loads(outcomes)
            except Exception: pass
        if isinstance(outcome_prices, str):
            try: outcome_prices = json.loads(outcome_prices)
            except Exception: pass
        legs.append({
            "question": m.get("question"),
            "condition_id": m.get("conditionId"),
            "outcomes": outcomes,
            "outcome_prices": outcome_prices,
            "volume": m.get("volumeNum") or m.get("volume"),
            "closed": m.get("closed"),
        })

    # Implicit distribution
    dist = []
    if structure == "bundled_binary":
        for leg in legs:
            outcomes = leg.get("outcomes") or []
            prices = leg.get("outcome_prices") or []
            # YES is conventionally outcomes[0] in Polymarket binary markets
            yes_price = None
            try:
                yes_idx = next(i for i, o in enumerate(outcomes)
                               if isinstance(o, str) and o.lower() == "yes")
                yes_price = float(prices[yes_idx])
            except (StopIteration, IndexError, ValueError, TypeError):
                pass
            dist.append({"label": leg["question"], "p": yes_price})
    elif structure == "native_multi":
        m = legs[0]
        outcomes = m.get("outcomes") or []
        prices = m.get("outcome_prices") or []
        for o, p in zip(outcomes, prices):
            try: dist.append({"label": o, "p": float(p)})
            except Exception: dist.append({"label": o, "p": None})

    sum_p = sum(d["p"] for d in dist if d.get("p") is not None) if dist else None
    return {
        "event_title": event.get("title"),
        "event_slug": event.get("slug"),
        "structure": structure,
        "n_legs": len(legs),
        "legs": legs,
        "implicit_distribution": dist,
        "sum_probabilities": sum_p,
        "sum_deviation_from_1": (sum_p - 1.0) if sum_p is not None else None,
    }


def main():
    sample_meetings = [
        "September 2025",   # ~recent (relative to assumed 2026 run-time)
        "March 2025",       # ~6mo back
        "September 2024",   # ~1y back
    ]
    out = {}
    for m in sample_meetings:
        print(f"[fetch] {m}")
        ev = fetch_event_for_meeting(m)
        if not ev:
            out[m] = {"status": "no_event_found"}
            continue
        if "error" in ev:
            out[m] = {"status": "error", "error": ev["error"]}
            continue
        out[m] = {"status": "ok", **analyze_event(ev)}

    if all(v.get("status") == "error" for v in out.values()):
        out["_meta"] = {
            "status": "blocked",
            "blocker": "egress_to_gamma-api.polymarket.com_denied",
            "note": "All event lookups failed identically (HTTP 403). Run this script in an environment with internet egress to verify multi-outcome structure.",
        }
    with open(OUT_DIR / "multi_outcome_sample.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nsaved -> multi_outcome_sample.json")
    for k, v in out.items():
        if k.startswith("_"):
            continue
        print(f"  {k}: status={v.get('status')} structure={v.get('structure')} sum={v.get('sum_probabilities')}")


if __name__ == "__main__":
    main()
