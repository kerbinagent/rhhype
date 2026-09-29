#!/usr/bin/env python3
"""Offline quality and direct-route screen for a stopped RH canonical AMM capture."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rh_small_canonical_amm import ASSETS, MAX_BYTES, ROUNDS, SIZES, sha, total_bytes, walk_hl


def positive(value):
    try:
        x = Decimal(str(value))
    except Exception:
        return None
    return x if x.is_finite() and x > 0 else None


def valid_hl_book(book, received_ms):
    if not isinstance(book, dict) or not isinstance(book.get("levels"), list) or len(book["levels"]) != 2:
        return "book_shape"
    source = book.get("time")
    if not isinstance(source, int) or not isinstance(received_ms, int) or source <= 0 or source > received_ms:
        return "book_clock"
    sides = []
    for levels in book["levels"]:
        if not isinstance(levels, list) or not levels:
            return "empty_side"
        parsed = []
        for level in levels:
            if not isinstance(level, dict):
                return "malformed_level"
            p, q = positive(level.get("px")), positive(level.get("sz"))
            if p is None or q is None:
                return "nonpositive_or_nonfinite_level"
            parsed.append(p)
        sides.append(parsed)
    bids, asks = sides
    if any(a <= b for a, b in zip(bids, bids[1:])):
        return "bids_not_strict_descending"
    if any(a >= b for a, b in zip(asks, asks[1:])):
        return "asks_not_strict_ascending"
    if bids[0] >= asks[0]:
        return "crossed_book"
    return None


def evaluate_quote(row, quote, hl_meta):
    if "error" in quote:
        return {"status": "quote_error", "error": quote["error"]}
    book = row.get("hl_book")
    issue = valid_hl_book(book, row.get("hl_book_received_ms"))
    if issue:
        return {"status": "invalid_hl_book", "reason": issue}
    amount = positive(quote.get("usd_amount"))
    q_token = positive(quote.get("token_qty"))
    multiplier = positive(row.get("current_multiplier"))
    if None in (amount, q_token, multiplier):
        return {"status": "bad_quote_quantity"}
    q_share = q_token * multiplier
    if Decimal(quote["underlying_shares"]) != q_share:
        return {"status": "quantity_conversion_mismatch"}
    side = quote["side"]
    if side not in ("buy", "sell"):
        return {"status": "bad_side"}
    levels = book["levels"][0 if side == "buy" else 1]
    walked = walk_hl(levels, q_share)
    if walked is None:
        return {"status": "insufficient_hl_depth"}
    if Decimal(quote["hl_walk_value_usdc"]) != walked:
        return {"status": "walk_mismatch"}
    if walked < Decimal(10):
        return {"status": "hl_below_min_notional"}
    lot = Decimal(hl_meta["size_step"])
    exact_lot = q_share % lot == 0
    if exact_lot != quote["hl_exact_lot"]:
        return {"status": "lot_flag_mismatch"}
    source_skew = abs(book["time"] - row["block_time_ms"])
    receipt_skew = abs(quote["received_ms"] - row["hl_book_received_ms"])
    if source_skew != quote["hl_source_vs_block_ms"] or receipt_skew != quote["hl_receipt_vs_quote_ms"]:
        return {"status": "skew_mismatch"}
    near = source_skew <= 2000 and receipt_skew <= 2000
    gross = walked - amount if side == "buy" else amount - walked
    hl_fee = walked * Decimal(hl_meta["derived_taker_bps"]) / 10_000
    reserve = max(amount, walked) * Decimal(5) / 10_000
    if Decimal(quote["entry_gross_gap_usd_at_parity"]) != gross or Decimal(quote["hl_entry_fee_usdc"]) != hl_fee or Decimal(quote["modeled_5bp_reserve_usd"]) != reserve:
        return {"status": "cashflow_mismatch"}
    return {"status": "quality_checked", "exact_hl_lot": exact_lot,
            "near_time_2s": near, "gross_entry_gap": str(gross),
            "entry_gap_after_one_hl_fee": str(gross - hl_fee),
            "entry_gap_after_one_fee_reserve": str(gross - hl_fee - reserve),
            "source_skew_ms": source_skew, "receipt_skew_ms": receipt_skew,
            "underlying_shares": str(q_share)}


def summarize(capture):
    capture = Path(capture).resolve()
    manifest = json.loads((capture / "manifest.json").read_text())
    if manifest.get("status") != "complete" or manifest.get("rounds_completed") != ROUNDS:
        raise ValueError("capture not complete")
    if total_bytes(capture) > MAX_BYTES:
        raise ValueError("capture exceeds 8MB total cap")
    frozen = json.loads((capture / "frozen-plan.json").read_text())
    verified = json.loads((capture / "verified-plan.json").read_text())
    if tuple(frozen["assets"]) != ASSETS or tuple(frozen["sizes_usd"]) != SIZES or tuple(verified) != ASSETS:
        raise ValueError("frozen universe mismatch")
    rows = [json.loads(line) for line in (capture / "quotes.jsonl").open()]
    observations = {(r["round"], r["symbol"]): r for r in rows if "symbol" in r}
    if len(observations) != ROUNDS * len(ASSETS) or any(
            (round_number, symbol) not in observations
            for round_number in range(ROUNDS) for symbol in ASSETS):
        raise ValueError("missing or duplicate round/asset observations")
    quality = Counter()
    direct_best = []
    for round_number in range(ROUNDS):
        for symbol in ASSETS:
            row = observations[(round_number, symbol)]
            if "error" in row:
                quality["asset_error"] += 1
                continue
            if len(row.get("quotes", [])) != 16:
                quality["incomplete_quote_batch"] += 1
                continue
            groups = defaultdict(list)
            for quote in row["quotes"]:
                result = evaluate_quote(row, quote, verified[symbol]["hl"])
                quality[result["status"]] += 1
                if result["status"] != "quality_checked":
                    continue
                if not result["near_time_2s"]:
                    quality["source_or_receipt_skew_over_2s"] += 1
                if not result["exact_hl_lot"]:
                    quality["nonlot_continuous_hedge"] += 1
                groups[(quote["side"], quote["budget_usd"])].append((quote, result))
            for (side, budget), choices in groups.items():
                if len(choices) != 2:
                    quality["direct_pool_pair_incomplete"] += 1
                    continue
                # Buy: same USDG input, maximize acquired token amount. Sell:
                # same token input, maximize USDG output. No split routing.
                chosen, check = max(choices, key=lambda pair:
                    Decimal(pair[0]["token_qty"] if side == "buy" else pair[0]["usd_amount"]))
                direct_best.append({"round": round_number, "symbol": symbol, "side": side,
                                    "budget_usd": budget, "pool": chosen["pool"],
                                    **check})
    by_group = defaultdict(list)
    for row in direct_best:
        by_group[(row["symbol"], row["side"], row["budget_usd"])].append(row)
    groups = []
    for (symbol, side, budget), values in sorted(by_group.items()):
        near = [v for v in values if v["near_time_2s"]]
        exact = [v for v in near if v["exact_hl_lot"]]
        positive_gap = [v for v in near if Decimal(v["entry_gap_after_one_fee_reserve"]) > 0]
        fee_only_positive = [v for v in near if Decimal(v["entry_gap_after_one_hl_fee"]) > 0]
        groups.append({"symbol": symbol, "side": side, "budget_usd": budget,
                       "valid_direct_pairs": len(values), "near_time_pairs": len(near),
                       "near_time_nonlot": sum(not v["exact_hl_lot"] for v in near),
                       "near_time_exact_lot": len(exact),
                       "near_time_positive_entry_gap_after_one_hl_fee": len(fee_only_positive),
                       "near_time_median_entry_gap_after_one_hl_fee_usd":
                           str(statistics.median(Decimal(v["entry_gap_after_one_hl_fee"]) for v in near)) if near else None,
                       "near_time_positive_entry_gap_after_one_hl_fee_and_reserve": len(positive_gap),
                       "near_time_median_entry_gap_after_one_fee_reserve_usd":
                           str(statistics.median(Decimal(v["entry_gap_after_one_fee_reserve"]) for v in near)) if near else None,
                       "near_time_exact_lot_positive_entry_gap": sum(
                           Decimal(v["entry_gap_after_one_fee_reserve"]) > 0 for v in exact)})
    result = {"capture": str(capture.relative_to(Path(__file__).resolve().parents[1])),
              "capture_status": manifest["status"], "capture_total_bytes": total_bytes(capture),
              "frozen_script_sha256": frozen["script_sha256"],
              "raw_quotes_sha256": sha(capture / "quotes.jsonl"),
              "method": "quality-checked optimistic one-entry quote screen, not executable arbitrage or roundtrip",
              "quality_counts": dict(quality), "groups": groups, "best_direct_rows": direct_best}
    out = Path(__file__).resolve().parents[1] / "reports/rh-small-canonical-amm"
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    result = summarize(args.capture)
    print(json.dumps({"quality_counts": result["quality_counts"],
                      "best_direct_rows": len(result["best_direct_rows"])}))


if __name__ == "__main__":
    main()
