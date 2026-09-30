#!/usr/bin/env python3
"""Read-only RH two-maker / HL-versus-Core taker hedge quote comparison.

Inputs are the stopped BTC/ETH and NVDA/XAG archives used by
analyze_hedge_venue_hurdle.py. No public request, order, or capture occurs.
The static case assumes both RH maker fills at one unchanged book; the delayed
case uses the first fresh matched tri-venue book 10-16 seconds later. Neither
case observes an RH maker fill or queue priority.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.analyze_hedge_venue_hurdle import (
    CRYPTO_CAPTURE, NS, ROOT, RWA, SIZES,
    common_step, dec, file_sha, hl_anchors,
    iter_crypto_books, iter_jsonl_gz, matched_stream, quantity, utc_ns, walk,
)

ASSETS = ("BTC", "ETH", "NVDA", "XAG")
SIDES = ("buy_rh", "sell_rh")
STAGES = ("static", "delayed")
TARGET = Decimal("0.10")
RESERVE_BPS = Decimal(5)
CAPITAL_ANNUAL = Decimal("0.05")
MAX_ROWS = 10_000


def plan_metadata(manifest):
    """Use market limits and fees frozen with the capture, not a later survey."""
    path = Path(manifest["market_plan"])
    if not path.is_file() or file_sha(path) != manifest["market_plan_sha256"]:
        raise ValueError("pre-capture market plan hash mismatch")
    plan = json.loads(path.read_text())
    markets = {venue: {} for venue in ("rh_lighter", "hyperliquid", "lighter")}
    for pair in plan["pairs"]:
        asset = pair["asset"]
        for source in (pair["hl"], pair["other"]):
            venue = source["venue"]
            spec = {"size_step": source["step"], "min_qty": source.get("min_qty"),
                    "min_notional": source["min_notional"], "max_qty": None,
                    "taker_fee_bps": source["fee_bps"]}
            previous = markets[venue].get(asset)
            if previous is not None and previous != spec:
                raise ValueError(f"conflicting frozen market metadata: {asset}/{venue}")
            markets[venue][asset] = spec
    return markets, path


def valid_quantity(q, books, metadata):
    """One quantity satisfies all three venues' size/minimum limits."""
    if q <= 0:
        return False
    for venue in ("rh_lighter", "hyperliquid", "lighter"):
        spec = metadata[venue]
        step = dec(spec["size_step"])
        if q % step or q < dec(spec.get("min_qty") or step):
            return False
        if spec.get("max_qty") is not None and q > dec(spec["max_qty"]):
            return False
        book = books[venue]
        if not book.get("bids") or not book.get("asks"):
            return False
        if dec(book["bids"][0][0]) <= 0 or dec(book["asks"][0][0]) <= dec(book["bids"][0][0]):
            return False
        if any(q * dec(book[side][0][0]) < dec(spec["min_notional"])
               for side in ("bids", "asks")):
            return False
    return True


def delayed_observation(observations, times, anchor):
    """First matched quote whose every venue source and receipt follows due."""
    due = anchor + 10 * NS
    ix = bisect.bisect_left(times, due)
    while ix < len(observations) and times[ix] <= anchor + 16 * NS:
        observed, books = observations[ix]
        if all(books[venue][field] >= due
               for venue in ("rh_lighter", "hyperliquid", "lighter")
               for field in ("source_utc_ns", "receipt_utc_ns")):
            return observed, books
        ix += 1
    return None


def cycle(q, side, rh_entry, rh_exit, hedge_entry, hedge_exit, hedge_fee_bps,
          seconds=0):
    """Cashflows use own fill notionals; RH maker fee is Standard 0 bp."""
    q = dec(q)
    rh_in = q * dec(rh_entry["rh_lighter"]["bids" if side == "buy_rh" else "asks"][0][0])
    rh_out = q * dec(rh_exit["rh_lighter"]["asks" if side == "buy_rh" else "bids"][0][0])
    hedge_in = walk(hedge_entry["bids" if side == "buy_rh" else "asks"], q)
    hedge_out = walk(hedge_exit["asks" if side == "buy_rh" else "bids"], q)
    if hedge_in is None or hedge_out is None:
        return None
    if side == "buy_rh":
        gross = -rh_in + hedge_in + rh_out - hedge_out
    else:
        gross = rh_in - hedge_in - rh_out + hedge_out
    fee = (hedge_in + hedge_out) * dec(hedge_fee_bps) / 10_000
    reserve = max(rh_in, hedge_in) * RESERVE_BPS / 10_000
    capital = (rh_in + hedge_in) * CAPITAL_ANNUAL * dec(seconds) / dec(365 * 86400)
    fee_only = gross - fee - capital
    return {"gross": gross, "fee": fee, "capital": capital,
            "reserve": reserve, "fee_only": fee_only,
            "stress": fee_only - reserve,
            "rh_entry": rh_in, "rh_exit": rh_out,
            "hedge_entry": hedge_in, "hedge_exit": hedge_out}


