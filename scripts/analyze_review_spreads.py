#!/usr/bin/env python3
"""Decompose one paper-review window from exact paired, retained trade fills.

Reads SQLite in one short, read-only transaction. The optional gzip evidence
can be replayed without a mutable production database. No simulated fills or
counterfactual exits are made here.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


MAX_ROWS = 5_000
MAX_EVIDENCE_BYTES = 8_000_000
MAX_DECODED_BYTES = 64_000_000
MAX_REVIEW_BYTES = 256_000
MAX_SUMMARY_BYTES = 8_000_000
TOL = Decimal("0.0000001")
YEAR_SECONDS = Decimal(365 * 86400)


def d(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("missing or boolean number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid number: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("nonfinite number")
    return result


def near(name: str, computed: Decimal, stored: Any) -> None:
    if abs(computed - d(stored)) > TOL:
        raise ValueError(f"{name} mismatch: computed={computed}, stored={stored}")


def read_window(db_path: Path, review_path: Path, strategy: str) -> dict[str, Any]:
    if review_path.stat().st_size > MAX_REVIEW_BYTES:
        raise ValueError("review exceeds 256 KB cap")
    review_bytes = review_path.read_bytes()
    if len(review_bytes) > MAX_REVIEW_BYTES:
        raise ValueError("review exceeds 256 KB cap")
    review = json.loads(review_bytes)
    lower, upper = d(review["window_start_at"]), d(review["window_end_at"])
    expected = int(review["strategies"][strategy]["expected_completed_count"])
    uri = db_path.resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA busy_timeout=1000")
        db.execute("BEGIN")
        config_row = db.execute(
            "SELECT updated,json_extract(payload,'$.engine.config') "
            "FROM engine_state WHERE id=1").fetchone()
        if config_row is None or config_row[1] is None:
            raise ValueError("missing durable engine config")
        where = ("status IN ('CLOSED','CLOSED_ESTIMATED') "
                 "AND CAST(json_extract(payload,'$.settled_at') AS REAL)>? "
                 "AND CAST(json_extract(payload,'$.settled_at') AS REAL)<=? "
                 "AND json_extract(payload,'$.strategy')=?")
        params = (float(lower), float(upper), strategy)
        count = db.execute(f"SELECT COUNT(*) FROM trades WHERE {where}", params).fetchone()[0]
        if count > MAX_ROWS:
            raise ValueError(f"window has {count} rows, above cap {MAX_ROWS}")
        trades = [json.loads(raw) for (raw,) in db.execute(
            f"SELECT payload FROM trades WHERE {where} "
            "ORDER BY CAST(json_extract(payload,'$.settled_at') AS REAL),id",
            params)]
        db.rollback()
    finally:
        db.close()
    return {
        "schema": 1, "source_db": str(db_path.resolve()),
        "review_path": str(review_path.resolve()),
        "review_sha256": hashlib.sha256(review_bytes).hexdigest(),
        "review_checkpoint_at": review["checkpoint_at"],
        "window_start_at": review["window_start_at"],
        "window_end_at": review["window_end_at"],
        "strategy": strategy, "expected_completed_count": expected,
        "review_coverage": review["strategies"][strategy]["coverage"],
        "db_count": count, "config_read_checkpoint_at": config_row[0],
        "config": json.loads(config_row[1]), "trades": trades,
    }


def read_sample(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ValueError("compressed evidence exceeds 8 MB cap")
    with gzip.open(path, "rb") as stream:
        decoded = stream.read(MAX_DECODED_BYTES + 1)
    if len(decoded) > MAX_DECODED_BYTES:
        raise ValueError("decoded evidence exceeds 64 MB cap")
    sample = json.loads(decoded)
    if not isinstance(sample, dict) or not isinstance(sample.get("trades"), list):
        raise ValueError("invalid evidence schema")
    if len(sample["trades"]) > MAX_ROWS:
        raise ValueError(f"evidence exceeds {MAX_ROWS} trades")
    return sample


def decompose(trade: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    if trade.get("status") != "CLOSED":
        raise ValueError("not exact CLOSED")
    signal, legs = trade["signal"], trade["legs"]
    if not isinstance(legs, list) or len(legs) != 2:
        raise ValueError("not two legs")
    by_key = {leg["key"]: leg for leg in legs}
    if len(by_key) != 2 or set(by_key) != {signal["buy"], signal["sell"]}:
        raise ValueError("signal and leg keys differ")
    long, short = by_key[signal["buy"]], by_key[signal["sell"]]
    if (long.get("side"), short.get("side")) != ("long", "short"):
        raise ValueError("leg directions differ")
    quantity = d(signal["quantity"])
    if quantity <= 0:
        raise ValueError("nonpositive signal quantity")
    values: dict[str, Decimal] = {}
    fee_total = Decimal(0)
    capital_numerator = Decimal(0)
    for name, leg in (("long", long), ("short", short)):
        if leg.get("entry_result") != "filled":
            raise ValueError(f"{name} entry not filled")
        leg_qty = d(leg["quantity"])
        if leg_qty <= 0 or abs(leg_qty - quantity) > max(TOL, quantity * Decimal("1e-9")):
            raise ValueError(f"{name} entry quantity differs from signal")
        fills = leg.get("exit_fills")
        if not isinstance(fills, list) or not fills:
            raise ValueError(f"{name} exit fills missing")
        exit_qty = sum((d(fill["quantity"]) for fill in fills), Decimal(0))
        exit_value = sum((d(fill["value"]) for fill in fills), Decimal(0))
        if abs(exit_qty - leg_qty) > TOL:
            raise ValueError(f"{name} exit fill quantity incomplete")
        entry_value = d(leg["entry_value"])
        near(f"{name} exit value", exit_value, leg["exit_value"])
        entry_fee = entry_value * d(leg["entry_fee_bps"]) / 10_000
        exit_fee = sum((d(fill["value"]) * d(fill["fee_bps"]) / 10_000
                        for fill in fills), Decimal(0))
        for fill in fills:
            near(f"{name} exit fill fee", d(fill["value"]) * d(fill["fee_bps"]) / 10_000,
                 fill["fee"])
        near(f"{name} entry fee", entry_fee, leg["entry_fee"])
        near(f"{name} exit fee", exit_fee, leg["exit_fee"])
        near(f"{name} combined fee", entry_fee + exit_fee, leg["fees_usd"])
        side_sign = Decimal(1) if name == "long" else Decimal(-1)
        near(f"{name} price PnL", side_sign * (exit_value - entry_value), leg["price_pnl"])
        duration = d(leg["exit_time"]) - d(leg["entry_time"])
        if duration < 0:
            raise ValueError(f"{name} exit before entry")
        capital_numerator += duration * entry_value * d(config["margin_fraction"])
        values[f"{name}_entry_value"] = entry_value
        values[f"{name}_exit_value"] = exit_value
        values[f"{name}_entry_fee"] = entry_fee
        values[f"{name}_exit_fee"] = exit_fee
        fee_total += entry_fee + exit_fee
    entry_spread = values["short_entry_value"] - values["long_entry_value"]
    exit_liability = values["short_exit_value"] - values["long_exit_value"]
    signal_spread = d(signal["sell_value"]) - d(signal["buy_value"])
    gross = entry_spread - exit_liability
    reserve = max(values["long_entry_value"], values["short_entry_value"]) * d(config["extra_cost_bps"]) / 10_000
    capital = capital_numerator * d(config["capital_rate"]) / YEAR_SECONDS
    funding = d(trade["funding_usd"])
    net = gross - fee_total - reserve - capital + funding
    for name, computed, field in (("gross price", gross, "price_pnl"),
                                  ("four fees", fee_total, "fees_usd"),
                                  ("reserve", reserve, "other_costs_usd"),
                                  ("capital", capital, "capital_costs_usd"),
                                  ("net", net, "net_pnl_usd")):
        near(name, computed, trade[field])
    return {"id": trade["id"], "asset": trade["asset"],
            "route": signal["route"], "quantity": quantity,
            "entry_spread": entry_spread,
            "exit_liability": exit_liability,
            "signal_entry_spread": signal_spread,
            "entry_deterioration": signal_spread - entry_spread,
            "gross": gross, "fees": fee_total,
            "reserve": reserve, "capital": capital, "funding": funding,
            "net": net, **values}


def analyze(sample: dict[str, Any]) -> dict[str, Any]:
    rows = []
    bad = []
    for trade in sample["trades"]:
        try:
            rows.append(decompose(trade, sample["config"]))
        except (KeyError, TypeError, ValueError) as exc:
            bad.append({"id": str(trade.get("id", ""))[:100], "reason": str(exc)[:160]})
    fields = ("signal_entry_spread", "entry_spread", "entry_deterioration",
              "exit_liability", "gross", "long_entry_fee", "short_entry_fee",
              "long_exit_fee", "short_exit_fee", "fees", "reserve", "capital",
              "funding", "net")
    totals = {key: sum((row[key] for row in rows), Decimal(0)) for key in fields}
    by_route = defaultdict(list)
    by_asset = defaultdict(list)
    for row in rows:
        by_route[row["route"]].append(row)
        by_asset[row["asset"]].append(row)
    def grouped(groups: dict[str, list]) -> list[dict[str, Any]]:
        return sorted(({"name": name, "count": len(items),
                        "gross": str(sum((r["gross"] for r in items), Decimal(0))),
                        "net": str(sum((r["net"] for r in items), Decimal(0)))}
                       for name, items in groups.items()), key=lambda x: Decimal(x["net"]))
    count = len(rows)
    complete = (not bad and count == sample["db_count"] == sample["expected_completed_count"]
                and sample["review_coverage"] == "complete")
    return {
        "strategy": sample["strategy"],
        "review_sha256": sample["review_sha256"],
        "window_start_at": sample["window_start_at"],
        "window_end_at": sample["window_end_at"],
        "expected": sample["expected_completed_count"],
        "db_count": sample["db_count"], "validated": count,
        "validation_errors": bad, "coverage_complete": complete,
        "totals_usd": {key: str(value) for key, value in totals.items()},
        "per_trade_usd": {key: str(totals[key] / count) if count else None
                          for key in ("entry_spread", "exit_liability", "gross", "fees",
                                      "reserve", "capital", "net")},
        "counts": {"entry_spread_positive": sum(r["entry_spread"] > 0 for r in rows),
                   "gross_positive": sum(r["gross"] > 0 for r in rows),
                   "net_positive": sum(r["net"] > 0 for r in rows),
                   "entry_deteriorated": sum(r["entry_deterioration"] > 0 for r in rows)},
        "by_route": grouped(by_route), "by_asset": grouped(by_asset),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/paper-monitor/paper.sqlite3"))
    parser.add_argument("--strategy", default="shadow_baseline")
    parser.add_argument("--sample", type=Path, help="Replay previously frozen gzip evidence")
    parser.add_argument("--freeze", type=Path, help="Write bounded gzip evidence")
    parser.add_argument("--summary", type=Path, help="Write JSON summary")
    args = parser.parse_args()
    if args.sample:
        if args.review:
            parser.error("--sample and --review are mutually exclusive")
        sample = read_sample(args.sample)
    else:
        if not args.review:
            parser.error("--review is required without --sample")
        sample = read_window(args.db, args.review, args.strategy)
    report = analyze(sample)
    report["analyzer_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.sample:
        compressed = args.sample.read_bytes()
        if len(compressed) > MAX_EVIDENCE_BYTES:
            raise ValueError("compressed evidence exceeds 8 MB cap")
        report["evidence_sha256"] = hashlib.sha256(compressed).hexdigest()
        report["evidence_bytes"] = len(compressed)
    if args.freeze:
        data = gzip.compress(json.dumps(sample, sort_keys=True, separators=(",", ":"),
                                        allow_nan=False).encode(), mtime=0)
        if len(data) > MAX_EVIDENCE_BYTES:
            raise ValueError("evidence exceeds 8 MB cap")
        args.freeze.parent.mkdir(parents=True, exist_ok=True)
        args.freeze.write_bytes(data)
        report["evidence_sha256"] = hashlib.sha256(data).hexdigest()
        report["evidence_bytes"] = len(data)
    output = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if len(output.encode()) > MAX_SUMMARY_BYTES:
        raise ValueError("summary exceeds 8 MB cap")
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
