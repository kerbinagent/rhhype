#!/usr/bin/env python3
"""Bounded, read-only public quote/trade capture for later maker research.

This script never signs, authenticates, places orders, or requests account data.
It records feeds only; it does not infer hypothetical maker fills or P&L.
"""

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import signal
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import aiohttp


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKETS = ROOT / "data/paper-monitor/markets.json"
DEFAULT_OUTPUT = ROOT / "data/raw/maker-capture"
URLS = {
    "hyperliquid": "wss://api.hyperliquid.xyz/ws",
    "lighter": "wss://mainnet.zklighter.elliot.ai/stream?readonly=true",
    "rh_lighter": "wss://api.rh.lighter.xyz/stream?readonly=true",
}
HARD_SECONDS = 600
HARD_BYTES = 25_000_000
MANIFEST_RESERVE = 65_536
MAX_RECONNECTS = 3
MAX_FRAME_BYTES = 4 * 1024 * 1024


class SizeCapReached(Exception):
    """The next complete compressed record would exceed the payload cap."""


def utc_iso_ns(value):
    return datetime.fromtimestamp(value / 1e9, timezone.utc).isoformat()


def parse_epoch_ns(value, unit):
    """Parse a source timestamp with a declared unit; reject ambiguity."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("timestamp is not an integer")
    if isinstance(value, str) and (not value or not value.isascii() or not value.isdigit()):
        raise ValueError("timestamp is not decimal digits")
    n = int(value)
    factor = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}[unit]
    result = n * factor
    if not 1_577_836_800_000_000_000 <= result <= 4_102_444_800_000_000_000:
        raise ValueError("timestamp outside 2020–2100")
    return result


def integer(value, name):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{name} is not an integer")
    if isinstance(value, str) and (not value or not value.isascii() or not value.isdigit()):
        raise ValueError(f"{name} is not decimal digits")
    return int(value)


class BoundedGzip:
    """One gzip member per NDJSON record makes the compressed byte cap exact."""

    def __init__(self, path, total_cap=HARD_BYTES, reserve=MANIFEST_RESERVE):
        if total_cap <= reserve:
            raise ValueError("total cap must exceed manifest reserve")
        self.path = Path(path)
        self.limit = total_cap - reserve
        self.bytes_written = 0
        self.records = 0
        self.file = self.path.open("xb")

    def write(self, row):
        body = json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        member = gzip.compress(body, compresslevel=6, mtime=0)
        if self.bytes_written + len(member) > self.limit:
            raise SizeCapReached
        self.file.write(member)
        self.bytes_written += len(member)
        self.records += 1

    def close(self):
        if not self.file.closed:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()


def select_markets(path, include_rh=True):
    """Freeze BTC/ETH market IDs from the monitor's public discovery plan."""
    source = Path(path).read_bytes()
    plan = json.loads(source)
    pairs = plan["pairs"]
    chosen = {venue: {} for venue in URLS if include_rh or venue != "rh_lighter"}
    for row in pairs:
        asset = row.get("asset")
        if asset not in ("BTC", "ETH"):
            continue
        hl, other = row.get("hl", {}), row.get("other", {})
        if hl.get("venue") != "hyperliquid" or hl.get("asset") != asset:
            continue
        venue = other.get("venue")
        if venue not in chosen or other.get("asset") != asset:
            continue
        chosen["hyperliquid"][asset] = str(hl["market"])
        chosen[venue][asset] = str(other["market"])
    if any(set(markets) != {"BTC", "ETH"} for markets in chosen.values()):
        raise ValueError("BTC and ETH are required for each selected venue in markets.json")
    return chosen, hashlib.sha256(source).hexdigest()


