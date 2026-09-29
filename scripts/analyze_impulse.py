#!/usr/bin/env python3
"""Offline analysis of stopped impulse quote observations; no fill inference."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/impulse-research/impulse_snapshot.json"
DEFAULT_OUTPUT = ROOT / "reports/impulse"
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ROWS = 5000
DELAYS = (.5, 1.0)
FEE_FIELDS = ("buy_entry_fee", "sell_entry_fee", "buy_exit_fee", "sell_exit_fee")
ECONOMIC_FIELDS = ("gross_capture_usd", "four_fees_usd", "reserve_usd", "capital_usd",
                   "net_after_four_fees_usd", "net_after_reserve_usd")
ENTRY_TIME_FIELDS = ("entry_time", "entry_hl_source_time", "entry_other_source_time",
                     "entry_hl_received", "entry_other_received")
EXIT_TIME_FIELDS = ("exit_time", "exit_due", "exit_hl_source_time", "exit_other_source_time",
                    "exit_hl_received", "exit_other_received")


def number(value, name):
    if isinstance(value, bool): raise ValueError(f"{name} must be finite")
    try: result = float(value)
    except (TypeError, ValueError, OverflowError): raise ValueError(f"{name} must be finite") from None
    if not math.isfinite(result): raise ValueError(f"{name} must be finite")
    return result


def count(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def counter_map(raw, name):
    if not isinstance(raw, dict): raise ValueError(f"{name} must be an object")
    return {key: count(value, f"{name}.{key}") for key, value in raw.items()}


def scenario_coverage(raw):
    candidates = raw.get("candidates", 0)
    entry = raw.get("paired_entry_quotes", 0)
    complete = raw.get("scenario_complete", 0)
    terminal = sum(value for key, value in raw.items() if key.startswith("scenario_"))
    return {"counts": raw, "candidate_to_entry_fraction": entry/candidates if candidates else None,
            "entry_to_complete_fraction": complete/entry if entry else None,
            "scenario_accounting_residual": candidates-terminal}


def quantile(values, fraction):
    ordered = sorted(values)
    if not ordered: return None
    point = (len(ordered)-1)*fraction
    lo, hi = math.floor(point), math.ceil(point)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(point-lo)


def distribution(values):
    values = list(values)
    if not values:
        return {"count": 0, "mean": None, "p10": None, "median": None, "p90": None}
    return {"count": len(values), "mean": statistics.fmean(values),
            "p10": quantile(values, .1), "median": quantile(values, .5),
            "p90": quantile(values, .9)}


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")


def read_snapshot(path):
    path = Path(path)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("impulse snapshot exceeds 32 MiB input cap")
    with path.open() as source: snapshot = json.load(source)
    if not isinstance(snapshot, dict): raise ValueError("snapshot must be an object")
    return snapshot


def validate_row(raw, index):
    if not isinstance(raw, dict): raise ValueError(f"terminal row {index} must be an object")
    row = dict(raw)
    if row.get("status") not in ("complete", "censored"):
        raise ValueError(f"terminal row {index} has invalid status")
    if not isinstance(row.get("pair"), str) or not row["pair"]:
        raise ValueError(f"terminal row {index} lacks physical pair")
    if row.get("direction") not in ("hl_buy", "other_buy"):
        raise ValueError(f"terminal row {index} has invalid direction")
    delay = number(row.get("delay_seconds"), f"row {index} delay_seconds")
    if delay not in DELAYS: raise ValueError(f"terminal row {index} has unexpected scenario delay")
    row["delay_seconds"] = delay
    for name in ("trigger_time", "confirmation_time", "entry_due", "terminal_time"):
        row[name] = number(row.get(name), f"row {index} {name}")
    if row["confirmation_time"] < row["trigger_time"]:
        raise ValueError(f"terminal row {index} confirmation precedes trigger")
    if abs(row["entry_due"]-row["confirmation_time"]-delay) > 1e-6:
        raise ValueError(f"terminal row {index} entry due differs from confirmation plus delay")
    if row.get("candidate_id") is None:
        raise ValueError(f"terminal row {index} lacks candidate_id")
    if row["status"] == "censored":
        if not isinstance(row.get("censor_reason"), str) or not row["censor_reason"]:
            raise ValueError(f"terminal row {index} lacks censor reason")
    else:
        if row.get("censor_reason") is not None:
            raise ValueError(f"terminal row {index} complete with censor reason")
        for name in ("entry_buy_value", "entry_sell_value",
                     "exit_long_value", "exit_short_buyback_value", "gross_capture_usd",
                     "four_fees_usd", "reserve_usd", "capital_usd",
                     "net_after_reserve_usd", *FEE_FIELDS):
            row[name] = number(row.get(name), f"row {index} {name}")
        if any(row[name] <= 0 for name in ("entry_buy_value", "entry_sell_value",
                                          "exit_long_value", "exit_short_buyback_value")):
            raise ValueError(f"terminal row {index} has nonpositive quote notional")
        if any(row[name] < 0 for name in (*FEE_FIELDS, "four_fees_usd", "reserve_usd", "capital_usd")):
            raise ValueError(f"terminal row {index} has negative fee or reserve")
        gross = (row["entry_sell_value"]-row["entry_buy_value"]+
                 row["exit_long_value"]-row["exit_short_buyback_value"])
        if abs(gross-row["gross_capture_usd"]) > 1e-5:
            raise ValueError(f"terminal row {index} gross quote signs do not reconcile")
        row["net_after_four_fees_usd"] = row["gross_capture_usd"]-row["four_fees_usd"]
        if abs(sum(row[name] for name in FEE_FIELDS)-row["four_fees_usd"]) > 1e-5:
            raise ValueError(f"terminal row {index} four fees do not reconcile")
        if abs(row["net_after_four_fees_usd"]-row["reserve_usd"]-
               row["capital_usd"]-row["net_after_reserve_usd"]) > 1e-5:
            raise ValueError(f"terminal row {index} net quote does not reconcile")
    if row.get("entry_time") is not None or row["status"] == "complete":
        for name in ENTRY_TIME_FIELDS:
            row[name] = number(row.get(name), f"row {index} {name}")
        if row["entry_time"] < row["entry_due"]-1e-6 or row["entry_time"] > row["trigger_time"]+2+1e-6:
            raise ValueError(f"terminal row {index} entry violates due/deadline")
        if any(row[name] < row["entry_due"]-1e-6 for name in
               ("entry_hl_source_time", "entry_other_source_time",
                "entry_hl_received", "entry_other_received")):
            raise ValueError(f"terminal row {index} entry source/receipt precedes due")
    if row["status"] == "complete":
        for name in EXIT_TIME_FIELDS:
            row[name] = number(row.get(name), f"row {index} {name}")
        if row["exit_time"] < row["entry_time"]:
            raise ValueError(f"terminal row {index} exit precedes entry")
        if abs(row["exit_due"]-row["entry_time"]-5.5) > 1e-6:
            raise ValueError(f"terminal row {index} exit due differs from entry plus 5.5s")
        if row["exit_time"] < row["exit_due"]-1e-6 or row["exit_time"] > row["trigger_time"]+10+1e-6:
            raise ValueError(f"terminal row {index} exit violates due/deadline")
        if any(row[name] < row["exit_due"]-1e-6 for name in
               ("exit_hl_source_time", "exit_other_source_time",
                "exit_hl_received", "exit_other_received")):
            raise ValueError(f"terminal row {index} exit source/receipt precedes due")
    return row


def economic_summary(rows):
    complete = [row for row in rows if row["status"] == "complete"]
    result = {name: distribution(row[name] for row in complete)
              for name in (*ECONOMIC_FIELDS, *FEE_FIELDS)}
    n = len(complete)
    return {"complete_quote_rows": n, "distributions_usd": result,
            "four_fee_positive_fraction": sum(row["net_after_four_fees_usd"] > 0 for row in complete)/n if n else None,
            "after_reserve_capital_positive_fraction": sum(row["net_after_reserve_usd"] > 0 for row in complete)/n if n else None}


def terminal_summary(rows):
    statuses = Counter(row["status"] for row in rows)
    censored = Counter(row["censor_reason"] for row in rows if row["status"] == "censored")
    with_entry = sum(row.get("entry_time") is not None for row in rows)
    entry = [row for row in rows if row.get("entry_time") is not None]
    complete = [row for row in rows if row["status"] == "complete"]
    timing = {
        "entry_collector_after_trigger": distribution(row["entry_time"]-row["trigger_time"] for row in entry),
        "entry_collector_after_confirmation": distribution(row["entry_time"]-row["confirmation_time"] for row in entry),
        "entry_collector_after_due": distribution(row["entry_time"]-row["entry_due"] for row in entry),
        "entry_hl_source_after_due": distribution(row["entry_hl_source_time"]-row["entry_due"] for row in entry),
        "entry_other_source_after_due": distribution(row["entry_other_source_time"]-row["entry_due"] for row in entry),
        "entry_hl_receipt_after_due": distribution(row["entry_hl_received"]-row["entry_due"] for row in entry),
        "entry_other_receipt_after_due": distribution(row["entry_other_received"]-row["entry_due"] for row in entry),
        "exit_collector_after_due": distribution(row["exit_time"]-row["exit_due"] for row in complete),
        "exit_collector_after_entry": distribution(row["exit_time"]-row["entry_time"] for row in complete),
        "exit_hl_source_after_due": distribution(row["exit_hl_source_time"]-row["exit_due"] for row in complete),
        "exit_other_source_after_due": distribution(row["exit_other_source_time"]-row["exit_due"] for row in complete),
        "exit_hl_receipt_after_due": distribution(row["exit_hl_received"]-row["exit_due"] for row in complete),
        "exit_other_receipt_after_due": distribution(row["exit_other_received"]-row["exit_due"] for row in complete),
    }
    return {"retained_terminal_rows": len(rows), "complete": statuses["complete"],
            "censored": statuses["censored"], "with_paired_entry_quote": with_entry,
            "censor_reasons": dict(censored), "quote_economics": economic_summary(rows),
            "timing_seconds": timing}


def grouped(rows, key):
    groups = defaultdict(list)
    for row in rows: groups[key(row)].append(row)
    return {name: {str(delay): terminal_summary([row for row in groups[name]
                                                if row["delay_seconds"] == delay])
                   for delay in DELAYS}
            for name in sorted(groups)}


def paired_candidates(rows):
    by_candidate = defaultdict(dict)
    for row in rows:
        candidate = (row["pair"], row["candidate_id"])
        delay = row["delay_seconds"]
        if delay in by_candidate[candidate]:
            raise ValueError(f"duplicate retained scenario for candidate {candidate}")
        by_candidate[candidate][delay] = row
    both = [scenarios for scenarios in by_candidate.values() if set(scenarios) == set(DELAYS)]
    complete = [scenarios for scenarios in both if all(row["status"] == "complete"
                                                       for row in scenarios.values())]
    delta = [scenarios[1.0]["net_after_reserve_usd"]-scenarios[.5]["net_after_reserve_usd"]
             for scenarios in complete]
    return {"retained_candidate_ids": len(by_candidate),
            "both_scenarios_retained": len(both),
            "unpaired_in_retained_export": len(by_candidate)-len(both),
            "both_scenarios_complete": len(complete),
            "stress_minus_primary_net_after_reserve_usd": distribution(delta),
            "both_four_fee_positive": sum(all(scenarios[delay]["net_after_four_fees_usd"] > 0
                                             for delay in DELAYS) for scenarios in complete),
            "both_after_reserve_capital_positive": sum(all(scenarios[delay]["net_after_reserve_usd"] > 0
                                                       for delay in DELAYS) for scenarios in complete),
            "one_or_both_censored": len(both)-len(complete),
            "comparison_basis": "same candidate_id, same frozen quantity and direction; only pairs with both complete quotes have dollar deltas"}


def analyze(snapshot):
    impulse = snapshot.get("model")
    if snapshot.get("status") not in ("stopped", "finished") or not isinstance(impulse, dict) or not impulse.get("finished"):
        raise ValueError("analysis requires a stopped/finished pilot and model.finished=true")
    if impulse.get("model_version") != 1: raise ValueError("unsupported impulse model version")
    raw_rows = impulse.get("terminal_rows")
    if not isinstance(raw_rows, list) or len(raw_rows) > MAX_ROWS:
        raise ValueError("terminal_rows must be a list of at most 5000 rows")
    rows = [validate_row(row, index) for index, row in enumerate(raw_rows)]
    counts = counter_map(impulse.get("counts") or {}, "counts")
    gates = counter_map(impulse.get("gates") or {}, "gates")
    censored = counter_map(impulse.get("censored") or {}, "censored")
    armed = counts.get("armed", 0)
    candidates = counts.get("confirmed_candidates", 0)
    complete = counts.get("scenario_complete", 0)
    censored_total = sum(censored.values())
    pending_arms = count(impulse.get("pending_arms", 0), "pending_arms")
    pending_scenarios = count(impulse.get("pending_scenarios", 0), "pending_scenarios")
    if pending_arms or pending_scenarios:
        raise ValueError("finished impulse pilot still has pending arms or scenarios")
    arm_terminal = counter_map(impulse.get("arm_outcomes") or {}, "arm_outcomes")
    by_delay_raw = {key: counter_map(value, f"by_delay.{key}") for key, value in
                    (impulse.get("by_delay") or {}).items()}
    by_delay_all = {str(delay): scenario_coverage(by_delay_raw.get(str(delay), {}))
                    for delay in DELAYS}
    by_pair_direction_delay = {key: scenario_coverage(counter_map(value, f"by_pair_direction_delay.{key}"))
                               for key, value in (impulse.get("by_pair_direction_delay") or {}).items()}
    retained = terminal_summary(rows)
    dropped = counts.get("terminal_export_dropped", 0)
    retained.update({"all_run_terminal_export_dropped": dropped,
                     "export_truncated": dropped > 0,
                     "all_run_complete_not_retained": complete-retained["complete"],
                     "all_run_censored_not_retained": censored_total-retained["censored"]})
    warnings = []
    if 2*candidates != complete+censored_total+pending_scenarios:
        warnings.append("candidate_scenario_conservation_mismatch")
    if armed != sum(arm_terminal.values())+pending_arms:
        warnings.append("arm_conservation_mismatch")
    if counts.get("arm_terminal", 0) != sum(arm_terminal.values()):
        warnings.append("arm_outcome_counter_mismatch")
    if candidates > armed: warnings.append("confirmed_exceeds_armed")
    if 2*candidates != len(rows)+dropped:
        warnings.append("terminal_export_drop_count_mismatch")
    if retained["all_run_complete_not_retained"] < 0 or retained["all_run_censored_not_retained"] < 0:
        warnings.append("retained_rows_exceed_all_run_counters")
    if any(row["scenario_accounting_residual"] for row in by_delay_all.values()):
        warnings.append("delay_scenario_conservation_mismatch")
    if any(row["counts"].get("candidates", 0) != candidates for row in by_delay_all.values()):
        warnings.append("delay_candidate_count_mismatch")
    if any(row["scenario_accounting_residual"] for row in by_pair_direction_delay.values()):
        warnings.append("pair_direction_delay_conservation_mismatch")
    if sum(row["counts"].get("candidates", 0) for row in by_pair_direction_delay.values()) != 2*candidates:
        warnings.append("pair_direction_delay_candidate_count_mismatch")
    if any(counts.get(f"scenario_{reason}", 0) != amount for reason, amount in censored.items()):
        warnings.append("scenario_censor_reason_count_mismatch")
    paired = paired_candidates(rows)
    by_delay = {str(delay): terminal_summary([row for row in rows if row["delay_seconds"] == delay])
                for delay in DELAYS}
    return {"source_status": snapshot["status"], "source_updated_at": snapshot.get("updated_at"),
            "model_version": impulse["model_version"],
            "study_assumptions": {key: impulse.get(key) for key in
                ("metric", "fee_assumption", "rh_usdg_usdc_assumption", "comparison_control",
                 "target_usd", "extra_cost_bps", "entry_delays_seconds",
                 "entry_deadline_seconds", "exit_request_after_entry_seconds",
                 "exit_observation_delay_seconds", "hard_trigger_to_exit_seconds")},
            "all_run": {"counts": counts, "gates": gates, "censor_reasons": censored,
                        "by_pair_counters": impulse.get("by_pair") or {},
                        "by_delay_counters": by_delay_all,
                        "by_pair_direction_delay_counters": by_pair_direction_delay,
                        "arm_terminal": arm_terminal,
                        "arm_accounting_residual": armed-sum(arm_terminal.values())-pending_arms,
                        "candidate_scenario_accounting_residual": 2*candidates-complete-censored_total-pending_scenarios,
                        "candidate_to_paired_entry_fraction": counts.get("paired_entry_quotes", 0)/(2*candidates) if candidates else None,
                        "paired_entry_to_complete_fraction": complete/counts["paired_entry_quotes"]
                        if counts.get("paired_entry_quotes", 0) else None,
                        "mean_complete_net_after_reserve_usd": impulse.get("mean_complete_net_after_reserve_usd")},
            "retained_export": retained, "retained_by_delay": by_delay,
            "paired_same_candidate": paired,
            "retained_by_pair_direction": grouped(rows, lambda row: row["pair"]+"|"+row["direction"]),
            "retained_by_five_minute_trigger_block_utc": grouped(
                rows, lambda row: utc(int(row["trigger_time"]//300)*300)),
            "retained_by_pair_direction_and_five_minute_block_utc": grouped(
                rows, lambda row: row["pair"]+"|"+row["direction"]+"|"+
                utc(int(row["trigger_time"]//300)*300)),
            "validation_warnings": warnings,
            "interpretation": [
                "Prospective quotes at a frozen quantity, not orders, paired fills, cash P&L, or realized profit.",
                "The 0.5 s and 1 s arrival scenarios share each confirmed candidate; their counts are correlated.",
                "First eligible future quote with insufficient entry or exit depth is censored, not treated as zero.",
                "Funding-unknown and stopped-pending outcomes stay censored, not breakeven observations.",
                "Source clocks across venues are not calibrated; receipt order is collector order only.",
                "USDG and USDC are treated at parity for this quote screen, with no conversion or collateral claim.",
                "There is no no-impulse control in v1; retained rows can omit older terminal scenarios."]}


def fmt(value, digits=2):
    return "?" if value is None else f"{value:,.{digits}f}"


def markdown(result):
    all_run = result["all_run"]
    counts = all_run["counts"]
    retained = result["retained_export"]
    lines = ["# Impulse dislocation quote study", "",
             "Stopped pilot. Quotes are prospective observations, not fills or cash P&L.", "",
             "## Full-run gate, arm, and scenario accounting", "",
             f"Armed {counts.get('armed', 0)}; confirmed candidates {counts.get('confirmed_candidates', 0)}; "
             f"paired entry quotes {counts.get('paired_entry_quotes', 0)}; complete quotes "
             f"{counts.get('scenario_complete', 0)}. Candidate scenario accounting residual "
             f"{all_run['candidate_scenario_accounting_residual']}; arm accounting residual "
             f"{all_run['arm_accounting_residual'] if all_run['arm_accounting_residual'] is not None else '?'}.", "",
             "Gate counts: " + (", ".join(f"{name}={value}" for name, value in sorted(all_run["gates"].items())) or "none") + ".", "",
             "Arm terminals: " + (", ".join(f"{name}={value}" for name, value in sorted(all_run["arm_terminal"].items())) or "not exported") + ".", "",
             "Censor reasons: " + (", ".join(f"{name}={value}" for name, value in sorted(all_run["censor_reasons"].items())) or "none") + ".", "",
             "| Arrival | Candidates | Paired entry quotes | Complete | Entry depth | Exit depth | "
             "Entry missing | Exit missing | Funding unknown | Stopped pending |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for delay in DELAYS:
        row = all_run["by_delay_counters"][str(delay)]["counts"]
        lines.append(f"| {delay:g} s | {row.get('candidates',0)} | {row.get('paired_entry_quotes',0)} | "
                     f"{row.get('scenario_complete',0)} | {row.get('scenario_entry_depth',0)} | "
                     f"{row.get('scenario_exit_depth',0)} | {row.get('scenario_entry_missing',0)} | "
                     f"{row.get('scenario_exit_missing',0)} | {row.get('scenario_funding_unknown',0)} | "
                     f"{row.get('scenario_stopped_pending',0)} |")
    lines += ["", "Other gate and censor reasons, including invalidation and minimum-notional failures, "
              "remain in the JSON counters.", "",
             "## Retained arrival scenarios", "",
             f"Terminal rows retained {retained['retained_terminal_rows']}; all-run export drops "
             f"{retained['all_run_terminal_export_dropped']}. Retained complete "
             f"{retained['complete']} of {counts.get('scenario_complete', 0)} all-run; retained censored "
             f"{retained['censored']} of {sum(all_run['censor_reasons'].values())} all-run. "
             "Distributions below use retained complete quoted outcomes only.", "",
             "| Arrival | Retained complete | Retained censored | Four-fee net mean / p10 / median / p90 USD | "
             "Four-fee positive | After reserve and capital mean / p10 / median / p90 USD | Positive |",
             "|---|---:|---:|---|---:|---|---:|"]
    for delay in DELAYS:
        summary = result["retained_by_delay"][str(delay)]
        econ = summary["quote_economics"]
        def shape(name):
            dist = econ["distributions_usd"][name]
            return " / ".join(fmt(dist[field]) for field in ("mean", "p10", "median", "p90"))
        def fraction(value): return "?" if value is None else f"{value:.1%}"
        lines.append(f"| {delay:g} s | {summary['complete']} | {summary['censored']} | "
                     f"{shape('net_after_four_fees_usd')} | "
                     f"{fraction(econ['four_fee_positive_fraction'])} | "
                     f"{shape('net_after_reserve_usd')} | "
                     f"{fraction(econ['after_reserve_capital_positive_fraction'])} |")
    lines += ["", "Entry timings include retained scenarios with a paired entry quote, even if the exit "
              "was censored. Exit timings include complete quotes only. Values are median milliseconds "
              "after each scenario's due time; HL and other venue are shown separately.", "",
              "| Arrival | Entry source HL / other ms | Entry receipt HL / other ms | "
              "Exit source HL / other ms | Exit receipt HL / other ms |",
              "|---|---:|---:|---:|---:|"]
    for delay in DELAYS:
        times = result["retained_by_delay"][str(delay)]["timing_seconds"]
        # The keys name stage before venue; spell them out to prevent mixing
        # exchange source time and collector receipt time.
        def pair_stage(stage, clock):
            hl = times[f"{stage}_hl_{clock}_after_due"]["median"]
            other = times[f"{stage}_other_{clock}_after_due"]["median"]
            return f"{fmt(hl*1000 if hl is not None else None, 0)} / " \
                   f"{fmt(other*1000 if other is not None else None, 0)}"
        lines.append(f"| {delay:g} s | {pair_stage('entry', 'source')} | "
                     f"{pair_stage('entry', 'receipt')} | {pair_stage('exit', 'source')} | "
                     f"{pair_stage('exit', 'receipt')} |")
    paired = result["paired_same_candidate"]
    lines += ["", "## Same-candidate paired comparison", "",
              f"Both scenarios retained for {paired['both_scenarios_retained']} candidates; both complete for "
              f"{paired['both_scenarios_complete']}. Retained candidates with only one scenario row: "
              f"{paired['unpaired_in_retained_export']}. Stress minus primary net quoted outcome "
              f"median ${fmt(paired['stress_minus_primary_net_after_reserve_usd']['median'])} "
              "among complete pairs only. Missing or censored outcomes are never filled with zero.", "",
              "## Retained breakouts", "",
              "The JSON contains scenario-separated counts and full mean/p10/median/p90 distributions "
              "for gross capture, each of four fees, reserve, capital, and net quotes by pair direction "
              "and five-minute UTC trigger block, separately and jointly. Censored-only groups remain present. "
              "These are retained-row views, "
              "not full-run cohort rates.", "",
              "Validation warnings: " + (", ".join(result["validation_warnings"]) or "none") + ".", "",
              "## Interpretation", ""]
    lines.extend(f"- {item}" for item in result["interpretation"])
    return "\n".join(lines)+"\n"


def write_report(result, out, name):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for suffix, content in (("json", json.dumps(result, indent=2, allow_nan=False)+"\n"),
                            ("md", markdown(result))):
        target = out/f"{name}.{suffix}"
        temporary = target.with_suffix(target.suffix+".tmp")
        temporary.write_text(content)
        os.replace(temporary, target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--name", default="latest")
    args = parser.parse_args(argv)
    if not args.name.isascii() or not 1 <= len(args.name) <= 32 or not all(
            char.isalnum() or char in "-_" for char in args.name):
        parser.error("--name must be 1..32 ASCII letters, digits, dash, or underscore")
    result = analyze(read_snapshot(args.snapshot))
    write_report(result, args.out, args.name)
    print(args.out/f"{args.name}.md")


if __name__ == "__main__": main()
