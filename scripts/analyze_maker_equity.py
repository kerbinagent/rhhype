#!/usr/bin/env python3
"""Offline NVDA/XAG public-book maker shadow replay; never observed fills."""

import argparse
import bisect
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_maker_capture import (  # noqa: E402
    SECOND, archive_load, iso, last_quote, require_contiguous_capture, sha256_file,
)
from scripts.analyze_maker_roundtrip import first_full_flow  # noqa: E402

ASSETS = ("NVDA", "XAG")
ROUTES = (("hyperliquid", "lighter"), ("lighter", "hyperliquid"),
          ("hyperliquid", "rh_lighter"), ("rh_lighter", "hyperliquid"))
LIGHTER = {"lighter", "rh_lighter"}
BASE_DELAY_NS = 100_000_000
STANDARD_TAKER_NS = 300_000_000
EXIT_HOLD_NS = 5 * SECOND
HARD_FLOW_DEADLINE_NS = 10 * SECOND
SHARED_LOADER_BASELINE_SHA256 = "a224448f09f60d9973bed981b295d56af8a67ae2e50bf033355eab8c76c7c02e"


def fees_from_frozen(path):
    """Validate public, tier-0 inputs; never infer a wallet's authenticated rate."""
    document = json.loads(path.read_text())
    body = document["markets"]
    if document.get("source_url") != "https://api.hyperliquid.xyz/info" or not document.get("response_sha256"):
        raise ValueError("fee input missing public API provenance")
    if set(body) != set(ASSETS):
        raise ValueError("fee inputs must contain NVDA and XAG only")
    result = {}
    for asset, row in body.items():
        if row.get("coin") != ("xyz:NVDA" if asset == "NVDA" else "xyz:SILVER"):
            raise ValueError(f"{asset}: unexpected HIP-3 coin")
        if (Decimal(str(row["deployerFeeScale"])) != 1
                or row["growthMode"] != "enabled" or row["collateralToken"] != 0
                or row["isAlignedQuoteToken"] is not False):
            raise ValueError(f"{asset}: sampled HIP-3 fee conditions changed; review required")
        if (Decimal(str(row["baseMakerBps"])) != Decimal("1.5")
                or Decimal(str(row["baseTakerBps"])) != Decimal("4.5")
                or Decimal(str(row["lighterStandardMakerBps"])) != 0
                or Decimal(str(row["lighterStandardTakerBps"])) != 0):
            raise ValueError(f"{asset}: fee baseline differs from frozen policy")
        scale = Decimal("2") * Decimal("0.1")
        result[asset] = {"hyperliquid": {"maker": float(Decimal("1.5") * scale),
                                         "taker": float(Decimal("4.5") * scale)},
                         "lighter": {"maker": 0.0, "taker": 0.0},
                         "rh_lighter": {"maker": 0.0, "taker": 0.0}}
    return result


def plan_markets(path, selected):
    """Recover frozen lot/minimums for exactly the captured market IDs."""
    plan = json.loads(path.read_text())
    result = {}
    for asset in ASSETS:
        result[asset] = {}
        for row in plan["pairs"]:
            if row.get("asset") != asset:
                continue
            expected_unit = "one underlying share" if asset == "NVDA" else "one troy ounce silver"
            if (row.get("contract_unit") != expected_unit
                    or Decimal(str(row.get("displayed_unit_multiplier"))) != 1
                    or len(row.get("unit_evidence", [])) < 2):
                raise ValueError(f"{asset}: unverified contract unit")
            hl, other = row["hl"], row["other"]
            if str(hl["market"]) != selected["hyperliquid"][asset]:
                raise ValueError(f"{asset}: HL market ID does not match capture")
            if hl.get("collateral") != "USDC" or hl.get("fee_bps") != 0.9:
                raise ValueError(f"{asset}: changed HL collateral or public taker fee")
            venue = other["venue"]
            if venue not in LIGHTER or str(other["market"]) != selected[venue][asset]:
                continue
            if other.get("collateral") != ("USDC" if venue == "lighter" else "USDG"):
                raise ValueError(f"{asset}: changed Lighter collateral")
            result[asset]["hyperliquid"] = hl
            result[asset][venue] = other
        if set(result[asset]) != {"hyperliquid", "lighter", "rh_lighter"}:
            raise ValueError(f"{asset}: frozen metadata lacks all three venues")
    return result


