"""Static RH-maker hedge-venue comparison on stopped public archives only.

This is a matched-book cost diagnostic, not a maker-fill or execution replay.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.maker_book_archive import BookRebuilder, selected_markets  # noqa: E402
RWA = ROOT / "reports/maker-book-archive-v1/derived/book-events.jsonl.gz"
CRYPTO_CAPTURE = ROOT / "data/raw/maker-capture/20260929T1939Z"
META = ROOT / "data/raw/rh-maker-metadata/20260929T210845Z/normalized.json"
CORE_META = ROOT / "data/raw/comparators/20260929T035055Z/lighter/markets.json"
SIZES = (100, 250, 500, 1000)
NS = 1_000_000_000


def dec(value):
    return Decimal(str(value))


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def utc_ns(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * NS)


def hl_anchors(events, assets, end_ns, spacing_ns=5 * NS, horizon_ns=10 * NS):
    """Predeclare anchors from HL L2 receipt events, independent of hedge choice."""
    out = {asset: [] for asset in assets}
    for event in events:
        asset = event.get("asset")
        received = event.get("receipt_utc_ns")
        if (event.get("venue") != "hyperliquid" or asset not in out
                or not event.get("valid") or not isinstance(received, int)
                or received + horizon_ns > end_ns):
            continue
        if not out[asset] or received - out[asset][-1] >= spacing_ns:
            out[asset].append(received)
    return out


def iter_jsonl_gz(path):
    with gzip.open(path, "rt") as f:
        for line in f:
            yield json.loads(line)


def iter_crypto_books(capture_dir):
    manifest = json.loads((capture_dir / "manifest.json").read_text())
    if manifest.get("end_reason") != "duration_limit" or manifest.get("truncated"):
        raise ValueError("crypto archive must be a stopped, complete duration-limit capture")
    pending = []
    rebuilder = BookRebuilder(selected_markets(manifest), pending.append)
    prior = None
    for row in iter_jsonl_gz(capture_dir / "frames.jsonl.gz"):
        now = row.get("receipt_utc_ns")
        if not isinstance(now, int) or (prior is not None and now < prior):
            raise ValueError("nonmonotone or missing raw receipt")
        prior = now
        rebuilder.process(row)
        while pending:
            yield pending.pop(0)


def fresh(book, anchor_ns):
    if not book or not book.get("valid"):
        return False
    receipt, source = book.get("receipt_utc_ns"), book.get("source_utc_ns")
    return (isinstance(receipt, int) and isinstance(source, int)
            and 0 <= anchor_ns - receipt <= NS
            and 0 <= anchor_ns - source <= 2 * NS
            and source <= receipt)


def matched_books(snapshot, asset, anchor_ns):
    keys = ("rh_lighter", "hyperliquid", "lighter")
    books = {v: snapshot.get((asset, v)) for v in keys}
    if not all(fresh(books[v], anchor_ns) for v in keys):
        return None
    received = [books[v]["receipt_utc_ns"] for v in keys]
    source = [books[v]["source_utc_ns"] for v in keys]
    if max(received) - min(received) > NS or max(source) - min(source) > NS:
        return None
    return books


def matched_stream(events, assets):
    """Keep only simultaneous fresh tri-venue observations at event receipts."""
    latest = {}
    out = {asset: [] for asset in assets}
    prior = None
    for event in events:
        received = event["receipt_utc_ns"]
        if prior is not None and received < prior:
            raise ValueError("nonmonotone decoded book receipt")
        prior = received
        asset = event["asset"]
        latest[(asset, event["venue"])] = event
        if asset in out:
            matched = matched_books(latest, asset, received)
            if matched is not None:
                out[asset].append((received, matched))
    return out


def common_step(*steps):
    return max(map(dec, steps))  # Published size steps here are powers of ten.


def quantity(budget, rh_ask, step):
    return (dec(budget) / dec(rh_ask) / dec(step)).to_integral_value(rounding=ROUND_FLOOR) * dec(step)


def walk(levels, qty):
    remaining = dec(qty)
    value = Decimal(0)
    for price, available in levels:
        take = min(remaining, dec(available))
        if take > 0:
            value += take * dec(price)
            remaining -= take
        if remaining <= 0:
            break
    return None if remaining > 0 else value


def valid_size(q, entry, exit_, rh, hl, core):
    checks = ((rh, entry["rh_lighter"], exit_["rh_lighter"]),
              (hl, entry["hyperliquid"], exit_["hyperliquid"]),
              (core, entry["lighter"], exit_["lighter"]))
    for meta, start, end in checks:
        step = dec(meta["size_step"])
        minimum = dec(meta.get("min_qty") or step)
        if q < minimum or q % step:
            return False
        if meta.get("max_qty") is not None and q > dec(meta["max_qty"]):
            return False
        if any(q * dec(book["bids"][0][0]) < dec(meta["min_notional"]) for book in (start, end)):
            return False
    return True


def pair_cashflows(q, maker_bid, rh_exit_bid_value, hedge_entry_bid_value,
                   hedge_exit_ask_value, hl_or_core_fee_bps, rh_maker_bps=0, rh_exit_bps=0,
                   reserve_bps=5):
    """Exact four synthetic cash flows; all fees use their own leg notional."""
    q, maker_bid = dec(q), dec(maker_bid)
    rh_entry = q * maker_bid
    rh_exit = dec(rh_exit_bid_value)
    hedge_entry = dec(hedge_entry_bid_value)
    hedge_exit = dec(hedge_exit_ask_value)
    fee = (rh_entry * dec(rh_maker_bps) + rh_exit * dec(rh_exit_bps)
           + hedge_entry * dec(hl_or_core_fee_bps) + hedge_exit * dec(hl_or_core_fee_bps)) / 10_000
    gross = -rh_entry + hedge_entry + rh_exit - hedge_exit
    reserve = max(rh_entry, hedge_entry) * dec(reserve_bps) / 10_000
    return {"gross": gross, "fee": fee, "reserve": reserve,
            "net_before_reserve": gross - fee, "net_after_reserve": gross - fee - reserve,
            "rh_entry": rh_entry, "rh_exit": rh_exit,
            "hedge_entry": hedge_entry, "hedge_exit": hedge_exit}


def core_market_meta():
    rows = json.loads(CORE_META.read_text())["order_book_details"]
    return {r["symbol"]: {"size_step": str(Decimal(10) ** -int(r["supported_size_decimals"])),
                          "min_qty": r["min_base_amount"], "min_notional": r["min_quote_amount"],
                          "max_qty": None, "taker_fee_bps": "0"}
            for r in rows if r.get("market_type") == "perp" and r.get("status") == "active"}


def analyze_dataset(assets, anchors_by_asset, matched_by_asset, metadata, core_meta):
    rows = []
    coverage = Counter()
    for asset in assets:
        rh = metadata["rh_lighter"][asset]
        hl = metadata["hyperliquid"][asset]
        core = core_meta[asset]
        step = common_step(rh["size_step"], hl["size_step"], core["size_step"])
        observations = matched_by_asset[asset]
        observed_times = [t for t, _ in observations]
        exact_entry = {t: books for t, books in observations}
        for anchor in anchors_by_asset[asset]:
            entry = exact_entry.get(anchor)
            exit_ix = bisect.bisect_left(observed_times, anchor + 10 * NS)
            if exit_ix < len(observations) and observed_times[exit_ix] <= anchor + 16 * NS:
                exit_time, exit_ = observations[exit_ix]
            else:
                exit_time, exit_ = None, None
            for budget in SIZES:
                key = (asset, budget)
                coverage[(key, "anchors")] += 1
                if entry is None:
                    coverage[(key, "entry_not_matched")] += 1
                    continue
                coverage[(key, "entry_matched")] += 1
                if exit_ is None:
                    coverage[(key, "exit_not_matched")] += 1
                    continue
                coverage[(key, "entry_exit_matched")] += 1
                q = quantity(budget, entry["rh_lighter"]["asks"][0][0], step)
                if q <= 0 or not valid_size(q, entry, exit_, rh, hl, core):
                    coverage[(key, "invalid_size")] += 1
                    continue
                maker_bid = dec(entry["rh_lighter"]["bids"][0][0])
                rh_exit = walk(exit_["rh_lighter"]["bids"], q)
                if rh_exit is None:
                    coverage[(key, "rh_exit_depth")] += 1
                    continue
                legs = {}
                for venue in ("hyperliquid", "lighter"):
                    sell = walk(entry[venue]["bids"], q)
                    buy = walk(exit_[venue]["asks"], q)
                    if sell is None or buy is None:
                        coverage[(key, f"{venue}_depth")] += 1
                        break
                    fee = dec(hl["taker_fee_bps"]) if venue == "hyperliquid" else Decimal(0)
                    legs[venue] = pair_cashflows(q, maker_bid, rh_exit, sell, buy, fee)
                if len(legs) != 2:
                    continue
                coverage[(key, "complete_common")] += 1
                h, c = legs["hyperliquid"], legs["lighter"]
                row = {"asset": asset, "budget_usd": budget, "anchor_ns": anchor,
                       "exit_due_ns": anchor + 10 * NS, "exit_observed_ns": exit_time,
                       "q": str(q),
                       "rh_maker_bid": str(maker_bid), "rh_exit_proceeds": str(rh_exit),
                       "hl_fee_bps_per_taker": str(hl["taker_fee_bps"]),
                       "core_standard_fee_bps_per_taker": "0"}
                for label, result in (("hl", h), ("core", c)):
                    row.update({f"{label}_{field}": str(value) for field, value in result.items()})
                row["core_minus_hl_net_after_reserve"] = str(c["net_after_reserve"] - h["net_after_reserve"])
                row["core_premium_2p8_net_after_reserve"] = str(
                    pair_cashflows(q, maker_bid, rh_exit, c["hedge_entry"], c["hedge_exit"],
                                   Decimal("2.8"))["net_after_reserve"])
                rows.append(row)
    return rows, coverage


def run(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    crypto_manifest = json.loads((CRYPTO_CAPTURE / "manifest.json").read_text())
    rwa_manifest = json.loads((ROOT / "data/raw/maker-capture/20260929T2022Z/manifest.json").read_text())
    if rwa_manifest.get("end_reason") != "duration_limit" or rwa_manifest.get("truncated"):
        raise ValueError("RWA archive is not a complete stopped capture")
    metadata = json.loads(META.read_text())["markets"]
    core_meta = core_market_meta()
    all_rows, all_coverage = [], Counter()
    for assets, end, event_factory in (
        (("BTC", "ETH"), utc_ns(crypto_manifest["ended_utc"]),
         lambda: iter_crypto_books(CRYPTO_CAPTURE)),
        (("NVDA", "XAG"), utc_ns(rwa_manifest["ended_utc"]),
         lambda: iter_jsonl_gz(RWA)),
    ):
        anchors_by_asset = hl_anchors(event_factory(), assets, end)
        matched_by_asset = matched_stream(event_factory(), assets)
        rows, coverage = analyze_dataset(assets, anchors_by_asset, matched_by_asset, metadata, core_meta)
        all_rows.extend(rows)
        all_coverage.update(coverage)
    rows_path = out_dir / "matched-rows.csv"
    if all_rows:
        with rows_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
    else:
        rows_path.write_text("asset,budget_usd,anchor_ns\n")
    groups = {}
    for asset in ("BTC", "ETH", "NVDA", "XAG"):
        for budget in SIZES:
            subset = [r for r in all_rows if r["asset"] == asset and r["budget_usd"] == budget]
            key = f"{asset}:{budget}"
            diffs = [dec(r["core_minus_hl_net_after_reserve"]) for r in subset]
            groups[key] = {"coverage": {kind: all_coverage[((asset, budget), kind)]
                                        for kind in ("anchors", "entry_matched", "entry_exit_matched",
                                                     "invalid_size", "rh_exit_depth", "hyperliquid_depth",
                                                     "lighter_depth", "complete_common")},
                           "median_core_minus_hl_usd": str(median(diffs)) if diffs else None,
                           "core_lower_total_hurdle_count": sum(d > 0 for d in diffs),
                           "core_higher_total_hurdle_count": sum(d < 0 for d in diffs),
                           "equal_total_hurdle_count": sum(d == 0 for d in diffs)}
    summary = {"method": "HL L2 receipt anchors spaced >=5s per asset; same RH anchor/quantity; all three venues fresh at entry and first matched observation in +10–16s",
               "freshness": "receipt<=1s, source<=2s, cross-venue receipt/source skew<=1s",
               "sizes_usd": list(SIZES), "groups": groups,
               "rows": len(all_rows), "source_sha256": {
                   "crypto_frames": file_sha(CRYPTO_CAPTURE / "frames.jsonl.gz"),
                   "rwa_reconstructed_books": file_sha(RWA),
                   "rh_hl_metadata": file_sha(META), "core_metadata": file_sha(CORE_META),
                   "script": file_sha(Path(__file__))},
               "notes": ["No hypothetical maker order was placed or fill observed.",
                         "Exit books at +10s are static fresh observations, not fill-time execution.",
                         "USDG/USDC collateral conversion and funding are not modeled."]}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/rh-hedge-venue-choice")
    args = parser.parse_args()
    result = run(args.out)
    print(json.dumps({"rows": result["rows"], "groups": result["groups"]}, indent=2))
