#!/usr/bin/env python3
"""Read-only, bounded comparison of synchronized depth and BBO paper pilots.

Lifetime P&L comes only from each engine ledger. Retained trades supply
diagnostics and may cover less than the lifetime population. No portfolio
totals are added together: the portfolios share signals and market feeds.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPTH = ROOT / "data/paper-monitor-feed-depth"
DEFAULT_BBO = ROOT / "data/paper-monitor-feed-bbo"
DEFAULT_OUT = ROOT / "reports/feed-experiment"
END_STATUSES = ("CLOSED", "CLOSED_ESTIMATED")


def finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds") if value is not None else None


def metric(values):
    ordered = sorted(x for value in values if (x := finite(value)) is not None)
    if not ordered:
        return {"count": 0, "median": None, "p95": None, "mean": None}
    return {"count": len(ordered), "median": statistics.median(ordered),
            "p95": ordered[math.ceil(.95 * len(ordered)) - 1],
            "mean": statistics.fmean(ordered)}


def market_id(market):
    return f"{market['venue']}:{market['market']}"


def pair_id(pair):
    return f"{pair['asset']}|{market_id(pair['hl'])}|{market_id(pair['other'])}"


def pair_economics(pair):
    fields = ("venue", "market", "fee_bps", "published_fee_floor_bps", "step",
              "min_qty", "max_qty", "min_notional", "collateral")
    return {"asset": pair["asset"], "category": pair.get("category"),
            "hl": {key: pair["hl"].get(key) for key in fields},
            "other": {key: pair["other"].get(key) for key in fields}}


def read_run(path: Path, max_trades: int) -> dict:
    """Hold the SQLite read transaction only for the state and bounded rows."""
    path = Path(path)
    config = json.loads((path / "paper_config.json").read_text())
    markets = json.loads((path / "markets.json").read_text())
    snapshot = json.loads((path / "paper_snapshot.json").read_text())
    uri = (path / "paper.sqlite3").resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True, timeout=.5)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        checkpoint = db.execute("SELECT payload,updated FROM engine_state WHERE id=1").fetchone()
        if checkpoint is None:
            raise ValueError(f"No paper checkpoint in {path}")
        state = json.loads(checkpoint[0])
        saved_at = finite(state.get("saved_at")) or float(checkpoint[1])
        rows = db.execute(
            "SELECT payload FROM trades WHERE status IN ('CLOSED','CLOSED_ESTIMATED') "
            "AND closed_at<=? ORDER BY closed_at DESC LIMIT ?",
            (saved_at, max_trades + 1)).fetchall()
        retained_at_checkpoint = db.execute(
            "SELECT COUNT(*) FROM trades WHERE status IN ('CLOSED','CLOSED_ESTIMATED') "
            "AND closed_at<=?", (saved_at,)).fetchone()[0]
        db.execute("COMMIT")
    finally:
        db.close()
    pairs = {pair_id(pair): pair for pair in markets["pairs"]}
    return {"path": str(path), "config": config, "pairs": pairs,
            "snapshot": snapshot, "state": state,
            "checkpoint_at": saved_at, "sqlite_updated_at": float(checkpoint[1]),
            "trades": [json.loads(row[0]) for row in rows[:max_trades]],
            "retained_closed_at_checkpoint": retained_at_checkpoint,
            "query_truncated": len(rows) > max_trades}


def ledger_row(ledger):
    exact = int(ledger.get("closed_trades", 0))
    estimated = int(ledger.get("estimated_trades", 0))
    closed = exact + estimated
    wins = int(ledger.get("closed_wins_exact", 0)) + int(ledger.get("closed_wins_estimated", 0))
    losses = int(ledger.get("closed_losses_exact", 0)) + int(ledger.get("closed_losses_estimated", 0))
    pnl_exact = float(ledger.get("closed_pnl_exact", 0))
    pnl_estimated = float(ledger.get("closed_pnl_estimated", 0))
    return {"closed_exact": exact, "closed_estimated": estimated, "closed_total": closed,
            "closed_pnl_exact_usd": pnl_exact, "closed_pnl_estimated_usd": pnl_estimated,
            "closed_pnl_total_usd": pnl_exact + pnl_estimated,
            "wins": wins, "losses": losses, "flat": max(0, closed - wins - losses),
            "aborted": int(ledger.get("aborted_trades", 0)),
            "entry_attempts": int(ledger.get("entry_attempts", 0)),
            "winning_sum_usd": float(ledger.get("closed_profit_sum_exact", 0)) +
                               float(ledger.get("closed_profit_sum_estimated", 0)),
            "losing_sum_usd": float(ledger.get("closed_loss_sum_exact", 0)) +
                              float(ledger.get("closed_loss_sum_estimated", 0)),
            "fees_usd": float(ledger.get("fees_usd", 0)),
            "funding_usd": float(ledger.get("funding_usd", 0)),
            "other_costs_usd": float(ledger.get("other_costs_usd", 0)),
            "capital_costs_usd": float(ledger.get("capital_costs_usd", 0)),
            "mean_pnl_per_closed_usd": (pnl_exact + pnl_estimated) / closed if closed else None,
            "win_fraction": wins / closed if closed else None}


def pairing(trade):
    legs = trade.get("legs", ())
    if len(legs) != 2:
        return "unknown"
    quantities = [finite(leg.get("quantity")) for leg in legs]
    if trade.get("exit_reason") == "entry_failure" or any(q is None or q <= 0 for q in quantities):
        return "failed_hedge"
    if abs(quantities[0] - quantities[1]) > max(1e-9, quantities[0] * 1e-9):
        return "failed_hedge"
    return "paired"


def diagnostic(trades, pair_map, cumulative_closed, common_cutoff):
    own = list(trades)
    common = [trade for trade in own if finite(trade.get("closed_at")) is not None and
              float(trade["closed_at"]) <= common_cutoff and
              finite(trade.get("settled_at")) is not None and float(trade["settled_at"]) <= common_cutoff]
    classes = Counter(pairing(trade) for trade in common)
    paired = [trade for trade in common if pairing(trade) == "paired"]
    source = Counter()
    hl_source = Counter()
    observed_legs = total_legs = filled_legs = hl_filled_legs = 0
    entry_ms, exit_ms, deterioration, pnl_minus_signal = [], [], [], []
    category = defaultdict(lambda: {"closed": 0, "pnl_usd": 0.0, "failed_hedges": 0})
    route = defaultdict(lambda: {"closed": 0, "pnl_usd": 0.0, "failed_hedges": 0,
                                  "wins": 0, "category": "unknown", "asset": "unknown"})
    for trade in common:
        legs = trade.get("legs", ())
        for leg in legs:
            total_legs += 1
            if finite(leg.get("quantity")) is None or float(leg["quantity"]) <= 0:
                continue
            filled_legs += 1
            observation = leg.get("entry_observation")
            if isinstance(observation, dict):
                observed_legs += 1
            label = observation.get("book_source", "unknown") if isinstance(observation, dict) else "missing_observation"
            source[str(label)] += 1
            if leg.get("venue") == "hyperliquid":
                hl_filled_legs += 1
                hl_source[str(label)] += 1
        exit_request = finite(trade.get("exit_requested_at"))
        closed = finite(trade.get("closed_at"))
        if exit_request is not None and closed is not None and closed >= exit_request:
            exit_ms.append((closed - exit_request) * 1000)
        pnl = finite(trade.get("net_pnl_usd")) or 0.0
        pair = pair_map.get(trade.get("pair_id"), {})
        group = str(pair.get("category") or "unknown")
        category[group]["closed"] += 1
        category[group]["pnl_usd"] += pnl
        failed = pairing(trade) == "failed_hedge"
        category[group]["failed_hedges"] += int(failed)
        direction = trade.get("signal", {}).get("route") or trade.get("pair_id") or "unknown"
        r = route[direction]
        r.update(category=group, asset=trade.get("asset", "unknown"))
        r["closed"] += 1
        r["pnl_usd"] += pnl
        r["failed_hedges"] += int(failed)
        r["wins"] += int(pnl > 0)
    paired_exit_request_count = 0
    for trade in paired:
        legs = trade["legs"]
        if finite(trade.get("exit_requested_at")) is not None:
            paired_exit_request_count += 1
        created = finite(trade.get("created_at"))
        fill_times = [finite(leg.get("entry_time")) for leg in legs]
        if created is not None and all(t is not None and t >= created for t in fill_times):
            entry_ms.append((max(fill_times) - created) * 1000)
        long = next((leg for leg in legs if leg.get("side") == "long"), None)
        short = next((leg for leg in legs if leg.get("side") == "short"), None)
        signal = trade.get("signal", {})
        signal_qty = finite(signal.get("quantity"))
        if long and short and signal_qty is not None and abs(signal_qty - float(long["quantity"])) <= max(1e-9, signal_qty * 1e-9):
            actual_entry = float(short["entry_value"]) - float(long["entry_value"]) - sum(float(leg.get("entry_fee", 0)) for leg in legs)
            planned_entry = finite(signal.get("opening_edge_usd"))
            if planned_entry is not None:
                deterioration.append(actual_entry - planned_entry)
                pnl = finite(trade.get("net_pnl_usd"))
                if pnl is not None:
                    pnl_minus_signal.append(pnl - planned_entry)
    return {"retained_closed_own_checkpoint": len(own),
            "retained_closed_common_cutoff": len(common),
            "lifetime_closed_at_own_checkpoint": cumulative_closed,
            "coverage_fraction_own_checkpoint": len(own) / cumulative_closed if cumulative_closed else None,
            "common_cutoff_fraction_of_lifetime": len(common) / cumulative_closed if cumulative_closed else None,
            "paired": classes["paired"], "failed_hedge": classes["failed_hedge"],
            "other_or_unknown_pairing": classes["unknown"],
            "entry_observation_legs": observed_legs, "filled_entry_legs": filled_legs,
            "hyperliquid_filled_entry_legs": hl_filled_legs, "all_entry_legs": total_legs,
            "entry_observation_coverage_fraction": observed_legs / filled_legs if filled_legs else None,
            "paired_exit_request_coverage_fraction": paired_exit_request_count / len(paired) if paired else None,
            "entry_book_source_counts": dict(source), "hyperliquid_entry_book_source_counts": dict(hl_source),
            "paired_created_to_last_entry_fill_ms": metric(entry_ms),
            "exit_request_to_closed_ms": metric(exit_ms),
            "same_size_actual_minus_signal_entry_edge_usd": metric(deterioration),
            "same_size_net_trade_minus_signal_entry_edge_usd": metric(pnl_minus_signal),
            "retained_categories": dict(category), "routes": dict(route)}


def outstanding(positions, portfolio, checkpoint_at):
    current = [position for position in positions.values()
               if position.get("strategy") == portfolio]
    status = Counter(position.get("status", "unknown") for position in current)
    ages = [checkpoint_at - created for position in current
            if (created := finite(position.get("created_at"))) is not None]
    exit_ages = [checkpoint_at - requested for position in current
                 if position.get("status") == "EXITING" and
                 (requested := finite(position.get("exit_requested_at"))) is not None]
    one_lot_residuals = []
    for position in current:
        if position.get("status") != "EXITING": continue
        age = checkpoint_at - (finite(position.get("created_at")) or checkpoint_at)
        if age < 60: continue
        for leg in position.get("legs", ()):
            remaining, step = finite(leg.get("remaining")), finite(leg.get("step"))
            if remaining is not None and step is not None and step > 0 and 0 < remaining <= step * (1 + 1e-6):
                one_lot_residuals.append({"position_id": position.get("id"),
                                          "asset": position.get("asset"),
                                          "venue": leg.get("venue"),
                                          "remaining": remaining, "lot_step": step,
                                          "age_seconds": age})
    return {"total": len(current), "status_counts": dict(status),
            "filled_exposure_positions": sum(any((finite(leg.get("remaining")) or 0) > 0
                                                  for leg in position.get("legs", ())) for position in current),
            "pending_entries": status["ENTRY_PENDING"], "pending_exits": status["EXITING"],
            "pending_funding": status["AWAITING_FUNDING"],
            "oldest_age_seconds": max(ages) if ages else None,
            "oldest_exit_request_age_seconds": max(exit_ages) if exit_ages else None,
            "aged_one_lot_exit_residuals": one_lot_residuals[:20],
            "aged_one_lot_exit_residual_count": len(one_lot_residuals)}


def compare(depth: dict, bbo: dict, *, max_routes=50, skew_limit=5.0,
            pilot_minutes=40.0, now=None) -> dict:
    now = time.time() if now is None else float(now)
    depth_pairs, bbo_pairs = depth["pairs"], bbo["pairs"]
    pair_delta = {"depth_only": sorted(set(depth_pairs) - set(bbo_pairs)),
                  "bbo_only": sorted(set(bbo_pairs) - set(depth_pairs)),
                  "economics_differ": sorted(key for key in set(depth_pairs) & set(bbo_pairs)
                                             if pair_economics(depth_pairs[key]) != pair_economics(bbo_pairs[key]))}
    config_equal = depth["config"] == bbo["config"]
    common = min(depth["checkpoint_at"], bbo["checkpoint_at"])
    skew = abs(depth["checkpoint_at"] - bbo["checkpoint_at"])
    starts = {label: finite(run["state"]["engine"].get("shadow_started_at"))
              for label, run in (("depth", depth), ("bbo", bbo))}
    start_gap = abs(starts["depth"] - starts["bbo"]) if all(v is not None for v in starts.values()) else None
    ledgers = {label: {name: ledger_row(row) for name, row in run["state"]["engine"]["ledgers"].items()}
               for label, run in (("depth", depth), ("bbo", bbo))}
    names = sorted(set(ledgers["depth"]) | set(ledgers["bbo"]))
    portfolios = {}
    all_routes = defaultdict(dict)
    for name in names:
        left, right = ledgers["depth"].get(name), ledgers["bbo"].get(name)
        if left is None or right is None:
            portfolios[name] = {"missing_portfolio": True, "depth": left, "bbo": right}
            continue
        dtrades = [trade for trade in depth["trades"] if trade.get("strategy") == name]
        btrades = [trade for trade in bbo["trades"] if trade.get("strategy") == name]
        d = diagnostic(dtrades, depth_pairs, left["closed_total"], common)
        b = diagnostic(btrades, bbo_pairs, right["closed_total"], common)
        for route, row in d.pop("routes").items():
            all_routes[(name, route)]["depth"] = row
        for route, row in b.pop("routes").items():
            all_routes[(name, route)]["bbo"] = row
        portfolios[name] = {"depth": left, "bbo": right,
                            "outstanding_at_checkpoint": {
                                "depth": outstanding(depth["state"]["engine"].get("positions", {}),
                                                     name, depth["checkpoint_at"]),
                                "bbo": outstanding(bbo["state"]["engine"].get("positions", {}),
                                                   name, bbo["checkpoint_at"])},
                            "difference_bbo_minus_depth": {
                                "closed_total": right["closed_total"] - left["closed_total"],
                                "closed_pnl_total_usd": right["closed_pnl_total_usd"] - left["closed_pnl_total_usd"],
                                "wins": right["wins"] - left["wins"],
                                "aborted": right["aborted"] - left["aborted"]},
                            "retained_diagnostics": {"depth": d, "bbo": b}}
    ranked_routes = sorted(all_routes.items(), key=lambda item: -sum(
        row.get("closed", 0) for row in item[1].values()))[:max_routes]
    routes = [{"portfolio": name, "route": route,
               "depth": rows.get("depth"), "bbo": rows.get("bbo")}
              for (name, route), rows in ranked_routes]
    flags = []
    if not config_equal: flags.append("configs_differ")
    if any(pair_delta.values()): flags.append("pair_universe_or_economics_differ")
    if skew > skew_limit: flags.append("checkpoint_skew_exceeds_limit")
    if start_gap is None or start_gap > 1: flags.append("pilot_starts_not_matched")
    if depth["query_truncated"] or bbo["query_truncated"]:
        flags.append("diagnostic_query_limit_reached")
    for name, row in portfolios.items():
        diag = row.get("retained_diagnostics")
        if diag and any(side["coverage_fraction_own_checkpoint"] is not None and
                        side["coverage_fraction_own_checkpoint"] < .95
                        for side in diag.values()):
            flags.append("retained_trades_pruned_or_query_limited")
            break
    for row in portfolios.values():
        diag = row.get("retained_diagnostics")
        if not diag: continue
        d, b = diag["depth"], diag["bbo"]
        observed = (d["entry_observation_coverage_fraction"], b["entry_observation_coverage_fraction"])
        if all(value is not None for value in observed) and abs(observed[0] - observed[1]) > .25:
            flags.append("entry_observation_instrumentation_differs")
        exit_coverage = [side["paired_exit_request_coverage_fraction"] for side in (d, b)]
        if d["paired"] >= 10 and b["paired"] >= 10 and all(value is not None for value in exit_coverage) and abs(exit_coverage[0] - exit_coverage[1]) > .25:
            flags.append("exit_request_instrumentation_differs")
        if any(side["aged_one_lot_exit_residual_count"] for side in row["outstanding_at_checkpoint"].values()):
            flags.append("aged_one_lot_exit_residual_censoring")
    snapshot = {}
    for label, run in (("depth", depth), ("bbo", bbo)):
        snap = run["snapshot"]
        observed = finite(snap.get("updated_at"))
        snapshot[label] = {"snapshot_at": observed, "snapshot_utc": utc(observed),
                           "snapshot_age_seconds": now - observed if observed is not None else None,
                           "snapshot_minus_checkpoint_seconds": observed - run["checkpoint_at"] if observed is not None else None,
                           "status": snap.get("status"), "hl_quote_mode": snap.get("hl_quote_mode"),
                           "cpu_percent_one_core": finite(snap.get("cpu_percent_one_core")),
                           "loop_lag_p95_ms": finite(snap.get("loop_lag_p95_ms")),
                           "book_events_per_second": finite(snap.get("book_events_per_second"))}
    if snapshot["depth"]["hl_quote_mode"] not in ("depth", "l2book") or snapshot["bbo"]["hl_quote_mode"] != "bbo_plus_depth":
        flags.append("feed_modes_not_verified")
    if any(v["snapshot_age_seconds"] is None or
           (v["status"] not in ("stopped", "failed") and v["snapshot_age_seconds"] > 15)
           for v in snapshot.values()):
        flags.append("stale_performance_snapshot")
    duration = common - min(v for v in starts.values() if v is not None) if any(v is not None for v in starts.values()) else None
    both_stopped = all(v["status"] == "stopped" for v in snapshot.values())
    early_quantity_bug = (both_stopped and duration is not None and duration < pilot_minutes * 60 and
                          "aged_one_lot_exit_residual_censoring" in flags)
    if early_quantity_bug:
        flags.append("early_stop_due_quantity_bug")
    return {"generated_at": now, "generated_utc": utc(now),
            "comparison_status": ("early_stop_due_quantity_bug" if early_quantity_bug else
                                  "interim" if duration is None or duration < pilot_minutes * 60 else
                                  "duration_reached"),
            "decision": ("Do not rank feeds from this pilot: aged one-lot exit residuals censor closed-trade outcomes. "
                         "Repeat both feeds after the execution fix."
                         if "aged_one_lot_exit_residual_censoring" in flags else
                         "No automatic feed promotion; evaluate after a matched, sufficiently populated run."),
            "config_equal": config_equal,
            "pair_count": {"depth": len(depth_pairs), "bbo": len(bbo_pairs)},
            "pair_differences": pair_delta, "portfolio_names_match": set(ledgers["depth"]) == set(ledgers["bbo"]),
            "pilot_start_at": starts, "pilot_start_gap_seconds": start_gap,
            "checkpoint_at": {"depth": depth["checkpoint_at"], "bbo": bbo["checkpoint_at"]},
            "checkpoint_utc": {"depth": utc(depth["checkpoint_at"]), "bbo": utc(bbo["checkpoint_at"])},
            "checkpoint_skew_seconds": skew, "common_retained_cutoff": common,
            "common_retained_cutoff_utc": utc(common), "common_duration_seconds": duration,
            "snapshot_performance_separate_times": snapshot,
            "retention": {label: {"stored_closed_at_own_checkpoint": run["retained_closed_at_checkpoint"],
                                  "queried_closed": len(run["trades"]),
                                  "query_truncated": run["query_truncated"]}
                          for label, run in (("depth", depth), ("bbo", bbo))},
            "portfolios_independent_do_not_sum": portfolios,
            "retained_route_rows_top_by_count": routes,
            "retained_route_rows_omitted": max(0, len(all_routes) - len(routes)),
            "comparability_flags": sorted(set(flags)),
            "limitations": [
                "Cumulative ledger totals are each run's latest checkpoint and cannot be rewound to the common cutoff.",
                "Retained trade diagnostics use the common earlier checkpoint cutoff and may omit pruned trades.",
                "Depth and BBO portfolios share opportunities; portfolio P&L must not be summed as independent returns.",
                "The feed cohorts may have different numbers and mixes of attempted trades; net P&L alone cannot rank feeds.",
                "Public displayed quotes and paper fills do not prove executable orders.",
                "CPU and p95 lag are separate snapshot observations, not one synchronized measurement.",
                "Entry-edge deterioration is measured only for paired, full planned size; exit delay requires exit_requested_at.",
                "Only trades settled by the common earlier checkpoint enter retained comparisons; open and unsettled positions stay separate.",
            ]}


def _cash(value):
    return "?" if value is None else f"{value:+,.2f}"


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def _measure(value, digits=1):
    return "?" if value is None else f"{value:.{digits}f}"


def markdown(result):
    lines = ["# Depth versus BBO paper pilot", "",
             f"Generated: {result['generated_utc']} · status: **{result['comparison_status']}**", "",
             f"Common retained-trade cutoff: {result['common_retained_cutoff_utc']} "
             f"(checkpoint skew {result['checkpoint_skew_seconds']:.2f} s).", "",
             f"Config equal: **{result['config_equal']}**. Pair counts: depth {result['pair_count']['depth']}, "
             f"BBO {result['pair_count']['bbo']}. Flags: {', '.join(result['comparability_flags']) or 'none'}.", "",
             "## Lifetime ledger totals", "",
             "Each row is an independent paper portfolio. The totals are at each run's own checkpoint.", "",
             "| Portfolio | Feed | Attempts | Closed | Exact P&L | Est. P&L | Total P&L | Wins | Losses | Aborted | Mean/trade |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for portfolio, row in result["portfolios_independent_do_not_sum"].items():
        for feed in ("depth", "bbo"):
            value = row.get(feed)
            if not value: continue
            lines.append(f"| {portfolio} | {feed} | {value['entry_attempts']} | {value['closed_total']} | "
                         f"{_cash(value['closed_pnl_exact_usd'])} | {_cash(value['closed_pnl_estimated_usd'])} | "
                         f"{_cash(value['closed_pnl_total_usd'])} | "
                         f"{value['wins']} | {value['losses']} | {value['aborted']} | "
                         f"{_cash(value['mean_pnl_per_closed_usd'])} |")
    lines += ["", "## Outstanding at each checkpoint", "",
              "Aged one-lot residuals are a known execution censoring risk for this pilot.", "",
              "| Portfolio | Feed | Filled exposure | Entry pending | Exit pending | Funding pending | Oldest age s | Oldest exit wait s | Aged one-lot residuals |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for portfolio, row in result["portfolios_independent_do_not_sum"].items():
        for feed in ("depth", "bbo"):
            state = row.get("outstanding_at_checkpoint", {}).get(feed)
            if not state: continue
            lines.append(f"| {portfolio} | {feed} | {state['filled_exposure_positions']} | "
                         f"{state['pending_entries']} | {state['pending_exits']} | "
                         f"{state['pending_funding']} | {_measure(state['oldest_age_seconds'],0)} | "
                         f"{_measure(state['oldest_exit_request_age_seconds'],0)} | "
                         f"{state['aged_one_lot_exit_residual_count']} |")
    lines += ["", "## Retained closed-trade diagnostics", "",
              "These rows use only trades retained in SQLite at the earlier checkpoint cutoff.", "",
              "| Portfolio | Feed | Common retained / lifetime | Common fraction | Paired | Failed hedge | Entry ms median | Exit ms median | Full-size entry gap $ median |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for portfolio, row in result["portfolios_independent_do_not_sum"].items():
        for feed in ("depth", "bbo"):
            diag = row.get("retained_diagnostics", {}).get(feed)
            if not diag: continue
            coverage = diag["common_cutoff_fraction_of_lifetime"]
            entry = diag["paired_created_to_last_entry_fill_ms"]["median"]
            entry_n = diag["paired_created_to_last_entry_fill_ms"]["count"]
            exit_delay = diag["exit_request_to_closed_ms"]["median"]
            exit_n = diag["exit_request_to_closed_ms"]["count"]
            edge = diag["same_size_actual_minus_signal_entry_edge_usd"]["median"]
            lines.append(f"| {portfolio} | {feed} | {diag['retained_closed_common_cutoff']} / "
                         f"{diag['lifetime_closed_at_own_checkpoint']} | "
                         f"{coverage:.1%} | " if coverage is not None else
                         f"| {portfolio} | {feed} | {diag['retained_closed_common_cutoff']} / "
                         f"{diag['lifetime_closed_at_own_checkpoint']} | ? | ")
            lines[-1] += (f"{diag['paired']} | {diag['failed_hedge']} | "
                          f"{entry:.0f} (n={entry_n}) | " if entry is not None else
                          f"{diag['paired']} | {diag['failed_hedge']} | ? | ")
            lines[-1] += f"{exit_delay:.0f} (n={exit_n}) | " if exit_delay is not None else "? | "
            lines[-1] += f"{_cash(edge)} |"
    lines += ["", "## Performance snapshots", "",
              "Performance figures are from separate JSON snapshot timestamps.", "",
              "| Feed | Snapshot UTC | CPU % of one core | p95 loop lag ms | Book events/s |",
              "|---|---|---:|---:|---:|"]
    for feed, row in result["snapshot_performance_separate_times"].items():
        lines.append(f"| {feed} | {row['snapshot_utc']} | {_measure(row['cpu_percent_one_core'])} | "
                     f"{_measure(row['loop_lag_p95_ms'])} | {_measure(row['book_events_per_second'],0)} |")
    lines += ["", "## Hyperliquid entry provenance", "",
              "Counts are retained closed-trade legs at the common cutoff. Missing observations limit source comparisons.", "",
              "| Portfolio | Feed | Observed / filled legs | HL filled | HL BBO | HL l2book | HL missing |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for portfolio, row in result["portfolios_independent_do_not_sum"].items():
        for feed in ("depth", "bbo"):
            diag = row.get("retained_diagnostics", {}).get(feed)
            if not diag or not diag["filled_entry_legs"]: continue
            sources = diag["hyperliquid_entry_book_source_counts"]
            lines.append(f"| {portfolio} | {feed} | {diag['entry_observation_legs']} / "
                         f"{diag['filled_entry_legs']} | {diag['hyperliquid_filled_entry_legs']} | "
                         f"{sources.get('bbo',0)} | "
                         f"{sources.get('l2book',0)} | {sources.get('missing_observation',0)} |")
    lines += ["", "## Retained route examples", "",
              "Top rows by retained closed count. Category and P&L are for one portfolio and route at a time.", "",
              "| Portfolio | Route | Category | Depth closed / P&L | BBO closed / P&L |",
              "|---|---|---|---:|---:|"]
    for item in result["retained_route_rows_top_by_count"][:10]:
        depth, bbo = item.get("depth") or {}, item.get("bbo") or {}
        category = depth.get("category") or bbo.get("category") or "unknown"
        lines.append(f"| {_cell(item['portfolio'])} | {_cell(item['route'])} | {_cell(category)} | "
                     f"{depth.get('closed',0)} / {_cash(depth.get('pnl_usd'))} | "
                     f"{bbo.get('closed',0)} / {_cash(bbo.get('pnl_usd'))} |")
    lines += ["", "## Reading this result", "",
              result["decision"], "",
              "Full source counts and crypto/RWA groups are in the JSON under each portfolio's retained diagnostics.", "",
              "### Limits", ""]
    lines.extend(f"- {item}" for item in result["limitations"])
    return "\n".join(lines) + "\n"


def write_report(result: dict, output: Path, name: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    stem = output / name
    for suffix, content in ((".json", json.dumps(result, indent=2, allow_nan=False) + "\n"),
                            (".md", markdown(result))):
        target = stem.with_suffix(suffix)
        temporary = target.with_suffix(suffix + ".tmp")
        temporary.write_text(content)
        os.replace(temporary, target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=Path, default=DEFAULT_DEPTH)
    parser.add_argument("--bbo", type=Path, default=DEFAULT_BBO)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--name", default="latest", help="bounded output stem; reruns overwrite")
    parser.add_argument("--max-trades", type=int, default=2000)
    parser.add_argument("--max-routes", type=int, default=50)
    parser.add_argument("--checkpoint-skew-seconds", type=float, default=5)
    parser.add_argument("--pilot-minutes", type=float, default=40)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", args.name): parser.error("--name must be 1..32 letters, digits, dash, or underscore")
    if args.max_trades < 1 or args.max_trades > 5000: parser.error("--max-trades must be 1..5000")
    if args.max_routes < 1 or args.max_routes > 200: parser.error("--max-routes must be 1..200")
    if args.checkpoint_skew_seconds < 0 or args.pilot_minutes <= 0: parser.error("skew and pilot duration must be valid")
    result = compare(read_run(args.depth, args.max_trades), read_run(args.bbo, args.max_trades),
                     max_routes=args.max_routes, skew_limit=args.checkpoint_skew_seconds,
                     pilot_minutes=args.pilot_minutes)
    write_report(result, args.out, args.name)
    print(args.out / (args.name + ".md"))


if __name__ == "__main__":
    main()
