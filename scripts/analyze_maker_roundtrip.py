#!/usr/bin/env python3
"""Conditional public-feed maker-flow/hedge/unwind replay; never actual fills."""

import argparse
import bisect
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.analyze_maker_capture import (  # noqa: E402
    FEES_BPS, ROUTES, SECOND, archive_load, candidate_quote, iso,
    last_quote, require_contiguous_capture, sha256_file,
)

FROZEN_METHOD = ROOT / "reports/maker-roundtrip-v1/frozen-method.md"


def first_full_flow(trades, receipt_times, arrival_ns, expiry_ns, side, price, ahead, qty):
    """First *observed* trade taking cumulative qualifying flow strictly above ahead+q."""
    i = bisect.bisect_left(receipt_times, arrival_ns)
    flow = 0.0
    ids = set()
    while i < len(trades) and trades[i]["receipt_ns"] < expiry_ns:
        trade = trades[i]
        i += 1
        if not arrival_ns <= trade["source_ns"] < expiry_ns or trade["id"] in ids:
            continue
        ids.add(trade["id"])
        qualifying = ((not trade["buy_aggressor"] and trade["price"] <= price + 1e-10)
                      if side == "buy" else
                      (trade["buy_aggressor"] and trade["price"] >= price - 1e-10))
        if qualifying:
            flow += trade["qty"]
            if flow > ahead + qty + 1e-12:
                return {"receipt_ns": trade["receipt_ns"], "source_ns": trade["source_ns"],
                        "cumulative_qualifying_qty": flow, "trigger_trade_id": str(trade["id"])}
    return None


def first_hedge_quote(series, receipt_times, target_ns, flow_source_ns, side, qty):
    """First time-valid quote; a shallow first quote censors rather than retries."""
    i = bisect.bisect_left(receipt_times, target_ns)
    while i < len(series) and series[i]["receipt_ns"] <= target_ns + SECOND:
        quote = series[i]
        i += 1
        if quote["source_ns"] < flow_source_ns or not 0 <= quote["receipt_ns"] - quote["source_ns"] <= 2 * SECOND:
            continue
        available = quote["bid_size"] if side == "buy" else quote["ask_size"]
        if available + 1e-12 < qty:
            return None, "insufficient_hedge_top_depth"
        return quote, "hedge_found"
    return None, "missing_fresh_hedge_quote"


def first_exit_pair(maker_quotes, hedge_quotes, target_ns, maker_side, qty):
    """First time-valid paired exits; shallow first pair censors rather than retries."""
    events = []
    for label, series in (("maker", maker_quotes), ("hedge", hedge_quotes)):
        receipts = [q["receipt_ns"] for q in series]
        i = bisect.bisect_left(receipts, target_ns)
        while i < len(series) and series[i]["receipt_ns"] <= target_ns + SECOND:
            quote = series[i]
            i += 1
            if quote["source_ns"] >= target_ns and 0 <= quote["receipt_ns"] - quote["source_ns"] <= 2 * SECOND:
                events.append((quote["receipt_ns"], label, quote))
    events.sort(key=lambda item: item[0])
    latest = {}
    for observed_ns, label, quote in events:
        latest[label] = quote
        maker = latest.get("maker")
        hedge = latest.get("hedge")
        if maker is None or hedge is None:
            continue
        if (abs(maker["source_ns"] - hedge["source_ns"]) > 0.5 * SECOND
                or abs(maker["receipt_ns"] - hedge["receipt_ns"]) > 0.5 * SECOND):
            continue
        # Maker buy exits at its bid, hedge short exits at its ask; reverse for maker sell.
        maker_size = maker["bid_size"] if maker_side == "buy" else maker["ask_size"]
        hedge_size = hedge["ask_size"] if maker_side == "buy" else hedge["bid_size"]
        if maker_size + 1e-12 < qty or hedge_size + 1e-12 < qty:
            return None, "insufficient_exit_top_depth"
        return (maker, hedge, observed_ns), "exit_found"
    labels = {label for _, label, _ in events}
    if labels != {"maker", "hedge"}:
        return None, "missing_future_exit_side"
    return None, "exit_skew_or_unsynchronized"


