#!/usr/bin/env python3
"""Stopped-pilot RH bid queue diagnostic; observed prints are not fills."""
from __future__ import annotations

import gzip
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rh_maker_events import iter_events  # noqa: E402

CAPTURE = ROOT / "data/raw/rh-small-maker/20260929T212132Z"
AUDIT = ROOT / "data/derived/rh-small-maker-v1-cached/audit.jsonl.gz"
ANALYSIS = ROOT / "reports/rh-small-maker-v1/cached-analysis.json.gz"
OUT = ROOT / "reports/rh-entry-queue-followup/diagnostics.json"
ASSETS = ("BTC", "ETH")
TIERS = ("standard", "premium")
TICKS = {"BTC": Decimal("0.1"), "ETH": Decimal("0.01")}
NS = 1_000_000_000


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def collect_audit():
    analysis = json.load(gzip.open(ANALYSIS, "rt"))
    if analysis["audit_sha256"] != digest(AUDIT):
        raise ValueError("cached audit SHA mismatch")
    events = defaultdict(list)
    with gzip.open(AUDIT, "rt") as f:
        for line in f:
            x = json.loads(line)
            if (x.get("asset") in ASSETS and x.get("tier") in TIERS
                    and x.get("policy") == "fixed_best" and x.get("budget_usd") == 1000):
                events[(x["asset"], x["tier"])].append(x)
    intervals = defaultdict(list)
    counters = {}
    unknowns = {}
    for key, rows in events.items():
        pending = active = None
        counters[key] = Counter(x["event"] for x in rows)
        for row in rows:
            typ = row["event"]
            if typ == "quote_requested":
                if pending is not None or active is not None:
                    raise ValueError("overlapping quote requests")
                pending = row
            elif typ == "activated":
                if pending is None or active is not None:
                    raise ValueError("activation without pending quote")
                active = {"asset": key[0], "tier": key[1], "decision_ns": pending["ns"],
                          "activation_ns": row["ns"], "due_ns": pending["due_ns"],
                          "price": pending["price"], "qty": pending["qty"],
                          "ahead_same": row["ahead_same"], "ahead_better": row["ahead_better"]}
                pending = None
            elif typ == "post_only_reject":
                pending = None
            elif typ in ("cancel_effective", "unknown"):
                if active is not None:
                    active["end_ns"] = row["ns"]
                    active["end_reason"] = row.get("reason") or typ
                    intervals[key].append(active)
                    active = None
                if typ == "unknown":
                    unknowns[key] = row
                    pending = None
        if active is not None:
            raise ValueError("unclosed audit activation")
    return intervals, counters, unknowns, analysis


def collect_public(intervals):
    targets = {asset: sorted({x[k] for tier in TIERS for x in intervals[(asset, tier)]
                              for k in ("decision_ns", "activation_ns")}) for asset in ASSETS}
    positions = {a: 0 for a in ASSETS}
    latest = {a: None for a in ASSETS}
    book_at = {a: {} for a in ASSETS}
    sells = defaultdict(list)
    first = min(x["decision_ns"] for group in intervals.values() for x in group)
    last = max(x["end_ns"] for group in intervals.values() for x in group)
    end = None
    for event in iter_events(CAPTURE):
        typ = event["type"]
        if typ == "end":
            end = event
            break
        now = event["received_ns"]
        if now < first - 2 * NS:
            continue
        if now > last + 2 * NS:
            continue
        for asset in ASSETS:
            ts = targets[asset]
            while positions[asset] < len(ts) and ts[positions[asset]] < now:
                book_at[asset][ts[positions[asset]]] = latest[asset]
                positions[asset] += 1
        asset = event.get("asset")
        if asset not in ASSETS or event.get("venue") != "rh_lighter":
            continue
        if typ == "book":
            latest[asset] = event
        elif typ == "invalidate" and event.get("scope") in ("book", "all"):
            latest[asset] = None
        elif typ == "trade" and event.get("side") == "sell":
            sells[asset].append(event)
    if end is None or end["truncated"] or not end["raw_sha_verified"]:
        raise ValueError("stopped raw archive failed final verification")
    for asset in ASSETS:
        ts = targets[asset]
        while positions[asset] < len(ts):
            book_at[asset][ts[positions[asset]]] = latest[asset]
            positions[asset] += 1
    return book_at, sells


