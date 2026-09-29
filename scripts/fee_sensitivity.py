#!/usr/bin/env python3
"""Frozen-holdout fee sensitivity; observed fills, exits, and filters never change."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

import filter_experiments as frozen

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data/evidence/research-filter-sample.json.gz"
FILTER_SUMMARY = ROOT / "reports/filter-experiments/summary.json"
OUT = ROOT / "reports/fee-sensitivity"
EXPECTED_SHA256 = "b2412d250f8ee2bf3b5e335032b046d8e3d4e9eaace309f939cd8562722f06bc"
SCENARIOS = ("recorded", "zero_fees", "zero_reserve", "zero_both")


def scenario_net(trade, scenario):
    value = trade["net_pnl_usd"]
    if scenario in ("zero_fees", "zero_both"):
        value += trade["fees_usd"]
    if scenario in ("zero_reserve", "zero_both"):
        value += trade["other_costs_usd"]
    return value


def classify(trade):
    if trade["status"] == "ABORTED":
        return "aborted"
    if trade["status"] not in frozen.CLOSED:
        raise ValueError(f"not a settled close: {trade['status']}")
    if trade.get("exit_reason") == "entry_failure":
        return "failed_hedge"
    if len(trade["legs"]) == 2 and all(leg.get("entry_result") == "filled" for leg in trade["legs"]):
        return "paired"
    raise ValueError(f"unclassified closed attempt: {trade['id']}")


def four_leg_turnover(trade):
    """Actual entry and exit dollars on both filled legs, never target notional."""
    if classify(trade) != "paired":
        raise ValueError("four-leg turnover requires a completed paired hedge")
    values = [leg[field] for leg in trade["legs"] for field in ("entry_value", "exit_value")]
    if len(values) != 4 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError(f"invalid four-leg turnover: {trade['id']}")
    return sum(values)


def need_bps(net_usd, turnover_usd):
    """Extra uniform four-leg-turnover-equivalent improvement to break even."""
    if turnover_usd <= 0 or not math.isfinite(turnover_usd):
        raise ValueError("invalid turnover")
    return max(0.0, -net_usd) / turnover_usd * 10_000


def quantile(values, q):
    if not values:
        return None
    items = sorted(values)
    position = (len(items)-1)*q
    lower = int(position)
    upper = min(lower+1,len(items)-1)
    return items[lower] + (items[upper]-items[lower])*(position-lower)


def verify_accounting(trade):
    if classify(trade) == "aborted":
        return
    expected_reserve = .0005 * max(leg["entry_value"] for leg in trade["legs"])
    if abs(trade["other_costs_usd"] - expected_reserve) > 1e-9:
        raise ValueError(f"reserve is not 5bp of max entry value: {trade['id']}")
    pnl = trade["price_pnl"] - trade["fees_usd"] - trade["other_costs_usd"] - trade["capital_costs_usd"] + trade["funding_usd"]
    if abs(pnl-trade["net_pnl_usd"]) > 1e-8:
        raise ValueError(f"P&L components do not reconcile: {trade['id']}")


def summarize(rows):
    paired = [p for p in rows if classify(p) == "paired"]
    failed = [p for p in rows if classify(p) == "failed_hedge"]
    closed = paired+failed
    turnover = sum(four_leg_turnover(p) for p in paired)
    result = {"attempts":len(rows),"closed":len(closed),"aborted":len(rows)-len(closed),
              "paired":len(paired),"failed_hedges":len(failed),
              "paired_four_leg_turnover_usd":turnover,
              "paired_mean_four_leg_turnover_usd":turnover/len(paired) if paired else None,
              "recorded_fees_usd":sum(p["fees_usd"] for p in closed),
              "modeled_5bp_reserve_usd":sum(p["other_costs_usd"] for p in closed)}
    scenarios = {}
    for scenario in SCENARIOS:
        all_net = sum(scenario_net(p,scenario) for p in closed)
        pair_net = sum(scenario_net(p,scenario) for p in paired)
        fail_net = sum(scenario_net(p,scenario) for p in failed)
        needs = [need_bps(scenario_net(p,scenario),four_leg_turnover(p)) for p in paired]
        scenarios[scenario] = {
            "all_closed_net_usd":all_net,
            "all_closed_positive":sum(scenario_net(p,scenario)>0 for p in closed),
            "paired_net_usd":pair_net,
            "paired_positive":sum(scenario_net(p,scenario)>0 for p in paired),
            "failed_hedge_net_usd":fail_net,
            "failed_hedge_positive":sum(scenario_net(p,scenario)>0 for p in failed),
            "paired_aggregate_extra_bps_to_zero":max(0.0,-pair_net)/turnover*10_000 if turnover else None,
            "paired_median_attempt_extra_bps_to_zero":statistics.median(needs) if needs else None,
            "paired_p90_attempt_extra_bps_to_zero":quantile(needs,.9),
            "paired_max_attempt_extra_bps_to_zero":max(needs) if needs else None,
        }
    result["scenarios"] = scenarios
    return result


def load_frozen_holdout(sample_path=SAMPLE, summary_path=FILTER_SUMMARY):
    digest=hashlib.sha256(Path(sample_path).read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"frozen evidence SHA-256 changed: {digest}")
    sample=frozen.load(sample_path)
    source_summary=json.loads(Path(summary_path).read_text())
    rows=frozen.dedupe_attempts(frozen.settled(sample["trades"],"shadow_baseline"))
    for p in rows:
        p["_class"] = frozen.class_of(p,sample["category_by_pair"])
    train,holdout,boundary,purged=frozen.split_chronological(rows)
    if boundary != source_summary["train_test"]["cut_at"]:
        raise ValueError("chronological boundary differs from frozen report")
    if len(holdout) != source_summary["train_test"]["holdout"]["attempts"] or purged != source_summary["train_test"]["train_crossing_outcomes_purged"]:
        raise ValueError("holdout or purge count differs from frozen report")
    for p in train:
        known_at=p.get("closed_at") if p["status"] == "ABORTED" else p.get("settled_at")
        if known_at is None or known_at >= boundary:
            raise ValueError(f"training outcome not known at boundary: {p['id']}")
    for p in holdout:
        verify_accounting(p)
    recorded=sum(p["net_pnl_usd"] for p in holdout if classify(p) != "aborted")
    if abs(recorded-source_summary["train_test"]["holdout"]["net_pnl_usd"])>1e-8:
        raise ValueError("holdout recorded P&L differs from frozen report")
    return sample,source_summary,train,holdout,boundary,purged,digest


def analyze(sample_path=SAMPLE, summary_path=FILTER_SUMMARY):
    sample,reference,train,holdout,boundary,purged,digest=load_frozen_holdout(sample_path,summary_path)
    paired=[p for p in holdout if classify(p)=="paired"]
    failed=[p for p in holdout if classify(p)=="failed_hedge"]
    primary=summarize(holdout)
    by_venue={}
    for venue in sorted({frozen.venue_of(p) for p in paired}):
        by_venue[venue]=summarize([p for p in paired if frozen.venue_of(p)==venue])
    # Reuse the thresholds already chosen in training by the frozen report.
    # No fee scenario re-selects a threshold or simulates a new fill.
    fixed_filters={}
    for family,choices in frozen.candidates().items():
        label=reference["experiments"][family]["chosen_threshold"]
        predicate=next((fn for name,fn in choices if name==label),None)
        if predicate is None:
            raise ValueError(f"missing frozen filter {family}={label}")
        selected=[p for p in holdout if predicate(p)]
        baseline=frozen.outcome(selected)
        if abs(baseline["net_pnl_usd"]-reference["experiments"][family]["holdout"]["net_pnl_usd"])>1e-8:
            raise ValueError(f"frozen filter mismatch: {family}")
        fixed_filters[family]={"threshold":label,"result":summarize(selected)}
    per_attempt=[]
    for p in paired:
        turnover=four_leg_turnover(p)
        row={"id":p["id"],"asset":p["asset"],"pair_id":p["pair_id"],
             "settled_at":p["settled_at"],"four_leg_turnover_usd":turnover,
             "hl_turnover_usd":sum(l["entry_value"]+l["exit_value"] for l in p["legs"] if l["venue"]=="hyperliquid"),
             "other_venue_turnover_usd":sum(l["entry_value"]+l["exit_value"] for l in p["legs"] if l["venue"]!="hyperliquid"),
             "recorded_fees_usd":p["fees_usd"],"modeled_5bp_reserve_usd":p["other_costs_usd"]}
        for scenario in SCENARIOS:
            value=scenario_net(p,scenario)
            row[f"net_{scenario}_usd"]=value
            row[f"additional_improvement_{scenario}_bps_of_four_leg_turnover"]=need_bps(value,turnover)
        per_attempt.append(row)
    result={"frozen_evidence_sha256":digest,"checkpoint_at":sample["checkpoint_at"],
            "chronological_split_at":boundary,"train_outcomes_known_before_split":len(train),
            "train_crossing_outcomes_purged":purged,"fee_scenario":"remove recorded explicit fees and/or 5bp modeled reserve without changing any recorded price, size, fill, exit, capital charge, or funding",
            "primary_holdout":primary,"paired_by_countervenue":by_venue,
            "fixed_train_selected_filters_on_same_holdout":fixed_filters,
            "failed_hedge_note":"failed hedges are summarized separately and have no valid four-leg turnover denominator"}
    return result,per_attempt,failed


def write(out=OUT,sample_path=SAMPLE,summary_path=FILTER_SUMMARY):
    result,per_attempt,failed=analyze(sample_path,summary_path)
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    (out/"summary.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    with (out/"paired_attempts.csv").open("w",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=list(per_attempt[0]) if per_attempt else ["id"])
        writer.writeheader();writer.writerows(per_attempt)
    failed_rows=[{"id":p["id"],"asset":p["asset"],"pair_id":p["pair_id"],
                  "settled_at":p["settled_at"],"recorded_fees_usd":p["fees_usd"],
                  "modeled_5bp_reserve_usd":p["other_costs_usd"],
                  **{f"net_{s}_usd":scenario_net(p,s) for s in SCENARIOS}} for p in failed]
    with (out/"failed_hedges.csv").open("w",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=list(failed_rows[0]) if failed_rows else ["id"])
        writer.writeheader();writer.writerows(failed_rows)
    hold=result["primary_holdout"]
    print(json.dumps({"holdout_attempts":hold["attempts"],
                      "recorded_net_usd":hold["scenarios"]["recorded"]["all_closed_net_usd"],
                      "zero_both_net_usd":hold["scenarios"]["zero_both"]["all_closed_net_usd"],
                      "out":str(out)}))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,default=OUT)
    args=parser.parse_args()
    write(args.out)


if __name__=="__main__":
    main()
