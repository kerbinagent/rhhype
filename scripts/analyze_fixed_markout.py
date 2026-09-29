#!/usr/bin/env python3
"""Analyze a stopped fixed-quantity quote pilot without treating quotes as fills."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/fixed-markout-research/fixed_markout_snapshot.json"
DEFAULT_OUTPUT = ROOT / "reports/fixed-markout"
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ROWS = 5000
MODELS = ("conditional_linear", "persistence", "historical_median", "horizon_delta")
THRESHOLDS = ("0", "0.25")
COHORTS = tuple(f"{model}_gt_{threshold}" for model in MODELS for threshold in THRESHOLDS)
MODEL_ROLES = {"conditional_linear": "primary", "persistence": "reference",
               "historical_median": "secondary", "horizon_delta": "secondary"}


def finite(value):
    if isinstance(value, bool): return None
    try: number = float(value)
    except (ValueError, TypeError, OverflowError): return None
    return number if math.isfinite(number) else None


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def number(value, name):
    result = finite(value)
    if result is None: raise ValueError(f"{name} must be finite")
    return result


def quantile(values, fraction):
    """Linearly interpolate at (n-1)*fraction; a singleton retains its value."""
    ordered = sorted(values)
    if not ordered: return None
    point = (len(ordered)-1)*fraction
    low = math.floor(point)
    high = math.ceil(point)
    return ordered[low] + (ordered[high]-ordered[low])*(point-low)


def distribution(values):
    values = list(values)
    if not values:
        return {"count": 0, "mean": None, "p10": None, "median": None, "p90": None}
    return {"count": len(values), "mean": statistics.fmean(values),
            "p10": quantile(values, .1), "median": quantile(values, .5),
            "p90": quantile(values, .9)}


def quote_summary(rows):
    four = [row["net_after_four_fees_usd"] for row in rows]
    reserved = [row["net_after_reserves_usd"] for row in rows]
    fee_keys = ("buy_entry_fee_usd", "sell_entry_fee_usd", "buy_exit_fee_usd",
                "sell_exit_fee_usd")
    return {"matched_rows": len(rows),
            "gross_capture_usd": distribution(row["gross_capture_usd"] for row in rows),
            "total_four_fees_usd": distribution(row["total_four_fees_usd"] for row in rows),
            "four_fee_components_usd": {key: distribution(row[key] for row in rows)
                                        for key in fee_keys},
            "net_after_four_fees_usd": distribution(four),
            "net_after_reserves_usd": distribution(reserved),
            "four_fee_positive_fraction": sum(value > 0 for value in four)/len(four) if four else None,
            "after_reserves_positive_fraction": sum(value > 0 for value in reserved)/len(reserved) if reserved else None}


def coverage(raw, name):
    raw = raw or {}
    values = {key: integer(raw.get(key, 0), f"{name}.{key}")
              for key in ("anchors", "matched", "censored", "pending")}
    anchors = values["anchors"]
    return {**values,
            "matched_fraction": values["matched"]/anchors if anchors else None,
            "censored_fraction": values["censored"]/anchors if anchors else None,
            "accounting_residual": anchors-values["matched"]-values["censored"]-values["pending"]}


def validate_row(row, index):
    if not isinstance(row, dict): raise ValueError(f"terminal row {index} must be an object")
    status = row.get("status")
    if status not in ("matched", "censored"):
        raise ValueError(f"terminal row {index} has invalid status")
    route = row.get("route")
    if not isinstance(route, str) or "|" not in route or not route.split("|", 1)[0]:
        raise ValueError(f"terminal row {index} has invalid route")
    clean = dict(row)
    clean["anchor_time"] = number(row.get("anchor_time"), f"row {index} anchor_time")
    if status == "matched":
        for key in ("gross_capture_usd", "total_four_fees_usd", "net_after_four_fees_usd",
                    "net_after_reserves_usd", "buy_entry_fee_usd", "sell_entry_fee_usd",
                    "buy_exit_fee_usd", "sell_exit_fee_usd"):
            clean[key] = number(row.get(key), f"row {index} {key}")
    forecasts = row.get("frozen_forecasts_bps")
    if forecasts is not None:
        if not isinstance(forecasts, dict) or set(forecasts) != set(MODELS):
            raise ValueError(f"terminal row {index} has incomplete frozen forecasts")
        screens = row.get("prediction_screens_usd")
        flags = row.get("screen_flags")
        if not isinstance(screens, dict) or set(screens) != set(MODELS):
            raise ValueError(f"terminal row {index} has incomplete frozen dollar screens")
        if not isinstance(flags, dict) or set(flags) != set(COHORTS) or any(
                not isinstance(flag, bool) for flag in flags.values()):
            raise ValueError(f"terminal row {index} has incomplete frozen cohort flags")
        clean["prediction_screens_usd"] = {
            model: number(screens[model], f"row {index} {model} screen") for model in MODELS}
    return clean


def scoped_summaries(rows):
    matched = [row for row in rows if row["status"] == "matched"]
    scored = [row for row in matched if row.get("frozen_forecasts_bps") is not None]
    return {"matched": quote_summary(matched), "v2_scored_matched": quote_summary(scored),
            "selected_matched": {cohort: quote_summary([row for row in scored
                                                         if row["screen_flags"][cohort]])
                                 for cohort in COHORTS}}


def grouped_summaries(rows, key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return {name: scoped_summaries(groups[name]) | {
                "retained_terminal_counts": {
                    "matched": sum(row["status"] == "matched" for row in groups[name]),
                    "censored": sum(row["status"] == "censored" for row in groups[name]),
                    "matched_scored": sum(row["status"] == "matched" and
                                          row.get("frozen_forecasts_bps") is not None for row in groups[name]),
                    "censored_scored": sum(row["status"] == "censored" and
                                           row.get("frozen_forecasts_bps") is not None for row in groups[name])}}
            for name in sorted(groups)}


def paired_forecast_errors(rows):
    scored = [row for row in rows if row["status"] == "matched" and
              row.get("frozen_forecasts_bps") is not None]
    models = {}
    for model in MODELS:
        forecast = [row["prediction_screens_usd"][model] for row in scored]
        actual = [row["net_after_four_fees_usd"] for row in scored]
        errors = [outcome-prediction for outcome, prediction in zip(actual, forecast)]
        models[model] = {"role": MODEL_ROLES[model], "paired_anchor_count": len(scored),
                         "forecast_usd": distribution(forecast),
                         "actual_four_fee_net_usd": distribution(actual),
                         "error_actual_minus_forecast_usd": distribution(errors),
                         "absolute_error_usd": distribution(abs(value) for value in errors),
                         "rmse_usd": math.sqrt(statistics.fmean(value*value for value in errors))
                         if errors else None}
    return {"common_scored_matched_anchor_count": len(scored), "models": models,
            "error_definition": "actual four-fee quote net USD minus frozen dollar screen USD"}


def analyze(snapshot):
    if snapshot.get("status") not in ("stopped", "finished") or not snapshot.get("fixed_markout", {}).get("finished"):
        raise ValueError("analysis requires a stopped/finished pilot and fixed_markout.finished=true")
    fixed = snapshot["fixed_markout"]
    if fixed.get("model_version") != 1: raise ValueError("unsupported fixed markout model version")
    if fixed.get("pending_anchors") != 0: raise ValueError("finished pilot still has pending anchors")
    raw_rows = fixed.get("terminal_rows")
    if not isinstance(raw_rows, list) or len(raw_rows) > MAX_ROWS:
        raise ValueError("terminal_rows must be a list of at most 5000 rows")
    rows = [validate_row(row, index) for index, row in enumerate(raw_rows)]
    counts = fixed.get("counts") or {}
    if not isinstance(counts, dict): raise ValueError("counts must be an object")
    all_counts = {key: integer(value, f"counts.{key}") for key, value in counts.items()}
    for key in ("anchors", "warmup_anchors", "v2_scored_anchors", "matched_anchors",
                "matched_scored_anchors", "censored_anchors", "censored_scored_anchors",
                "terminal_export_dropped"):
        all_counts.setdefault(key, 0)
    censor_reasons = {name: integer(value, f"censored.{name}")
                      for name, value in (fixed.get("censored") or {}).items()}
    rejections = {name: integer(value, f"rejections.{name}")
                  for name, value in (fixed.get("rejections") or {}).items()}
    per_route = {route: {name: integer(value, f"per_route.{route}.{name}")
                         for name, value in metrics.items()}
                 for route, metrics in (fixed.get("per_route") or {}).items()}
    if not isinstance(fixed.get("all_v2_scored_coverage"), dict):
        raise ValueError("missing all_v2_scored_coverage")
    source_cohorts = fixed.get("selected_anchor_coverage")
    if not isinstance(source_cohorts, dict) or set(source_cohorts) != set(COHORTS):
        raise ValueError("missing or unexpected predeclared selected cohorts")
    all_scored = coverage(fixed["all_v2_scored_coverage"], "all_v2_scored_coverage")
    all_cohorts = {name: coverage(source_cohorts[name], name) for name in COHORTS}
    retained = {"terminal_rows": len(rows),
                "matched": sum(row["status"] == "matched" for row in rows),
                "censored": sum(row["status"] == "censored" for row in rows),
                "matched_scored": sum(row["status"] == "matched" and
                                      row.get("frozen_forecasts_bps") is not None for row in rows),
                "censored_scored": sum(row["status"] == "censored" and
                                       row.get("frozen_forecasts_bps") is not None for row in rows)}
    retained["missing_matched_from_export"] = all_counts["matched_anchors"]-retained["matched"]
    retained["missing_censored_from_export"] = all_counts["censored_anchors"]-retained["censored"]
    retained["terminal_export_dropped_all_run"] = all_counts["terminal_export_dropped"]
    retained["export_truncated"] = retained["terminal_export_dropped_all_run"] > 0
    warnings = []
    if all_counts["anchors"] != all_counts["matched_anchors"]+all_counts["censored_anchors"]:
        warnings.append("all_run_anchor_accounting_mismatch")
    if all_counts["v2_scored_anchors"] != all_counts["matched_scored_anchors"]+all_counts["censored_scored_anchors"]:
        warnings.append("all_run_scored_accounting_mismatch")
    if all_counts["anchors"] != all_counts["warmup_anchors"]+all_counts["v2_scored_anchors"]:
        warnings.append("warmup_plus_scored_anchor_mismatch")
    if (all_scored["anchors"], all_scored["matched"], all_scored["censored"]) != (
            all_counts["v2_scored_anchors"], all_counts["matched_scored_anchors"],
            all_counts["censored_scored_anchors"]):
        warnings.append("all_scored_coverage_count_mismatch")
    if sum(censor_reasons.values()) != all_counts["censored_anchors"]:
        warnings.append("censor_reason_accounting_mismatch")
    if all_scored["accounting_residual"] or any(row["accounting_residual"] for row in all_cohorts.values()):
        warnings.append("cohort_accounting_mismatch")
    if retained["missing_matched_from_export"] < 0 or retained["missing_censored_from_export"] < 0:
        warnings.append("retained_rows_exceed_all_run_counters")
    if all_counts["terminal_export_dropped"] != all_counts["anchors"]-len(rows):
        warnings.append("terminal_export_drop_count_mismatch")
    if all_counts.get("route_metric_evictions", 0):
        warnings.append("per_route_full_run_counters_evicted")
    blocks = grouped_summaries(rows, lambda row: utc(int(row["anchor_time"]//300)*300))
    return {"source_updated_at": finite(snapshot.get("updated_at")),
            "source_status": snapshot["status"], "model_version": fixed["model_version"],
            "metric": fixed.get("metric"), "fee_assumption": fixed.get("fee_assumption"),
            "horizon_seconds": fixed.get("horizon_seconds"),
            "deadline_seconds": fixed.get("deadline_seconds"),
            "all_run": {"counts": all_counts, "censor_reasons": censor_reasons,
                        "rejections": rejections, "per_route_counts_bounded": per_route,
                        "v2_scored_coverage": all_scored,
                        "selected_cohort_coverage": all_cohorts},
            "retained_export": retained,
            "retained_quote_summaries": scoped_summaries(rows),
            "by_asset": grouped_summaries(rows, lambda row: row["route"].split("|", 1)[0]),
            "by_directed_route": grouped_summaries(rows, lambda row: row["route"]),
            "by_five_minute_anchor_block_utc": blocks,
            "paired_four_model_dollar_forecast_errors": paired_forecast_errors(rows),
            "validation_warnings": warnings,
            "interpretation": [
                "These are prospective fixed-original-quantity quotes after four frozen Standard taker fees, not fills or cash P&L.",
                "The reserve-adjusted quote screen additionally subtracts fixed extra-cost and elapsed capital estimates.",
                "Censored anchors have no observed economic outcome; retained rows may omit older terminals.",
                "Opposite directions and fee-screen cohorts share books, so rows and cohorts are not independent returns.",
                "Frozen v2 bps forecasts converted to dollars are diagnostics, not calibrated fixed-quantity predictions."]}


def read_snapshot(path):
    path = Path(path)
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("fixed markout snapshot exceeds 32 MiB input cap")
    with path.open() as source: snapshot = json.load(source)
    if not isinstance(snapshot, dict): raise ValueError("snapshot must be an object")
    return snapshot


def fmt(value, digits=2):
    return "?" if value is None else f"{value:,.{digits}f}"


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds") if value is not None else "?"


def markdown(result):
    all_run = result["all_run"]
    counts = all_run["counts"]
    retained = result["retained_export"]
    lines = ["# Fixed-quantity prospective quote study", "",
             f"Stopped snapshot: {utc(result['source_updated_at'])}. "
             f"Horizon {result['horizon_seconds']}–{result['deadline_seconds']} seconds.", "",
             "These are observed quotes at the original quantity, after four frozen Standard taker fees. "
             "They are not orders, fills, realized P&L, or an executable strategy claim.", "",
             "## Full-run coverage and censoring", "",
             f"Anchors {counts['anchors']}; warmup {counts['warmup_anchors']}; v2-scored "
             f"{counts['v2_scored_anchors']}; matched {counts['matched_anchors']}; "
             f"censored {counts['censored_anchors']}.", "",
             "| Cohort | Role | Anchors | Matched | Censored | Pending | Matched % | Censored % |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for name, row in [("all_v2_scored", all_run["v2_scored_coverage"]),
                      *all_run["selected_cohort_coverage"].items()]:
        role = "all scored" if name == "all_v2_scored" else MODEL_ROLES[name.rsplit("_gt_", 1)[0]]
        match = "?" if row["matched_fraction"] is None else f"{row['matched_fraction']:.1%}"
        censor = "?" if row["censored_fraction"] is None else f"{row['censored_fraction']:.1%}"
        lines.append(f"| {name} | {role} | {row['anchors']} | {row['matched']} | "
                     f"{row['censored']} | {row['pending']} | {match} | {censor} |")
    lines += ["", "Censor reasons: " + (", ".join(f"{name}={value}" for name, value in
                                           sorted(all_run["censor_reasons"].items())) or "none") + ".", "",
              "## Retained export and quote outcomes", "",
              f"Terminal rows retained {retained['terminal_rows']}; export drops "
              f"{retained['terminal_export_dropped_all_run']}. Retained matched "
              f"{retained['matched']} of {counts['matched_anchors']} full-run matched; retained censored "
              f"{retained['censored']} of {counts['censored_anchors']} full-run censored. "
              "All dollar distributions below use retained matched rows only.", "",
              "| Retained subset | n | Four-fee net mean / p10 / median / p90 USD | Four-fee positive | "
              "After-reserve net mean / p10 / median / p90 USD | After-reserve positive |",
              "|---|---:|---|---:|---|---:|"]
    def add_quote_row(label, row):
        four = row["net_after_four_fees_usd"]
        reserve = row["net_after_reserves_usd"]
        shape = lambda dist: " / ".join(fmt(dist[key]) for key in ("mean", "p10", "median", "p90"))
        fraction = lambda value: "?" if value is None else f"{value:.1%}"
        lines.append(f"| {label} | {row['matched_rows']} | {shape(four)} | "
                     f"{fraction(row['four_fee_positive_fraction'])} | {shape(reserve)} | "
                     f"{fraction(row['after_reserves_positive_fraction'])} |")
    summary = result["retained_quote_summaries"]
    add_quote_row("all matched", summary["matched"])
    add_quote_row("v2-scored matched", summary["v2_scored_matched"])
    for name in COHORTS: add_quote_row(name, summary["selected_matched"][name])
    matched_fees = summary["matched"]["four_fee_components_usd"]
    lines += ["", "Retained all-matched gross quoted capture mean: "
              f"${fmt(summary['matched']['gross_capture_usd']['mean'])}; four frozen-fee means "
              f"buy entry ${fmt(matched_fees['buy_entry_fee_usd']['mean'])}, "
              f"sell entry ${fmt(matched_fees['sell_entry_fee_usd']['mean'])}, "
              f"buy exit ${fmt(matched_fees['buy_exit_fee_usd']['mean'])}, "
              f"sell exit ${fmt(matched_fees['sell_exit_fee_usd']['mean'])}. All fee distributions are in JSON."]
    lines += ["", "Selected thresholds were frozen at $0 and $0.25. The conditional-linear "
              "cohorts are primary; persistence is a reference; historical-median and horizon-delta "
              "are secondary. Cohorts overlap and censoring can bias matched-only quote summaries.", "",
              "## Paired four-model forecast errors", "",
              "Every model below is evaluated on the same retained matched v2-scored anchors. "
              "Error is actual four-fee quote net minus the frozen dollar screen.", "",
              "| Model | Role | Same n | Mean error USD | Median absolute error USD | RMSE USD |",
              "|---|---|---:|---:|---:|---:|"]
    paired = result["paired_four_model_dollar_forecast_errors"]
    for model in MODELS:
        row = paired["models"][model]
        lines.append(f"| {model} | {row['role']} | {row['paired_anchor_count']} | "
                     f"{fmt(row['error_actual_minus_forecast_usd']['mean'])} | "
                     f"{fmt(row['absolute_error_usd']['median'])} | {fmt(row['rmse_usd'])} |")
    lines += ["", "## Retained breakdowns", "",
              "Full distributions and selected-cohort results by asset, directed route, and five-minute "
              "UTC anchor block are in the JSON. These breakouts are retained-row views, not full-run rates.", "",
              f"Asset groups: {len(result['by_asset'])}; directed routes: {len(result['by_directed_route'])}; "
              f"five-minute blocks: {len(result['by_five_minute_anchor_block_utc'])}."]
    for title, groups in (("Asset", result["by_asset"]),
                          ("Directed route", result["by_directed_route"]),
                          ("Five-minute UTC anchor block", result["by_five_minute_anchor_block_utc"])):
        lines += ["", f"### {title}", "",
                  "| Group | Matched n | Censored n | Four-fee net median USD | Four-fee positive | "
                  "After-reserve positive | V2-scored matched n | Primary selected >$0 n | Primary selected >$0.25 n |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for name, group in groups.items():
            matched = group["matched"]
            scored = group["v2_scored_matched"]
            selected = group["selected_matched"]
            fraction = lambda value: "?" if value is None else f"{value:.1%}"
            lines.append(f"| {str(name).replace('|', '&#124;')} | {matched['matched_rows']} | "
                         f"{group['retained_terminal_counts']['censored']} | "
                         f"{fmt(matched['net_after_four_fees_usd']['median'])} | "
                         f"{fraction(matched['four_fee_positive_fraction'])} | "
                         f"{fraction(matched['after_reserves_positive_fraction'])} | "
                         f"{scored['matched_rows']} | "
                         f"{selected['conditional_linear_gt_0']['matched_rows']} | "
                         f"{selected['conditional_linear_gt_0.25']['matched_rows']} |")
    lines += ["", "Validation warnings: " + (", ".join(result["validation_warnings"]) or "none") + ".", "",
              "## Interpretation", ""]
    lines.extend(f"- {item}" for item in result["interpretation"])
    return "\n".join(lines) + "\n"


def write_report(result, out, name):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for suffix, content in (("json", json.dumps(result, indent=2, allow_nan=False) + "\n"),
                            ("md", markdown(result))):
        target = out / f"{name}.{suffix}"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content)
        os.replace(temporary, target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--name", default="latest")
    args = parser.parse_args(argv)
    if not args.name.isascii() or not args.name.replace("-", "").replace("_", "").isalnum() or len(args.name) > 32:
        parser.error("--name must be 1..32 ASCII letters, digits, dash, or underscore")
    result = analyze(read_snapshot(args.snapshot))
    write_report(result, args.out, args.name)
    print(args.out / f"{args.name}.md")


if __name__ == "__main__": main()
