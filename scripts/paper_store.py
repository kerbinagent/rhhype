"""Bounded, restart-safe storage for the streaming paper monitor.

The engine owns cumulative accounting in ``state``.  Retained observations and
closed trades are an inspection window, never the source of lifetime P&L.
``checkpoint`` writes the state and its associated records in one transaction.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
from typing import Iterable


class PaperStoreError(RuntimeError):
    """Persistence failed; the previous durable checkpoint remains readable."""


def _json(value: object, limit: int, label: str) -> str:
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is not finite JSON: {exc}") from exc
    if len(result.encode("utf-8")) > limit:
        raise ValueError(f"{label} exceeds {limit} bytes; reduce retained detail")
    return result


def _text(value: object, limit: int, label: str) -> str:
    result = str(value)
    if not result or len(result.encode("utf-8")) > limit:
        raise ValueError(f"{label} must contain 1 to {limit} UTF-8 bytes")
    return result


def _time(value: object, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


class PaperStore:
    """SQLite ring with page, transaction, row, age, and evidence limits.

    A caller may invoke methods through ``asyncio.to_thread``.  The connection
    is protected by a lock, and ``checkpoint`` is the preferred batch API.
    Signal fields: route, timestamp, net_edge_usd (or budgeted_edge_usd),
    optional strategy.  Trade fields: id, status, optional closed_at.
    Evidence items passed to checkpoint are ``(key, payload, kind, timestamp)``.
    """

    STATE_LIMIT = 2 * 1024 * 1024
    TRADE_LIMIT = 64 * 1024
    SIGNAL_LIMIT = 16 * 1024

    def __init__(
        self,
        path: Path,
        config: dict,
        max_db_mb: int = 128,
        max_events: int = 20_000,
        max_trades: int = 5_000,
        window_seconds: float = 86_400,
        evidence_max_bytes: int = 16 * 1024 * 1024,
        max_evidence_rows: int = 2_000,
        per_evidence_max_bytes: int = 256 * 1024,
    ) -> None:
        if min(max_db_mb, max_events, max_trades, max_evidence_rows,
               evidence_max_bytes, per_evidence_max_bytes) <= 0 or window_seconds <= 0:
            raise ValueError("All paper-store budgets must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Reserve a quarter of the user disk budget for one WAL transaction.
        # SQLite's journal_size_limit acts only after a checkpoint; bounded
        # batch inputs and a truncate checkpoint after each write are required.
        self.max_db_bytes = int(max_db_mb * 1024 * 1024)
        self.main_db_limit_bytes = self.max_db_bytes * 3 // 4
        self.wal_budget_bytes = self.max_db_bytes - self.main_db_limit_bytes
        self.max_events = int(max_events)
        self.max_trades = int(max_trades)
        self.window_seconds = float(window_seconds)
        self.evidence_max_bytes = int(evidence_max_bytes)
        self.max_evidence_rows = int(max_evidence_rows)
        self.per_evidence_max_bytes = min(int(per_evidence_max_bytes), self.evidence_max_bytes)
        self._lock = threading.RLock()
        self._operations = 0
        self._last_maintenance_at = 0.0
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None,
                                  check_same_thread=False)
        try:
            self.db.execute("PRAGMA busy_timeout=10000")
            self.db.execute("PRAGMA page_size=4096")
            self.db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA wal_autocheckpoint=64")
            self.db.execute(f"PRAGMA journal_size_limit={self.wal_budget_bytes}")
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            page_cap = self.main_db_limit_bytes // page_size
            if page_cap < 32:
                raise ValueError("max_db_mb is too small for the paper-store schema")
            applied_cap = self.db.execute(f"PRAGMA max_page_count={page_cap}").fetchone()[0]
            if applied_cap > page_cap:
                raise ValueError("Existing paper database exceeds max_db_mb; increase the limit")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS engine_state (id INTEGER PRIMARY KEY CHECK(id=1),
                    payload TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS signal_events (id INTEGER PRIMARY KEY,
                    ts REAL NOT NULL, route TEXT NOT NULL, strategy TEXT NOT NULL,
                    score REAL NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS signal_events_ts ON signal_events(ts);
                CREATE TABLE IF NOT EXISTS top_signals (route TEXT NOT NULL,
                    strategy TEXT NOT NULL, score REAL NOT NULL, ts REAL NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(route, strategy));
                CREATE INDEX IF NOT EXISTS top_signals_score ON top_signals(score);
                CREATE TABLE IF NOT EXISTS trades (id TEXT PRIMARY KEY,
                    status TEXT NOT NULL, ts REAL NOT NULL, closed_at REAL,
                    payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS trades_closed ON trades(closed_at);
                CREATE TABLE IF NOT EXISTS evidence (key TEXT PRIMARY KEY,
                    kind TEXT NOT NULL, ts REAL NOT NULL, size INTEGER NOT NULL,
                    payload BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS evidence_ts ON evidence(ts);
            """)
            signature = hashlib.sha256(_json(config, self.STATE_LIMIT, "config").encode()).hexdigest()
            previous = self.db.execute("SELECT value FROM meta WHERE key='config_hash'").fetchone()
            if previous and previous[0] != signature:
                raise ValueError("Paper store config/model differs from its saved state; use a new database path")
            self.db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('config_hash',?)", (signature,))
            self.db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('stats',?)",
                            ('{"signals_seen":0,"trades_seen":0,"evidence_seen":0}',))
        except BaseException:
            self.db.close()
            raise

    def _stats(self) -> dict:
        return json.loads(self.db.execute("SELECT value FROM meta WHERE key='stats'").fetchone()[0])

    def _write_stats(self, stats: dict) -> None:
        self.db.execute("UPDATE meta SET value=? WHERE key='stats'",
                        (_json(stats, 4096, "stats"),))

    def _record_trade(self, trade: dict, stats: dict) -> None:
        trade_id = _text(trade["id"], 256, "trade id")
        status = _text(trade["status"], 64, "trade status")
        closed = trade.get("closed_at")
        closed_ts = _time(closed, "closed_at") if closed is not None else None
        ts = _time(trade.get("timestamp", closed_ts if closed_ts is not None else time.time()),
                   "trade timestamp")
        payload = _json(trade, self.TRADE_LIMIT, "trade")
        existed = self.db.execute("SELECT 1 FROM trades WHERE id=?", (trade_id,)).fetchone()
        self.db.execute("INSERT INTO trades(id,status,ts,closed_at,payload) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET status=excluded.status, ts=excluded.ts, "
                        "closed_at=excluded.closed_at, payload=excluded.payload",
                        (trade_id, status, ts, closed_ts, payload))
        if not existed:
            stats["trades_seen"] += 1

    def _record_signal(self, signal: dict, stats: dict) -> None:
        if "route" not in signal or "timestamp" not in signal or not any(
            key in signal for key in ("net_edge_usd", "budgeted_edge_usd")
        ):
            raise ValueError("signal needs route, timestamp, and net_edge_usd")
        route = _text(signal["route"], 256, "signal route")
        strategy = _text(signal.get("strategy", "standard"), 64, "signal strategy")
        ts = _time(signal["timestamp"], "signal timestamp")
        score = float(signal.get("net_edge_usd", signal.get("budgeted_edge_usd")))
        if not (-float("inf") < score < float("inf")):
            raise ValueError("signal score must be finite")
        payload = _json(signal, self.SIGNAL_LIMIT, "signal")
        self.db.execute("INSERT INTO signal_events(ts,route,strategy,score,payload) VALUES(?,?,?,?,?)",
                        (ts, route, strategy, score, payload))
        stats["signals_seen"] += 1
        old = self.db.execute("SELECT score FROM top_signals WHERE route=? AND strategy=?",
                              (route, strategy)).fetchone()
        if old is None or score > old[0]:
            self.db.execute("INSERT INTO top_signals(route,strategy,score,ts,payload) VALUES(?,?,?,?,?) "
                            "ON CONFLICT(route,strategy) DO UPDATE SET score=excluded.score, "
                            "ts=excluded.ts,payload=excluded.payload",
                            (route, strategy, score, ts, payload))
            self.db.execute("DELETE FROM top_signals WHERE rowid IN "
                            "(SELECT rowid FROM top_signals ORDER BY score DESC, ts DESC LIMIT -1 OFFSET 10)")

    def _record_evidence(self, key: str, payload: dict, kind: str, timestamp: float,
                         stats: dict) -> None:
        key = _text(key, 256, "evidence key")
        kind = _text(kind, 64, "evidence kind")
        timestamp = _time(timestamp, "evidence timestamp")
        raw = _json(payload, self.per_evidence_max_bytes * 8, "evidence").encode()
        compressed = gzip.compress(raw, compresslevel=5, mtime=0)
        if len(compressed) > self.per_evidence_max_bytes:
            raise ValueError(f"compressed evidence exceeds {self.per_evidence_max_bytes} bytes")
        existed = self.db.execute("SELECT 1 FROM evidence WHERE key=?", (key,)).fetchone()
        self.db.execute("INSERT INTO evidence(key,kind,ts,size,payload) VALUES(?,?,?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET kind=excluded.kind,ts=excluded.ts,"
                        "size=excluded.size,payload=excluded.payload",
                        (key, kind, timestamp, len(compressed), compressed))
        if not existed:
            stats["evidence_seen"] += 1

    def _prune(self, now: float, aggressive: bool = False) -> None:
        cutoff = now - self.window_seconds
        self.db.execute("DELETE FROM signal_events WHERE ts<?", (cutoff,))
        self.db.execute("DELETE FROM trades WHERE closed_at IS NOT NULL AND closed_at<?", (cutoff,))
        self.db.execute("DELETE FROM evidence WHERE ts<?", (cutoff,))
        open_count = self.db.execute("SELECT COUNT(*) FROM trades WHERE closed_at IS NULL").fetchone()[0]
        if open_count > self.max_trades:
            raise PaperStoreError("Open trade count exceeds max_trades; increase the budget")
        for table, cap, order, where in (
            ("signal_events", self.max_events, "ts DESC,id DESC", "1=1"),
            ("trades", self.max_trades - open_count, "COALESCE(closed_at,ts) DESC", "closed_at IS NOT NULL"),
            ("evidence", self.max_evidence_rows, "ts DESC", "1=1"),
        ):
            if aggressive:
                cap = max(0, cap // 2)
            self.db.execute(f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} "
                            f"WHERE {where} ORDER BY {order} LIMIT -1 OFFSET ?)", (cap,))
        # Unclosed trades are not evicted: they may be needed for inspection.
        total = self.db.execute("SELECT COALESCE(SUM(size),0) FROM evidence").fetchone()[0]
        limit = self.evidence_max_bytes // (2 if aggressive else 1)
        while total > limit:
            oldest = self.db.execute("SELECT key,size FROM evidence ORDER BY ts,key LIMIT 1").fetchone()
            if oldest is None:
                break
            self.db.execute("DELETE FROM evidence WHERE key=?", (oldest[0],))
            total -= oldest[1]

    def _disk_sizes(self) -> tuple[int, int]:
        wal_path = self.path.with_name(self.path.name + "-wal")
        try:
            db_bytes = os.path.getsize(self.path)
        except FileNotFoundError:
            db_bytes = 0
        try:
            wal_bytes = os.path.getsize(wal_path)
        except FileNotFoundError:
            wal_bytes = 0
        return db_bytes, wal_bytes

    def _batch_estimate(self, payload: str | None, trades: tuple,
                        signals: tuple, evidence: tuple) -> int:
        # Conservative allowance for table/index pages and WAL framing. This
        # bounds each write batch; actual sizes are checked after checkpoint.
        records = len(trades) + len(signals) + len(evidence)
        raw = len(payload.encode()) if payload is not None else 0
        for name, items in (("trade", trades), ("signal", signals)):
            for item in items:
                raw += len(_json(item, self.TRADE_LIMIT if name == "trade" else self.SIGNAL_LIMIT,
                                 name).encode())
        for _, item, _, _ in evidence:
            raw += len(_json(item, self.per_evidence_max_bytes * 8, "evidence").encode())
        return 64 * 1024 + 3 * raw + 12 * 1024 * records

    def _before_write(self, estimated_wal_bytes: int) -> None:
        if estimated_wal_bytes > self.wal_budget_bytes:
            raise PaperStoreError("Paper checkpoint batch exceeds reserved WAL budget; "
                                  "reduce report interval or increase max_db_mb")
        db_bytes, wal_bytes = self._disk_sizes()
        if db_bytes > self.main_db_limit_bytes:
            raise PaperStoreError("Paper database exceeds its main-file budget; increase max_db_mb")
        if wal_bytes:
            self._truncate_wal(strict=True)
        _, wal_bytes = self._disk_sizes()
        if wal_bytes + estimated_wal_bytes > self.wal_budget_bytes:
            raise PaperStoreError("Paper WAL lacks space for a bounded checkpoint")

    def checkpoint(self, state: dict | None, trades: Iterable[dict] = (),
                   signals: Iterable[dict] = (),
                   evidence: Iterable[tuple[str, dict, str, float]] = ()) -> None:
        """Atomically persist a ledger checkpoint and associated inspection data."""
        payload = None if state is None else _json(state, self.STATE_LIMIT, "engine state")
        # Iterables may be generators; materialize for an SQLITE_FULL retry.
        trades, signals, evidence = tuple(trades), tuple(signals), tuple(evidence)
        estimated_wal_bytes = self._batch_estimate(payload, trades, signals, evidence)
        with self._lock:
            self._before_write(estimated_wal_bytes)
            for attempt in range(2):
                committed = False
                try:
                    self.db.execute("BEGIN IMMEDIATE")
                    stats = self._stats()
                    for trade in trades:
                        self._record_trade(trade, stats)
                    for signal in signals:
                        self._record_signal(signal, stats)
                    for key, item, kind, ts in evidence:
                        self._record_evidence(key, item, kind, ts, stats)
                    if payload is not None:
                        self.db.execute("INSERT INTO engine_state(id,payload,updated) VALUES(1,?,?) "
                                        "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,"
                                        "updated=excluded.updated", (payload, time.time()))
                    self._write_stats(stats)
                    self._prune(time.time())
                    self.db.execute("COMMIT")
                    committed = True
                    self._operations += 1
                    self._compact(strict=False)
                    db_bytes, wal_bytes = self._disk_sizes()
                    if db_bytes + wal_bytes > self.max_db_bytes:
                        raise PaperStoreError("Checkpoint is durable, but paper database passed "
                                              "its disk budget; increase max_db_mb before more writes")
                    return
                except sqlite3.Error as exc:
                    if self.db.in_transaction:
                        self.db.execute("ROLLBACK")
                    if committed:
                        raise PaperStoreError("Checkpoint is durable, but WAL maintenance failed; "
                                              "stop writes and inspect disk space/readers") from exc
                    if attempt == 0 and ("full" in str(exc).lower() or "page" in str(exc).lower()):
                        try:
                            self.maintenance(aggressive=True)
                        except sqlite3.Error:
                            pass
                        continue
                    raise PaperStoreError("Paper store has insufficient space for an atomic checkpoint; "
                                          "increase max_db_mb or use a fresh path. Previous state is intact.") from exc
                except BaseException:
                    if self.db.in_transaction:
                        self.db.execute("ROLLBACK")
                    raise

    def save_state(self, state: dict) -> None:
        self.checkpoint(state)

    def load_state(self) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT payload FROM engine_state WHERE id=1").fetchone()
            return json.loads(row[0]) if row else None

    def record_trade(self, trade: dict) -> None:
        self.checkpoint(None, trades=(trade,))

    def record_signal(self, signal: dict) -> None:
        self.checkpoint(None, signals=(signal,))

    def record_evidence(self, key: str, payload: dict, kind: str, timestamp: float) -> None:
        self.checkpoint(None, evidence=((key, payload, kind, timestamp),))

    def snapshot(self, now: float | None = None) -> dict:
        with self._lock:
            current = time.time() if now is None else float(now)
            if current - self._last_maintenance_at >= min(30.0, self.window_seconds / 2):
                self.maintenance(current)
            top = [json.loads(r[0]) for r in self.db.execute(
                "SELECT payload FROM top_signals ORDER BY score DESC,ts DESC LIMIT 10")]
            trades = [json.loads(r[0]) for r in self.db.execute(
                "SELECT payload FROM trades ORDER BY COALESCE(closed_at,ts) DESC LIMIT 20")]
            counts = {name: self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                      for name in ("signal_events", "trades", "evidence")}
            db_bytes, wal_bytes = self._disk_sizes()
            return {"state": self.load_state(), "top_signals": top,
                    "latest_trades": trades, "retained_events": counts["signal_events"],
                    "retained_trades": counts["trades"],
                    "retained_evidence": counts["evidence"],
                    "retained": {"events": counts["signal_events"],
                                 "trades": counts["trades"],
                                 "evidence": counts["evidence"]},
                    "evidence_bytes": self.db.execute(
                        "SELECT COALESCE(SUM(size),0) FROM evidence").fetchone()[0],
                    "storage_stats": self._stats() | {"db_bytes": db_bytes,
                        "wal_bytes": wal_bytes, "max_db_bytes": self.max_db_bytes,
                        "main_db_limit_bytes": self.main_db_limit_bytes,
                        "wal_budget_bytes": self.wal_budget_bytes}}

    def get_evidence(self, key: str) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT payload FROM evidence WHERE key=?", (key,)).fetchone()
            return json.loads(gzip.decompress(row[0])) if row else None

    def _truncate_wal(self, *, strict: bool) -> bool:
        self.db.execute("PRAGMA busy_timeout=100")
        try:
            result = self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        finally:
            self.db.execute("PRAGMA busy_timeout=10000")
        if result[0] != 0 and strict:
            raise PaperStoreError("Paper WAL is pinned by a reader; close that reader "
                                  "before more writes")
        return result[0] == 0

    def _compact(self, *, strict: bool = True, full: bool = False) -> bool:
        if not self._truncate_wal(strict=strict):
            return False
        if self.db.execute("PRAGMA freelist_count").fetchone()[0]:
            self.db.execute("PRAGMA incremental_vacuum" if full else
                            "PRAGMA incremental_vacuum(256)")
            return self._truncate_wal(strict=strict)
        return True

    def maintenance(self, now: float | None = None, *, aggressive: bool = False) -> None:
        with self._lock:
            current = time.time() if now is None else float(now)
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._prune(current, aggressive)
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise
            self._compact(strict=False, full=aggressive)
            self._last_maintenance_at = current

    def flush(self) -> None:
        with self._lock:
            self._compact()

    def close(self) -> None:
        with self._lock:
            try:
                self.flush()
            finally:
                self.db.close()
