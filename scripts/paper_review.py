"""One-shot, bounded review of the paper monitor's durable checkpoints.

Run this command again when due; it never changes trading decisions or starts a
background process. SQLite is read in a short, consistent read transaction.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import statistics
import time
from uuid import uuid4


MAX_TRADES = 5_000
MAX_REPORT_BYTES = 256 * 1024
MAX_STATE_BYTES = 64 * 1024
MAX_REPORTS = 72
REPORT_NAME = re.compile(r"review-\d{8}T\d{6}\.\d{6}Z\.json\Z")
LEDGER_FIELDS = ("closed_pnl_exact", "closed_pnl_estimated", "closed_trades",
                 "estimated_trades", "closed_wins_exact", "closed_wins_estimated",
                 "aborted_trades", "fees_usd", "funding_usd", "other_costs_usd",
                 "capital_costs_usd")
COUNT_FIELDS = {"closed_trades", "estimated_trades", "closed_wins_exact",
                "closed_wins_estimated", "aborted_trades"}
ENTRY_REASONS = {"no_depth", "price_limit", "lot_rounding", "min_notional",
                 "min_qty", "notional_cap"}
VENUES = {"hyperliquid", "lighter", "rh_lighter", "aster"}
HEALTH_NUMBERS = ("cpu_percent_one_core", "resident_memory_mb", "peak_rss_mb",
                  "loop_lag_ms", "loop_lag_p95_ms", "max_loop_lag_ms",
                  "book_events_per_second", "metadata_age_seconds")
SELECTOR_NUMBERS = ("version", "criteria_changed_at", "migrated_from_version",
                    "sampled_routes", "warm_routes", "training_skew_limit_seconds",
                    "convergence_skew_limit_seconds", "conservative_skew_limit_seconds",
                    "cooldown_skew_limit_seconds", "max_route_samples",
                    "max_route_span_seconds", "pending_confirmations",
                    "confirmation_min_seconds", "confirmation_expiry_seconds",
                    "confirmation_instrumentation_version", "confirmation_instrumentation_begin_at")
POLICY_NUMBERS = ("checked", "allowed", "entered", "rejected_signal", "rejected_skew",
                  "rejected_cooldown", "rejected_warmup", "rejected_forecast",
                  "rejected_duplicate", "rejected_confirmation", "warm_routes",
                  "pending_confirmations")


def _finite(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _ledger(ledger: object) -> dict:
    if not isinstance(ledger, dict):
        ledger = {}
    return {key: (int(_finite(ledger.get(key))) if key in COUNT_FIELDS else
                  _finite(ledger.get(key))) for key in LEDGER_FIELDS}


def _delta(current: dict, previous: dict) -> dict:
    result = {key: current[key] - previous[key] for key in LEDGER_FIELDS}
    result["closed_net_usd"] = result["closed_pnl_exact"] + result["closed_pnl_estimated"]
    result["completed_trades"] = result["closed_trades"] + result["estimated_trades"]
    result["wins"] = result["closed_wins_exact"] + result["closed_wins_estimated"]
    return result


def _numeric_subset(keys: tuple[str, ...], values: dict) -> dict:
    result = {}
    for key in keys:
        if key in values:
            value = _finite(values[key], math.nan)
            result[key] = value if math.isfinite(value) else None
    return result


def _bounded_counts(values: dict, limit: int = 12) -> dict:
    return {str(key)[:40]: max(0, int(_finite(value)))
            for key, value in list(values.items())[:limit]}


def _read_checkpoint(db_path: Path, lower: float | None, upper_limit: float,
                     interval_seconds: float) -> tuple[float, dict, list[dict], int, list[dict], int]:
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA busy_timeout=1000")
        connection.execute("BEGIN")
        row = connection.execute("SELECT updated,payload FROM engine_state WHERE id=1").fetchone()
        if row is None:
            raise ValueError("paper engine has no durable checkpoint")
        checkpoint_at, raw = row
        checkpoint_at = float(checkpoint_at)
        if not math.isfinite(checkpoint_at) or checkpoint_at < 0:
            raise ValueError("paper engine checkpoint has an invalid time")
        if checkpoint_at > upper_limit + 60:
            raise ValueError("checkpoint time is ahead of review clock")
        if lower is None:
            lower = checkpoint_at - interval_seconds
        state = json.loads(raw)
        engine = state.get("engine", state)
        if not isinstance(engine, dict) or not isinstance(engine.get("ledgers"), dict):
            raise ValueError("paper engine checkpoint has no ledgers")
        # settled_at is the completion boundary; closed_at can precede funding
        # settlement. COUNT detects a query cap without fetching extra payloads.
        where = ("status IN ('CLOSED','CLOSED_ESTIMATED') AND "
                 "CAST(json_extract(payload,'$.settled_at') AS REAL)>? AND "
                 "CAST(json_extract(payload,'$.settled_at') AS REAL)<=?")
        params = (lower, checkpoint_at)
        retained_count = connection.execute(
            f"SELECT COUNT(*) FROM trades WHERE {where}", params).fetchone()[0]
        records = [json.loads(raw) for (raw,) in connection.execute(
            f"SELECT payload FROM trades WHERE {where} "
            "ORDER BY CAST(json_extract(payload,'$.settled_at') AS REAL),id LIMIT ?",
            (*params, MAX_TRADES))]
        aborted_where = "status='ABORTED' AND closed_at>? AND closed_at<=?"
        aborted_count = connection.execute(
            f"SELECT COUNT(*) FROM trades WHERE {aborted_where}", params).fetchone()[0]
        aborted = [json.loads(raw) for (raw,) in connection.execute(
            f"SELECT payload FROM trades WHERE {aborted_where} ORDER BY closed_at,id LIMIT ?",
            (*params, max(0, MAX_TRADES-len(records))))]
        connection.rollback()
        return checkpoint_at, engine, records, retained_count, aborted, aborted_count
    finally:
        connection.close()


def _read_health(source: Path, read_at: float) -> dict:
    path = source / "paper_snapshot.json"
    try:
        snapshot = json.loads(path.read_text())
        if not isinstance(snapshot, dict):
            raise ValueError("invalid snapshot")
    except (OSError, UnicodeError, ValueError):
        return {"read_at": read_at, "snapshot_updated_at": None,
                "status": "unavailable", "not_atomic_with_db": True}
    updated = _finite(snapshot.get("updated_at", snapshot.get("updated_timestamp")), math.nan)
    feeds = snapshot.get("feeds", {})
    if not isinstance(feeds, dict):
        feeds = {}
    selector = snapshot.get("entry_policies", {})
    if not isinstance(selector, dict):
        selector = {}
    policies = selector.get("policies", {})
    if not isinstance(policies, dict):
        policies = {}
    cancel_reasons = selector.get("confirmation_cancel_reasons", {})
    if not isinstance(cancel_reasons, dict):
        cancel_reasons = {}
    observations = selector.get("observation_counts", {})
    if not isinstance(observations, dict):
        observations = {}
    portfolios = snapshot.get("strategies", {})
    if not isinstance(portfolios, dict):
        portfolios = {}
    stats = snapshot.get("stats", {})
    if not isinstance(stats, dict):
        stats = {}
    lifecycle = selector.get("confirmation_lifecycle", {})
    if not isinstance(lifecycle, dict):
        lifecycle = {}
    terminal_reasons = lifecycle.get("terminal_reasons", {})
    if not isinstance(terminal_reasons, dict):
        terminal_reasons = {}
    waiting = selector.get("confirmation_waiting_checks", {})
    if not isinstance(waiting, dict):
        waiting = {}
    health = {"read_at": read_at,
            "snapshot_updated_at": updated if math.isfinite(updated) else None,
            "snapshot_age_seconds": max(0, read_at - updated) if math.isfinite(updated) else None,
            "status": str(snapshot.get("status", "unknown"))[:80],
            "pair_count": max(0, int(_finite(snapshot.get("pair_count")))),
            "performance_status": str(snapshot.get("performance_status", "unknown"))[:40],
            "target_refresh_priorities": {
                str(priority): _numeric_subset(tuple(
                    f"target_refresh_priority_{priority}_{kind}" for kind in
                    ("requests", "successes", "errors")), stats)
                for priority in range(5)},
            "portfolios": {str(name)[:40]: _numeric_subset(
                ("open_positions", "pending_entries", "pending_exits", "pending_funding",
                 "reserved_usd", "original_reserved_usd", "wallet_cash_usd"), row)
                for name, row in list(portfolios.items())[:8] if isinstance(row, dict)},
            "feeds": {str(name)[:40]: {"connected": value.get("connected") is True,
                                        **_numeric_subset(("messages", "gaps", "errors"), value)}
                      for name, value in list(feeds.items())[:8] if isinstance(value, dict)},
            "entry_policies": {**_numeric_subset(SELECTOR_NUMBERS, selector),
                               "confirmation_lifecycle": {
                                   **_numeric_subset(("armed", "eligible_unique", "completed_entered",
                                                      "terminal_total", "pending", "accounting_residual"), lifecycle),
                                   "terminal_reasons": _bounded_counts(terminal_reasons, 32)},
                               "confirmation_waiting_checks": _bounded_counts(waiting),
                               "confirmation_cancel_reasons": _bounded_counts(cancel_reasons),
                               "observation_counts": _bounded_counts(observations),
                               "policies": {str(name)[:40]: _numeric_subset(POLICY_NUMBERS, row)
                                            for name, row in list(policies.items())[:8]
                                            if isinstance(row, dict)}},
            "not_atomic_with_db": True}
    health.update(_numeric_subset(HEALTH_NUMBERS, snapshot))
    return health


def _category(trade: dict) -> str:
    if trade.get("exit_reason") == "entry_failure":
        return "failed_hedge"
    legs = trade.get("legs")
    if (trade.get("opened_at") is not None and isinstance(legs, list) and len(legs) == 2
            and all(isinstance(leg, dict) and leg.get("entry_result") == "filled"
                    for leg in legs)):
        first, second = (_finite(leg.get("quantity"), math.nan) for leg in legs)
        if math.isfinite(first) and math.isfinite(second) and first > 0 and abs(first-second) <= 1e-9:
            return "paired"
    return "other"


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _paired_entry_deterioration(trade: dict) -> float | None:
    signal = trade.get("signal")
    legs = trade.get("legs")
    if not isinstance(signal, dict) or not isinstance(legs, list) or len(legs) != 2:
        return None
    buy, sell = signal.get("buy"), signal.get("sell")
    if not isinstance(buy, str) or not isinstance(sell, str) or buy == sell:
        return None
    by_key = {leg.get("key"): leg for leg in legs if isinstance(leg, dict)}
    if len(by_key) != 2 or set(by_key) != {buy, sell}:
        return None
    long, short = by_key[buy], by_key[sell]
    if long.get("side") != "long" or short.get("side") != "short":
        return None
    quantity = _finite(signal.get("quantity"), math.nan)
    buy_value = _finite(signal.get("buy_value"), math.nan)
    sell_value = _finite(signal.get("sell_value"), math.nan)
    long_quantity = _finite(long.get("quantity"), math.nan)
    short_quantity = _finite(short.get("quantity"), math.nan)
    long_value = _finite(long.get("entry_value"), math.nan)
    short_value = _finite(short.get("entry_value"), math.nan)
    if not all(math.isfinite(value) and value > 0 for value in
               (quantity, buy_value, sell_value, long_quantity, short_quantity,
                long_value, short_value)):
        return None
    # A fully filled paper intent uses the signal quantity on both legs. Treat
    # discrepant records as incomplete evidence rather than scaling a partial.
    tolerance = max(1e-9, quantity * 1e-9)
    if (abs(long_quantity-quantity) > tolerance or
            abs(short_quantity-quantity) > tolerance):
        return None
    deterioration = (long_value - buy_value / quantity * long_quantity
                     + sell_value / quantity * short_quantity - short_value)
    return deterioration if math.isfinite(deterioration) else None


def _paired_entry_time(trade: dict) -> float | None:
    created = _finite(trade.get("created_at"), math.nan)
    legs = trade.get("legs")
    if not math.isfinite(created) or not isinstance(legs, list) or len(legs) != 2:
        return None
    times = [_finite(leg.get("entry_time"), math.nan) if isinstance(leg, dict)
             else math.nan for leg in legs]
    if not all(math.isfinite(value) and value >= created for value in times):
        return None
    return max(times) - created


def _paired_exit_price_deterioration(trade: dict) -> tuple[float | None, str | None]:
    """Price-only change from fresh request-time liability to actual full exits.

    A positive value means the short buyback cost minus the long sale proceeds
    worsened. Funding, fees, reserve, and capital are deliberately excluded.
    """
    observed = trade.get("exit_request_observation")
    if not isinstance(observed, dict):
        return None, "legacy_no_request_observation"
    if observed.get("version") != 1:
        return None, "unsupported_observation_version"
    if observed.get("capture_type") != "normal_request":
        return None, "non_normal_request"
    if observed.get("closing_price_status") != "valid":
        return None, "request_price_unavailable"
    if observed.get("receipt_pair_skew_valid") is not True:
        return None, "request_pair_skew_invalid"
    request_at = _finite(trade.get("exit_requested_at"), math.nan)
    marked_at = _finite(observed.get("requested_at"), math.nan)
    captured_at = _finite(observed.get("captured_at"), math.nan)
    skew = _finite(observed.get("received_skew_seconds"), math.nan)
    if (not all(math.isfinite(x) for x in (request_at, marked_at, captured_at, skew))
            or request_at < 0 or abs(request_at-marked_at) > 1e-6
            or abs(captured_at-marked_at) > 1e-6 or skew < 0
            or observed.get("exit_reason") != trade.get("exit_reason")):
        return None, "request_time_invalid"
    legs = trade.get("legs")
    request_legs = observed.get("legs")
    signal = trade.get("signal")
    if (not isinstance(legs, list) or len(legs) != 2
            or not isinstance(request_legs, list) or len(request_legs) != 2
            or not isinstance(signal, dict)):
        return None, "leg_identity_invalid"
    by_key = {leg.get("key"): leg for leg in legs if isinstance(leg, dict)}
    requested = {leg.get("key"): leg for leg in request_legs if isinstance(leg, dict)}
    if (len(by_key) != 2 or len(requested) != 2 or set(by_key) != set(requested)
            or set(by_key) != {signal.get("buy"), signal.get("sell")}
            or by_key[signal.get("buy")].get("side") != "long"
            or by_key[signal.get("sell")].get("side") != "short"):
        return None, "leg_identity_invalid"
    original_q = _finite(signal.get("quantity"), math.nan)
    if not math.isfinite(original_q) or original_q <= 0:
        return None, "original_quantity_invalid"
    actual_values = {}
    request_values = {}
    tolerance = max(1e-9, original_q * 1e-9)
    for key, leg in by_key.items():
        request_leg = requested[key]
        if request_leg.get("side") != leg.get("side"):
            return None, "leg_identity_invalid"
        quantity = _finite(leg.get("quantity"), math.nan)
        remaining = _finite(leg.get("remaining"), math.nan)
        request_q = _finite(request_leg.get("remaining_quantity"), math.nan)
        if (not all(math.isfinite(x) for x in (quantity, remaining, request_q))
                or abs(quantity-original_q) > tolerance
                or abs(request_q-original_q) > tolerance
                or abs(remaining) > tolerance):
            return None, "not_full_original_quantity"
        receipt = _finite(request_leg.get("book_received_at"), math.nan)
        source = _finite(request_leg.get("book_engine_time"), math.nan)
        receipt_age = _finite(request_leg.get("receipt_age_seconds"), math.nan)
        source_age = _finite(request_leg.get("source_age_seconds"), math.nan)
        if (request_leg.get("book_valid") is not True
                or request_leg.get("clock_valid") is not True
                or request_leg.get("walk_status") != "valid"
                or not all(math.isfinite(x) for x in (receipt, source, receipt_age, source_age))
                or source > receipt + 1e-6 or receipt > marked_at + 1e-6
                or receipt_age < 0 or source_age < 0):
            return None, "request_book_invalid"
        request_value = _finite(request_leg.get("exit_walk_value_usd"), math.nan)
        actual_value = _finite(leg.get("exit_value"), math.nan)
        fills = leg.get("exit_fills")
        if (not math.isfinite(request_value) or request_value <= 0
                or not math.isfinite(actual_value) or actual_value <= 0):
            return None, "exit_value_invalid"
        if not isinstance(fills, list) or not fills:
            return None, "exit_fills_missing"
        fill_q = fill_value = 0.0
        for fill in fills:
            if not isinstance(fill, dict):
                return None, "exit_fills_invalid"
            q = _finite(fill.get("quantity"), math.nan)
            value = _finite(fill.get("value"), math.nan)
            at = _finite(fill.get("timestamp"), math.nan)
            if (not all(math.isfinite(x) for x in (q, value, at))
                    or q <= 0 or value <= 0 or at < marked_at):
                return None, "exit_fills_invalid"
            fill_q += q
            fill_value += value
        if (abs(fill_q-original_q) > tolerance
                or abs(fill_value-actual_value) > max(1e-7, actual_value * 1e-9)):
            return None, "exit_fills_not_full_original"
        request_values[leg["side"]] = request_value
        actual_values[leg["side"]] = actual_value
    liability = request_values["short"]-request_values["long"]
    recorded = _finite(observed.get("requested_closing_liability_usd"), math.nan)
    if not math.isfinite(recorded) or abs(recorded-liability) > max(1e-7, abs(liability) * 1e-9):
        return None, "request_liability_inconsistent"
    deterioration = actual_values["short"]-actual_values["long"]-recorded
    return (deterioration, None) if math.isfinite(deterioration) else (None, "exit_value_invalid")


def _trade_summary(trades: list[dict]) -> dict:
    classes = {name: {"count": 0, "wins": 0, "net_usd": 0.0} for name in
               ("paired", "failed_hedge", "other")}
    quality = {name: {"count": 0, "wins": 0, "net_usd": 0.0} for name in
               ("exact", "estimated")}
    routes = defaultdict(lambda: {"count": 0, "net_usd": 0.0})
    latencies = []
    deterioration_values = []
    exit_deterioration_values = []
    exit_missing = defaultdict(int)
    entry_times = []
    for trade in trades:
        pnl = _finite(trade.get("net_pnl_usd"))
        win = int(pnl > 0)
        category_name = _category(trade)
        category = classes[category_name]
        category["count"] += 1
        category["wins"] += win
        category["net_usd"] += pnl
        if category_name == "paired":
            deterioration = _paired_entry_deterioration(trade)
            if deterioration is not None:
                deterioration_values.append(deterioration)
            entry_time = _paired_entry_time(trade)
            if entry_time is not None:
                entry_times.append(entry_time)
            exit_deterioration, missing_reason = _paired_exit_price_deterioration(trade)
            if missing_reason is None:
                exit_deterioration_values.append(exit_deterioration)
            else:
                exit_missing[missing_reason] += 1
        kind = "estimated" if trade.get("status") == "CLOSED_ESTIMATED" else "exact"
        quality[kind]["count"] += 1
        quality[kind]["wins"] += win
        quality[kind]["net_usd"] += pnl
        route = str(trade.get("pair_id") or trade.get("asset") or "unknown")[:160]
        routes[route]["count"] += 1
        routes[route]["net_usd"] += pnl
        requested = _finite(trade.get("exit_requested_at"), math.nan)
        flat = _finite(trade.get("closed_at"), math.nan)
        if math.isfinite(requested) and math.isfinite(flat) and flat >= requested:
            latencies.append(flat - requested)
    groups = [{"route": route, **values} for route, values in routes.items()]
    groups.sort(key=lambda item: (item["net_usd"], item["route"]))
    paired_count = classes["paired"]["count"]
    return {"count": len(trades), "wins": sum(x["wins"] for x in quality.values()),
            "net_usd": sum(x["net_usd"] for x in quality.values()),
            "quality": quality, "classes": classes,
            "aborted_count": None,  # Abort count comes from the cumulative ledger delta.
            "exit_request_to_flat_seconds": {
                "observed": len(latencies), "missing": len(trades)-len(latencies),
                "median": statistics.median(latencies) if latencies else None,
                "p95": _percentile(latencies, .95)},
            "paired_signal_to_entry_deterioration_usd": {
                "observed": len(deterioration_values),
                "missing": paired_count-len(deterioration_values),
                "sum": sum(deterioration_values),
                "median": statistics.median(deterioration_values) if deterioration_values else None,
                "p95": _percentile(deterioration_values, .95),
                "positive_is_worse": True},
            "paired_entry_time_seconds": {
                "observed": len(entry_times), "missing": paired_count-len(entry_times),
                "median": statistics.median(entry_times) if entry_times else None,
                "p95": _percentile(entry_times, .95)},
            "paired_exit_request_to_actual_price_deterioration_usd": {
                "observed": len(exit_deterioration_values),
                "missing": paired_count-len(exit_deterioration_values),
                "missing_reasons": dict(sorted(exit_missing.items())),
                "sum": sum(exit_deterioration_values) if exit_deterioration_values else None,
                "median": statistics.median(exit_deterioration_values) if exit_deterioration_values else None,
                "p95": _percentile(exit_deterioration_values, .95),
                "worsened": sum(value > 1e-9 for value in exit_deterioration_values),
                "improved": sum(value < -1e-9 for value in exit_deterioration_values),
                "unchanged": sum(abs(value) <= 1e-9 for value in exit_deterioration_values),
                "positive_is_worse": True,
                "price_only_excludes_fees_funding_and_capital": True},
            "worst_routes": groups[:10], "best_routes": list(reversed(groups[-10:]))}


def _entry_rejections(trades: list[dict]) -> dict:
    counts = defaultdict(lambda: defaultdict(int))
    for trade in trades:
        legs = trade.get("legs", [])
        for leg in legs if isinstance(legs, list) else []:
            if not isinstance(leg, dict) or not leg.get("entry_rejection_reason"):
                continue
            venue = leg.get("venue")
            venue = venue if isinstance(venue, str) and venue in VENUES else "other"
            reason = leg["entry_rejection_reason"]
            reason = reason if isinstance(reason, str) and reason in ENTRY_REASONS else "other"
            counts[venue][reason] += 1
    return {venue: dict(reasons) for venue, reasons in sorted(counts.items())}


def _json_bytes(value: dict, limit: int, name: str) -> bytes:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(data) > limit:
        raise ValueError(f"{name} exceeds {limit} bytes")
    return data


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _next_due(previous: dict | None, now: float, interval: float) -> float:
    if previous is None:
        return now + interval
    due = _finite(previous.get("next_due_at"), now + interval)
    if due <= now:
        due += (math.floor((now - due) / interval) + 1) * interval
    return due


def review(source: Path | str = Path("data/paper-monitor"),
           out: Path | str = Path("data/strategy-reviews"),
           now: float | None = None, interval_seconds: float = 1200) -> dict:
    """Write one review and return it; caller controls recurring invocation."""
    source, out = Path(source), Path(out)
    if interval_seconds <= 0 or not math.isfinite(interval_seconds):
        raise ValueError("interval_seconds must be positive and finite")
    read_at = time.time() if now is None else float(now)
    if not math.isfinite(read_at):
        raise ValueError("review clock must be finite")
    previous_path = out / "review_state.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else None
    if previous is not None and not isinstance(previous, dict):
        raise ValueError("invalid previous review state")
    previous_at = _finite(previous.get("checkpoint_at"), math.nan) if previous else None
    if previous is not None and not math.isfinite(previous_at):
        raise ValueError("invalid previous checkpoint time")
    db_path = source / "paper.sqlite3" if source.is_dir() else source
    # First review can describe recent retained trades, but cannot claim an
    # interval ledger delta without an earlier cumulative checkpoint.
    lower = previous_at if previous is not None else None
    checkpoint_at, engine, trades, retained_count, aborted, aborted_count = _read_checkpoint(
        db_path, lower, read_at, interval_seconds)
    if previous_at is not None and checkpoint_at <= previous_at:
        raise ValueError("paper checkpoint has not advanced since the previous review")
    if previous is None:
        # Anchor the initial retained window to the actual durable checkpoint.
        lower = checkpoint_at - interval_seconds
    current_ledgers = {name: _ledger(row) for name, row in engine["ledgers"].items()}
    shadow_start = _finite(engine.get("shadow_started_at"), math.nan)
    current_starts = {}
    for name, row in engine["ledgers"].items():
        started = _finite(row.get("started_at"), math.nan) if isinstance(row, dict) else math.nan
        if not math.isfinite(started) and name in ("shadow_baseline", "cooldown", "convergence",
                                                   "conservative"):
            started = shadow_start
        current_starts[name] = started if math.isfinite(started) else None
    prior_ledgers = previous.get("ledgers", {}) if previous else {}
    if not isinstance(prior_ledgers, dict):
        raise ValueError("invalid previous ledgers")
    by_strategy = defaultdict(list)
    for trade in trades:
        if isinstance(trade, dict):
            by_strategy[str(trade.get("strategy", "unknown"))].append(trade)
    aborted_by_strategy = defaultdict(list)
    for trade in aborted:
        if isinstance(trade, dict):
            aborted_by_strategy[str(trade.get("strategy", "unknown"))].append(trade)
    result = {}
    for name, current in current_ledgers.items():
        old = prior_ledgers.get(name)
        introduced = previous is not None and old is None
        started_at = current_starts[name]
        start_at = started_at if introduced and started_at is not None and started_at >= previous_at else None
        if previous is None:
            ledger_delta = None
        elif introduced and start_at is not None:
            ledger_delta = _delta(current, _ledger({}))
        elif introduced:
            ledger_delta = None
        else:
            ledger_delta = _delta(current, _ledger(old))
        selected = [trade for trade in by_strategy[name]
                    if not introduced or start_at is None or
                    _finite(trade.get("settled_at")) > start_at]
        selected_aborted = [trade for trade in aborted_by_strategy[name]
                            if not introduced or start_at is None or
                            _finite(trade.get("closed_at")) > start_at]
        summary = _trade_summary(selected)
        summary["entry_rejections_by_venue"] = _entry_rejections(selected + selected_aborted)
        summary["retained_aborted_count"] = len(selected_aborted)
        expected = ledger_delta["completed_trades"] if ledger_delta is not None else None
        if retained_count + aborted_count > MAX_TRADES:
            coverage = "query_cap"
        elif expected is None:
            coverage = "unverifiable_without_prior_ledger"
        elif summary["count"] != expected:
            coverage = "missing_or_extra_retained_trades"
        else:
            coverage = "complete"
        if ledger_delta is not None:
            summary["aborted_count"] = ledger_delta["aborted_trades"]
        result[name] = {"new_since_previous": introduced,
                        "started_at": started_at,
                        "ledger_delta": ledger_delta,
                        "retained_completion_window": summary,
                        "coverage": coverage,
                        "retained_completed_count": summary["count"],
                        "expected_completed_count": expected,
                        "aborted_coverage": ("unverifiable_without_prior_ledger" if ledger_delta is None
                                             else "query_cap" if retained_count + aborted_count > MAX_TRADES
                                             else "complete" if len(selected_aborted) == ledger_delta["aborted_trades"]
                                             else "missing_or_extra_retained_trades")}
    next_due = _next_due(previous, read_at, interval_seconds)
    report = {"version": 1, "reviewed_at": read_at, "checkpoint_at": checkpoint_at,
              "window_start_at": lower, "window_end_at": checkpoint_at,
              "first_review": previous is None,
              "cumulative_deltas_available": previous is not None and all(
                  row["ledger_delta"] is not None for row in result.values()),
              "retained_window_total": retained_count,
              "retained_aborted_window_total": aborted_count,
              "retained_window_query_capped": retained_count + aborted_count > MAX_TRADES,
              "next_due_at": next_due,
              "snapshot_health": _read_health(source if source.is_dir() else source.parent, read_at),
              "entry_rejections_by_venue": _entry_rejections(trades + aborted),
              "strategies": result}
    state = {"version": 1, "checkpoint_at": checkpoint_at,
             "next_due_at": next_due, "ledgers": current_ledgers,
             "strategy_started_at": current_starts,
             "shadow_started_at": shadow_start if math.isfinite(shadow_start) else None}
    report_bytes = _json_bytes(report, MAX_REPORT_BYTES, "report")
    state_bytes = _json_bytes(state, MAX_STATE_BYTES, "review state")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(checkpoint_at, timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    archived = out / f"review-{stamp}.json"
    if archived.exists():
        raise ValueError("report for this checkpoint already exists")
    _atomic_write(archived, report_bytes)
    _atomic_write(out / "latest.json", report_bytes)
    _atomic_write(previous_path, state_bytes)
    archive = sorted(path for path in out.iterdir() if REPORT_NAME.fullmatch(path.name))
    for path in archive[:-MAX_REPORTS]:
        path.unlink()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/paper-monitor"))
    parser.add_argument("--out", type=Path, default=Path("data/strategy-reviews"))
    parser.add_argument("--interval-seconds", type=float, default=1200)
    args = parser.parse_args()
    report = review(args.source, args.out, interval_seconds=args.interval_seconds)
    print(json.dumps({"checkpoint_at": report["checkpoint_at"],
                      "next_due_at": report["next_due_at"],
                      "strategies": list(report["strategies"])}, sort_keys=True))


if __name__ == "__main__":
    main()