class FeedQuality:
    """Annotate raw messages; an invalid Lighter book needs a fresh snapshot."""

    def __init__(self):
        self.books = {}
        self.trade_valid = {}
        self.invalidations = Counter()

    def invalidate(self, venue, market, generation, reason):
        key = (venue, market)
        self.books[key] = {"generation": generation, "valid": False, "nonce": None}
        self.invalidations[f"{venue}|{market}|{reason}"] += 1
        return {"quality": "invalid", "reason": reason, "book_frame_ok": False}

    def disconnect(self, venue, markets, generation):
        for market in markets:
            self.invalidate(venue, market, generation, "disconnect")
            self.trade_valid[(venue, market, generation)] = False

    def inspect(self, venue, payload, generation):
        if not isinstance(payload, dict):
            return {"quality": "invalid", "reason": "non_object_frame", "market": None}
        if venue == "hyperliquid":
            return self._hyperliquid(payload, generation)
        return self._lighter(venue, payload, generation)

    def _hyperliquid(self, payload, generation):
        channel = payload.get("channel")
        data = payload.get("data")
        if channel not in ("bbo", "l2Book", "trades"):
            return {"quality": "control", "market": None, "channel": str(channel)}
        if channel == "trades":
            if not isinstance(data, list):
                return {"quality": "invalid", "reason": "malformed_trade_batch", "market": None, "channel": channel}
            markets = {str(x.get("coin")) for x in data if isinstance(x, dict) and x.get("coin")}
            market = next(iter(markets)) if len(markets) == 1 else None
            if market is None and data:
                return {"quality": "invalid", "reason": "mixed_or_missing_trade_market", "market": None, "channel": channel}
            try:
                times = [parse_epoch_ns(x["time"], "ms") for x in data]
            except (KeyError, TypeError, ValueError) as exc:
                if market:
                    self.trade_valid[("hyperliquid", market, generation)] = False
                self.invalidations[f"hyperliquid|{market}|malformed_trade_time"] += 1
                return {"quality": "invalid", "reason": "malformed_trade_time", "market": market,
                        "channel": channel, "detail": str(exc)[:100]}
            return {"quality": "wire_ok" if self.trade_valid.get(("hyperliquid", market, generation), True) else "gap_after_bad_trade",
                    "market": market, "channel": channel, "trade_count": len(data),
                    "source_min_ns": min(times) if times else None, "source_max_ns": max(times) if times else None}
        if not isinstance(data, dict) or not data.get("coin"):
            return {"quality": "invalid", "reason": "malformed_book", "market": None, "channel": channel}
        market = str(data["coin"])
        try:
            source = parse_epoch_ns(data["time"], "ms")
            sides = data["bbo"] if channel == "bbo" else data["levels"]
            if not isinstance(sides, list) or len(sides) != 2:
                raise ValueError("missing two sides")
            if channel == "bbo" and any(side is None for side in sides):
                return {"market": market, "channel": channel, "source_min_ns": source,
                        **self.invalidate("hyperliquid", market, generation, "empty_book_side")}
            if channel == "l2Book" and any(not isinstance(side, list) for side in sides):
                raise ValueError("malformed levels")
        except (KeyError, TypeError, ValueError) as exc:
            return {"market": market, "channel": channel, "detail": str(exc)[:100],
                    **self.invalidate("hyperliquid", market, generation, "malformed_book_time_or_levels")}
        self.books[("hyperliquid", market)] = {"generation": generation, "valid": True, "nonce": None}
        return {"quality": "wire_ok", "market": market, "channel": channel,
                "source_min_ns": source, "source_max_ns": source, "book_frame_ok": True}

    def _lighter(self, venue, payload, generation):
        typ, channel = payload.get("type"), str(payload.get("channel", ""))
        if ":" not in channel:
            return {"quality": "control", "market": None, "channel": channel or str(typ)}
        feed, market = channel.split(":", 1)
        if feed not in ("order_book", "ticker", "trade"):
            return {"quality": "control", "market": market, "channel": feed}
        result = {"market": market, "channel": feed}
        if feed == "order_book":
            body = payload.get("order_book")
            if not isinstance(body, dict):
                return result | self.invalidate(venue, market, generation, "malformed_book")
            try:
                source = parse_epoch_ns(body.get("last_updated_at", payload.get("last_updated_at")), "us")
                nonce = integer(body["nonce"], "nonce")
                if not isinstance(body.get("bids"), list) or not isinstance(body.get("asks"), list):
                    raise ValueError("missing book sides")
                if typ == "subscribed/order_book":
                    self.books[(venue, market)] = {"generation": generation, "valid": True, "nonce": nonce}
                    return result | {"quality": "wire_ok_snapshot", "source_min_ns": source,
                                     "source_max_ns": source, "nonce": nonce, "book_frame_ok": True}
                if typ != "update/order_book":
                    return result | {"quality": "control", "source_min_ns": source}
                state = self.books.get((venue, market))
                if not state or state["generation"] != generation or not state["valid"]:
                    return result | self.invalidate(venue, market, generation, "delta_without_snapshot") | {"resubscribe": True}
                begin = integer(body["begin_nonce"], "begin_nonce")
                if begin != state["nonce"] or nonce <= state["nonce"]:
                    return result | self.invalidate(venue, market, generation, "nonce_gap") | {
                        "begin_nonce": begin, "nonce": nonce, "expected_begin_nonce": state["nonce"], "resubscribe": True}
                state["nonce"] = nonce
                return result | {"quality": "wire_ok", "source_min_ns": source, "source_max_ns": source,
                                 "nonce": nonce, "begin_nonce": begin, "book_frame_ok": True}
            except (KeyError, TypeError, ValueError) as exc:
                return result | self.invalidate(venue, market, generation, "malformed_book_time_or_nonce") | {
                    "detail": str(exc)[:100], "resubscribe": True}
        if feed == "ticker":
            try:
                body = payload["ticker"]
                source = parse_epoch_ns(body["last_updated_at"], "us")
                if not isinstance(body.get("a"), dict) or not isinstance(body.get("b"), dict):
                    raise ValueError("missing BBO side")
                return result | {"quality": "wire_ok", "source_min_ns": source, "source_max_ns": source}
            except (KeyError, TypeError, ValueError) as exc:
                self.invalidations[f"{venue}|{market}|malformed_ticker"] += 1
                return result | {"quality": "invalid", "reason": "malformed_ticker", "detail": str(exc)[:100]}
        if typ not in ("update/trade", "subscribed/trade"):
            return result | {"quality": "control"}
        trades = payload.get("trades", [])
        liquidation = payload.get("liquidation_trades", [])
        if not isinstance(trades, list) or not isinstance(liquidation, list):
            self.trade_valid[(venue, market, generation)] = False
            self.invalidations[f"{venue}|{market}|malformed_trade_batch"] += 1
            return result | {"quality": "invalid", "reason": "malformed_trade_batch"}
        try:
            times = [parse_epoch_ns(x["timestamp"], "ms") for x in trades + liquidation]
        except (KeyError, TypeError, ValueError) as exc:
            self.trade_valid[(venue, market, generation)] = False
            self.invalidations[f"{venue}|{market}|malformed_trade_time"] += 1
            return result | {"quality": "invalid", "reason": "malformed_trade_time", "detail": str(exc)[:100]}
        transaction_times = []
        for trade in trades + liquidation:
            if trade.get("transaction_time") is not None:
                try:
                    transaction_times.append(parse_epoch_ns(trade["transaction_time"], "us"))
                except (TypeError, ValueError):
                    self.invalidations[f"{venue}|{market}|malformed_optional_transaction_time"] += 1
        return result | {"quality": "wire_ok" if self.trade_valid.get((venue, market, generation), True) else "gap_after_bad_trade",
                         "trade_count": len(times), "source_min_ns": min(times) if times else None,
                         "source_max_ns": max(times) if times else None,
                         "transaction_min_ns": min(transaction_times) if transaction_times else None,
                         "transaction_max_ns": max(transaction_times) if transaction_times else None,
                         "trade_nonce": payload.get("nonce")}


