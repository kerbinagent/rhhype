#!/usr/bin/env python3
"""Exploratory fixed-size, four-taker public-quote replay; never fill P&L."""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_maker_capture import (  # noqa: E402
    SECOND, archive_load, iso, last_quote, require_contiguous_capture, sha256_file,
)
from scripts.analyze_maker_equity import (  # noqa: E402
    eligible_leg, fees_from_frozen, funding_boundary, plan_markets,
)

METHOD = ROOT / "reports/size-sensitivity-v1/frozen-method.md"
EXPECTED_METHOD_SHA256 = "378498c8187cfd806eb46c056d6165925fc35543797e1e82bc1c9021ca92e643"
EXPECTED_ARCHIVE_GZIP_SHA256 = "3a1ffe9e3578899df800bf8fceec7beda8fc82b136a6c00edc64a20a8316f775"
EXPECTED_ARCHIVE_MANIFEST_SHA256 = "a3f83c319f5e71938ffa9ae6ec170eb48b3024123147e554ee4c20296cade898"
FEE_INPUTS = ROOT / "reports/maker-equity-v2/fee-inputs.json"
SIZES = (100, 250, 1000)
ROUTES = (("hyperliquid", "lighter"), ("lighter", "hyperliquid"),
          ("hyperliquid", "rh_lighter"), ("rh_lighter", "hyperliquid"))
BASE_DELAY_NS = 100_000_000
LIGHTER_PROCESSING_NS = 300_000_000
HOLD_NS = 5 * SECOND
HARD_NS = 10 * SECOND
YEAR_SECONDS = 365 * 86400


def due_time(start_ns, venue):
    return start_ns + BASE_DELAY_NS + (LIGHTER_PROCESSING_NS if venue != "hyperliquid" else 0)


