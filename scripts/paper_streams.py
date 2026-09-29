"""Public, fail-closed streaming order books for the paper monitor.

The callback is synchronous so receipt time and book state are delivered in the
same event-loop turn. It must do bounded work; persistence belongs elsewhere.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
from uuid import uuid4
from collections import defaultdict, deque
from urllib.parse import quote

import aiohttp

LOG = logging.getLogger(__name__)
WS_URLS = {
    "hyperliquid": "wss://api.hyperliquid.xyz/ws",
    "lighter": "wss://mainnet.zklighter.elliot.ai/stream?readonly=true",
    "rh_lighter": "wss://api.rh.lighter.xyz/stream?readonly=true",
    "aster": "wss://fstream.asterdex.com",
}
ASTER_SNAPSHOT = "https://fapi.asterdex.com/fapi/v3/depth"
# Lighter sends the full book on subscription; 5,000 levels/side bounds RAM.
# Exceeding the bound invalidates instead of silently corrupting future depth.
STATE_LIMIT = 5000
BUFFER_LIMIT = 4096
LIGHTER_KEEPALIVE_SECONDS = 30.0


def _levels(rows, *, lighter=False):
    out = {}
    for row in rows:
        if lighter:
            price, size = row["price"], row["size"]
        elif isinstance(row, dict):
            price, size = row["px"], row["sz"]
        else:
            price, size = row[:2]
        price, size = float(price), float(size)
        if not math.isfinite(price) or not math.isfinite(size) or price <= 0 or size < 0:
            raise ValueError("non-finite or negative order book level")
        if size:
            out[price] = size
    return out


def _timestamp(value, divisor=1000):
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        return None
    return value / divisor


def _hl_top_signature(raw_bids, raw_asks):
    """Exact HL top identity, including number of resting orders when exposed."""
    try:
        bids = [x for x in raw_bids if float(x['sz']) > 0]
        asks = [x for x in raw_asks if float(x['sz']) > 0]
        bid = max(bids, key=lambda x: float(x['px']))
        ask = min(asks, key=lambda x: float(x['px']))
        return (float(bid['px']), float(bid['sz']), int(bid['n']),
                float(ask['px']), float(ask['sz']), int(ask['n']))
    except (KeyError, TypeError, ValueError, OverflowError, IndexError):
        return None


class StreamManager:
    def __init__(self, session: aiohttp.ClientSession, markets: list[dict],
                 on_book, on_status, max_levels: int = 100,
                 prefer_bbo: bool = False):
        if max_levels < 1 or max_levels > STATE_LIMIT:
            raise ValueError("max_levels must be 1..5000")
        self.session, self.on_book, self.on_status = session, on_book, on_status
        # A manager can be rebuilt after market discovery changes. Never reuse
        # a generation from an earlier manager or process lifetime.
        self.instance_id = uuid4().hex
        self.max_levels = max_levels
        self.prefer_bbo = bool(prefer_bbo)
        self.markets = {(m["venue"], str(m["market"])): m for m in markets}
        self.states: dict[tuple[str, str], dict] = {}
        self.generations: dict[tuple[str, str], str] = {}
        self.snapshot_tasks: set[asyncio.Task] = set()
        self.snapshot_gate = asyncio.Semaphore(2)
        self._last_snapshot_start = 0.0
        self._snapshot_lock = asyncio.Lock()
        self.counters = defaultdict(lambda: defaultdict(int))
        self.active_connections = defaultdict(int)
        self._last_message_status = defaultdict(float)
        self.resubscribe = set()
        # Per-generation Hyperliquid source-time high water. BBO never carries
        # cached L2 depth; contemporaneous L2 depth is checked independently.
        self.hl_last = {}
        self.hl_block_l2 = {}

    def _status(self, venue, **changes):
        counts = self.counters[venue]
        for key in ("connected", "subscriptions", "messages", "reconnects", "gaps", "errors", "keepalives", "older_book_drops"):
            if key in changes and isinstance(changes[key], int) and key != "connected":
                counts[key] += changes[key]
        if set(changes) == {"messages"}:
            now = time.monotonic()
            if now - self._last_message_status[venue] < 1:
                return
            self._last_message_status[venue] = now
        self.on_status(venue, {**changes, **dict(counts)})

    def _invalidate(self, key, reason, generation=None):
        self.states.pop(key, None)
        venue, market = key
        self.on_book({"venue": venue, "market": self.markets[key]["market"],
                      "bids": [], "asks": [], "received": time.time(),
                      "engine_time": None, "sequence": None,
                      "generation": generation or self.generations.get(key),
                      "valid": False, "reason": reason})

    def _publish(self, key, bids, asks, *, engine_time=None, sequence=None,
                 generation=None, source=None):
        if not bids or not asks or max(bids) >= min(asks):
            self._invalidate(key, "empty_or_crossed", generation)
            self._status(key[0], gaps=1, reason="empty_or_crossed")
            if key[0] in ("lighter", "rh_lighter"):
                self.resubscribe.add(key)
            return False
        if len(bids) > STATE_LIMIT or len(asks) > STATE_LIMIT:
            self._invalidate(key, "book_overflow", generation)
            self._status(key[0], gaps=1, reason="book_overflow")
            if key[0] in ("lighter", "rh_lighter"):
                self.resubscribe.add(key)
            return False
        event = {"venue": key[0], "market": self.markets[key]["market"],
                      "bids": sorted(bids.items(), reverse=True)[:self.max_levels],
                      "asks": sorted(asks.items())[:self.max_levels],
                      "received": time.time(), "engine_time": engine_time,
                      "sequence": sequence, "generation": generation,
                      "valid": True}
        if source is not None:
            event["source"] = source
        self.on_book(event)
        return True

    def _hl_accept(self, key, generation, source_ms, source, top=None):
        last = self.hl_last.get(key)
        if last is None or last['generation'] != generation:
            return True
        if source_ms < last['source_ms']:
            self._status('hyperliquid', older_book_drops=1)
            return False
        if source_ms > last['source_ms']:
            return True
        # BBO has priority at equal source time. An equal-time L2 snapshot can
        # add depth only if its top prices and displayed sizes exactly match.
        if source == 'bbo' and last['source'] == 'l2book':
            return True
        if (source == 'l2book' and last['source'] == 'bbo' and
                top is not None and top == last.get('top')):
            return True
        self._status('hyperliquid', older_book_drops=1)
        return False

    def _hl_record(self, key, generation, source_ms, source, top=None):
        self.hl_last[key] = {'generation': generation, 'source_ms': source_ms,
                             'source': source, 'top': top}

    def process_message(self, venue: str, message: dict, generation: str):
        """Process HL/Lighter websocket frames; useful for deterministic replay."""
        kind = message.get("channel") if venue == "hyperliquid" else message.get("type")
        if venue == "hyperliquid":
            if kind == "activeAssetCtx":
                data = message.get("data", {})
                key = (venue, str(data.get("coin", "")))
                ctx = data.get("ctx", {})
                if key in self.markets and ctx.get("oraclePx") is not None:
                    try:
                        price = float(ctx["oraclePx"])
                        if math.isfinite(price) and price > 0:
                            self._status(venue, references=[{
                                "venue": venue, "market": self.markets[key]["market"],
                                "timestamp": time.time(), "timestamp_source": "received",
                                "oracle_price": price, "reference_price": price,
                                "reference_kind": "oracle",
                                "estimated_funding_rate": ctx.get("funding")}])
                    except (TypeError, ValueError):
                        pass
                return
            if kind not in ("l2Book", "bbo") or (kind == "bbo" and not self.prefer_bbo):
                return
            data = message.get("data")
            if not isinstance(data, dict) or data.get("coin") is None:
                self._status(venue, errors=1, reason="missing_hl_identity")
                return
            key = (venue, str(data["coin"]))
            if key not in self.markets:
                return
            try:
                raw_time = data["time"]
                source_ms = int(raw_time)
                if (isinstance(raw_time, bool) or not math.isfinite(float(raw_time)) or
                        float(raw_time) != source_ms or source_ms <= 0):
                    raise ValueError("invalid source time")
                if kind == "bbo":
                    sides = data["bbo"]
                    if not isinstance(sides, list) or len(sides) != 2 or any(x is None for x in sides):
                        last = self.hl_last.get(key)
                        if last and last['generation'] == generation and source_ms < last['source_ms']:
                            self._status(venue, older_book_drops=1)
                            return
                        self._hl_record(key, generation, source_ms, 'bbo')
                        self._invalidate(key, "bbo_missing_side", generation)
                        return
                    bids, asks = _levels([sides[0]]), _levels([sides[1]])
                    if len(bids) != 1 or len(asks) != 1:
                        raise ValueError("empty BBO side")
                    top = _hl_top_signature([sides[0]], [sides[1]])
                    source = 'bbo'
                else:
                    raw_bids, raw_asks = data["levels"]
                    bids, asks = _levels(raw_bids), _levels(raw_asks)
                    top = _hl_top_signature(raw_bids, raw_asks)
                    source = 'l2book'
                if kind == 'l2Book' and self.hl_block_l2.get(key) == generation:
                    return
                if not self._hl_accept(key, generation, source_ms, source, top):
                    return
                if self._publish(key, bids, asks, engine_time=source_ms/1000,
                                 sequence=source_ms, generation=generation,
                                 source=source):
                    self._hl_record(key, generation, source_ms, source, top)
                    if kind == 'bbo':
                        self.hl_block_l2.pop(key, None)
                else:
                    self._hl_record(key, generation, source_ms, source)
            except (KeyError, TypeError, ValueError, OverflowError, IndexError) as exc:
                if kind == 'bbo':
                    self.hl_block_l2[key] = generation
                self._invalidate(key, f"malformed_book:{exc}", generation)
                self._status(venue, errors=1, reason="malformed_book")
            return
        if venue not in ("lighter", "rh_lighter"):
            return
        if kind in ("subscribed/market_stats", "update/market_stats"):
            stats = message.get("market_stats", {})
            key = (venue, str(stats.get("market_id", "")))
            if key in self.markets:
                try:
                    price = float(stats["mark_price"])
                    if math.isfinite(price) and price > 0:
                        self._status(venue, references=[{
                            "venue": venue, "market": self.markets[key]["market"],
                            "timestamp": _timestamp(message.get("timestamp")) or time.time(),
                            "timestamp_source": "server" if message.get("timestamp") else "received",
                            "reference_price": price, "reference_kind": "mark",
                            "index_price": stats.get("index_price"),
                            "funding_rate": stats.get("funding_rate"),
                            "funding_timestamp": stats.get("funding_timestamp")}])
                except (KeyError, TypeError, ValueError):
                    pass
            return
        if kind not in ("subscribed/order_book", "update/order_book"):
            return
        channel = message.get("channel", "")
        if not channel.startswith("order_book:"):
            return
        key = (venue, channel.split(":", 1)[1])
        if key not in self.markets:
            return
        try:
            body = message["order_book"]
            nonce = int(body["nonce"])
            if kind == "subscribed/order_book":
                bids = _levels(body["bids"], lighter=True)
                asks = _levels(body["asks"], lighter=True)
            else:
                prior = self.states.get(key)
                if prior is None or prior["generation"] != generation:
                    return  # a delta without a snapshot cannot establish a book
                begin_nonce = int(body["begin_nonce"])
                if begin_nonce != prior["nonce"] or nonce <= prior["nonce"]:
                    self._invalidate(key, "nonce_gap", generation)
                    self._status(venue, gaps=1, reason="nonce_gap")
                    self.resubscribe.add(key)
                    return
                bids, asks = prior["bids"].copy(), prior["asks"].copy()
                for side, rows in ((bids, body["bids"]), (asks, body["asks"])):
                    for row in rows:
                        price, size = float(row["price"]), float(row["size"])
                        if not math.isfinite(price) or not math.isfinite(size) or price <= 0 or size < 0:
                            raise ValueError("invalid delta level")
                        if size:
                            side[price] = size
                        else:
                            side.pop(price, None)
            if self._publish(key, bids, asks,
                             engine_time=_timestamp(body.get("last_updated_at"), 1_000_000),
                             sequence=nonce, generation=generation):
                self.states[key] = {"bids": bids, "asks": asks,
                                    "nonce": nonce, "generation": generation}
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            self._invalidate(key, f"malformed_book:{exc}", generation)
            self._status(venue, errors=1, reason="malformed_book")
            self.resubscribe.add(key)

    def process_aster_delta(self, message: dict, generation: str):
        """Apply a diff only after the REST snapshot and sequence handshake."""
        data = message.get("data", message)
        key = ("aster", str(data.get("s", "")))
        if key not in self.markets:
            return
        state = self.states.get(key)
        if state is None or state.get("generation") != generation:
            return
        if state.get("buffer") is not None:
            if len(state["buffer"]) == BUFFER_LIMIT:
                self._invalidate(key, "bootstrap_overflow", generation)
                self._status("aster", gaps=1, reason="bootstrap_overflow")
                return
            state["buffer"].append(data)
            return
        try:
            first, last, prior = int(data["U"]), int(data["u"]), int(data["pu"])
            if state.get("await_bridge"):
                if last < state["sequence"]:
                    return
                # U denotes the first *changed* order ID and may skip values.
                # pu is the link from the prior diff batch; the snapshot ID
                # must lie inside that preceding-to-current interval.
                if prior > state["sequence"]:
                    self._invalidate(key, "bootstrap_gap", generation)
                    self._status("aster", gaps=1, reason="bootstrap_gap")
                    return
                if last == state["sequence"]:
                    return
                # A snapshot may land in the middle of a batched diff. Its
                # first bridge's pu precedes the snapshot ID by design.
                state["sequence"] = prior
                state["await_bridge"] = False
            # Aster's U is the first changed order ID in the batch, so it can
            # jump ahead of pu. Only pu links consecutive stream events.
            if prior != state["sequence"] or last <= state["sequence"]:
                self._invalidate(key, "sequence_gap", generation)
                self._status("aster", gaps=1, reason="sequence_gap")
                return
            bids, asks = state["bids"].copy(), state["asks"].copy()
            for side, rows in ((bids, data["b"]), (asks, data["a"])):
                for row in rows:
                    price, size = float(row[0]), float(row[1])
                    if not math.isfinite(price) or not math.isfinite(size) or price <= 0 or size < 0:
                        raise ValueError("invalid delta level")
                    if size:
                        side[price] = size
                    else:
                        side.pop(price, None)
            if self._publish(key, bids, asks, engine_time=_timestamp(data.get("E") or data.get("T")),
                             sequence=last, generation=generation):
                state.update(bids=bids, asks=asks, sequence=last)
        except (KeyError, ValueError, TypeError, IndexError, OverflowError) as exc:
            self._invalidate(key, f"malformed_delta:{exc}", generation)
            self._status("aster", errors=1, reason="malformed_delta")

    async def _bootstrap_aster(self, key, generation):
        async with self.snapshot_gate:
            # Snapshot requests are rate spaced, including across concurrent sockets.
            async with self._snapshot_lock:
                delay = max(0, self._last_snapshot_start + 2.0 - time.monotonic())
                if delay:
                    await asyncio.sleep(delay)
                self._last_snapshot_start = time.monotonic()
            try:
                async with self.session.get(ASTER_SNAPSHOT,
                                            params={"symbol": key[1], "limit": 1000},
                                            timeout=aiohttp.ClientTimeout(total=12)) as response:
                    response.raise_for_status()
                    body = await response.json()
                state = self.states.get(key)
                if state is None or state["generation"] != generation:
                    return
                bids, asks = _levels(body["bids"]), _levels(body["asks"])
                sequence = int(body["lastUpdateId"])
                events = state["buffer"]
                state.update(bids=bids, asks=asks, sequence=sequence,
                             buffer=None, await_bridge=True)
                # The initial event must straddle the REST snapshot's last ID.
                while events and int(events[0]["u"]) < sequence:
                    events.popleft()
                if not events:
                    self._publish(key, bids, asks,
                                  engine_time=_timestamp(body.get("E") or body.get("T")),
                                  sequence=sequence, generation=generation)
                    return
                first = events.popleft()
                if int(first["pu"]) > sequence:
                    self._invalidate(key, "bootstrap_gap", generation)
                    self._status("aster", gaps=1, reason="bootstrap_gap")
                    return
                # REST snapshot itself is a valid book but no engine timestamp is guaranteed.
                if not self._publish(key, bids, asks, engine_time=_timestamp(body.get("E") or body.get("T")),
                                     sequence=sequence, generation=generation):
                    return
                self.process_aster_delta(first, generation)
                for event in events:
                    if key not in self.states:
                        return
                    self.process_aster_delta(event, generation)
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError,
                    ValueError, OverflowError) as exc:
                self._invalidate(key, f"snapshot_error:{exc}", generation)
                self._status("aster", errors=1, reason="snapshot_error")

    def _aster_task(self, key, generation):
        task = asyncio.create_task(self._bootstrap_aster(key, generation))
        self.snapshot_tasks.add(task)
        task.add_done_callback(self.snapshot_tasks.discard)

    def _start_priority_aster_bootstraps(self, group, generation):
        # Aster REST snapshot starts are spaced two seconds apart. Give held
        # positions a place ahead of new-market scans after a restart.
        for market in group:
            if not market.get("risk_priority"):
                continue
            key = ("aster", str(market["market"]))
            if key in self.states:
                continue
            self.states[key] = {"generation": generation,
                                "buffer": deque(maxlen=BUFFER_LIMIT)}
            self._aster_task(key, generation)

    async def _connection(self, venue, group, stop, index):
        count = 0
        while not stop.is_set():
            count += 1
            generation = f"{self.instance_id}:{venue}:{index}:{count}"
            keys = [(venue, str(m["market"])) for m in group]
            self.resubscribe.difference_update(keys)
            for key in keys:
                self.generations[key] = generation
                self._invalidate(key, "connecting" if count == 1 else "reconnecting", generation)
            if count > 1:
                self._status(venue, reconnects=1)
            if venue == "aster":
                stream_names = []
                for m in group:
                    symbol = str(m["market"]).lower()
                    stream_names.extend((symbol + "@depth@100ms", symbol + "@markPrice@1s"))
                streams = "/".join(quote(name) for name in stream_names)
                url = WS_URLS[venue] + "/stream?streams=" + streams
            else:
                url = WS_URLS[venue]
            connected = False
            try:
                async with self.session.ws_connect(url, heartbeat=30, receive_timeout=75,
                                                   max_msg_size=4 * 1024 * 1024,
                                                   timeout=aiohttp.ClientTimeout(total=15)) as ws:
                    self.active_connections[venue] += 1
                    connected = True
                    self._status(venue, connected=True,
                                 connections=self.active_connections[venue])
                    if venue == "hyperliquid":
                        for m in group:
                            await ws.send_json({"method": "subscribe", "subscription":
                                                {"type": "l2Book", "coin": m["market"]}})
                            if self.prefer_bbo:
                                await ws.send_json({"method": "subscribe", "subscription":
                                                    {"type": "bbo", "coin": m["market"]}})
                            await ws.send_json({"method": "subscribe", "subscription":
                                                {"type": "activeAssetCtx", "coin": m["market"]}})
                            await asyncio.sleep(0.02)
                    elif venue in ("lighter", "rh_lighter"):
                        for m in group:
                            await ws.send_json({"type": "subscribe", "channel":
                                                f"order_book/{m['market']}"})
                            await ws.send_json({"type": "subscribe", "channel":
                                                f"market_stats/{m['market']}"})
                            await asyncio.sleep(0.02)
                    self._status(venue, subscriptions=(3 if venue == 'hyperliquid' and self.prefer_bbo else 2) * len(group))
                    if venue == "aster":
                        self._start_priority_aster_bootstraps(group, generation)
                        # Let those tasks enter the spaced snapshot queue before
                        # a buffered ordinary-market delta can schedule its own.
                        await asyncio.sleep(0)
                    next_keepalive = time.monotonic() + LIGHTER_KEEPALIVE_SECONDS
                    while not stop.is_set():
                        # aiohttp's heartbeat resets on incoming traffic. Lighter
                        # instead requires an outbound frame at least every 120s,
                        # including while subscribed markets are continuously busy.
                        if venue in ("lighter", "rh_lighter") and time.monotonic() >= next_keepalive:
                            await ws.send_json({"type": "ping"})
                            self._status(venue, keepalives=1, last_keepalive_at=time.time())
                            next_keepalive = time.monotonic() + LIGHTER_KEEPALIVE_SECONDS
                        try:
                            frame = await ws.receive(timeout=2)
                        except asyncio.TimeoutError:
                            continue
                        if frame.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                          aiohttp.WSMsgType.ERROR):
                            self._status(venue, last_disconnect_at=time.time(),
                                         last_close_code=ws.close_code,
                                         last_close_reason=str(frame.extra or frame.data or frame.type.name)[:160])
                            break
                        if frame.type != aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            data = json.loads(frame.data)
                        except (json.JSONDecodeError, TypeError):
                            self._status(venue, errors=1, reason="invalid_json")
                            continue
                        self._status(venue, messages=1)
                        if venue == "aster":
                            payload = data.get("data", data)
                            if payload.get("e") == "markPriceUpdate":
                                key = (venue, str(payload.get("s", "")))
                                if key in self.markets:
                                    try:
                                        price = float(payload["p"])
                                        if math.isfinite(price) and price > 0:
                                            self._status(venue, references=[{
                                                "venue": venue, "market": self.markets[key]["market"],
                                                "timestamp": _timestamp(payload.get("E")) or time.time(),
                                                "timestamp_source": "server" if payload.get("E") else "received",
                                                "reference_price": price, "reference_kind": "mark",
                                                "index_price": payload.get("i"),
                                                "estimated_funding_rate": payload.get("r"),
                                                "next_funding_timestamp": payload.get("T")}])
                                    except (KeyError, TypeError, ValueError):
                                        pass
                                continue
                            if payload.get("e") != "depthUpdate":
                                continue
                            key = (venue, str(payload.get("s", "")))
                            if key not in self.markets:
                                continue
                            state = self.states.get(key)
                            if state is None:
                                self.states[key] = {"generation": generation,
                                                    "buffer": deque(maxlen=BUFFER_LIMIT)}
                                self._aster_task(key, generation)
                            self.process_aster_delta(payload, generation)
                            # A failed bootstrap restarts when the next event arrives.
                        else:
                            if data.get("type") == "ping":
                                await ws.send_json({"type": "pong"})
                            self.process_message(venue, data, generation)
                            if venue in ("lighter", "rh_lighter"):
                                pending = self.resubscribe.intersection(keys)
                                for key in pending:
                                    self.resubscribe.discard(key)
                                    channel = f"order_book/{key[1]}"
                                    await ws.send_json({"type": "unsubscribe", "channel": channel})
                                    await ws.send_json({"type": "subscribe", "channel": channel})
                                    self._status(venue, subscriptions=1, reason="resync")
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
                self._status(venue, errors=1, reason=str(exc)[:160])
            finally:
                if connected:
                    self.active_connections[venue] -= 1
                self._status(venue, connected=bool(self.active_connections[venue]),
                             connections=self.active_connections[venue])
                for key in keys:
                    if self.generations.get(key) == generation:
                        self._invalidate(key, "disconnected", generation)
                        self.states.pop(key, None)
            if not stop.is_set():
                delay = min(30, 2 ** min(count, 5)) * random.uniform(0.75, 1.25)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass

    async def run(self, stop: asyncio.Event):
        groups = defaultdict(list)
        for market in self.markets.values():
            venue = market["venue"]
            if venue not in WS_URLS:
                raise ValueError(f"unsupported venue: {venue}")
            groups[venue].append(market)
        tasks = []
        try:
            for venue, markets in groups.items():
                # Chunk to bound socket traffic and Aster's 200-stream limit.
                size = 50 if venue == "hyperliquid" else 30 if venue == "aster" else 25
                for i in range(0, len(markets), size):
                    tasks.append(asyncio.create_task(
                        self._connection(venue, markets[i:i + size], stop, i // size)))
            if tasks:
                await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            for task in self.snapshot_tasks:
                task.cancel()
            await asyncio.gather(*tasks, *self.snapshot_tasks, return_exceptions=True)