def analyze_dataset(assets, anchors_by_asset, matched_by_asset, metadata):
    rows = []
    coverage = Counter()
    for asset in assets:
        specs = {venue: metadata[venue][asset]
                 for venue in ("rh_lighter", "hyperliquid", "lighter")}
        step = common_step(*(spec["size_step"] for spec in specs.values()))
        obs = matched_by_asset[asset]
        times = [t for t, _ in obs]
        exact = {t: books for t, books in obs}
        for anchor in anchors_by_asset[asset]:
            entry = exact.get(anchor)
            delayed = delayed_observation(obs, times, anchor)
            for budget in SIZES:
                for side in SIDES:
                    for stage in STAGES:
                        key = (stage, asset, budget, side)
                        coverage[key, "anchors"] += 1
                        if entry is None:
                            coverage[key, "entry_unmatched"] += 1
                            continue
                        coverage[key, "entry_matched"] += 1
                        if stage == "delayed" and delayed is None:
                            coverage[key, "exit_unmatched"] += 1
                            continue
                        exit_time, exit_books = (anchor, entry) if stage == "static" else delayed
                        q = quantity(budget, entry["rh_lighter"]["asks"][0][0], step)
                        if not valid_quantity(q, entry, specs) or not valid_quantity(q, exit_books, specs):
                            coverage[key, "size_invalid"] += 1
                            continue
                        seconds = Decimal(exit_time - anchor) / NS
                        h = cycle(q, side, entry, exit_books, entry["hyperliquid"],
                                  exit_books["hyperliquid"],
                                  specs["hyperliquid"]["taker_fee_bps"], seconds)
                        c = cycle(q, side, entry, exit_books, entry["lighter"],
                                  exit_books["lighter"], 0, seconds)
                        if h is None or c is None:
                            coverage[key, "hedge_depth_missing"] += 1
                            continue
                        coverage[key, "complete_common"] += 1
                        row = {"stage": stage, "asset": asset, "budget_usd": budget,
                               "side": side, "anchor_ns": anchor, "exit_ns": exit_time,
                               "q": str(q), "rh_bid_entry": str(entry["rh_lighter"]["bids"][0][0]),
                               "rh_ask_entry": str(entry["rh_lighter"]["asks"][0][0]),
                               "rh_bid_exit": str(exit_books["rh_lighter"]["bids"][0][0]),
                               "rh_ask_exit": str(exit_books["rh_lighter"]["asks"][0][0]),
                               "hl_fee_bps_per_taker": str(specs["hyperliquid"]["taker_fee_bps"]),
                               "core_fee_bps_per_taker": "0"}
                        for label, result in (("hl", h), ("core", c)):
                            row.update({f"{label}_{name}": str(value)
                                        for name, value in result.items()})
                            for gate in ("fee_only", "stress"):
                                row[f"{label}_{gate}_positive"] = result[gate] > 0
                                row[f"{label}_{gate}_target"] = result[gate] >= TARGET
                        row["core_minus_hl_fee_only"] = str(c["fee_only"] - h["fee_only"])
                        row["core_minus_hl_stress"] = str(c["stress"] - h["stress"])
                        rows.append(row)
                        if len(rows) > MAX_ROWS:
                            raise ValueError("matched row bound exceeded")
    return rows, coverage