def conditional_roundtrip(maker_side, maker_price, hedge_entry, maker_exit, hedge_exit,
                          qty, maker_venue, hedge_venue):
    """Cashflow identity for an explicitly hypothetical full-q fill and four displayed trades."""
    hedge_entry_px = hedge_entry["bid"] if maker_side == "buy" else hedge_entry["ask"]
    maker_exit_px = maker_exit["bid"] if maker_side == "buy" else maker_exit["ask"]
    hedge_exit_px = hedge_exit["ask"] if maker_side == "buy" else hedge_exit["bid"]
    if maker_side == "buy":
        gross_cash = qty * ((maker_exit_px - maker_price) + (hedge_entry_px - hedge_exit_px))
    else:
        gross_cash = qty * ((maker_price - maker_exit_px) + (hedge_exit_px - hedge_entry_px))
    maker_entry_fee = qty * maker_price * FEES_BPS[maker_venue]["maker"] / 10_000
    hedge_entry_fee = qty * hedge_entry_px * FEES_BPS[hedge_venue]["taker"] / 10_000
    maker_exit_fee = qty * maker_exit_px * FEES_BPS[maker_venue]["taker"] / 10_000
    hedge_exit_fee = qty * hedge_exit_px * FEES_BPS[hedge_venue]["taker"] / 10_000
    total_fee = maker_entry_fee + hedge_entry_fee + maker_exit_fee + hedge_exit_fee
    initial = qty * maker_price
    reserve = max(qty * maker_price, qty * hedge_entry_px) * 5 / 10_000
    return {"maker_entry_px": maker_price, "hedge_entry_px": hedge_entry_px,
            "maker_exit_px": maker_exit_px, "hedge_exit_px": hedge_exit_px,
            "maker_entry_fee_usd": maker_entry_fee, "hedge_entry_fee_usd": hedge_entry_fee,
            "maker_exit_fee_usd": maker_exit_fee, "hedge_exit_fee_usd": hedge_exit_fee,
            "four_fee_usd": total_fee, "conditional_gross_usd": gross_cash,
            "conditional_net_usd": gross_cash - total_fee,
            "conditional_gross_bps": gross_cash / initial * 10_000,
            "conditional_net_bps": (gross_cash - total_fee) / initial * 10_000,
            "five_bp_larger_entry_reserve_usd": reserve,
            "conditional_net_after_reserve_usd": gross_cash - total_fee - reserve,
            "conditional_net_after_reserve_bps": (gross_cash - total_fee - reserve) / initial * 10_000}