def subscriptions(venue, markets):
    if venue == "hyperliquid":
        return [{"method": "subscribe", "subscription": {"type": feed, "coin": coin}}
                for coin in markets.values() for feed in ("bbo", "l2Book", "trades")]
    return [{"type": "subscribe", "channel": f"{feed}/{market}"}
            for market in markets.values() for feed in ("order_book", "ticker", "trade")]


def compact_counts(values, limit):
    """Bound manifest size while retaining the most frequent error/feed keys."""
    rows = values.most_common(limit)
    return {str(key)[:100]: count for key, count in rows}, max(0, len(values) - len(rows))


class Capture:
    def __init__(self, writer, selected, seconds, total_cap):
        self.writer = writer
        self.selected = selected
        self.seconds = seconds
        self.total_cap = total_cap
        self.stop = asyncio.Event()
        self.end_reason = None
        self.started_ns = time.time_ns()
        self.quality = FeedQuality()
        self.counts = Counter()
        self.errors = []
        self.generations = []
        self.dropped_on_cap = 0
        self.last_source_by_channel = {}

    def finish(self, reason):
        if self.end_reason is None:
            self.end_reason = reason
            self.stop.set()

    def record(self, row):
        if self.stop.is_set():
            return False
        try:
            self.writer.write(row)
            self.counts[f"{row.get('venue')}|{row.get('market')}|{row.get('channel')}"] += 1
            return True
        except SizeCapReached:
            self.dropped_on_cap += 1
            self.finish("compressed_size_cap")
            return False

    def error(self, venue, detail):
        self.counts[f"{venue}|errors"] += 1
        if len(self.errors) < 50:
            self.errors.append({"at_utc": utc_iso_ns(time.time_ns()), "venue": venue, "detail": str(detail)[:240]})

    def note_source_order(self, venue, generation, annotation):
        """Flag within-channel regressions; never merge BBO and L2 here."""
        market, channel = annotation.get("market"), annotation.get("channel")
        source = annotation.get("source_max_ns")
        if market is None or channel is None or source is None:
            return
        key = (venue, generation, market, channel)
        prior = self.last_source_by_channel.get(key)
        if prior is not None and source < prior:
            annotation["source_regression_within_channel"] = True
            self.counts[f"{venue}|{market}|{channel}|source_regressions"] += 1
        else:
            self.last_source_by_channel[key] = source

    async def venue_loop(self, venue):
        markets = self.selected[venue]
        generation_number = 0
        for attempt in range(1, MAX_RECONNECTS + 1):
            if self.stop.is_set():
                break
            generation_number += 1
            generation = f"{venue}:{generation_number}:{uuid.uuid4().hex[:8]}"
            generation_record = {"venue": venue, "generation": generation,
                                 "opened_utc": utc_iso_ns(time.time_ns())}
            self.generations.append(generation_record)
            try:
                timeout = aiohttp.ClientTimeout(total=None, sock_connect=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.ws_connect(URLS[venue], heartbeat=30, receive_timeout=10,
                                                  max_msg_size=MAX_FRAME_BYTES) as ws:
                        self.record({"kind": "connection_open", "venue": venue, "generation": generation,
                                     "receipt_utc_ns": time.time_ns(), "markets": markets})
                        for sub in subscriptions(venue, markets):
                            await ws.send_json(sub)
                        next_ping = time.monotonic() + 60
                        last_resubscribe = {}
                        while not self.stop.is_set():
                            if venue != "hyperliquid" and time.monotonic() >= next_ping:
                                await ws.send_json({"type": "ping"})
                                self.counts[f"{venue}|outbound_keepalive"] += 1
                                next_ping = time.monotonic() + 60
                            try:
                                frame = await ws.receive(timeout=1)
                            except asyncio.TimeoutError:
                                continue
                            receipt_ns, monotonic_ns = time.time_ns(), time.monotonic_ns()
                            if frame.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                              aiohttp.WSMsgType.ERROR):
                                self.error(venue, f"socket closed: {frame.type.name}, {str(frame.data)[:100]}")
                                break
                            if frame.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                payload = json.loads(frame.data)
                            except (TypeError, json.JSONDecodeError) as exc:
                                self.record({"kind": "invalid_json", "venue": venue, "generation": generation,
                                             "receipt_utc_ns": receipt_ns, "receipt_monotonic_ns": monotonic_ns,
                                             "detail": str(exc)[:100]})
                                self.error(venue, "invalid JSON frame")
                                break
                            if venue != "hyperliquid" and isinstance(payload, dict) and payload.get("type") == "ping":
                                await ws.send_json({"type": "pong"})
                            annotation = self.quality.inspect(venue, payload, generation)
                            if (venue == "hyperliquid" and annotation.get("quality") == "invalid"
                                    and annotation.get("channel") == "trades" and annotation.get("market") is None):
                                for affected in markets.values():
                                    self.quality.trade_valid[(venue, affected, generation)] = False
                                annotation["all_venue_trade_markets_invalidated"] = True
                            self.note_source_order(venue, generation, annotation)
                            if (venue == "hyperliquid" and isinstance(payload, dict)
                                    and payload.get("channel") == "subscriptionResponse") or (
                                    venue != "hyperliquid" and isinstance(payload, dict)
                                    and str(payload.get("type", "")).startswith("subscribed/")):
                                self.counts[f"{venue}|subscription_acks"] += 1
                            market = annotation.get("market")
                            row = {"kind": "frame", "venue": venue, "generation": generation,
                                   "receipt_utc_ns": receipt_ns, "receipt_monotonic_ns": monotonic_ns,
                                   "market": market, "channel": annotation.get("channel"),
                                   "annotation": annotation, "payload": payload}
                            if not self.record(row):
                                break
                            if annotation.get("quality") == "invalid":
                                self.counts[f"{venue}|invalid_frames"] += 1
                            if annotation.get("resubscribe") and market in set(markets.values()):
                                now = time.monotonic()
                                if now - last_resubscribe.get(market, -1e9) >= 2:
                                    channel = f"order_book/{market}"
                                    await ws.send_json({"type": "unsubscribe", "channel": channel})
                                    await ws.send_json({"type": "subscribe", "channel": channel})
                                    last_resubscribe[market] = now
                                    self.counts[f"{venue}|book_resubscribe"] += 1
                        self.record({"kind": "connection_close", "venue": venue, "generation": generation,
                                     "receipt_utc_ns": time.time_ns(), "close_code": ws.close_code})
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
                self.error(venue, exc)
            finally:
                if not self.stop.is_set():
                    self.quality.disconnect(venue, markets.values(), generation)
                self.counts[f"{venue}|connections_ended"] += 1
                generation_record["closed_utc"] = utc_iso_ns(time.time_ns())
            if not self.stop.is_set() and attempt < MAX_RECONNECTS:
                await asyncio.sleep(min(5, attempt))


