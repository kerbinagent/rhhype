"""Read-only terminal view of a paper monitor's atomic JSON snapshot."""
from __future__ import annotations

from contextlib import contextmanager
import json
import fcntl
import shlex
import math
from pathlib import Path
import shutil
import signal
import sys
import time
from typing import Iterator


TIERS = ("standard", "plus", "premium")


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _int(value: object) -> int:
    result = _number(value)
    return max(0, int(result)) if result is not None else 0


def _cash(value: object, width: int = 9) -> str:
    amount = _number(value)
    if amount is None:
        return "?".rjust(width)
    for precision in (2, 1, 0):
        shown = f"{amount:+,.{precision}f}"
        if len(shown) <= width:
            return shown.rjust(width)
    return (f"{amount:+.1e}" if len(f"{amount:+.1e}") <= width else "#" * width).rjust(width)


def _brief_cash(value: object) -> str:
    amount = _number(value)
    if amount is None:
        return "?"
    scale, unit = (1_000_000, "m") if abs(amount) >= 1_000_000 else ((1000, "k") if abs(amount) >= 1000 else (1, ""))
    return f"{amount / scale:+.1f}{unit}"


def _label(value: object) -> str:
    # JSON text may contain terminal controls, newlines, or wide Unicode.
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in str(value))


def _route(value: object) -> str:
    route = _label(value)
    for old, new in (("hyperliquid:xyz:", "HL:"), ("hyperliquid:", "HL:"),
                     ("rh_lighter:", "RH:"), ("lighter:", "LC:"), ("aster:", "AS:")):
        route = route.replace(old, new)
    return route


def _strategy_lines(snapshot: dict, width: int) -> list[str]:
    strategies = snapshot.get("strategies") or {}
    if not isinstance(strategies, dict):
        strategies = {}
    positions = snapshot.get("positions") or []
    if not isinstance(positions, list):
        positions = []
    if width >= 79:
        lines = ["Tier     Exact      Est     Open Pos Ent Pen Inc   Fees   Fund  Other   Cap"]
        for tier in TIERS:
            row = strategies.get(tier) or {}
            if not isinstance(row, dict):
                row = {}
            entries = row.get("pending_entries")
            if entries is None:
                entries = sum(isinstance(p, dict) and p.get("strategy") == tier
                              and p.get("status") == "ENTRY_PENDING" for p in positions)
            lines.append(
                f"{tier.title():<8} {_cash(row.get('closed_pnl_exact'), 10)} "
                f"{_cash(row.get('closed_pnl_estimated'), 7)} "
                f"{_cash(row.get('open_liquidation_pnl'), 8)} "
                f"{_int(row.get('open_positions')):>3} "
                f"{_int(entries):>3} "
                f"{_int(row.get('pending_funding')):>3} "
                f"{_int(row.get('incomplete_trades')):>3} "
                f"{_cash(row.get('fees_usd'), 6)} "
                f"{_cash(row.get('funding_usd'), 6)} "
                f"{_cash(row.get('other_costs_usd'), 6)} "
                f"{_cash(row.get('capital_costs_usd'), 5)}")
    elif width >= 49:
        lines = ["Tier      Closed exact  Closed est  Open exit  Pos"]
        for tier in TIERS:
            row = strategies.get(tier) or {}
            if not isinstance(row, dict):
                row = {}
            lines.append(f"{tier.title():<8} {_cash(row.get('closed_pnl_exact'), 12)} "
                         f"{_cash(row.get('closed_pnl_estimated'), 11)} "
                         f"{_cash(row.get('open_liquidation_pnl'), 10)} "
                         f"{_int(row.get('open_positions')):>3}")
    else:
        lines = ["Tier      Closed exact  Open exit"]
        for tier in TIERS:
            row = strategies.get(tier) or {}
            if not isinstance(row, dict):
                row = {}
            lines.append(f"{tier.title():<8} {_cash(row.get('closed_pnl_exact'), 12)} "
                         f"{_cash(row.get('open_liquidation_pnl'), 10)}")
    return lines