def common_qty(asset, maker, hedge, maker_price):
    steps = [Decimal(str(maker["step"])), Decimal(str(hedge["step"]))]
    if any(step <= 0 for step in steps):
        raise ValueError("lot step must be positive")
    step = max(steps)
    if any(step % other != 0 for other in steps):
        raise ValueError("lot grids are not nested; explicit common lattice required")
    expected = Decimal("0.001") if asset == "NVDA" else Decimal("0.01")
    if step != expected:
        raise ValueError(f"{asset}: common lot changed from frozen policy")
    price = Decimal(str(maker_price))
    qty = (Decimal("1000") / price / step).to_integral_value(rounding=ROUND_FLOOR) * step
    if qty <= 0:
        return None
    if not eligible_leg(qty, price, maker):
        return None
    if qty < Decimal(str(hedge["min_qty"])):
        return None
    maximum = hedge.get("max_qty")
    if maximum is not None and qty > Decimal(str(maximum)):
        return None
    return float(qty)


def eligible_leg(qty, price, market):
    """Apply frozen lot, minimum, and any finite maximum to the original q."""
    q, p = Decimal(str(qty)), Decimal(str(price))
    if q <= 0 or p <= 0 or q < Decimal(str(market["min_qty"])):
        return False
    if q * p < Decimal(str(market["min_notional"])):
        return False
    maximum = market.get("max_qty")
    return maximum is None or q <= Decimal(str(maximum))


def decision_quote(maker, hedge, side, asset, meta, fees):
    p = maker["bid"] if side == "buy" else maker["ask"]
    qty = common_qty(asset, meta[maker["venue"]], meta[hedge["venue"]], p)
    if qty is None:
        return None
    hp = hedge["bid"] if side == "buy" else hedge["ask"]
    hs = hedge["bid_size"] if side == "buy" else hedge["ask_size"]
    if hs + 1e-12 < qty or not eligible_leg(qty, hp, meta[hedge["venue"]]):
        return None
    gross = (hp - p if side == "buy" else p - hp) / p * 10_000
    maker_fee = fees[maker["venue"]]["maker"]
    hedge_fee = fees[hedge["venue"]]["taker"] * hp / p
    exit_allowance = fees[maker["venue"]]["taker"] + fees[hedge["venue"]]["taker"]
    return {"price": p, "qty": qty, "gross_opening_bps": gross,
            "after_four_fee_allowance_bps": gross - maker_fee - hedge_fee - exit_allowance}


def hedge_due(flow_receipt_ns, hedge_venue):
    return flow_receipt_ns + BASE_DELAY_NS + (STANDARD_TAKER_NS if hedge_venue in LIGHTER else 0)


def first_activation_quote(series, times, due_ns):
    """First post-due source-and-receipt quote; no older maker queue reuse."""
    i = bisect.bisect_left(times, due_ns)
    while i < len(series) and series[i]["receipt_ns"] <= due_ns + SECOND:
        quote = series[i]
        i += 1
        if quote["source_ns"] >= due_ns and 0 <= quote["receipt_ns"] - quote["source_ns"] <= 2 * SECOND:
            return quote
    return None


def first_delayed_hedge(series, times, due_ns, flow_source_ns, hard_deadline_ns, side, qty, market):
    if due_ns > hard_deadline_ns:
        return None, "deadline_before_hedge"
    i = bisect.bisect_left(times, due_ns)
    limit = min(due_ns + SECOND, hard_deadline_ns)
    while i < len(series) and series[i]["receipt_ns"] <= limit:
        quote = series[i]
        i += 1
        if quote["source_ns"] < due_ns or quote["source_ns"] < flow_source_ns:
            continue
        if not 0 <= quote["receipt_ns"] - quote["source_ns"] <= 2 * SECOND:
            continue
        size = quote["bid_size"] if side == "buy" else quote["ask_size"]
        price = quote["bid"] if side == "buy" else quote["ask"]
        if size + 1e-12 < qty:
            return None, "insufficient_hedge_top_depth"
        if not eligible_leg(qty, price, market):
            return None, "hedge_minimum_or_maximum"
        return quote, "hedge_found"
    return None, "missing_due_hedge_quote"