async def capture(args, selected, plan_hash):
    out = args.out or DEFAULT_OUTPUT / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=False)
    writer = BoundedGzip(out / "frames.jsonl.gz", args.max_bytes)
    run = Capture(writer, selected, args.seconds, args.max_bytes)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, run.finish, f"signal_{sig.name.lower()}")
        except (NotImplementedError, RuntimeError):
            pass
    tasks = [asyncio.create_task(run.venue_loop(venue)) for venue in selected]
    deadline = time.monotonic() + args.seconds
    try:
        while not run.stop.is_set():
            if time.monotonic() >= deadline:
                run.finish("duration_limit")
                break
            if all(task.done() for task in tasks):
                run.finish("all_connections_ended")
                break
            await asyncio.sleep(0.2)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
    record_counts, omitted_record_count_keys = compact_counts(run.counts, 128)
    invalidations, omitted_invalidation_keys = compact_counts(run.quality.invalidations, 64)
    manifest = {"schema": "maker-public-capture-v1", "read_only": True,
                "started_utc": utc_iso_ns(run.started_ns), "ended_utc": utc_iso_ns(time.time_ns()),
                "end_reason": run.end_reason, "truncated": run.end_reason == "compressed_size_cap",
                "dropped_complete_frame_on_cap": run.dropped_on_cap,
                "configured_seconds": args.seconds, "configured_total_compressed_bytes": args.max_bytes,
                "compressed_payload_bytes": writer.bytes_written, "payload_records": writer.records,
                "market_plan": str(args.markets), "market_plan_sha256": plan_hash,
                "selected_markets": selected, "endpoints": URLS,
                "generations": run.generations, "record_counts": record_counts,
                "omitted_record_count_keys": omitted_record_count_keys,
                "invalidations": invalidations,
                "omitted_invalidation_keys": omitted_invalidation_keys,
                "errors": run.errors,
                "clock_sync_check": "not performed; receipt minus exchange source time is not a calibrated network latency",
                "notes": ["Raw payloads are public WebSocket frames with receipt UTC and monotonic timestamps.",
                          "Lighter book deltas are valid only after a same-generation snapshot and nonce continuity.",
                          "wire_ok means parseable source time and local feed checks only; it is not a synchronized executable book.",
                          "Hyperliquid L2 can arrive after a newer BBO; no cross-channel book merge is performed.",
                          "A timestamp or book gap invalidates affected evidence; no fill/P&L is inferred.",
                          "Concatenated gzip members form a normal gzip-readable NDJSON stream."]}
    body = json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    if writer.bytes_written + len(body) > args.max_bytes:
        raise RuntimeError("manifest reserve exhausted; compressed total cap cannot be guaranteed")
    (out / "manifest.json").write_bytes(body)
    print(out)
    print(f"reason={run.end_reason} records={writer.records} gzip_bytes={writer.bytes_written} "
          f"total_bytes={writer.bytes_written + len(body)}")
    return out


