#!/usr/bin/env python3
"""Offline size-aware join of archived Aster/dYdX books to Hyperliquid books.

Example: python scripts/analyze_comparator_live.py
The nearest quote is used once per HL snapshot and venue, with no forward fill.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import datetime as dt
from decimal import Decimal, ROUND_DOWN
import json
import pathlib
import statistics

from analyze_live import consume, fee_bps, levels


ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw"
OUT = ROOT / "data/derived"
SIZES = (1000, 10000, 100000)


def read_json(path):
    return json.loads(path.read_text())


def write_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0])
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def percentile(values, percent):
    if not values:
        return None
    vals = sorted(values)
    pos = (len(vals) - 1) * percent
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)


def venue_age(row):
    stamp = row.get("venue_time_ms")
    return row["received_ms"] - stamp if stamp is not None else None


def valid_book(row, venue, quality):
    if row.get("error"):
        quality[(venue, "http_error")] += 1
        return False
    if not row.get("body"):
        quality[(venue, "empty_body")] += 1
        return False
    try:
        row["_levels"] = levels(row)
    except (ValueError, KeyError, TypeError, IndexError):
        quality[(venue, "invalid_book")] += 1
        return False
    age = venue_age(row)
    if age is not None and (age > 5000 or age < -2000):
        quality[(venue, "stale_engine_time")] += 1
        return False
    quality[(venue, "valid_book")] += 1
    return True


def quote_market(row):
    return "EURUSD" if row["asset"] == "EUR" else row["asset"]


def step_for(venue, market, aster_meta, dydx_meta, hl_meta):
    base = quote_market({"asset": market})
    hl = hl_meta.get(base)
    if hl is None:
        return None, "no_hl_metadata"
    steps = [Decimal(10) ** -int(hl["sz_decimals"])]
    minimum = Decimal("0")
    if venue == "aster":
        symbol = market + "USDT"
        info = aster_meta.get(symbol)
        if info is None:
            return None, "no_aster_metadata"
        for item in info.get("filters", []):
            if item.get("filterType") in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                steps.append(Decimal(str(item["stepSize"])))
                minimum = max(minimum, Decimal(str(item.get("minQty", "0"))))
    elif venue == "dydx":
        symbol = market + "-USD"
        info = dydx_meta.get(symbol)
        if info is None:
            return None, "no_dydx_metadata"
        steps.append(Decimal(str(info["stepSize"])))
    return (max(steps), minimum), None


def book_depth_row(row, hl_round=None):
    bids, asks = row["_levels"]
    mid = (bids[0][0] + asks[0][0]) / 2
    return {"venue": row["venue"], "asset": quote_market(row), "market": row["market"],
            "round": row.get("round") if hl_round is None else hl_round,
            "received_ms": row["received_ms"], "venue_age_ms": venue_age(row),
            "mid": mid, "spread_bps": (asks[0][0] / bids[0][0] - 1) * 10000,
            "bid_depth_10bp_usd": sum(p*q for p, q in bids if p >= mid * .999),
            "ask_depth_10bp_usd": sum(p*q for p, q in asks if p <= mid * 1.001),
            "returned_bid_usd": sum(p*q for p, q in bids),
            "returned_ask_usd": sum(p*q for p, q in asks),
            "bid_levels": len(bids), "ask_levels": len(asks)}


def load_books(hl_run, comp_run):
    quality = collections.Counter()
    plan = read_json(hl_run / "plan.json")
    hl_meta = {x["asset"]: x for x in plan if x["venue"] == "hyperliquid" and x["kind"] == "perp"}
    inventory = sorted(p for p in (RAW / "comparators").iterdir()
                       if (p / "aster/markets.json").exists())[-1]
    aster_meta = {x["symbol"]: x for x in read_json(inventory / "aster/markets.json")["symbols"]}
    dydx_meta = read_json(inventory / "dydx/markets.json")["markets"]
    hl = collections.defaultdict(list)
    for line in (hl_run / "books.jsonl").open():
        row = json.loads(line)
        if row["venue"] != "hyperliquid" or row["market"].startswith("@"):
            continue
        base = row["asset"]
        if base not in hl_meta or row["market"] != hl_meta[base]["market"]:
            continue
        quality[("hyperliquid", "requests")] += 1
        if valid_book(row, "hyperliquid", quality):
            hl[base].append(row)
    comp = collections.defaultdict(list)
    for path in (comp_run / "aster").glob("*.jsonl"):
        for line in path.open():
            row = json.loads(line)
            quality[("aster", "requests")] += 1
            if valid_book(row, "aster", quality):
                comp[("aster", quote_market(row))].append(row)
    for path in (comp_run / "dydx").glob("*.jsonl"):
        for line in path.open():
            row = json.loads(line)
            quality[("dydx", "requests")] += 1
            if valid_book(row, "dydx", quality):
                comp[("dydx", quote_market(row))].append(row)
    for rows in list(hl.values()) + list(comp.values()):
        rows.sort(key=lambda r: r["received_ms"])
    return hl, comp, hl_meta, aster_meta, dydx_meta, quality, inventory


def nearest_pairs(hl, comp, window_ms):
    for (venue, asset), others in comp.items():
        if asset not in hl:
            continue
        times = [r["received_ms"] for r in others]
        for h in hl[asset]:
            pos = bisect.bisect_left(times, h["received_ms"])
            choices = [others[i] for i in (pos-1, pos) if 0 <= i < len(others)]
            if not choices:
                continue
            c = min(choices, key=lambda row: abs(row["received_ms"] - h["received_ms"]))
            skew = abs(c["received_ms"] - h["received_ms"])
            if skew <= window_ms:
                yield h, c, skew


def size_row(h, c, skew, size, direction, aster_meta, dydx_meta, hl_meta):
    hb, ha = h["_levels"]
    cb, ca = c["_levels"]
    hm = (hb[0][0] + ha[0][0]) / 2
    cm = (cb[0][0] + ca[0][0]) / 2
    venue = c["venue"]
    step_min, issue = step_for(venue, c["asset"], aster_meta, dydx_meta, hl_meta)
    valid_mapping = .95 <= cm/hm <= 1.05
    if issue is None:
        step, minimum = step_min
        q = (Decimal(str(size / hm)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    else:
        q = Decimal(0)
        minimum = Decimal(0)
    row = {"hl_round": h["round"], "hl_market": h["market"], "comparator_round": c["round"],
           "asset": quote_market(c), "comparator": venue, "comparator_market": c["market"],
           "direction": direction, "target_usd": size, "base_quantity": str(q),
           "hl_received_ms": h["received_ms"], "comparator_received_ms": c["received_ms"],
           "skew_ms": skew, "hl_venue_age_ms": venue_age(h),
           "comparator_venue_age_ms": venue_age(c), "comparator_has_venue_time": c.get("venue_time_ms") is not None,
           "hl_mid": hm, "comparator_mid": cm, "mid_ratio": cm/hm,
           "fillable_returned_book": False, "reason": "", "buy_cost_usd": None,
           "sell_proceeds_usd": None, "gross_entry_bps": None,
           "entry_fees_bps": None, "net_entry_bps": None,
           "hl_taker_fee_bps": fee_bps(hl_meta[quote_market(c)]),
           "comparator_taker_fee_bps": 4 if venue == "aster" else 5,
           "quote_parity_assumed": True}
    if issue:
        row["reason"] = issue
        return row
    if not valid_mapping:
        row["reason"] = "midpoint_mismatch_gt_5pct"
        return row
    if q <= 0 or q < minimum:
        row["reason"] = "quantity_below_market_step_or_minimum"
        return row
    qty = float(q)
    buybook, sellbook = (ca, hb) if direction == "buy_comparator_sell_hl" else (ha, cb)
    buy = consume(buybook, qty)
    sell = consume(sellbook, qty)
    if buy is None or sell is None:
        row["reason"] = "insufficient_returned_book_depth"
        return row
    buy_fee = row["comparator_taker_fee_bps"] if direction == "buy_comparator_sell_hl" else row["hl_taker_fee_bps"]
    sell_fee = row["hl_taker_fee_bps"] if direction == "buy_comparator_sell_hl" else row["comparator_taker_fee_bps"]
    fees = buy * buy_fee / 10000 + sell * sell_fee / 10000
    row.update(fillable_returned_book=True, reason="", buy_cost_usd=buy, sell_proceeds_usd=sell,
               gross_entry_bps=(sell/buy-1)*10000, entry_fees_bps=fees/buy*10000,
               net_entry_bps=(sell-buy-fees)/buy*10000)
    return row


def summarize(rows, pairs, window_ms):
    grouped = collections.defaultdict(list)
    paired = collections.Counter((quote_market(c), c["venue"]) for _, c, _ in pairs)
    for row in rows:
        key = (row["asset"], row["comparator"], row["direction"], row["target_usd"])
        grouped[key].append(row)
    out = []
    for key, group in grouped.items():
        filled = [r for r in group if r["fillable_returned_book"]]
        nets = [r["net_entry_bps"] for r in filled]
        positive = [r for r in filled if r["net_entry_bps"] > 0]
        success_rounds = sorted({r["hl_round"] for r in positive})
        longest = run = 0
        last = None
        for rnd in success_rounds:
            run = run + 1 if last is not None and rnd == last + 1 else 1
            longest = max(longest, run)
            last = rnd
        out.append({"asset": key[0], "comparator": key[1], "direction": key[2], "target_usd": key[3],
                    "join_window_ms": window_ms, "paired_snapshots": paired[(key[0], key[1])],
                    "fillable_snapshots": len(filled), "fillable_fraction": len(filled)/len(group),
                    "positive_net_snapshots": len(positive),
                    "positive_fraction_all_pairs": len(positive)/len(group),
                    "net_median_bps_fillable": statistics.median(nets) if nets else None,
                    "net_p05_bps_fillable": percentile(nets, .05),
                    "net_p95_bps_fillable": percentile(nets, .95),
                    "max_positive_consecutive_hl_rounds": longest,
                    "max_skew_ms": max(r["skew_ms"] for r in group),
                    "median_skew_ms": statistics.median(r["skew_ms"] for r in group),
                    "dydx_venue_age_unavailable": key[1] == "dydx"})
    return sorted(out, key=lambda r: (r["join_window_ms"], r["target_usd"], -r["positive_fraction_all_pairs"], r["asset"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hl-run", type=pathlib.Path,
                        default=RAW / "live/20260929T035450Z")
    parser.add_argument("--comparator-run", type=pathlib.Path,
                        default=RAW / "comparators/20260929T035236Z_live")
    parser.add_argument("--out", type=pathlib.Path, default=OUT)
    args = parser.parse_args()
    hl, comp, hm, am, dm, quality, inventory = load_books(args.hl_run, args.comparator_run)
    depth = [book_depth_row(r) for rs in hl.values() for r in rs]
    depth += [book_depth_row(r) for rs in comp.values() for r in rs]
    write_csv(args.out / "comparator_live_depth.csv", depth)
    audit = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
             "hl_run": str(args.hl_run), "comparator_run": str(args.comparator_run),
             "market_inventory": str(inventory), "fees_bps": {"aster_usdt_taker": 4, "dydx_base_taker": 5},
             "snapshot_counts": {f"{k[0]}:{k[1]}": v for k, v in quality.items()},
             "hl_valid_books": sum(map(len, hl.values())), "comparator_valid_books": sum(map(len, comp.values())),
             "dydx_venue_time_note": "dYdX REST orderbook response has no engine timestamp; source age is unknown",
             "selection": "one nearest comparator receipt per HL receipt; no forward fill; source age <=5s where engine time exists"}
    for window_ms, suffix in ((5000, ""), (15000, "_15s")):
        pairs = list(nearest_pairs(hl, comp, window_ms))
        rows = [size_row(h, c, skew, size, direction, am, dm, hm)
                for h, c, skew in pairs for size in SIZES
                for direction in ("buy_comparator_sell_hl", "buy_hl_sell_comparator")]
        write_csv(args.out / ("comparator_live_observations" + suffix + ".csv"), rows)
        summary = summarize(rows, pairs, window_ms)
        write_csv(args.out / ("comparator_live_summary" + suffix + ".csv"), summary)
        audit[f"window_{window_ms}_ms"] = {"paired_snapshots": len(pairs),
                                          "size_direction_rows": len(rows),
                                          "fillable_rows": sum(r["fillable_returned_book"] for r in rows),
                                          "positive_net_rows": sum(r["fillable_returned_book"] and r["net_entry_bps"] > 0 for r in rows),
                                          "max_skew_ms": max((s for _, _, s in pairs), default=None)}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "comparator_live_quality.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
