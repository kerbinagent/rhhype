#!/usr/bin/env python3
"""Offline, hypothetical batch-cost sensitivities for stopped RH maker quotes.

The input contains quoted four-leg cycles, not actual maker fills. Route costs
are caller-specified examples allocated across an assumed count of completed
cycles; no transfer price or frequency is inferred from these books.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports/passive-hedge-venues/matched-rows.csv"
DEST = ROOT / "reports/passive-cost-buffer"
ROUTE_COSTS = (Decimal(1), Decimal(2), Decimal(5))
COMPLETED_TURNS = (10, 50, 100)
MAX_SOURCE_ROWS = 10_000
TARGET = Decimal("0.10")
VENUES = ("hl", "core")


def load_rows(path: Path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or len(rows) > MAX_SOURCE_ROWS:
        raise ValueError("source row count outside bounded range")
    for row in rows:
        if row["stage"] not in ("static", "delayed") or row["side"] not in ("buy_rh", "sell_rh"):
            raise ValueError("unexpected source stage or side")
        for venue in VENUES:
            if any(Decimal(row[f"{venue}_{key}"]) < 0 for key in
                   ("rh_entry", "rh_exit", "hedge_entry", "hedge_exit", "reserve")):
                raise ValueError("negative leg notional or reserve")
    return rows


def scenario(rows, route_cost: Decimal, completed_turns: int):
    """Equal allocation C/M, only as a hypothetical homogeneous batch case."""
    if route_cost < 0 or completed_turns <= 0:
        raise ValueError("invalid batch cost or completed turn count")
    allocated = route_cost / Decimal(completed_turns)
    groups = defaultdict(list)
    for row in rows:
        for venue in VENUES:
            groups[(row["stage"], row["asset"], int(row["budget_usd"]),
                    row["side"], venue)].append(row)
    output = []
    for (stage, asset, budget, side, venue), subset in sorted(groups.items()):
        score = [Decimal(r[f"{venue}_fee_only"]) - allocated for r in subset]
        reserve = [Decimal(r[f"{venue}_reserve"]) for r in subset]
        turnover = [sum(Decimal(r[f"{venue}_{leg}"]) for leg in
                        ("rh_entry", "rh_exit", "hedge_entry", "hedge_exit"))
                    for r in subset]
        output.append({
            "stage": stage, "asset": asset, "budget_usd": budget, "side": side,
            "hedge_venue": venue, "common_quote_anchors": len(subset),
            "hypothetical_route_cost_usd": str(route_cost),
            "assumed_completed_turns_per_route": completed_turns,
            "allocated_usd_per_turn": str(allocated),
            "median_allocated_bp_of_four_fill_turnover": str(median(
                allocated * 10_000 / t for t in turnover)),
            "median_existing_5bp_stress_usd": str(median(reserve)),
            "allocated_less_than_5bp_stress": sum(allocated < x for x in reserve),
            "median_quote_net_after_allocated_usd": str(median(score)),
            "positive_quote_count": sum(x > 0 for x in score),
            "at_least_10c_quote_count": sum(x >= TARGET for x in score),
        })
    return output


def run(source: Path = SOURCE, dest: Path = DEST):
    rows = load_rows(source)
    output = []
    for cost in ROUTE_COSTS:
        for turns in COMPLETED_TURNS:
            output.extend(scenario(rows, cost, turns))
    if len(output) > 2_000:
        raise ValueError("scenario row bound exceeded")
    dest.mkdir(parents=True, exist_ok=True)
    csv_path = dest / "scenario-groups.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    metadata = {
        "source": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_rows": len(rows), "scenario_groups": len(output),
        "route_costs_usd_hypothetical": [str(x) for x in ROUTE_COSTS],
        "completed_turns_hypothetical": list(COMPLETED_TURNS),
        "allocation": "C_route/M, equal per completed turn; no actual transfer or maker fill observed",
        "score": "prior fee_only quoted cycle including explicit fill fees and capital cost, minus C_route/M; not realized P&L",
        "limits": ["No real RH maker fill, account, swap, bridge, withdrawal, or conversion quote",
                   "USDG/USDC parity remains a scenario assumption",
                   "Hypothetical batches assume homogeneous completed turns and available collateral"],
    }
    (dest / "summary.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=DEST)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.out)))
