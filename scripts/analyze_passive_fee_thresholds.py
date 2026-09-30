#!/usr/bin/env python3
"""HL taker-fee break-even screen for stopped RH-maker/maker quote rows.

No orders, network market requests, or invented passive fills. This reads the
immutable matched tri-venue quote rows and solves for a uniform fee charged
on each of the two *actual HL leg notionals*. Repeated anchors overlap and
must never be summed as trading returns.
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
SOURCE_SUMMARY = ROOT / "reports/passive-hedge-venues/summary.json"
FEE_INPUTS = ROOT / "reports/maker-equity-v2/fee-inputs.json"
OUT = ROOT / "reports/passive-fee-thresholds"
TARGET = Decimal("0.10")
CAPITAL_ANNUAL = Decimal("0.05")
RESERVE_BPS = Decimal("5")
OFFICIAL_DOCS_CHECKED_UTC = "2026-09-30"
NATIVE_BASE = Decimal("4.5")
NATIVE_TIER6 = Decimal("2.4")  # >$7B 14d weighted volume; official schedule.
DIAMOND_FACTOR = Decimal("0.6")  # >500k HYPE staked; 40% reduction.
HIP3_EXPECTED_MULTIPLIER = Decimal("0.2")  # d=1 -> 2d, growth -> 0.1.
MAX_ROWS = 10_000
EPS = Decimal("1e-18")
ASSETS = ("BTC", "ETH", "NVDA", "XAG")
SIZES = (100, 250, 500, 1000)
SIDES = ("buy_rh", "sell_rh")
STAGES = ("static", "delayed")
OFFICIAL_FEES = "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees"
OFFICIAL_HIP3 = "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-3-deployer-actions"


def dec(value: object) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite numeric input")
    return result


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= EPS


def published_rates(asset: str, frozen: dict) -> dict[str, Decimal]:
    if asset in ("BTC", "ETH"):
        multiplier = Decimal(1)
    elif asset in ("NVDA", "XAG"):
        item = frozen["markets"][asset]
        if (item["growthMode"] != "enabled" or dec(item["deployerFeeScale"]) != 1
                or item["isAlignedQuoteToken"] is not False
                or item["collateralToken"] != 0):
            raise ValueError(f"unexpected HIP-3 fee inputs for {asset}")
        d = dec(item["deployerFeeScale"])
        deployer_multiplier = d + 1 if d < 1 else 2 * d
        multiplier = deployer_multiplier * Decimal("0.1")
        if multiplier != HIP3_EXPECTED_MULTIPLIER:
            raise ValueError("unexpected HIP-3 growth/deployer multiplier")
    else:
        raise ValueError(f"unexpected asset {asset}")
    return {"base": NATIVE_BASE * multiplier,
            "tier6_volume_only": NATIVE_TIER6 * multiplier,
            "tier6_diamond": NATIVE_TIER6 * DIAMOND_FACTOR * multiplier,
            "multiplier": multiplier}


def threshold_row(row: dict[str, str], rates: dict[str, Decimal]) -> dict[str, str]:
    stage, asset, side = row["stage"], row["asset"], row["side"]
    budget = int(row["budget_usd"])
    if (stage not in STAGES or asset not in ASSETS or side not in SIDES
            or budget not in SIZES):
        raise ValueError("unexpected row cohort")
    e, x = dec(row["hl_hedge_entry"]), dec(row["hl_hedge_exit"])
    denom = e + x
    if e <= 0 or x <= 0 or denom <= 0:
        raise ValueError("nonpositive actual HL hedge notionals")
    gross = dec(row["hl_gross"])
    capital = dec(row["hl_capital"])
    reserve = dec(row["hl_reserve"])
    fee = dec(row["hl_fee"])
    source_rate = dec(row["hl_fee_bps_per_taker"])
    if not close(source_rate, rates["base"]):
        raise ValueError(f"source fee not current frozen tier0: {asset}")
    if not close(fee, denom * source_rate / 10_000):
        raise ValueError("HL fee/own-notional identity failed")
    if not close(dec(row["hl_fee_only"]), gross - fee - capital):
        raise ValueError("fee-only cash identity failed")
    if not close(dec(row["hl_stress"]), gross - fee - capital - reserve):
        raise ValueError("stress cash identity failed")
    if capital < 0 or reserve < 0:
        raise ValueError("negative capital or stress reserve")
    rh_entry, rh_exit = dec(row["hl_rh_entry"]), dec(row["hl_rh_exit"])
    if rh_entry <= 0 or rh_exit <= 0 or dec(row["q"]) <= 0:
        raise ValueError("nonpositive RH notional or common quantity")
    elapsed_ns = int(row["exit_ns"]) - int(row["anchor_ns"])
    if ((stage == "static" and elapsed_ns != 0)
            or (stage == "delayed" and not 10_000_000_000 <= elapsed_ns <= 16_000_000_000)):
        raise ValueError("unexpected static/delayed quote timing")
    expected_capital = ((rh_entry + e) * CAPITAL_ANNUAL
                        * dec(elapsed_ns) / 1_000_000_000 / (365 * 86400))
    if not close(capital, expected_capital):
        raise ValueError("actual entry-notional capital identity failed")
    if not close(reserve, max(rh_entry, e) * RESERVE_BPS / 10_000):
        raise ValueError("maximum-entry-notional reserve identity failed")
    implied_gross = ((-rh_entry + e + rh_exit - x) if side == "buy_rh"
                     else (rh_entry - e - rh_exit + x))
    if not close(gross, implied_gross):
        raise ValueError("four-leg gross cash identity failed")
    fee_only_max = (gross - capital - TARGET) * 10_000 / denom
    stress_max = (gross - capital - reserve - TARGET) * 10_000 / denom
    # Signed thresholds are retained: a negative value means even zero HL
    # taker fee cannot meet the fixed $0.10 target.
    output = {key: row[key] for key in ("stage", "asset", "budget_usd", "side",
                                       "anchor_ns", "exit_ns", "q")}
    output.update({
        "hl_two_leg_notional_usd": str(denom),
        "hl_gross_usd": str(gross), "capital_usd": str(capital),
        "reserve_usd": str(reserve), "target_usd": str(TARGET),
        "fee_only_max_taker_bps": str(fee_only_max),
        "stress_max_taker_bps": str(stress_max),
        "zero_fee_meets_fee_only": str(fee_only_max >= 0),
        "zero_fee_meets_stress": str(stress_max >= 0),
    })
    for label in ("base", "tier6_volume_only", "tier6_diamond"):
        rate = rates[label]
        output[f"{label}_taker_bps"] = str(rate)
        output[f"fee_only_meets_at_{label}"] = str(fee_only_max >= rate)
        output[f"stress_meets_at_{label}"] = str(stress_max >= rate)
    # A threshold equal to source base fee must reproduce the source target.
    if (fee_only_max >= rates["base"]) != (dec(row["hl_fee_only"]) >= TARGET):
        raise ValueError("fee-only source target flag mismatch")
    if (stress_max >= rates["base"]) != (dec(row["hl_stress"]) >= TARGET):
        raise ValueError("stress source target flag mismatch")
    return output


def fmt(value: Decimal) -> str:
    return f"{value:.3f}"


def summarize_group(rows: list[dict[str, str]], rates: dict[str, Decimal]) -> dict[str, object]:
    if not rows:
        raise ValueError("empty expected group")
    result: dict[str, object] = {"observations": len(rows)}
    for gate in ("fee_only", "stress"):
        values = [dec(r[f"{gate}_max_taker_bps"]) for r in rows]
        result[f"{gate}_median_max_bps"] = fmt(median(values))
        result[f"{gate}_negative_count"] = sum(x < 0 for x in values)
        for label, rate in (("zero_fee", Decimal(0)),
                            ("base", rates["base"]),
                            ("tier6_volume_only", rates["tier6_volume_only"]),
                            ("tier6_diamond", rates["tier6_diamond"])):
            count = sum(x >= rate for x in values)
            result[f"{gate}_{label}_clear_count"] = count
            result[f"{gate}_{label}_clear_fraction"] = f"{count}/{len(rows)}"
    return result


def run(source: Path, out: Path) -> dict:
    source = Path(source)
    out = Path(out)
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("source CSV exceeds 16 MiB bound")
    source_summary = json.loads(SOURCE_SUMMARY.read_text())
    fee_inputs = json.loads(FEE_INPUTS.read_text())
    fee_response = ROOT / fee_inputs["response_file"]
    if sha(fee_response) != fee_inputs["response_sha256"]:
        raise ValueError("frozen HIP-3 public metadata response hash mismatch")
    rates = {asset: published_rates(asset, fee_inputs) for asset in ASSETS}
    rows: list[dict[str, str]] = []
    with source.open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"stage", "asset", "budget_usd", "side", "anchor_ns", "exit_ns", "q",
                    "hl_hedge_entry", "hl_hedge_exit", "hl_gross", "hl_capital",
                    "hl_reserve", "hl_fee", "hl_fee_only", "hl_stress",
                    "hl_fee_bps_per_taker", "hl_rh_entry", "hl_rh_exit"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("source CSV missing required columns")
        for raw in reader:
            if len(rows) >= MAX_ROWS:
                raise ValueError("source CSV row bound exceeded")
            rows.append(threshold_row(raw, rates[raw["asset"]]))
    if len(rows) != source_summary["rows"]:
        raise ValueError("source summary row count mismatch")
    grouped: dict[tuple[str, str, int, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["stage"], row["asset"], int(row["budget_usd"]), row["side"])].append(row)
    if len(grouped) != 64:
        raise ValueError("expected 64 stage/asset/size/direction groups")
    groups = []
    for stage in STAGES:
        for asset in ASSETS:
            for budget in SIZES:
                for side in SIDES:
                    key = stage, asset, budget, side
                    values = grouped[key]
                    record = {"stage": stage, "asset": asset, "budget_usd": budget,
                              "side": side, "base_bps": str(rates[asset]["base"]),
                              "tier6_volume_only_bps": str(rates[asset]["tier6_volume_only"]),
                              "tier6_diamond_bps": str(rates[asset]["tier6_diamond"])}
                    record.update(summarize_group(values, rates[asset]))
                    groups.append(record)
    overall: dict[str, object] = {"observations": len(rows)}
    for gate in ("fee_only", "stress"):
        overall[f"{gate}_negative_count"] = sum(
            dec(row[f"{gate}_max_taker_bps"]) < 0 for row in rows)
        for label in ("zero_fee", "base", "tier6_volume_only", "tier6_diamond"):
            column = (f"zero_fee_meets_{gate}" if label == "zero_fee"
                      else f"{gate}_meets_at_{label}")
            count = sum(row[column] == "True" for row in rows)
            overall[f"{gate}_{label}_clear_count"] = count
            overall[f"{gate}_{label}_clear_fraction"] = f"{count}/{len(rows)}"
    out.mkdir(parents=True, exist_ok=True)
    for filename, data in (("threshold-rows.csv", rows), ("groups.csv", groups)):
        with (out / filename).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    result = {
        "classification": "stopped-book conditional fee threshold; no observed RH maker fills",
        "source_rows": len(rows), "groups": len(groups), "target_usd": str(TARGET),
        "overall": overall,
        "denominator": "sum of actual two HL hedge leg notionals in each matched row",
        "fee_only_definition": "gross minus modeled 5% annual capital; excludes separate 5bp reserve",
        "stress_definition": "fee-only minus separate 5bp maximum-entry-notional reserve",
        "rates_bps": {asset: {k: str(v) for k, v in schedule.items()}
                      for asset, schedule in rates.items()},
        "discount_eligibility": "base assumes no user discount; tier6 requires >$7B 14d weighted volume; Diamond requires >500,000 HYPE staked; no referral/aligned discount assumed",
        "source_sha256": {"matched_rows": sha(source), "source_summary": sha(SOURCE_SUMMARY),
                          "fee_inputs": sha(FEE_INPUTS), "fee_raw_response": sha(fee_response),
                          "script": sha(Path(__file__))},
        "official_sources": [OFFICIAL_FEES, OFFICIAL_HIP3],
        "official_docs_checked_utc": OFFICIAL_DOCS_CHECKED_UTC,
        "market_configuration": "frozen September 29 xyz metadata, not re-queried; current docs applied conditionally to that configuration",
        "limits": ["RH maker entry/exit fills and queue priority unobserved",
                   "static opposite RH maker fills cannot be simultaneous",
                   "delayed books are quotes, not fill-time executions",
                   "overlapping anchors are not independent returns",
                   "USDG/USDC conversion and funding excluded",
                   "staking capital/opportunity cost and volume-tier acquisition costs excluded"],
    }
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Passive HL fee threshold screen", "",
             "Each cell is median maximum HL taker bp per fill, followed by the fraction of matched rows whose $0.10 target survives at current base and published tier 6 + Diamond rates. Fee-only includes modeled capital; stress also subtracts the separate 5 bp reserve. Negative median means zero HL fee is insufficient for the median row.",
             "", "| Stage | Asset | Size | RH side | n | Fee-only max bp | Fee-only base | Fee-only Diamond | Stress max bp | Stress base | Stress Diamond |",
             "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for group in groups:
        lines.append("| " + " | ".join(str(group[key]) for key in (
            "stage", "asset", "budget_usd", "side", "observations",
            "fee_only_median_max_bps", "fee_only_base_clear_fraction",
            "fee_only_tier6_diamond_clear_fraction", "stress_median_max_bps",
            "stress_base_clear_fraction", "stress_tier6_diamond_clear_fraction")) + " |")
    lines.extend(["", "See `groups.csv` for zero-fee and volume-only counts; `threshold-rows.csv` retains every signed row threshold. These rows are conditional quote screens, not realized fills or portfolio returns.", ""])
    (out / "REPORT.md").write_text("\n".join(lines))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    summary = run(args.source, args.out)
    print(json.dumps({"source_rows": summary["source_rows"], "groups": summary["groups"]}))
