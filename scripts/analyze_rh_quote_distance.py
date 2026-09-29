#!/usr/bin/env python3
"""Public RH trade-flow diagnostic for a fixed bid/ask quote-distance ladder.

Stopped archives only. Flow past a hypothetical price is not an actual fill.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rh_maker_events import iter_events  # noqa: E402

CAPTURES = (ROOT / "data/raw/maker-capture/20260929T1939Z",
            ROOT / "data/raw/maker-capture/20260929T2022Z")
META = ROOT / "data/raw/rh-maker-metadata/20260929T210845Z/normalized.json"
OUT = ROOT / "reports/rh-quote-distance-flow"
NS = 1_000_000_000
OFFSETS = (0, 2, 5, 10, 20)
SIZES = (100, 250, 500, 1000)
SPACING = 12 * NS
WINDOW = 10 * NS
ACTIVATION = 300_000_000
GRACE = 2 * NS
MAX_BOOK_GAP = 2 * NS


def D(x):
    return Decimal(str(x))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ladder_price(best, offset_bps, tick, side):
    unrounded = D(best) * (1 - D(offset_bps) / 10_000 if side == "bid"
                             else 1 + D(offset_bps) / 10_000)
    unit = D(tick)
    rounding = ROUND_FLOOR if side == "bid" else ROUND_CEILING
    return (unrounded / unit).to_integral_value(rounding=rounding) * unit


def quote_qty(budget, price, step):
    unit = D(step)
    return (D(budget) / price / unit).to_integral_value(rounding=ROUND_FLOOR) * unit


def trade_eligible(trade, side, price):
    return ((side == "bid" and trade["side"] == "sell" and D(trade["price"]) <= price)
            or (side == "ask" and trade["side"] == "buy" and D(trade["price"]) >= price))


def first_queue(book, side, price):
    other = D(book["asks"][0][0]) if side == "bid" else D(book["bids"][0][0])
    if (side == "bid" and price >= other) or (side == "ask" and price <= other):
        return None  # Would cross the observed opposite side on activation.
    levels = book["bids"] if side == "bid" else book["asks"]
    return sum((D(q) for p, q in levels if D(p) == price), Decimal(0))


def make_branches(asset, anchor, book, meta):
    branches = []
    for side in ("bid", "ask"):
        best = book["bids"][0][0] if side == "bid" else book["asks"][0][0]
        for offset in OFFSETS:
            price = ladder_price(best, offset, meta["price_tick"], side)
            for budget in SIZES:
                q = quote_qty(budget, price, meta["size_step"])
                reason = None
                if q < D(meta["min_qty"]) or q * price < D(meta["min_notional"]):
                    reason = "size_or_minimum"
                branches.append({"asset": asset, "anchor_ns": anchor, "side": side,
                                 "offset_bps": offset, "budget_usd": budget,
                                 "quote_price": price, "quantity": q,
                                 "ahead_qty": None, "at_qty": Decimal(0),
                                 "through_qty": Decimal(0), "qualified_flow_qty": Decimal(0),
                                 "possible_qty": Decimal(0), "touch_count": 0,
                                 "reason": reason})
    return branches


def observe_trade(branch, trade, activation_source_ns, activation_receipt_ns, due_ns, end_ns):
    if branch["reason"] or not trade_eligible(trade, branch["side"], branch["quote_price"]):
        return
    source, receipt = trade["source_ns"], trade["received_ns"]
    if source < due_ns or source > end_ns:
        return
    if source < activation_source_ns or receipt < activation_receipt_ns or receipt - source > GRACE:
        branch["reason"] = "ambiguous_trade_clock_or_queue_initialization"
        return
    qty = D(trade["qty"])
    branch["touch_count"] += 1
    if D(trade["price"]) == branch["quote_price"]:
        branch["at_qty"] += qty
    else:
        branch["through_qty"] += qty
    branch["qualified_flow_qty"] += qty
    branch["possible_qty"] = min(branch["quantity"],
                                  max(Decimal(0), branch["qualified_flow_qty"] - branch["ahead_qty"]))


def close_episode(ep, now, rows):
    if ep is None:
        return
    if ep["activation_book_ns"] is None:
        for b in ep["branches"]:
            if not b["reason"]:
                b["reason"] = "no_advanced_activation_book"
    elif ep["last_book_ns"] < ep["end_ns"] - MAX_BOOK_GAP:
        for b in ep["branches"]:
            if not b["reason"]:
                b["reason"] = "book_gap_or_stale_at_window_end"
    for b in ep["branches"]:
        possible = b["possible_qty"]
        rows.append({k: str(b[k]) if isinstance(b[k], Decimal) else b[k]
                     for k in ("asset", "anchor_ns", "side", "offset_bps", "budget_usd",
                               "quote_price", "quantity", "ahead_qty", "at_qty", "through_qty",
                               "qualified_flow_qty", "possible_qty", "touch_count", "reason")})


def analyze_capture(capture, metadata):
    manifest = json.loads((capture / "manifest.json").read_text())
    if manifest.get("end_reason") != "duration_limit" or manifest.get("truncated"):
        raise ValueError("archive is not a stopped complete duration-limit capture")
    assets = set(manifest["selected_markets"]["rh_lighter"])
    digest = sha(capture / "frames.jsonl.gz")
    episodes = {asset: None for asset in assets}
    last_anchor = {asset: -10**30 for asset in assets}
    rows = []
    counts = Counter()
    end = None
    for event in iter_events(capture, expected_raw_sha256=digest):
        typ = event["type"]
        if typ == "end":
            end = event
            break
        now = event["received_ns"]
        for asset in assets:
            ep = episodes[asset]
            if ep and now > ep["end_ns"] + GRACE:
                close_episode(ep, now, rows)
                episodes[asset] = None
        asset = event.get("asset")
        if asset not in assets or event.get("venue") != "rh_lighter":
            continue
        ep = episodes[asset]
        if typ == "invalidate":
            if ep and now <= ep["end_ns"] + GRACE:
                for b in ep["branches"]:
                    if not b["reason"]:
                        b["reason"] = "feed_invalidation"
            continue
        if typ == "trade":
            if not ep or now > ep["end_ns"] + GRACE:
                continue
            if ep["activation_book_ns"] is None:
                ep["pre_activation_trades"].append(event)
            else:
                for b in ep["branches"]:
                    observe_trade(b, event, ep["activation_source_ns"], ep["activation_book_ns"],
                                  ep["due_ns"], ep["end_ns"])
            continue
        if typ != "book" or not event.get("valid"):
            continue
        source = event.get("source_ns")
        if not isinstance(source, int) or source > now or now - source > GRACE:
            if ep:
                for b in ep["branches"]:
                    if not b["reason"]:
                        b["reason"] = "book_clock_invalid_or_stale"
            continue
        if ep:
            if ep["last_book_ns"] is not None and now - ep["last_book_ns"] > MAX_BOOK_GAP:
                for b in ep["branches"]:
                    if not b["reason"]:
                        b["reason"] = "book_gap"
            if event["generation"] != ep["generation"]:
                for b in ep["branches"]:
                    if not b["reason"]:
                        b["reason"] = "book_generation_change"
            ep["last_book_ns"] = now
            if ep["activation_book_ns"] is None and now >= ep["due_ns"] and source >= ep["due_ns"]:
                if now > ep["due_ns"] + MAX_BOOK_GAP:
                    for b in ep["branches"]:
                        if not b["reason"]:
                            b["reason"] = "activation_observation_delayed"
                ep["activation_book_ns"] = now
                ep["activation_source_ns"] = source
                for b in ep["branches"]:
                    if b["reason"]:
                        continue
                    b["ahead_qty"] = first_queue(event, b["side"], b["quote_price"])
                    if b["ahead_qty"] is None:
                        b["reason"] = "marketable_at_activation"
                for trade in ep["pre_activation_trades"]:
                    for b in ep["branches"]:
                        observe_trade(b, trade, source, now, ep["due_ns"], ep["end_ns"])
                ep["pre_activation_trades"].clear()
            continue
        if now - last_anchor[asset] < SPACING or not event["bids"] or not event["asks"]:
            continue
        if D(event["bids"][0][0]) >= D(event["asks"][0][0]):
            continue
        last_anchor[asset] = now
        counts["anchors"] += 1
        episodes[asset] = {"generation": event["generation"], "due_ns": now + ACTIVATION,
                           "end_ns": now + WINDOW, "last_book_ns": now,
                           "activation_book_ns": None, "activation_source_ns": None,
                           "pre_activation_trades": [],
                           "branches": make_branches(asset, now, event, metadata[asset])}
    if end is None or end["truncated"] or not end["raw_sha_verified"]:
        raise ValueError("archive did not end cleanly with verified raw SHA")
    for ep in episodes.values():
        if ep:
            for b in ep["branches"]:
                if not b["reason"]:
                    b["reason"] = "archive_end_before_window_complete"
            close_episode(ep, end["received_ns"], rows)
    return rows, dict(counts), {"capture": str(capture.relative_to(ROOT)), "sha256": digest,
                                "adapter_counts": end["counts"]}


def summarize(rows):
    out = defaultdict(Counter)
    for r in rows:
        key = (r["asset"], r["side"], r["offset_bps"], r["budget_usd"])
        c = out[key]
        c["anchors"] += 1
        if r["reason"]:
            c["censored"] += 1
            c["reason:" + r["reason"]] += 1
            continue
        c["complete"] += 1
        if r["touch_count"]:
            c["touch"] += 1
        possible, q = D(r["possible_qty"]), D(r["quantity"])
        if possible > 0:
            c["possible_partial_or_full"] += 1
        if possible >= q and q > 0:
            c["possible_full"] += 1
        if D(r["through_qty"]) > 0:
            c["through_print"] += 1
    return [{"asset": key[0], "side": key[1], "offset_bps": key[2],
             "budget_usd": key[3], **dict(value)} for key, value in sorted(out.items())]


def main():
    metadata = json.loads(META.read_text())["markets"]["rh_lighter"]
    all_rows, sources = [], []
    for capture in CAPTURES:
        rows, _, source = analyze_capture(capture, metadata)
        all_rows.extend(rows)
        sources.append(source)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "rows.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    result = {"method": "fixed RH bid/ask ladder; public flow only, not fills",
              "offsets_bps": OFFSETS, "budgets_usd": SIZES,
              "window_ns": WINDOW, "activation_ns": ACTIVATION,
              "max_book_gap_ns": MAX_BOOK_GAP, "source_receipt_grace_ns": GRACE,
              "sources": sources, "metadata_sha256": sha(META),
              "script_sha256": sha(Path(__file__)), "rows_sha256": sha(path),
              "summary": summarize(all_rows)}
    (OUT / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"{len(all_rows)} rows, {len(result['summary'])} groups -> {OUT}")


if __name__ == "__main__":
    main()