def first_delayed_exit(maker_series, hedge_series, maker_venue, hedge_venue,
                       hedge_receipt_ns, hard_deadline_ns, side, qty, maker_market, hedge_market):
    objective = hedge_receipt_ns + EXIT_HOLD_NS
    due = {"maker": objective + BASE_DELAY_NS + (STANDARD_TAKER_NS if maker_venue in LIGHTER else 0),
           "hedge": objective + BASE_DELAY_NS + (STANDARD_TAKER_NS if hedge_venue in LIGHTER else 0)}
    if any(t > hard_deadline_ns for t in due.values()):
        return None, "deadline_before_exit", due
    events = []
    for label, series in (("maker", maker_series), ("hedge", hedge_series)):
        times = [q["receipt_ns"] for q in series]
        i = bisect.bisect_left(times, due[label])
        limit = min(due[label] + SECOND, hard_deadline_ns)
        while i < len(series) and series[i]["receipt_ns"] <= limit:
            q = series[i]
            i += 1
            if q["source_ns"] >= due[label] and 0 <= q["receipt_ns"] - q["source_ns"] <= 2 * SECOND:
                events.append((q["receipt_ns"], label, q))
    events.sort(key=lambda e: e[0])
    latest = {}
    for observed, label, q in events:
        latest[label] = q
        if set(latest) != {"maker", "hedge"}:
            continue
        m, h = latest["maker"], latest["hedge"]
        if (abs(m["source_ns"] - h["source_ns"]) > SECOND // 2
                or abs(m["receipt_ns"] - h["receipt_ns"]) > SECOND // 2):
            continue
        ms = m["bid_size"] if side == "buy" else m["ask_size"]
        hs = h["ask_size"] if side == "buy" else h["bid_size"]
        if ms + 1e-12 < qty or hs + 1e-12 < qty:
            return None, "insufficient_exit_top_depth", due
        mp = m["bid"] if side == "buy" else m["ask"]
        hp = h["ask"] if side == "buy" else h["bid"]
        if not eligible_leg(qty, mp, maker_market) or not eligible_leg(qty, hp, hedge_market):
            return None, "exit_minimum_or_maximum", due
        return (m, h, observed), "exit_found", due
    labels = {label for _, label, _ in events}
    if labels != {"maker", "hedge"}:
        return None, "missing_due_exit_side", due
    return None, "exit_skew_or_unsynchronized", due


def funding_boundary(start_ns, end_ns):
    hour = 3600 * SECOND
    return start_ns % hour == 0 or (start_ns // hour + 1) * hour <= end_ns


def capture_truncates_window(due_ns, hard_deadline_ns, capture_end_ns):
    return min(due_ns + SECOND, hard_deadline_ns) > capture_end_ns


def cashflow(side, price, hedge, maker_exit, hedge_exit, qty, maker_venue, hedge_venue, fees):
    hp = hedge["bid"] if side == "buy" else hedge["ask"]
    mp2 = maker_exit["bid"] if side == "buy" else maker_exit["ask"]
    hp2 = hedge_exit["ask"] if side == "buy" else hedge_exit["bid"]
    gross = qty * ((mp2 - price) + (hp - hp2) if side == "buy" else
                   (price - mp2) + (hp2 - hp))
    legs = ((price, maker_venue, "maker"), (hp, hedge_venue, "taker"),
            (mp2, maker_venue, "taker"), (hp2, hedge_venue, "taker"))
    own_fees = [qty * p * fees[v][role] / 10_000 for p, v, role in legs]
    reserve = max(qty * price, qty * hp) * 5 / 10_000
    denom = qty * price
    return {"hedge_entry_px": hp, "maker_exit_px": mp2, "hedge_exit_px": hp2,
            "gross_usd": gross, "four_fee_usd": sum(own_fees), "fee_legs_usd": own_fees,
            "net_bps": (gross - sum(own_fees)) / denom * 10_000,
            "net_after_reserve_bps": (gross - sum(own_fees) - reserve) / denom * 10_000,
            "reserve_usd": reserve}


def analyze(data, frozen_meta, fees, max_cases=10_000):
    require_contiguous_capture(data)
    selected = data["manifest"]["selected_markets"]
    if any(set(selected[v]) != set(ASSETS) for v in ("hyperliquid", "lighter", "rh_lighter")):
        raise ValueError("capture must contain NVDA and XAG on all three venues")
    start = int(datetime.fromisoformat(data["manifest"]["started_utc"]).timestamp() * SECOND)
    end = int(datetime.fromisoformat(data["manifest"]["ended_utc"]).timestamp() * SECOND)
    first = ((start + 3 * SECOND + 5 * SECOND - 1) // (5 * SECOND)) * 5 * SECOND
    qs = data["quotes"]
    qtimes = {k: [q["receipt_ns"] for q in v] for k, v in qs.items()}
    ts = {k: sorted(v, key=lambda t: (t["receipt_ns"], t["source_ns"]))
          for k, v in data["trades"].items()}
    ttimes = {k: [t["receipt_ns"] for t in v] for k, v in ts.items()}
    ahead_trade_count = {k: sum(t["source_ns"] > t["receipt_ns"] for t in v)
                         for k, v in ts.items()}
    summaries, cases = [], []
    for delay_s in (1.0, 0.5, 3.0):
        for asset in ASSETS:
            for maker_venue, hedge_venue in ROUTES:
                mk, hk = (maker_venue, asset), (hedge_venue, asset)
                mq, hq = qs[mk], qs[hk]
                mt, ht = qtimes.get(mk, []), qtimes.get(hk, [])
                for side in ("buy", "sell"):
                    counts, positives = Counter(), Counter()
                    clock_unassessable = ahead_trade_count.get(mk, 0) > 0
                    for anchor in range(first, end - 5 * SECOND, 5 * SECOND):
                        counts["anchors"] += 1
                        if clock_unassessable:
                            counts["timing_unassessable_trade_clock"] += 1
                            continue
                        m, h = last_quote(mq, mt, anchor), last_quote(hq, ht, anchor)
                        if m is None or h is None:
                            counts["stale_decision"] += 1
                            continue
                        if abs(m["source_ns"] - h["source_ns"]) > SECOND // 2:
                            counts["decision_skew"] += 1
                            continue
                        if abs(m["receipt_ns"] - h["receipt_ns"]) > SECOND // 2:
                            counts["decision_receipt_skew"] += 1
                            continue
                        d = decision_quote(m, h, side, asset, frozen_meta[asset], fees[asset])
                        if d is None:
                            counts["decision_depth_or_minimum"] += 1
                            continue
                        positive = d["after_four_fee_allowance_bps"] > 0

                        def bump(key):
                            counts[key] += 1
                            if positive:
                                positives[key] += 1

                        bump("quote_supported")
                        arrival = anchor + int(delay_s * SECOND)
                        arrived = first_activation_quote(mq, mt, arrival)
                        if arrived is None:
                            bump("missing_due_arrival_quote")
                            continue
                        price = d["price"]
                        current = arrived["bid"] if side == "buy" else arrived["ask"]
                        opposite = arrived["ask"] if side == "buy" else arrived["bid"]
                        if current != price or (side == "buy" and price >= opposite) or (
                                side == "sell" and price <= opposite):
                            bump("maker_price_moved_or_crossed")
                            continue
                        bump("same_price_arrival")
                        ahead = arrived["bid_size"] if side == "buy" else arrived["ask_size"]
                        activation = arrived["receipt_ns"]
                        full = first_full_flow(ts[mk], ttimes[mk], activation, anchor + 5 * SECOND,
                                               side, price, ahead, d["qty"])
                        if full is None:
                            bump("no_full_flow")
                            continue
                        bump("full_flow")
                        if len(cases) >= max_cases:
                            raise RuntimeError("case cap reached; no silent truncation")
                        hard = full["receipt_ns"] + HARD_FLOW_DEADLINE_NS
                        case = {"asset": asset, "maker": maker_venue, "hedge": hedge_venue,
                                "side": side, "maker_delay_s": delay_s, "anchor_utc": iso(anchor),
                                "maker_activation_receipt_utc": iso(activation),
                                "maker_activation_source_utc": iso(arrived["source_ns"]),
                                "flow_receipt_utc": iso(full["receipt_ns"]),
                                "flow_source_utc": iso(full["source_ns"]),
                                "hard_deadline_utc": iso(hard), "qty": d["qty"], "queue_ahead_qty": ahead,
                                "flow_qualifying_qty": full["cumulative_qualifying_qty"],
                                "maker_entry_px": price, "decision_positive": positive,
                                "decision_after_four_fee_allowance_bps": d["after_four_fee_allowance_bps"],
                                "hard_deadline_after_capture_end": hard > end,
                                "flow_to_deadline_crosses_funding_hour": funding_boundary(full["receipt_ns"], hard)}
                        cases.append(case)
                        due = hedge_due(full["receipt_ns"], hedge_venue)
                        case["hedge_due_utc"] = iso(due)
                        hedge, status = first_delayed_hedge(hq, ht, due, full["source_ns"], hard, side, d["qty"], frozen_meta[asset][hedge_venue])
                        if hedge is None and status == "missing_due_hedge_quote" and capture_truncates_window(due, hard, end):
                            case["terminal_hedge_window"] = True
                            case["underlying_hedge_status"] = status
                            status = "terminal_capture_hedge"
                        case["hedge_status"] = status
                        bump(status)
                        if hedge is None:
                            continue
                        case["hedge_receipt_utc"] = iso(hedge["receipt_ns"])
                        case["hedge_source_utc"] = iso(hedge["source_ns"])
                        pair, exit_status, due_by_side = first_delayed_exit(
                            mq, hq, maker_venue, hedge_venue, hedge["receipt_ns"], hard, side, d["qty"],
                            frozen_meta[asset][maker_venue], frozen_meta[asset][hedge_venue])
                        case["maker_exit_due_utc"] = iso(due_by_side["maker"])
                        case["hedge_exit_due_utc"] = iso(due_by_side["hedge"])
                        case["exit_status"] = exit_status
                        if (pair is None and exit_status in ("missing_due_exit_side", "exit_skew_or_unsynchronized")
                                and any(capture_truncates_window(due_by_side[v], hard, end)
                                        for v in ("maker", "hedge"))):
                            case["terminal_exit_window"] = True
                            case["underlying_exit_status"] = exit_status
                            exit_status = "terminal_capture_exit"
                            case["exit_status"] = exit_status
                        bump(exit_status)
                        if pair is None:
                            continue
                        maker_exit, hedge_exit, observed = pair
                        case["exit_observed_utc"] = iso(observed)
                        if funding_boundary(full["receipt_ns"], observed):
                            case["funding_status"] = "funding_boundary_unresolved"
                            bump("funding_boundary_unresolved")
                            continue
                        case["funding_status"] = "no_boundary_observed"
                        bump("complete_nonfunding_path")
                        case.update(cashflow(side, price, hedge, maker_exit, hedge_exit,
                                             d["qty"], maker_venue, hedge_venue, fees[asset]))
                        if case["net_bps"] > 0:
                            bump("positive_four_fee_net")
                        if case["net_after_reserve_bps"] > 0:
                            bump("positive_after_reserve")
                    for cohort in (counts, positives):
                        if cohort is counts:
                            if cohort["anchors"] != (cohort["timing_unassessable_trade_clock"]
                                + cohort["stale_decision"] + cohort["decision_skew"]
                                + cohort["decision_receipt_skew"] + cohort["decision_depth_or_minimum"]
                                + cohort["quote_supported"]):
                                raise RuntimeError("anchor gate conservation failed")
                        if cohort["quote_supported"] != (cohort["missing_due_arrival_quote"]
                            + cohort["maker_price_moved_or_crossed"] + cohort["same_price_arrival"]):
                            raise RuntimeError("arrival gate conservation failed")
                        if cohort["same_price_arrival"] != cohort["no_full_flow"] + cohort["full_flow"]:
                            raise RuntimeError("flow gate conservation failed")
                        if cohort["full_flow"] != (cohort["deadline_before_hedge"]
                            + cohort["insufficient_hedge_top_depth"] + cohort["hedge_minimum_or_maximum"]
                            + cohort["missing_due_hedge_quote"] + cohort["terminal_capture_hedge"]
                            + cohort["hedge_found"]):
                            raise RuntimeError("hedge gate conservation failed")
                        if cohort["hedge_found"] != (cohort["deadline_before_exit"]
                            + cohort["insufficient_exit_top_depth"] + cohort["exit_minimum_or_maximum"]
                            + cohort["missing_due_exit_side"] + cohort["exit_skew_or_unsynchronized"]
                            + cohort["terminal_capture_exit"]
                            + cohort["exit_found"]):
                            raise RuntimeError("exit gate conservation failed")
                        if cohort["exit_found"] != (cohort["funding_boundary_unresolved"]
                            + cohort["complete_nonfunding_path"]):
                            raise RuntimeError("funding gate conservation failed")
                    summaries.append({"asset": asset, "maker": maker_venue, "hedge": hedge_venue,
                                      "side": side, "maker_delay_s": delay_s,
                                      "maker_source_ahead_trade_count": ahead_trade_count.get(mk, 0),
                                      "all": dict(counts), "decision_positive_subset": dict(positives)})
    return summaries, cases


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fee-inputs", type=Path, required=True)
    ap.add_argument("--frozen-method", type=Path, required=True)
    ap.add_argument("--max-cases", type=int, default=10_000)
    args = ap.parse_args()
    if args.max_cases <= 0:
        ap.error("--max-cases must be positive")
    data = archive_load(args.capture)
    if not all(data["integrity"][k] for k in
               ("record_count_matches", "compressed_size_matches", "under_total_cap", "plan_hash_matches_current")):
        raise RuntimeError("capture integrity or frozen market-plan hash failed")
    fee_rates = fees_from_frozen(args.fee_inputs)
    metadata = plan_markets(Path(data["manifest"]["market_plan"]), data["manifest"]["selected_markets"])
    summaries, cases = analyze(data, metadata, fee_rates, args.max_cases)
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"capture": str(args.capture), "capture_integrity": data["integrity"],
              "market_plan_sha256": data["manifest"]["market_plan_sha256"],
              "fee_inputs": str(args.fee_inputs), "fee_inputs_sha256": sha256_file(args.fee_inputs),
              "frozen_method": str(args.frozen_method), "frozen_method_sha256": sha256_file(args.frozen_method),
              "analyzer_sha256": sha256_file(Path(__file__)),
              "shared_archive_loader_before_adapter_sha256": SHARED_LOADER_BASELINE_SHA256,
              "shared_archive_loader_sha256": sha256_file(ROOT / "scripts/analyze_maker_capture.py"),
              "fee_rates_bps": fee_rates, "cohorts": summaries, "full_flow_cases": len(cases),
              "classification": "conditional public-book quote path, no actual maker fill or execution P&L",
              "session": "single post-market capture; no regular-hours or overnight comparison",
              "rh_quote_comparison": "conditional USDG/USDC parity arithmetic; conversion cost and execution unmodeled",
              "financing": "unmodeled; 5 bp reserve is a generic stress allowance, not financing cashflow",
              "absent_control": "no all-taker control in this v2 study"}
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (args.out / "cases.json").write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n")
    with (args.out / "cases.csv").open("w", newline="") as f:
        fields = list(dict.fromkeys(k for row in cases for k in row)) or ["asset", "maker", "hedge"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(cases)
    print(f"{args.out}: {len(summaries)} cohorts, {len(cases)} hypothetical full-flow cases")


if __name__ == "__main__":
    main()