def analyze(data, max_cases=10_000):
    require_contiguous_capture(data)
    manifest = data["manifest"]
    start = int(datetime.fromisoformat(manifest["started_utc"]).timestamp() * SECOND)
    end = int(datetime.fromisoformat(manifest["ended_utc"]).timestamp() * SECOND)
    first = ((start + 3 * SECOND + 5 * SECOND - 1) // (5 * SECOND)) * (5 * SECOND)
    quotes = data["quotes"]
    q_times = {key: [q["receipt_ns"] for q in series] for key, series in quotes.items()}
    # The archive parser sorts trades by source; replay their *receipt* order to
    # avoid incorporating a later-observed trade into an earlier queue event.
    trades = {key: sorted(series, key=lambda t: (t["receipt_ns"], t["source_ns"]))
              for key, series in data["trades"].items()}
    t_times = {key: [t["receipt_ns"] for t in series] for key, series in trades.items()}
    cases, summaries = [], []
    for delay_s in (1.0, 0.5, 3.0):
        for maker_venue, hedge_venue in ROUTES:
            for asset in ("BTC", "ETH"):
                mk, hk = (maker_venue, asset), (hedge_venue, asset)
                maker_quotes, hedge_quotes = quotes[mk], quotes[hk]
                maker_times, hedge_times = q_times[mk], q_times[hk]
                maker_trades, maker_trade_times = trades[mk], t_times[mk]
                for side in ("buy", "sell"):
                    all_counts, positive_counts = Counter(), Counter()
                    for anchor in range(first, end - 6 * SECOND, 5 * SECOND):
                        all_counts["anchors"] += 1
                        m = last_quote(maker_quotes, maker_times, anchor)
                        h = last_quote(hedge_quotes, hedge_times, anchor)
                        if m is None or h is None:
                            all_counts["stale_at_decision"] += 1
                            continue
                        if abs(m["source_ns"] - h["source_ns"]) > 0.5 * SECOND:
                            all_counts["decision_source_skew"] += 1
                            continue
                        decision = candidate_quote(m, h, side, asset)
                        if decision is None:
                            all_counts["insufficient_decision_hedge_depth"] += 1
                            continue
                        positive = decision["after_four_fee_hurdle_bps"] > 0

                        def bump(name):
                            all_counts[name] += 1
                            if positive:
                                positive_counts[name] += 1

                        bump("quote_supported")
                        arrival = anchor + int(delay_s * SECOND)
                        arrived = last_quote(maker_quotes, maker_times, arrival)
                        if arrived is None:
                            bump("arrival_book_stale")
                            continue
                        current_px = arrived["bid"] if side == "buy" else arrived["ask"]
                        other_px = arrived["ask"] if side == "buy" else arrived["bid"]
                        price = decision["maker_price"]
                        if current_px != price or (side == "buy" and price >= other_px) or (
                                side == "sell" and price <= other_px):
                            bump("maker_price_moved_or_crossed")
                            continue
                        bump("same_price_at_arrival")
                        ahead = arrived["bid_size"] if side == "buy" else arrived["ask_size"]
                        full = first_full_flow(maker_trades, maker_trade_times, arrival,
                                               anchor + 5 * SECOND, side, price, ahead, decision["qty"])
                        if full is None:
                            bump("no_full_flow_signal")
                            continue
                        bump("full_flow_signal")
                        case = {"maker": maker_venue, "hedge": hedge_venue, "asset": asset,
                                "side": side, "arrival_delay_s": delay_s, "anchor_utc": iso(anchor),
                                "capture_end_utc": manifest["ended_utc"],
                                "maker_arrival_utc": iso(arrival), "maker_price": price,
                                "qty": decision["qty"], "queue_ahead_qty": ahead,
                                "cumulative_qualifying_trade_qty": full["cumulative_qualifying_qty"],
                                "first_full_flow_source_utc": iso(full["source_ns"]),
                                "first_full_flow_receipt_utc": iso(full["receipt_ns"]),
                                "trigger_trade_id": full["trigger_trade_id"],
                                "decision_entry_positive": positive,
                                "decision_after_four_fee_allowance_bps": decision["after_four_fee_hurdle_bps"]}
                        if len(cases) >= max_cases:
                            raise RuntimeError(f"full-flow case cap {max_cases} reached; no output silently truncated")
                        cases.append(case)
                        hedge_target = full["receipt_ns"] + int(0.1 * SECOND)
                        case["hedge_window_extends_past_capture_end"] = hedge_target + SECOND > end
                        hedge_quote, hedge_status = first_hedge_quote(
                            hedge_quotes, hedge_times, hedge_target, full["source_ns"], side, decision["qty"])
                        case["hedge_status"] = hedge_status
                        bump(hedge_status)
                        if hedge_quote is None:
                            continue
                        hedge_px = hedge_quote["bid"] if side == "buy" else hedge_quote["ask"]
                        case["hedge_receipt_utc"] = iso(hedge_quote["receipt_ns"])
                        case["hedge_source_utc"] = iso(hedge_quote["source_ns"])
                        case["hedge_entry_px"] = hedge_px
                        entry_gross = ((hedge_px - price) if side == "buy" else (price - hedge_px)) / price * 10_000
                        case["conditional_entry_after_two_fees_bps"] = (
                            entry_gross - FEES_BPS[maker_venue]["maker"]
                            - FEES_BPS[hedge_venue]["taker"] * hedge_px / price)
                        exit_target = hedge_quote["receipt_ns"] + 10 * SECOND
                        case["exit_window_extends_past_capture_end"] = exit_target + SECOND > end
                        pair, exit_status = first_exit_pair(maker_quotes, hedge_quotes, exit_target,
                                                            side, decision["qty"])
                        case["exit_status"] = exit_status
                        bump(exit_status)
                        if pair is None:
                            continue
                        maker_exit, hedge_exit, observed = pair
                        case["exit_target_utc"] = iso(exit_target)
                        case["exit_observed_utc"] = iso(observed)
                        case["exit_observed_after_target_s"] = (observed - exit_target) / SECOND
                        case.update(conditional_roundtrip(side, price, hedge_quote, maker_exit, hedge_exit,
                                                          decision["qty"], maker_venue, hedge_venue))
                        if case["conditional_net_bps"] > 0:
                            bump("conditional_displayed_net_positive")
                    summaries.append({"maker": maker_venue, "hedge": hedge_venue,
                                      "asset": asset, "side": side, "arrival_delay_s": delay_s,
                                      "all": dict(all_counts), "decision_entry_positive_subset": dict(positive_counts)})
    for row in summaries:
        for label in ("all", "decision_entry_positive_subset"):
            c = row[label]
            if (c.get("quote_supported", 0) != sum(c.get(k, 0) for k in
                    ("arrival_book_stale", "maker_price_moved_or_crossed", "same_price_at_arrival"))
                    or c.get("same_price_at_arrival", 0) != c.get("no_full_flow_signal", 0) + c.get("full_flow_signal", 0)
                    or c.get("full_flow_signal", 0) != sum(c.get(k, 0) for k in
                    ("hedge_found", "insufficient_hedge_top_depth", "missing_fresh_hedge_quote"))
                    or c.get("hedge_found", 0) != sum(c.get(k, 0) for k in
                    ("exit_found", "insufficient_exit_top_depth", "missing_future_exit_side", "exit_skew_or_unsynchronized"))):
                raise RuntimeError(f"cohort gate accounting failed: {row['maker']} {row['hedge']} {row['asset']} {row['side']} {label}")
    return summaries, cases


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--design", required=True, choices=("exploratory", "prospective"),
                    help="whether the method was frozen before this capture began")
    ap.add_argument("--max-cases", type=int, default=10_000)
    args = ap.parse_args()
    if args.max_cases <= 0:
        ap.error("--max-cases must be positive")
    data = archive_load(args.capture)
    if not all(data["integrity"][key] for key in
               ("record_count_matches", "compressed_size_matches", "under_total_cap")):
        raise RuntimeError("archive integrity failure")
    summaries, cases = analyze(data, args.max_cases)
    trade_clock_leads = {}
    for (venue, asset), series in sorted(data["trades"].items()):
        leads = [(trade["source_ns"] - trade["receipt_ns"]) / SECOND for trade in series
                 if trade["source_ns"] > trade["receipt_ns"]]
        trade_clock_leads[f"{venue}|{asset}"] = {
            "retained_trades": len(series), "source_ahead_of_receipt_count": len(leads),
            "max_source_lead_s": max(leads) if leads else 0.0}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps({
        "source_archive": str(args.capture), "integrity": data["integrity"],
        "design": args.design,
        "trade_clock_leads": trade_clock_leads,
        "method": str(FROZEN_METHOD), "method_sha256": sha256_file(FROZEN_METHOD),
        "analyzer": str(Path(__file__).resolve()), "analyzer_sha256": sha256_file(Path(__file__).resolve()),
        "model_caveats": {
            "hedge_quote_search_starts_after_flow_receipt_s": 0.1,
            "lighter_standard_taker_processing_delay_s_reference": 0.3,
            "lighter_taker_processing_delay_modeled": False,
            "exit_order_matching_modeled": False,
            "actual_maker_fill_observed": False,
            "network_latency_calibrated": False,
            "timing_unassessable_if_trade_source_ahead_of_receipt": any(
                entry["source_ahead_of_receipt_count"] > 0 for entry in trade_clock_leads.values()),
            "missing_hedge_is_unresolved_hypothetical_unhedged_exposure": True,
            "conditional_net_reported_only_for_complete_hedge_and_exit_books": True,
            "complete_case_selection_may_be_biased_by_depth_and_feed_activity": True,
            "overlapping_anchor_holds_not_summed_as_portfolio": True,
        },
        "classification":
        "conditional hypothetical displayed-book round trip, never observed maker fill or actual P&L",
        "summaries": summaries, "full_flow_cases": len(cases)}, indent=2, sort_keys=True) + "\n")
    (args.out / "cases.json").write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n")
    with (args.out / "cases.csv").open("w", newline="") as handle:
        fields = list(dict.fromkeys(key for row in cases for key in row)) or ["maker", "hedge", "asset"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(cases)
    print(f"{args.out}: {len(summaries)} cohorts, {len(cases)} hypothetical full-flow cases")


if __name__ == "__main__":
    main()