def _signal_lines(signals: list, width: int) -> tuple[str, list[str]]:
    if width >= 76:
        heading = " # Asset     Buy > short                 Tier      Edge $      bp  Age"
    elif width >= 52:
        heading = " # Asset     Buy > short          Edge $       bp"
    else:
        heading = " # Asset        Edge $"
    rows = []
    now = time.time()
    for index, item in enumerate(signals[:10], 1):
        if not isinstance(item, dict):
            continue
        age = _number(item.get("timestamp"))
        age_text = f"{max(0, int(now - age))}s" if age is not None else "?"
        asset = _label(item.get("asset", "?"))
        route = _route(item.get("buy", "?")) + " > " + _route(item.get("sell", "?"))
        edge = _cash(item.get("net_edge_usd"), 9)
        bp = _number(item.get("net_edge_bps"))
        bp_text = f"{bp:+7.1f}" if bp is not None else "      ?"
        if width >= 76:
            rows.append(f"{index:>2} {asset:<9.9} {route:<27.27} "
                        f"{_label(item.get('strategy', '?')):<8.8} {edge} {bp_text} {age_text:>5.5}")
        elif width >= 52:
            rows.append(f"{index:>2} {asset:<9.9} {route:<20.20} {edge} {bp_text}")
        else:
            rows.append(f"{index:>2} {asset:<12.12} {edge}")
    return heading, rows


def _position_line(snapshot: dict) -> str:
    positions = snapshot.get("positions") or []
    if not isinstance(positions, list):
        positions = []
    if not positions:
        return "Positions: none open"
    summaries = []
    for pos in positions[:2]:
        if not isinstance(pos, dict):
            continue
        age = _number(pos.get("age_seconds"))
        age_text = f"{int(age)}s" if age is not None else "?"
        pnl = _cash(pos.get("liquidation_pnl"), 7).strip()
        status = _label(pos.get("status", "?"))
        summaries.append(f"{_label(pos.get('asset', '?'))}/{_label(pos.get('strategy', '?'))} "
                         f"{status} {age_text} {pnl}")
    return "Positions: " + " | ".join(summaries) + (f" | +{len(positions)-2} more" if len(positions) > 2 else "")


def _diagnostic_line(snapshot: dict) -> str:
    feeds = snapshot.get("feeds") or {}
    if not isinstance(feeds, dict) or not feeds:
        return "Feeds: awaiting first books"
    parts = []
    for venue, state in list(feeds.items())[:5]:
        if isinstance(state, dict):
            label = state.get("status", "up" if state.get("connected") else "down" if "connected" in state else "?")
        else:
            label = state
        parts.append(f"{_label(venue)} {_label(label)}")
    return "Feeds: " + " | ".join(parts)


def _storage_line(snapshot: dict) -> str:
    storage = snapshot.get("storage") or {}
    latency = snapshot.get("latency") or {}
    if not isinstance(storage, dict):
        storage = {}
    if not isinstance(latency, dict):
        latency = {}
    details = []
    probe_delays = sorted((k for k, v in latency.items() if isinstance(v, dict)),
                          key=lambda key: _number(key) if _number(key) is not None else math.inf)
    if probe_delays:
        delay=probe_delays[0];stats=latency[delay]
        observed=_int(stats.get('observed'))
        elapsed=_number(stats.get('actual_delay_ms_sum'))
        actual=f"{elapsed/observed:.0f}ms" if observed and elapsed is not None else "?"
        return (f"Probe {delay}ms target: {_int(stats.get('survived'))}/{observed} positive, "
                f"{_int(stats.get('missing'))} missing; actual avg {actual}")
    for data, keys in ((latency, ("p50_ms", "p95_ms", "poll_interval_ms")),
                       (storage, ("rows", "max_rows", "bytes", "max_bytes"))):
        for key in keys:
            if key in data:
                details.append(f"{key}={_label(data[key])}")
    return "Diagnostics: " + (" | ".join(details) if details else "awaiting samples")


def _closed_sums_line(snapshot: dict) -> str | None:
    strategies = snapshot.get("strategies") or {}
    if not isinstance(strategies, dict):
        return None
    if not any(isinstance(strategies.get(tier), dict) and
               ("closed_winning_sum_usd" in strategies[tier] or
                "closed_losing_sum_usd" in strategies[tier]) for tier in TIERS):
        return None
    parts = []
    for tier, short in (("standard", "Std"), ("plus", "Plus"), ("premium", "Prem")):
        row = strategies.get(tier) or {}
        parts.append(f"{short} {_brief_cash(row.get('closed_winning_sum_usd'))}/"
                     f"{_brief_cash(row.get('closed_losing_sum_usd'))}")
    return "Closed win/loss sums USD: " + " | ".join(parts)


