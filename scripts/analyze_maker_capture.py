#!/usr/bin/env python3
"""Offline public-feed audit and hypothetical maker quote screen, never fill P&L."""

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/raw/maker-capture/20260929T1823Z"
DEFAULT_OUTPUT = ROOT / "data/derived/maker-capture-20260929T1823Z"
SECOND = 1_000_000_000
ROUTES = (("hyperliquid", "lighter"), ("lighter", "hyperliquid"),
          ("hyperliquid", "rh_lighter"), ("rh_lighter", "hyperliquid"))
FEES_BPS = {"hyperliquid": {"maker": 1.5, "taker": 4.5},
            "lighter": {"maker": 0.0, "taker": 0.0},
            "rh_lighter": {"maker": 0.0, "taker": 0.0}}
LOT = {"BTC": 0.00001, "ETH": 0.0001}


def iso(ns):
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).isoformat()


def percentile(values, p):
    if not values:
        return None
    a = sorted(values)
    i = (len(a) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(a) - 1)
    return a[lo] + (a[hi] - a[lo]) * (i - lo)


def finite_positive(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quote_from_record(row, symbol_by_market):
    venue, market, channel = row.get("venue"), row.get("market"), row.get("channel")
    symbol = symbol_by_market.get((venue, market))
    a = row.get("annotation") or {}
    if symbol is None or a.get("quality") != "wire_ok" or channel not in ("bbo", "ticker"):
        return None
    payload = row["payload"]
    if venue == "hyperliquid":
        sides = payload.get("data", {}).get("bbo")
        if not isinstance(sides, list) or len(sides) != 2 or not all(isinstance(x, dict) for x in sides):
            return None
        bid, ask = sides
        bp, bs, ap, ass = (finite_positive(bid.get("px")), finite_positive(bid.get("sz")),
                           finite_positive(ask.get("px")), finite_positive(ask.get("sz")))
    else:
        ticker = payload.get("ticker", {})
        bid, ask = ticker.get("b", {}), ticker.get("a", {})
        if not isinstance(bid, dict) or not isinstance(ask, dict):
            return None
        bp, bs, ap, ass = (finite_positive(bid.get("price")), finite_positive(bid.get("size")),
                           finite_positive(ask.get("price")), finite_positive(ask.get("size")))
    if None in (bp, bs, ap, ass) or bp >= ap:
        return None
    source, receipt = a.get("source_max_ns"), row.get("receipt_utc_ns")
    if not isinstance(source, int) or not isinstance(receipt, int):
        return None
    return {"venue": venue, "asset": symbol, "receipt_ns": receipt, "source_ns": source,
            "bid": bp, "bid_size": bs, "ask": ap, "ask_size": ass}


def trade_from_payload(venue, symbol, trade, receipt_ns):
    if not isinstance(trade, dict) or trade.get("type", "trade") != "trade":
        return None
    if venue == "hyperliquid":
        if trade.get("side") not in ("B", "A") or trade.get("coin") != symbol:
            return None
        buy_aggressor = trade["side"] == "B"
        if not isinstance(trade.get("tid"), int) or not isinstance(trade.get("hash"), str) or not trade["hash"]:
            return None
        identity = (trade.get("time"), trade["tid"], trade["hash"])
        source_ms = trade.get("time")
        px, qty = finite_positive(trade.get("px")), finite_positive(trade.get("sz"))
    else:
        if not isinstance(trade.get("is_maker_ask"), bool):
            return None
        buy_aggressor = trade["is_maker_ask"]
        identity = trade.get("trade_id")
        source_ms = trade.get("timestamp")
        px, qty = finite_positive(trade.get("price")), finite_positive(trade.get("size"))
    if px is None or qty is None or identity is None:
        return None
    try:
        source_ns = int(source_ms) * 1_000_000
    except (TypeError, ValueError):
        return None
    if source_ns <= 0 or source_ns > receipt_ns + 5 * SECOND:
        return None
    return {"venue": venue, "asset": symbol, "source_ns": source_ns, "receipt_ns": receipt_ns,
            "price": px, "qty": qty, "buy_aggressor": buy_aggressor, "id": identity}


def archive_load(directory):
    manifest_path = directory / "manifest.json"
    archive_path = directory / "frames.jsonl.gz"
    manifest = json.loads(manifest_path.read_text())
    selected = manifest["selected_markets"]
    symbol_by_market = {(venue, str(market)): symbol for venue, markets in selected.items()
                        for symbol, market in markets.items()}
    counts = Counter()
    annotations = Counter()
    quotes = defaultdict(list)
    trades = defaultdict(list)
    trade_ids = defaultdict(set)
    source_ages = defaultdict(list)
    receipt_times = defaultdict(list)
    first_ack = {}
    first_quote = {}
    first_trade_update = {}
    duplicate_trades = Counter()
    bad_trade_fields = Counter()
    unknown_trade_market = 0
    with gzip.open(archive_path, "rt") as f:
        for line in f:
            row = json.loads(line)
            counts["records"] += 1
            kind = row.get("kind")
            if kind != "frame":
                counts[f"kind:{kind}"] += 1
                continue
            venue, market, channel = row.get("venue"), row.get("market"), row.get("channel")
            a = row.get("annotation") or {}
            quality = a.get("quality")
            annotations[f"{venue}|{market}|{channel}|{quality}|{a.get('reason')}"] += 1
            counts[f"{venue}|{market}|{channel}"] += 1
            source, receipt = a.get("source_max_ns"), row.get("receipt_utc_ns")
            if isinstance(source, int) and isinstance(receipt, int):
                source_ages[(venue, market, channel)].append((receipt - source) / SECOND)
                receipt_times[(venue, market, channel)].append(receipt)
            if quality == "invalid" and channel == "trades" and market is None:
                unknown_trade_market += 1
            if quality == "invalid" or quality == "gap_after_bad_trade" or a.get("source_regression_within_channel"):
                counts["quality_exclusion_events"] += 1
            payload = row.get("payload") or {}
            if venue == "hyperliquid" and payload.get("channel") == "subscriptionResponse":
                first_ack.setdefault((venue, str(payload.get("data", {}).get("subscription"))), receipt)
            elif venue != "hyperliquid" and str(payload.get("type", "")).startswith("subscribed/"):
                first_ack.setdefault((venue, str(payload.get("channel"))), receipt)
            q = quote_from_record(row, symbol_by_market)
            if q:
                quotes[(venue, q["asset"])].append(q)
                first_quote.setdefault((venue, q["asset"]), receipt)
            if channel not in ("trades", "trade"):
                continue
            if quality not in ("wire_ok", "wire_ok_snapshot"):
                continue
            symbol = symbol_by_market.get((venue, market))
            if symbol is None:
                continue
            if venue == "hyperliquid":
                raw_trades = payload.get("data", [])
                update = True
            else:
                update = payload.get("type") == "update/trade"
                raw_trades = payload.get("trades", [])
            if not update:
                counts[f"{venue}|{symbol}|startup_trade_snapshot_events"] += len(raw_trades)
                continue
            first_trade_update.setdefault((venue, symbol), receipt)
            for raw in raw_trades:
                t = trade_from_payload(venue, symbol, raw, receipt)
                if t is None:
                    bad_trade_fields[(venue, symbol)] += 1
                    continue
                if t["id"] in trade_ids[(venue, symbol)]:
                    duplicate_trades[(venue, symbol)] += 1
                    continue
                trade_ids[(venue, symbol)].add(t["id"])
                trades[(venue, symbol)].append(t)
    # The first HL trade frame can precede the first BBO. Filter only after
    # discovering every first quote; filtering inline would admit that replay.
    discard_prequote_trades(trades, first_quote, counts)
    for key in quotes:
        quotes[key].sort(key=lambda x: x["receipt_ns"])
    for key in trades:
        trades[key].sort(key=lambda x: (x["source_ns"], x["receipt_ns"]))
    integrity = {"manifest_sha256": sha256_file(manifest_path), "gzip_sha256": sha256_file(archive_path),
                 "gzip_bytes": archive_path.stat().st_size, "manifest_bytes": manifest_path.stat().st_size,
                 "combined_bytes": archive_path.stat().st_size + manifest_path.stat().st_size,
                 "manifest_payload_records": manifest["payload_records"], "decoded_records": counts["records"],
                 "record_count_matches": counts["records"] == manifest["payload_records"],
                 "compressed_size_matches": archive_path.stat().st_size == manifest["compressed_payload_bytes"],
                 "under_total_cap": archive_path.stat().st_size + manifest_path.stat().st_size <= manifest["configured_total_compressed_bytes"],
                 "plan_hash_matches_current": sha256_file(Path(manifest["market_plan"])) == manifest["market_plan_sha256"]
                 if Path(manifest["market_plan"]).exists() else None}
    return {"manifest": manifest, "integrity": integrity, "quotes": quotes, "trades": trades,
            "counts": counts, "annotations": annotations,
            "source_ages": source_ages, "receipt_times": receipt_times,
            "first_ack": first_ack, "first_quote": first_quote, "first_trade_update": first_trade_update,
            "duplicate_trades": duplicate_trades, "bad_trade_fields": bad_trade_fields,
            "unknown_trade_market": unknown_trade_market}


def discard_prequote_trades(trades, first_quote, counts):
    for (venue, symbol), series in trades.items():
        threshold = first_quote.get((venue, symbol))
        if threshold is None:
            counts[f"{venue}|{symbol}|no_quote_for_trades"] += len(series)
            series.clear()
            continue
        keep = [t for t in series if t["source_ns"] >= threshold]
        counts[f"{venue}|{symbol}|prequote_trade_replays"] += len(series) - len(keep)
        series[:] = keep


def last_quote(quotes, timestamps, at_ns, max_age_ns=SECOND):
    i = bisect.bisect_right(timestamps, at_ns) - 1
    if i < 0:
        return None
    q = quotes[i]
    if at_ns - q["receipt_ns"] > max_age_ns or not 0 <= at_ns - q["source_ns"] <= 2 * SECOND:
        return None
    return q


def first_future_quote(quotes, timestamps, at_ns, max_wait_ns=SECOND):
    """Use an observed quote after a horizon, never a prior favorable book."""
    i = bisect.bisect_left(timestamps, at_ns)
    while i < len(quotes):
        q = quotes[i]
        if q["receipt_ns"] - at_ns > max_wait_ns:
            break
        if q["source_ns"] >= at_ns and 0 <= q["receipt_ns"] - q["source_ns"] <= 2 * SECOND:
            return q
        i += 1
    return None


def candidate_quote(maker, hedge, side, asset, notional=1000):
    p = maker["bid"] if side == "buy" else maker["ask"]
    size = math.floor(notional / p / LOT[asset] + 1e-9) * LOT[asset]
    if size <= 0:
        return None
    hedge_px = hedge["bid"] if side == "buy" else hedge["ask"]
    hedge_size = hedge["bid_size"] if side == "buy" else hedge["ask_size"]
    if hedge_size + 1e-12 < size:
        return None
    gross = ((hedge_px - p) if side == "buy" else (p - hedge_px)) / p * 10_000
    maker_fee = FEES_BPS[maker["venue"]]["maker"]
    hedge_fee = FEES_BPS[hedge["venue"]]["taker"] * hedge_px / p
    exit_fee_hurdle = FEES_BPS[maker["venue"]]["taker"] + FEES_BPS[hedge["venue"]]["taker"]
    return {"maker_price": p, "hedge_price": hedge_px, "qty": size, "gross_entry_bps": gross,
            "entry_after_fees_bps": gross - maker_fee - hedge_fee,
            "after_four_fee_hurdle_bps": gross - maker_fee - hedge_fee - exit_fee_hurdle,
            "maker_fee_bps": maker_fee, "hedge_taker_fee_bps": hedge_fee,
            "exit_two_taker_fee_hurdle_bps": exit_fee_hurdle}


def eligible_flow(trades, source_times, arrival_ns, expiry_ns, side, price, ahead, qty):
    """Trade-through evidence for one non-overlapping window, never a fill."""
    i = bisect.bisect_left(source_times, arrival_ns)
    flow = 0.0
    seen = set()
    first_partial = None
    first_partial_source = None
    while i < len(trades) and trades[i]["source_ns"] < expiry_ns:
        t = trades[i]
        i += 1
        if t["receipt_ns"] < arrival_ns or t["receipt_ns"] >= expiry_ns:
            continue
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        if side == "buy":
            qualifies = not t["buy_aggressor"] and t["price"] <= price + 1e-10
        else:
            qualifies = t["buy_aggressor"] and t["price"] >= price - 1e-10
        if not qualifies:
            continue
        flow += t["qty"]
        if first_partial is None and flow > ahead + 1e-12:
            first_partial = t["receipt_ns"]
            first_partial_source = t["source_ns"]
    return {"trade_flow_qty": flow, "possible_partial": flow > ahead + 1e-12,
            "possible_full": flow >= ahead + qty - 1e-12,
            "first_partial_receipt_ns": first_partial,
            "first_partial_source_ns": first_partial_source}


def require_contiguous_capture(data):
    """This small replay is only valid for one continuous feed generation per venue."""
    generations = Counter(g["venue"] for g in data["manifest"]["generations"])
    if any(generations[v] != 1 for v in ("hyperliquid", "lighter", "rh_lighter")):
        raise RuntimeError("multiple or missing feed generations require an interval-aware replay")
    if (data["counts"]["quality_exclusion_events"] or data["manifest"]["invalidations"]
            or data["manifest"].get("errors")
            or data["unknown_trade_market"] or any(data["bad_trade_fields"].values())):
        raise RuntimeError("feed or trade invalidation requires an interval-aware replay")


def screen(data, arrival_delay_s):
    require_contiguous_capture(data)
    quotes, trades = data["quotes"], data["trades"]
    quote_times = {k: [x["receipt_ns"] for x in a] for k, a in quotes.items()}
    trade_times = {k: [x["source_ns"] for x in a] for k, a in trades.items()}
    manifest = data["manifest"]
    start = int(datetime.fromisoformat(manifest["started_utc"]).timestamp() * SECOND)
    end = int(datetime.fromisoformat(manifest["ended_utc"]).timestamp() * SECOND)
    first_anchor = ((start + 3 * SECOND + 5 * SECOND - 1) // (5 * SECOND)) * (5 * SECOND)
    rows = []
    for maker_venue, hedge_venue in ROUTES:
        for asset in ("BTC", "ETH"):
            mk, hk = (maker_venue, asset), (hedge_venue, asset)
            mq, hq = quotes[mk], quotes[hk]
            mt, ht = quote_times[mk], quote_times[hk]
            ta, ts = trades[mk], trade_times[mk]
            for side in ("buy", "sell"):
                stats = Counter()
                gross_edges, after_fees, ahead_notional, source_skews = [], [], [], []
                for t0 in range(first_anchor, end - 6 * SECOND, 5 * SECOND):
                    stats["anchors"] += 1
                    m, h = last_quote(mq, mt, t0), last_quote(hq, ht, t0)
                    if m is None or h is None:
                        stats["stale_at_decision"] += 1
                        continue
                    skew = abs(m["source_ns"] - h["source_ns"]) / SECOND
                    if skew > 0.5:
                        stats["source_skew_gt_500ms"] += 1
                        continue
                    source_skews.append(skew)
                    quote = candidate_quote(m, h, side, asset)
                    if quote is None:
                        stats["insufficient_top_hedge_depth"] += 1
                        continue
                    stats["quote_supported"] += 1
                    gross_edges.append(quote["gross_entry_bps"])
                    after_fees.append(quote["after_four_fee_hurdle_bps"])
                    if quote["entry_after_fees_bps"] > 0:
                        stats["positive_entry_after_two_fees"] += 1
                    if quote["after_four_fee_hurdle_bps"] > 0:
                        stats["positive_after_four_fee_hurdle"] += 1
                    if quote["after_four_fee_hurdle_bps"] > 5:
                        stats["positive_after_four_fees_plus_5bp"] += 1
                    arrival = t0 + int(arrival_delay_s * SECOND)
                    next_m = last_quote(mq, mt, arrival)
                    if next_m is None:
                        stats["arrival_book_stale"] += 1
                        continue
                    p = quote["maker_price"]
                    current_p = next_m["bid"] if side == "buy" else next_m["ask"]
                    opposite_p = next_m["ask"] if side == "buy" else next_m["bid"]
                    if current_p != p or (side == "buy" and p >= opposite_p) or (side == "sell" and p <= opposite_p):
                        stats["quote_moved_or_post_only_reject"] += 1
                        continue
                    stats["same_price_at_arrival"] += 1
                    ahead = next_m["bid_size"] if side == "buy" else next_m["ask_size"]
                    ahead_notional.append(ahead * p)
                    flow = eligible_flow(ta, ts, arrival, t0 + 5 * SECOND, side, p, ahead, quote["qty"])
                    if flow["possible_partial"]:
                        stats["optimistic_possible_partial"] += 1
                        if quote["after_four_fee_hurdle_bps"] > 0:
                            stats["optimistic_possible_partial_and_fee_positive"] += 1
                        flow_hedge = last_quote(hq, ht, flow["first_partial_receipt_ns"])
                        if (flow_hedge is not None and abs(flow_hedge["source_ns"] - flow["first_partial_source_ns"])
                                <= 0.5 * SECOND):
                            flow_quote = candidate_quote(m, flow_hedge, side, asset)
                            if flow_quote is not None:
                                stats["optimistic_possible_partial_with_fresh_hedge"] += 1
                                if flow_quote["after_four_fee_hurdle_bps"] > 0:
                                    stats["optimistic_possible_partial_with_fresh_fee_positive_hedge"] += 1
                                    if quote["after_four_fee_hurdle_bps"] > 0:
                                        stats["decision_and_flow_hedge_fee_positive_with_partial_signal"] += 1
                    if flow["possible_full"]:
                        stats["optimistic_possible_full"] += 1
                rows.append({"maker": maker_venue, "hedge": hedge_venue, "asset": asset,
                             "side": side, "arrival_delay_s": arrival_delay_s, **stats,
                             "gross_entry_median_bps": percentile(gross_edges, 0.5),
                             "gross_entry_p90_bps": percentile(gross_edges, 0.9),
                             "after_four_fee_hurdle_median_bps": percentile(after_fees, 0.5),
                             "after_four_fee_hurdle_p90_bps": percentile(after_fees, 0.9),
                             "ahead_notional_median_usd": percentile(ahead_notional, 0.5),
                             "ahead_notional_p10_usd": percentile(ahead_notional, 0.1),
                             "source_skew_median_s": percentile(source_skews, 0.5)})
    return rows


def four_taker_control(data):
    """Predeclared displayed-book 1/2/5/10s markouts; no actual fills."""
    require_contiguous_capture(data)
    quotes = data["quotes"]
    times = {key: [x["receipt_ns"] for x in series] for key, series in quotes.items()}
    manifest = data["manifest"]
    start = int(datetime.fromisoformat(manifest["started_utc"]).timestamp() * SECOND)
    end = int(datetime.fromisoformat(manifest["ended_utc"]).timestamp() * SECOND)
    first = ((start + 3 * SECOND + SECOND - 1) // SECOND) * SECOND
    rows = []
    for other in ("lighter", "rh_lighter"):
        for asset in ("BTC", "ETH"):
            for long_venue, short_venue in (("hyperliquid", other), (other, "hyperliquid")):
                lk, sk = (long_venue, asset), (short_venue, asset)
                lq, sq = quotes[lk], quotes[sk]
                lt, st = times[lk], times[sk]
                for horizon in (1, 2, 5, 10):
                    counts = Counter()
                    gross_values, net_values, fees_values, elapsed_values = [], [], [], []
                    for t0 in range(first, end - (horizon + 2) * SECOND, SECOND):
                        counts["anchors"] += 1
                        entry_long = last_quote(lq, lt, t0)
                        entry_short = last_quote(sq, st, t0)
                        if entry_long is None or entry_short is None:
                            counts["missing_or_stale_entry"] += 1
                            continue
                        if abs(entry_long["source_ns"] - entry_short["source_ns"]) > 0.5 * SECOND:
                            counts["entry_source_skew_gt_500ms"] += 1
                            continue
                        q = math.floor(1000 / entry_long["ask"] / LOT[asset] + 1e-9) * LOT[asset]
                        if q <= 0 or q > entry_long["ask_size"] + 1e-12 or q > entry_short["bid_size"] + 1e-12:
                            counts["insufficient_entry_top_depth"] += 1
                            continue
                        counts["entry_qualified"] += 1
                        target = t0 + horizon * SECOND
                        exit_long = first_future_quote(lq, lt, target)
                        exit_short = first_future_quote(sq, st, target)
                        if exit_long is None or exit_short is None:
                            counts["missing_future_quote"] += 1
                            continue
                        if abs(exit_long["source_ns"] - exit_short["source_ns"]) > 0.5 * SECOND or abs(
                                exit_long["receipt_ns"] - exit_short["receipt_ns"]) > 0.5 * SECOND:
                            counts["future_quote_skew_gt_500ms"] += 1
                            continue
                        if q > exit_long["bid_size"] + 1e-12 or q > exit_short["ask_size"] + 1e-12:
                            counts["insufficient_exit_top_depth"] += 1
                            continue
                        counts["complete_same_quantity_books"] += 1
                        initial = q * entry_long["ask"]
                        gross_cash = q * ((exit_long["bid"] - entry_long["ask"])
                                          + (entry_short["bid"] - exit_short["ask"]))
                        fee_cash = q * (FEES_BPS[long_venue]["taker"] * (entry_long["ask"] + exit_long["bid"])
                                        + FEES_BPS[short_venue]["taker"] * (entry_short["bid"] + exit_short["ask"])) / 10_000
                        gross = gross_cash / initial * 10_000
                        net = (gross_cash - fee_cash) / initial * 10_000
                        gross_values.append(gross)
                        net_values.append(net)
                        fees_values.append(fee_cash / initial * 10_000)
                        elapsed_values.append((max(exit_long["receipt_ns"], exit_short["receipt_ns"]) - t0) / SECOND)
                        if net > 0:
                            counts["positive_displayed_net"] += 1
                    rows.append({"long": long_venue, "short": short_venue, "asset": asset,
                                 "horizon_s": horizon, **counts,
                                 "gross_median_bps": percentile(gross_values, 0.5),
                                 "net_median_bps": percentile(net_values, 0.5),
                                 "net_p90_bps": percentile(net_values, 0.9),
                                 "net_min_bps": min(net_values) if net_values else None,
                                 "four_taker_fee_median_bps": percentile(fees_values, 0.5),
                                 "actual_exit_receipt_elapsed_median_s": percentile(elapsed_values, 0.5),
                                 "actual_exit_receipt_elapsed_max_s": max(elapsed_values) if elapsed_values else None})
    return rows


def summarize_audit(data):
    summary = []
    for key, times in sorted(data["receipt_times"].items()):
        venue, market, channel = key
        if len(times) < 2:
            continue
        gaps = [(b - a) / SECOND for a, b in zip(times, times[1:])]
        ages = data["source_ages"][(venue, market, channel)]
        summary.append({"venue": venue, "market": market, "channel": channel,
                        "messages_with_source": len(times), "median_receipt_gap_s": percentile(gaps, 0.5),
                        "p99_receipt_gap_s": percentile(gaps, 0.99), "max_receipt_gap_s": max(gaps),
                        "median_receipt_minus_source_s": percentile(ages, 0.5),
                        "p99_receipt_minus_source_s": percentile(ages, 0.99),
                        "negative_receipt_minus_source_count": sum(x < 0 for x in ages)})
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    data = archive_load(args.capture)
    integrity = data["integrity"]
    if not all(integrity[k] for k in ("record_count_matches", "compressed_size_matches", "under_total_cap")):
        raise RuntimeError("archive integrity failure")
    rows = [r for delay in (0.5, 1.0, 3.0) for r in screen(data, delay)]
    control = four_taker_control(data)
    report = {"source_archive": str(args.capture), "integrity": integrity,
              "manifest_end_reason": data["manifest"]["end_reason"],
              "manifest_truncated": data["manifest"]["truncated"],
              "manifest_generations": data["manifest"]["generations"],
              "manifest_invalidations": data["manifest"]["invalidations"],
              "unknown_market_invalid_hl_trade_frames": data["unknown_trade_market"],
              "quality_exclusion_events": data["counts"]["quality_exclusion_events"],
              "duplicate_trade_ids": {str(k): v for k, v in data["duplicate_trades"].items()},
              "bad_trade_fields": {str(k): v for k, v in data["bad_trade_fields"].items()},
              "startup_trade_snapshot_counts": {k: v for k, v in data["counts"].items() if "startup_trade_snapshot" in k},
              "prequote_trade_replays": {k: v for k, v in data["counts"].items() if "prequote_trade_replays" in k},
              "kept_live_trade_counts": {str(k): len(v) for k, v in data["trades"].items()},
              "quote_counts": {str(k): len(v) for k, v in data["quotes"].items()},
              "feed_audit": summarize_audit(data), "screen_rows": rows,
              "four_taker_control_rows": control,
              "assumptions": {"maker_fee_bps": FEES_BPS, "fixed_notional_usd": 1000,
                              "lot_by_asset": LOT, "decision_grid_s": 5,
                              "quote_receipt_age_max_s": 1, "quote_source_age_max_s": 2,
                              "cross_venue_source_difference_max_s": 0.5,
                              "arrival_delays_s": [0.5, 1, 3], "trade_observation_window_end": "next 5s grid point",
                              "quote_hurdle": "maker entry fee + opposite taker entry fee + two taker exit fees; no exit spread/impact, funding, financing, conversion or unhedged risk",
                              "classification": "possible trade-through only, not actual queue position, fill, or P&L"}}
    report["assumptions"]["four_taker_control"] = (
        "Fixed base q of about $1,000, complete one-level entry and first future books, horizons 1/2/5/10s, "
        "at most one anchor per second per route, own-notional four taker fees, missing excluded rather than zero; "
        "displayed-book markout only, no fills or conversion/funding/financing")
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    with (args.out / "screen.csv").open("w", newline="") as f:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with (args.out / "four_taker_control.csv").open("w", newline="") as f:
        fields = list(dict.fromkeys(key for row in control for key in row))
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(control)
    print(args.out)
    print(f"records={integrity['decoded_records']} rows={len(rows)} unknown_hl_trades={data['unknown_trade_market']}")


if __name__ == "__main__":
    main()