def summarize(rows, coverage):
    groups = {}
    for stage in STAGES:
        for asset in ASSETS:
            for budget in SIZES:
                for side in SIDES:
                    key = (stage, asset, budget, side)
                    subset = [r for r in rows if (r["stage"], r["asset"], r["budget_usd"], r["side"]) == key]
                    diffs = [dec(r["core_minus_hl_fee_only"]) for r in subset]
                    entry = {"anchors": coverage[key, "anchors"],
                             "entry_matched": coverage[key, "entry_matched"],
                             "entry_unmatched": coverage[key, "entry_unmatched"],
                             "exit_unmatched": coverage[key, "exit_unmatched"],
                             "size_invalid": coverage[key, "size_invalid"],
                             "hedge_depth_missing": coverage[key, "hedge_depth_missing"],
                             "complete_common": coverage[key, "complete_common"]}
                    groups[":".join(map(str, key))] = {
                        "coverage": entry,
                        "median_core_minus_hl_fee_only_usd": str(median(diffs)) if diffs else None,
                        "core_better_fee_only": sum(x > 0 for x in diffs),
                        "hl_better_fee_only": sum(x < 0 for x in diffs),
                        "core": {gate: {"positive": sum(r[f"core_{gate}_positive"] for r in subset),
                                        "target": sum(r[f"core_{gate}_target"] for r in subset),
                                        "median_usd": str(median(dec(r[f"core_{gate}"]) for r in subset))
                                        if subset else None}
                                 for gate in ("fee_only", "stress")},
                        "hl": {gate: {"positive": sum(r[f"hl_{gate}_positive"] for r in subset),
                                      "target": sum(r[f"hl_{gate}_target"] for r in subset),
                                      "median_usd": str(median(dec(r[f"hl_{gate}"]) for r in subset))
                                      if subset else None}
                               for gate in ("fee_only", "stress")},
                    }
    return groups


def run(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    crypto_manifest = json.loads((CRYPTO_CAPTURE / "manifest.json").read_text())
    rwa_manifest = json.loads((ROOT / "data/raw/maker-capture/20260929T2022Z/manifest.json").read_text())
    for manifest in (crypto_manifest, rwa_manifest):
        if manifest.get("end_reason") != "duration_limit" or manifest.get("truncated"):
            raise ValueError("input must be a complete stopped duration-limit archive")
    all_rows, all_coverage = [], Counter()
    plan_paths = []
    for assets, manifest, end, factory in (
        (("BTC", "ETH"), crypto_manifest, utc_ns(crypto_manifest["ended_utc"]),
         lambda: iter_crypto_books(CRYPTO_CAPTURE)),
        (("NVDA", "XAG"), rwa_manifest, utc_ns(rwa_manifest["ended_utc"]),
         lambda: iter_jsonl_gz(RWA)),
    ):
        metadata, plan_path = plan_metadata(manifest)
        plan_paths.append(plan_path)
        anchors = hl_anchors(factory(), assets, end)
        matched = matched_stream(factory(), assets)
        rows, coverage = analyze_dataset(assets, anchors, matched, metadata)
        all_rows.extend(rows)
        all_coverage.update(coverage)
    groups = summarize(all_rows, all_coverage)
    path = out_dir / "matched-rows.csv"
    with path.open("w", newline="") as stream:
        fields = list(all_rows[0]) if all_rows else ["stage", "asset", "budget_usd", "side"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)
    result = {"method": "matched tri-venue stopped books; static same-book two-maker ceiling plus first matched +10-16s quote sensitivity",
              "freshness": "receipt <=1s, source <=2s, tri-venue receipt/source skew <=1s",
              "sizes_usd": list(SIZES), "target_usd": str(TARGET),
              "reserve_bps": str(RESERVE_BPS), "capital_annual": str(CAPITAL_ANNUAL),
              "rows": len(all_rows), "groups": groups,
              "source_sha256": {"crypto_frames": file_sha(CRYPTO_CAPTURE / "frames.jsonl.gz"),
                                "rwa_books": file_sha(RWA),
                                "crypto_market_plan": file_sha(plan_paths[0]),
                                "rwa_market_plan": file_sha(plan_paths[1]),
                                "script": file_sha(Path(__file__))},
              "limits": ["RH maker fills, queue priority, and cancellations are unobserved",
                         "Static same-book fills cannot be executed simultaneously",
                         "Delayed books are quotes, not fill-time execution",
                         "USDG/USDC conversion and funding excluded"]}
    (out_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/passive-hedge-venues")
    args = parser.parse_args()
    print(json.dumps({"rows": run(args.out)["rows"]}))