def tui_lines(snapshot: dict | None, columns: int, rows: int) -> list[str]:
    """Return a full frame that never wraps or scrolls, even on a tiny PTY."""
    width, height = max(1, columns - 1), max(1, rows - 1)
    if not isinstance(snapshot, dict):
        lines = ["RHHYPE paper monitor | Ctrl-C exits", "Waiting for monitor snapshot ..."]
    elif isinstance(snapshot.get("viewer_notice"), list):
        lines = ["RHHYPE viewer | Ctrl-C exits", *snapshot["viewer_notice"]]
    else:
        updated = _number(snapshot.get("updated_at", snapshot.get("updated_timestamp")))
        age = f"{max(0, int(time.time() - updated))}s" if updated is not None else "?"
        pairs = snapshot.get("pair_count", snapshot.get("pairs", 0))
        lines = [f"RHHYPE PAPER | {_label(snapshot.get('status', 'starting')).upper()} | "
                 f"{_int(pairs)} pairs | update {age} | Ctrl-C exits",
                 "Simulated USD P&L: Closed exact / estimated / open liquidation; costs below",
                 *_strategy_lines(snapshot, width)]
        signals = snapshot.get("top_signals") or []
        if not isinstance(signals, list):
            signals = []
        signals = signals[:10]
        heading, signal_rows = _signal_lines(signals, width)
        lines += ["Top opening signals (edge is NOT trade P&L)", heading]
        # Keep one row for a truncation or status footer at short heights.
        available = max(0, height - len(lines) - 1)
        shown = min(len(signal_rows), available)
        lines += signal_rows[:shown]
        if not signals and available:
            lines.append("No positive opening signals yet.")
        if len(signal_rows) > shown:
            lines.append(f"Showing {shown}/{len(signal_rows)} signals; enlarge terminal for all 10.")
        else:
            supplements = [
                "Exact final; Est estimated; Ent entry; Pen funding; Inc incomplete; ? unknown",
                _position_line(snapshot),
                _diagnostic_line(snapshot),
                _storage_line(snapshot),
                _closed_sums_line(snapshot) or "Signals are historical opening observations; Ctrl-C exits.",
            ]
            lines += supplements[:max(0, height - len(lines))]
    # Strip all non-ASCII including terminal controls and wide glyphs.
    return [_label(line)[:width] for line in lines[:height]]


def draw(snapshot: dict | None) -> None:
    size = shutil.get_terminal_size((80, 24))
    lines = tui_lines(snapshot, size.columns, size.lines)
    sys.stdout.write("\033[H\033[2J" + "\n".join(lines))
    sys.stdout.flush()


@contextmanager
def terminal() -> Iterator[None]:
    """Use the alternate screen and restore the cursor, including on exceptions."""
    if not sys.stdout.isatty():
        raise SystemExit("The paper monitor viewer needs a terminal")
    sys.stdout.write("\033[?1049h\033[?25l")
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()


def collector_running(directory: Path) -> bool | None:
    """Probe the writer lock without creating files or relying on stale PIDs."""
    try:
        with (directory / "paper.lock").open("r") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False
    except FileNotFoundError:
        return False
    except OSError:
        return None


def read_watch_snapshot(path: Path) -> dict:
    try:
        candidate = json.loads(path.read_text())
        if isinstance(candidate, dict):
            return candidate
        reason = "Snapshot has an invalid format."
    except FileNotFoundError:
        reason = "No snapshot has been written yet."
    except (json.JSONDecodeError, OSError, UnicodeError):
        reason = "Snapshot could not be read."
    running = collector_running(path.parent)
    lines = [reason]
    if running is False:
        lines += ["Collector is not running; --watch only opens the viewer.",
                  "Start the collector in another terminal:",
                  ".venv/bin/python scripts/monitor.py --no-tui"]
        default = Path(__file__).resolve().parents[1] / "data/paper-monitor"
        if path.parent.resolve() != default:
            lines[-1] += " \\"
            lines.append("  --out " + shlex.quote(str(path.parent)))
    elif running:
        lines.append("Collector is running; waiting for its first checkpoint.")
    else:
        lines.append("Collector status could not be checked.")
    lines += ["Watching: " + str(path), "Collector log: " + str(path.parent / "paper.log")]
    return {"viewer_notice": lines}


def watch(path: Path) -> None:
    """Display an atomic JSON snapshot until Ctrl-C or SIGTERM."""
    path = Path(path)
    if path.is_dir():
        path = path / "paper_snapshot.json"
    stopped = False

    def stop_view(signum: int, frame: object) -> None:
        nonlocal stopped
        stopped = True

    previous = {sig: signal.signal(sig, stop_view) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        with terminal():
            while not stopped:
                draw(read_watch_snapshot(path))
                # Signals interrupt sleep; the next loop condition exits cleanly.
                time.sleep(0.5)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: paper_ui.py SNAPSHOT.json")
    watch(Path(sys.argv[1]))