def score(intervals, books, sells, counters, unknowns, analysis):
    grouped = {}
    for key, cases in intervals.items():
        asset, tier = key
        diagnostics = Counter()
        same = []
        durations = []
        trade_distances = []
        improved_cases = 0
        candidate_extra_prints = 0
        candidate_extra_qty = Decimal(0)
        candidate_extra_closed_prints = 0
        extra_examples = []
        for case in cases:
            decision = books[asset].get(case["decision_ns"])
            activation = books[asset].get(case["activation_ns"])
            p, tick, q = Decimal(case["price"]), TICKS[asset], Decimal(case["qty"])
            same.append(Decimal(case["ahead_same"]))
            durations.append((case["end_ns"] - case["activation_ns"]) / NS)
            if not decision or not activation:
                diagnostics["missing_decision_or_activation_book"] += 1
                continue
            if (decision["received_ns"] > case["decision_ns"] or
                    activation["received_ns"] > case["activation_ns"]):
                raise ValueError("future book joined to audit decision")
            if (case["decision_ns"] - decision["received_ns"] > 2 * NS or
                    case["activation_ns"] - activation["received_ns"] > 2 * NS):
                diagnostics["book_over_2s_receipt_age"] += 1
                continue
            bid = Decimal(str(decision["bids"][0][0]))
            ask = Decimal(str(decision["asks"][0][0]))
            activation_ask = Decimal(str(activation["asks"][0][0]))
            if p != bid:
                diagnostics["quoted_price_differs_from_decision_best"] += 1
            improved = p + tick
            if improved >= ask:
                diagnostics["improved_would_cross_decision_ask"] += 1
                continue
            if improved >= activation_ask:
                diagnostics["improved_would_cross_activation_ask"] += 1
                continue
            improved_cases += 1
            ahead_improved = sum((Decimal(str(sz)) for px, sz in activation["bids"]
                                  if Decimal(str(px)) == improved), Decimal(0))
            if ahead_improved == 0:
                diagnostics["improved_same_price_queue_zero"] += 1
            eligible = [t for t in sells[asset]
                        if case["activation_ns"] <= t["received_ns"] <= case["end_ns"]
                        and t["source_ns"] >= activation["source_ns"]]
            old = [t for t in eligible if Decimal(str(t["price"])) <= p]
            better = [t for t in eligible if p < Decimal(str(t["price"])) <= improved]
            if old:
                diagnostics["old_bid_at_or_through_print_case"] += 1
            if better:
                diagnostics["extra_one_tick_print_case"] += 1
                for t in better[:3]:
                    if len(extra_examples) < 3:
                        extra_examples.append({"trade_id": t["trade_id"],
                                               "price": str(t["price"]), "qty": str(t["qty"]),
                                               "source_ns": t["source_ns"],
                                               "receipt_ns": t["received_ns"],
                                               "quote_price": str(p), "quote_qty": str(q),
                                               "activation_ns": case["activation_ns"],
                                               "interval_end_reason": case["end_reason"]})
            candidate_extra_prints += len(better)
            if case["end_ns"] != unknowns[key]["ns"]:
                candidate_extra_closed_prints += len(better)
            candidate_extra_qty += sum((Decimal(str(t["qty"])) for t in better), Decimal(0))
            diagnostics["old_bid_at_or_through_prints"] += len(old)
            diagnostics["old_bid_at_or_through_qty_milli"] += int(sum(Decimal(str(t["qty"])) for t in old) * 1000)
            for t in eligible:
                trade_distances.append((Decimal(str(t["price"])) - p) / p * 10_000)
            total_at_improved = sum((Decimal(str(t["qty"])) for t in old + better), Decimal(0))
            if total_at_improved > ahead_improved:
                diagnostics["improved_queue_exhaust_possible_case"] += 1
            if total_at_improved >= ahead_improved + q:
                diagnostics["improved_full_flow_possible_case"] += 1
        grouped[f"{tier}:{asset}"] = {
            "activated_intervals": len(cases), "active_seconds_receipt_to_cancel_or_unknown": sum(durations),
            "median_active_seconds": statistics.median(durations) if durations else None,
            "same_price_queue_median_base": str(statistics.median(same)) if same else None,
            "same_price_queue_zero": sum(x == 0 for x in same),
            "source_valid_trade_distance_median_bps": str(statistics.median(trade_distances)) if trade_distances else None,
            "source_valid_trade_distance_min_bps": str(min(trade_distances)) if trade_distances else None,
            "source_valid_sell_print_count": len(trade_distances),
            "one_tick_passive_at_decision_and_activation_cases": improved_cases,
            "one_tick_extra_price_band_prints": candidate_extra_prints,
            "one_tick_extra_price_band_prints_closed_intervals": candidate_extra_closed_prints,
            "one_tick_extra_price_band_qty": str(candidate_extra_qty),
            "one_tick_extra_price_band_examples": extra_examples,
            "audit_events": dict(counters[key]), "unknown_reason": unknowns[key].get("reason"),
            "diagnostics": dict(diagnostics)}
    return grouped


def main():
    intervals, counters, unknowns, analysis = collect_audit()
    books, sells = collect_public(intervals)
    groups = score(intervals, books, sells, counters, unknowns, analysis)
    result = {"scope": "stopped cached RH-maker pilot, fixed-best BTC/ETH $1000 only",
              "raw_capture_sha256": json.loads((CAPTURE / "manifest.json").read_text())["frames_sha256"],
              "cached_audit_sha256": digest(AUDIT), "one_tick_bps_at_reference_price":
              {"BTC_at_83400": str(TICKS["BTC"] / Decimal(83400) * 10_000),
               "ETH_at_2676": str(TICKS["ETH"] / Decimal(2676) * 10_000)},
              "groups": groups,
              "warning": "Retrospective public price-band observations only; adding an order changes queue and flow; no hypothetical fill or P&L is inferred."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(groups, indent=2))


if __name__ == "__main__":
    main()