def cli(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--markets", type=Path, default=DEFAULT_MARKETS)
    ap.add_argument("--out", type=Path, help="New output directory; must not already exist")
    ap.add_argument("--seconds", type=int, default=HARD_SECONDS, help="Duration, 1–600 seconds")
    ap.add_argument("--max-bytes", type=int, default=HARD_BYTES, help="Total compressed file cap, at most 25,000,000")
    ap.add_argument("--exclude-rh", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="Validate configuration without opening sockets or writing files")
    args = ap.parse_args(argv)
    if not 1 <= args.seconds <= HARD_SECONDS:
        ap.error("--seconds must be 1..600")
    if not MANIFEST_RESERVE + 1024 <= args.max_bytes <= HARD_BYTES:
        ap.error("--max-bytes must be 66,560..25,000,000")
    selected, plan_hash = select_markets(args.markets, not args.exclude_rh)
    if args.dry_run:
        print(json.dumps({"read_only": True, "selected_markets": selected,
                          "market_plan_sha256": plan_hash, "seconds": args.seconds,
                          "total_compressed_byte_cap": args.max_bytes,
                          "subscriptions": {venue: subscriptions(venue, markets)
                                            for venue, markets in selected.items()}}, indent=2))
        return
    asyncio.run(capture(args, selected, plan_hash))


if __name__ == "__main__":
    cli()