def fixed_qty(asset, target_usd, buy_ask, buy_market, sell_bid, sell_market):
    """Floor only once on the shared lot; both anchor minimums use own prices."""
    step = Decimal("0.001") if asset == "NVDA" else Decimal("0.01")
    if (max(Decimal(str(buy_market["step"])), Decimal(str(sell_market["step"]))) != step
            or any(step % Decimal(str(m["step"])) != 0 for m in (buy_market, sell_market))):
        raise ValueError(f"{asset}: frozen common lot changed")
    q = (Decimal(target_usd) / Decimal(str(buy_ask)) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    if q <= 0 or not eligible_leg(q, buy_ask, buy_market) or not eligible_leg(q, sell_bid, sell_market):
        return None
    return float(q)


def first_leg(series, times, due_ns, hard_ns, capture_end_ns, side, qty, market):
    """First individually eligible quote; a shallow first quote cannot be replaced."""
    import bisect
    if due_ns > hard_ns:
        return None, "deadline_before_leg"
    stop = min(due_ns + SECOND, hard_ns)
    i = bisect.bisect_left(times, due_ns)
    while i < len(series) and series[i]["receipt_ns"] <= stop:
        q = series[i]
        i += 1
        if q["source_ns"] < due_ns or not 0 <= q["receipt_ns"] - q["source_ns"] <= 2 * SECOND:
            continue
        px, depth = (q["ask"], q["ask_size"]) if side == "buy" else (q["bid"], q["bid_size"])
        if depth + 1e-12 < qty:
            return q, "shallow_first_quote"
        if not eligible_leg(qty, px, market):
            return q, "minimum_or_maximum_first_quote"
        return q, "eligible"
    return None, "terminal_capture" if stop > capture_end_ns else "missing_first_quote"


def cashflow(qty, buy_entry, sell_entry, buy_exit, sell_exit, buy_venue, sell_venue, fee_rates):
    prices = (buy_entry["ask"], sell_entry["bid"], buy_exit["bid"], sell_exit["ask"])
    fees = [qty * price * fee_rates[venue]["taker"] / 10_000
            for price, venue in zip(prices, (buy_venue, sell_venue, buy_venue, sell_venue))]
    gross = qty * ((prices[2] - prices[0]) + (prices[1] - prices[3]))
    reserve = max(qty * prices[0], qty * prices[1]) * 5 / 10_000
    capital = .05 / YEAR_SECONDS * qty * (
        prices[0] * (buy_exit["receipt_ns"] - buy_entry["receipt_ns"]) / SECOND +
        prices[1] * (sell_exit["receipt_ns"] - sell_entry["receipt_ns"]) / SECOND)
    basis = qty * prices[0]
    return {"buy_entry_px": prices[0], "sell_entry_px": prices[1],
            "buy_exit_px": prices[2], "sell_exit_px": prices[3],
            "buy_entry_notional": basis, "sell_entry_notional": qty * prices[1],
            "gross_usd": gross, "four_fee_usd": sum(fees), "fee_legs_usd": fees,
            "reserve_usd": reserve, "capital_usd": capital,
            "after_four_fee_bps": (gross - sum(fees)) / basis * 10_000,
            "after_fee_reserve_capital_bps": (gross - sum(fees) - reserve - capital) / basis * 10_000,
            "entry_receipt_skew_s": abs(buy_entry["receipt_ns"] - sell_entry["receipt_ns"]) / SECOND,
            "entry_source_skew_s": abs(buy_entry["source_ns"] - sell_entry["source_ns"]) / SECOND,
            "exit_receipt_skew_s": abs(buy_exit["receipt_ns"] - sell_exit["receipt_ns"]) / SECOND,
            "exit_source_skew_s": abs(buy_exit["source_ns"] - sell_exit["source_ns"]) / SECOND}


def analyze(data, markets, fees):
    require_contiguous_capture(data)
    selected = data["manifest"]["selected_markets"]
    if any(set(selected[v]) != {"NVDA", "XAG"} for v in ("hyperliquid", "lighter", "rh_lighter")):
        raise ValueError("capture must be the frozen NVDA/XAG three-venue archive")
    start = int(datetime.fromisoformat(data["manifest"]["started_utc"]).timestamp() * SECOND)
    end = int(datetime.fromisoformat(data["manifest"]["ended_utc"]).timestamp() * SECOND)
    first = ((start + 3 * SECOND + 5 * SECOND - 1) // (5 * SECOND)) * 5 * SECOND
    anchors = list(range(first, end - 5 * SECOND, 5 * SECOND))
    qs = data["quotes"]
    times = {k: [q["receipt_ns"] for q in v] for k, v in qs.items()}
    cases = []
    for asset in ("NVDA", "XAG"):
        for buy_venue, sell_venue in ROUTES:
            bk, sk = (buy_venue, asset), (sell_venue, asset)
            bq, sq = qs[bk], qs[sk]
            bt, st = times.get(bk, []), times.get(sk, [])
            for target in SIZES:
                for anchor in anchors:
                    row = {"asset": asset, "buy": buy_venue, "sell": sell_venue,
                           "target_usd": target, "anchor_utc": iso(anchor), "status": None}
                    cases.append(row)
                    b, s = last_quote(bq, bt, anchor), last_quote(sq, st, anchor)
                    if b is None or s is None:
                        row["status"] = "stale_decision"
                        row["buy_decision_fresh"] = b is not None
                        row["sell_decision_fresh"] = s is not None
                        continue
                    if (abs(b["source_ns"] - s["source_ns"]) > SECOND // 2
                            or abs(b["receipt_ns"] - s["receipt_ns"]) > SECOND // 2):
                        row["status"] = "decision_skew"
                        continue
                    qty = fixed_qty(asset, target, b["ask"], markets[asset][buy_venue],
                                    s["bid"], markets[asset][sell_venue])
                    if qty is None:
                        row["status"] = "anchor_minimum_or_lot"
                        continue
                    row.update(qty=qty, anchor_buy_px=b["ask"], anchor_sell_px=s["bid"],
                               anchor_buy_notional=qty * b["ask"],
                               anchor_sell_notional=qty * s["bid"])
                    hard = anchor + HARD_NS
                    b_due, s_due = due_time(anchor, buy_venue), due_time(anchor, sell_venue)
                    be, bs = first_leg(bq, bt, b_due, hard, end, "buy", qty, markets[asset][buy_venue])
                    se, ss = first_leg(sq, st, s_due, hard, end, "sell", qty, markets[asset][sell_venue])
                    row.update(buy_entry_status=bs, sell_entry_status=ss,
                               buy_entry_due_utc=iso(b_due), sell_entry_due_utc=iso(s_due))
                    for prefix, q in (("buy_entry", be), ("sell_entry", se)):
                        if q is not None:
                            row[prefix + "_receipt_utc"] = iso(q["receipt_ns"])
                            row[prefix + "_source_utc"] = iso(q["source_ns"])
                            row[prefix + "_top_px"] = q["ask"] if prefix.startswith("buy") else q["bid"]
                            row[prefix + "_top_size"] = q["ask_size"] if prefix.startswith("buy") else q["bid_size"]
                    if bs != "eligible" or ss != "eligible":
                        row["status"] = ("one_entry_leg_unresolved" if (bs == "eligible") != (ss == "eligible")
                                         else "both_entry_legs_unresolved")
                        continue
                    later_entry = max(be["receipt_ns"], se["receipt_ns"])
                    objective = later_entry + HOLD_NS
                    be_due, se_due = due_time(objective, buy_venue), due_time(objective, sell_venue)
                    bx, bxs = first_leg(bq, bt, be_due, hard, end, "sell", qty, markets[asset][buy_venue])
                    sx, sxs = first_leg(sq, st, se_due, hard, end, "buy", qty, markets[asset][sell_venue])
                    row.update(buy_exit_status=bxs, sell_exit_status=sxs,
                               buy_exit_due_utc=iso(be_due), sell_exit_due_utc=iso(se_due),
                               hard_deadline_utc=iso(hard))
                    for prefix, q in (("buy_exit", bx), ("sell_exit", sx)):
                        if q is not None:
                            row[prefix + "_receipt_utc"] = iso(q["receipt_ns"])
                            row[prefix + "_source_utc"] = iso(q["source_ns"])
                            row[prefix + "_top_px"] = q["bid"] if prefix.startswith("buy") else q["ask"]
                            row[prefix + "_top_size"] = q["bid_size"] if prefix.startswith("buy") else q["ask_size"]
                    if bxs != "eligible" or sxs != "eligible":
                        row["status"] = ("one_exit_leg_unresolved" if (bxs == "eligible") != (sxs == "eligible")
                                         else "both_exit_legs_unresolved")
                        continue
                    if funding_boundary(min(be["receipt_ns"], se["receipt_ns"]),
                                        max(bx["receipt_ns"], sx["receipt_ns"])):
                        row["status"] = "funding_boundary_unresolved"
                        continue
                    row.update(cashflow(qty, be, se, bx, sx, buy_venue, sell_venue, fees[asset]))
                    row["status"] = "complete_conditional_quote_path"
    return cases


def summarize(cases):
    groups = defaultdict(list)
    for row in cases:
        groups[(row["target_usd"], row["asset"], row["buy"], row["sell"])].append(row)
    cohort = []
    for (target, asset, buy, sell), rows in sorted(groups.items()):
        complete = [r for r in rows if r["status"] == "complete_conditional_quote_path"]
        counts = Counter(r["status"] for r in rows)
        for leg in ("buy_entry_status", "sell_entry_status", "buy_exit_status", "sell_exit_status"):
            counts.update(f"{leg}:{r[leg]}" for r in rows if leg in r)
        cohort.append({"target_usd": target, "asset": asset, "buy": buy, "sell": sell,
                       "anchors": len(rows), "status_counts": dict(counts),
                       "complete": len(complete),
                       "after_fee_reserve_capital_bps": [r["after_fee_reserve_capital_bps"] for r in complete]})
    by_key = defaultdict(dict)
    for r in cases:
        by_key[(r["asset"], r["buy"], r["sell"], r["anchor_utc"])][r["target_usd"]] = r
    matched = [(key, group) for key, group in by_key.items()
               if all(group[n]["status"] == "complete_conditional_quote_path" for n in SIZES)]
    intersections = {str(n): [group[n]["after_fee_reserve_capital_bps"] for _, group in matched] for n in SIZES}
    return {"cohorts": cohort, "total_candidates": len(cases),
            "status_counts_by_size": {str(n): dict(Counter(r["status"] for r in cases if r["target_usd"] == n))
                                      for n in SIZES},
            "matched_complete_anchor_count": len(matched),
            "matched_complete_keys": [dict(zip(("asset", "buy", "sell", "anchor_utc"), key))
                                      for key, _ in matched],
            "matched_complete_bps_by_size": intersections}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if sha256_file(METHOD) != EXPECTED_METHOD_SHA256:
        raise RuntimeError("frozen exploratory size method hash changed")
    data = archive_load(args.capture)
    if not all(data["integrity"][k] for k in
               ("record_count_matches", "compressed_size_matches", "under_total_cap", "plan_hash_matches_current")):
        raise RuntimeError("archive integrity failed")
    if (data["integrity"]["gzip_sha256"] != EXPECTED_ARCHIVE_GZIP_SHA256
            or data["integrity"]["manifest_sha256"] != EXPECTED_ARCHIVE_MANIFEST_SHA256):
        raise RuntimeError("this post hoc method is restricted to its frozen source archive")
    fees = fees_from_frozen(FEE_INPUTS)
    markets = plan_markets(Path(data["manifest"]["market_plan"]), data["manifest"]["selected_markets"])
    cases = analyze(data, markets, fees)
    if len(cases) != 1992:
        raise RuntimeError("unexpected anchor or cohort count for frozen archive")
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    report = summarize(cases)
    report.update({"design": "post hoc exploratory all-taker size/depth sensitivity on prior NVDA/XAG archive",
                   "no_fill_or_profit_claim": True,
                   "capture": str(args.capture), "capture_integrity": data["integrity"],
                   "method": str(METHOD), "method_sha256": EXPECTED_METHOD_SHA256,
                   "analyzer_sha256": sha256_file(Path(__file__)),
                   "archive_loader_sha256": sha256_file(ROOT / "scripts/analyze_maker_capture.py"),
                   "market_plan_sha256": data["manifest"]["market_plan_sha256"],
                   "fee_inputs_sha256": sha256_file(FEE_INPUTS),
                   "funding": "hour-crossing paths unresolved; no funding payment imputed",
                   "RH_parity": "conditional USDG/USDC parity quote arithmetic; no conversion execution",
                   "capital": "illustrative 5% annual on 100% of each own entry notional for its quote interval"})
    (out / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (out / "cases.json").write_text(json.dumps(cases, separators=(",", ":"), allow_nan=False) + "\n")
    fields = list(dict.fromkeys(k for row in cases for k in row))
    with (out / "cases.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(cases)
    print(f"{out}: {len(cases)} candidates; {sum(r['status']=='complete_conditional_quote_path' for r in cases)} complete quote paths")


if __name__ == "__main__":
    main()
