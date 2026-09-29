"""Public, read-only funding cashflows for simulated perpetual positions.

Times are Unix seconds. A position owns a settlement at ``entry_time < t <=
exit_time``. This convention excludes a fill exactly at the settlement instant
and includes a close exactly at that instant; venue-specific sequencing cannot
be reconstructed from public market data at subsecond precision.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import math
import time
from typing import Any

import aiohttp

HL_URL = "https://api.hyperliquid.xyz/info"
LIGHTER_URLS = {
    "lighter": "https://mainnet.zklighter.elliot.ai/api/v1",
    "rh_lighter": "https://api.rh.lighter.xyz/api/v1",
}
# The V3 paths are also served from Aster's established futures host. The
# documented fapi3 host returned HTTP 403 in the monitor's runtime environment;
# these public endpoints were verified HTTP 200 here on 2026-09-29.
ASTER_URL = "https://fapi.asterdex.com/fapi/v3"
HOUR = 3600
ASTER_SETTLEMENT_UNCERTAINTY_SECONDS = 15


def _finite(value: Any, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"invalid numeric value: {value!r}")
    return result


def _settlements(start: float, end: float) -> list[int]:
    """Hourly settlement instants strictly after start through end."""
    first = math.floor(start / HOUR) * HOUR + HOUR
    return list(range(first, math.floor(end / HOUR) * HOUR + 1, HOUR))


class FundingService:
    """Bounded funding and reference cache over one shared aiohttp session.

    `sample_references(markets)` accepts market dictionaries with `venue` and
    `market`; it batches each venue into one public metadata request. It is
    useful near UTC hour boundaries. Even a near-boundary public price is an
    *estimate* of the exact clearing price, and is marked as such.
    """

    def __init__(self, session: aiohttp.ClientSession, max_cache_events: int = 2048,
                 reference_tolerance_seconds: float = 90.0):
        self.session = session
        self.max_cache_events = max(1, int(max_cache_events))
        self.reference_tolerance_seconds = _finite(reference_tolerance_seconds, positive=True)
        self._responses: OrderedDict[tuple, tuple[float, list[dict]]] = OrderedDict()
        self._references: OrderedDict[tuple, tuple[float, float, str]] = OrderedDict()
        self._aster_schedules: OrderedDict[tuple[str, int], tuple[float, float]] = OrderedDict()
        self._next_request = {"hyperliquid": 0.0, "lighter": 0.0,
                              "rh_lighter": 0.0, "aster": 0.0}
        self._request_locks = {venue: asyncio.Lock() for venue in self._next_request}

    async def _request(self, venue: str, method: str, url: str, *, params=None, payload=None):
        # These are service-owned *additional* public requests. Keep Lighter to
        # <=10/minute per instance, leaving headroom for the live book collector.
        spacing = 6.0 if venue in LIGHTER_URLS else (3.0 if venue == "aster" else 1.0)
        async with self._request_locks[venue]:
            for attempt in range(3):
                delay = self._next_request[venue] - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                self._next_request[venue] = time.monotonic() + spacing
                try:
                    async with self.session.request(method, url, params=params, json=payload) as response:
                        if response.status != 200:
                            retry = response.headers.get("Retry-After", "0")
                            try:
                                retry = max(0.0, float(retry))
                            except (TypeError, ValueError):
                                retry = 0.0
                            if response.status in (418, 429):
                                self._next_request[venue] = max(self._next_request[venue], time.monotonic() + max(30.0, retry))
                            raise RuntimeError(f"{venue} HTTP {response.status}")
                        body = await response.json()
                        if venue in LIGHTER_URLS and (not isinstance(body, dict) or body.get("code") != 200):
                            raise ValueError(f"{venue} API error")
                        if isinstance(body, dict) and isinstance(body.get("code"), int) and body["code"] < 0:
                            raise ValueError(f"{venue} API error {body['code']}")
                        return body, time.time()
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError):
                    if attempt == 2:
                        raise
                    self._next_request[venue] = max(self._next_request[venue], time.monotonic() + min(8.0, 2.0 ** attempt))
        raise AssertionError("unreachable")

    def observe_reference(self, venue: str, market: str | int, ts: float,
                          oracle_price: float, kind: str | None = None) -> None:
        """Store a timestamped public oracle/index/mark reference for estimation."""
        price, timestamp = _finite(oracle_price, positive=True), _finite(ts)
        if kind is None:
            kind = "mark" if venue == "aster" else "index" if venue in LIGHTER_URLS else "oracle"
        # One best observation per market and UTC-hour boundary. Frequent
        # sampling cannot evict the useful near-boundary price in seconds.
        boundary = int(round(timestamp / HOUR)) * HOUR
        if abs(timestamp - boundary) > self.reference_tolerance_seconds:
            return
        key = (str(venue), str(market), boundary)
        old = self._references.get(key)
        if old and abs(old[0] - boundary) <= abs(timestamp - boundary):
            return
        self._references[key] = (timestamp, price, str(kind))
        self._references.move_to_end(key)
        while len(self._references) > self.max_cache_events:
            self._references.popitem(last=False)

    def _reference(self, venue: str, market: str, settlement: float):
        candidates = [(abs(ts - settlement), ts, px, kind)
                      for (v, m, _), (ts, px, kind) in self._references.items()
                      if v == venue and m == market and abs(ts - settlement) <= self.reference_tolerance_seconds]
        return min(candidates) if candidates else None

    def observe_aster_schedule(self, market: str, observed_at: float, next_funding_time: float) -> None:
        """Record a public V3 premiumIndex nextFundingTime snapshot.

        Both times are Unix seconds. Only a pre-boundary snapshot can prove
        that a later empty history window was not a missing hourly event.
        """
        observed_at, next_funding_time = _finite(observed_at), _finite(next_funding_time)
        next_hour = math.floor(observed_at / HOUR) * HOUR + HOUR
        key = (str(market), next_hour)
        self._aster_schedules[key] = (observed_at, next_funding_time)
        self._aster_schedules.move_to_end(key)
        while len(self._aster_schedules) > self.max_cache_events:
            self._aster_schedules.popitem(last=False)

    def _aster_hour_proven(self, market: str, hour: int, start: float, end: float) -> bool:
        snapshot = self._aster_schedules.get((market, hour))
        if snapshot is None:
            return False
        observed_at, next_funding_time = snapshot
        return (start - self.reference_tolerance_seconds <= observed_at < hour
                and next_funding_time > end + ASTER_SETTLEMENT_UNCERTAINTY_SECONDS)

    async def sample_references(self, markets: list[dict]) -> dict:
        """Batch public reference samples; return counts and errors per venue.

        Lighter history `value` already supplies a per-base-unit dollar payment;
        its batch index samples are still retained for cross-checks and a
        guarded fallback if a historical `value` is absent.
        """
        wanted: dict[str, set[str]] = {}
        for market in markets:
            wanted.setdefault(str(market["venue"]), set()).add(str(market["market"]))
        result = {"sampled": {}, "errors": {}}

        async def one(venue: str, names: set[str]):
            count = 0
            try:
                if venue == "hyperliquid":
                    dexes = {"xyz" if name.startswith("xyz:") else "" for name in names}
                    for dex in dexes:
                        body, received = await self._request(venue, "POST", HL_URL,
                                                            payload={"type": "metaAndAssetCtxs", "dex": dex})
                        metadata, contexts = body
                        if len(metadata["universe"]) != len(contexts):
                            raise ValueError("Hyperliquid context length mismatch")
                        for item, context in zip(metadata["universe"], contexts):
                            market = str(item["name"])
                            if market in names and context.get("oraclePx") is not None:
                                self.observe_reference(venue, market, received, context["oraclePx"], "oracle")
                                count += 1
                elif venue in LIGHTER_URLS:
                    body, received = await self._request(venue, "GET", LIGHTER_URLS[venue] + "/orderBookDetails")
                    for item in body.get("order_book_details", []):
                        market = str(item.get("market_id"))
                        if market in names and item.get("index_price") is not None:
                            self.observe_reference(venue, market, received, item["index_price"], "index")
                            count += 1
                elif venue == "aster":
                    body, received = await self._request(venue, "GET", ASTER_URL + "/premiumIndex")
                    for item in body if isinstance(body, list) else [body]:
                        market = str(item.get("symbol"))
                        if market in names and item.get("markPrice") is not None:
                            ts = _finite(item.get("time", received * 1000)) / 1000
                            self.observe_reference(venue, market, ts, item["markPrice"], "mark")
                            count += 1
                            if item.get("nextFundingTime") is not None:
                                self.observe_aster_schedule(market, ts,
                                                            _finite(item["nextFundingTime"]) / 1000)
                else:
                    raise ValueError(f"unsupported venue {venue}")
                result["sampled"][venue] = count
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                result["errors"][venue] = str(exc)

        await asyncio.gather(*(one(venue, names) for venue, names in wanted.items()))
        return result

    def _cached(self, key: tuple, requested_end: float):
        item = self._responses.get(key)
        if item is None:
            return None
        fetched, rows = item
        # Aster has no fixed hourly settlement. A response fetched before a
        # later open-position mark cannot prove that no event arrived between
        # the fetch and the mark, even if both fit the same aligned query.
        if key[0] == "aster" and fetched < requested_end:
            return None
        # Settlements can post late. Refresh recent windows; historical windows
        # are immutable for the lifetime of this paper process.
        if time.time() - fetched < (30 if key[-1] > time.time() - 7200 else 86400):
            self._responses.move_to_end(key)
            return rows
        del self._responses[key]
        return None

    def _cache(self, key: tuple, rows: list[dict]):
        self._responses[key] = (time.time(), rows)
        self._responses.move_to_end(key)
        while sum(max(1, len(item[1])) for item in self._responses.values()) > self.max_cache_events:
            self._responses.popitem(last=False)

    async def _history(self, venue: str, market: str, start: float, end: float) -> list[dict]:
        if venue == "aster":
            # Broad, aligned windows let many positions with nearby entry and
            # exit times share one response while the fetched-at check above
            # prevents reuse for a later as-of time.
            query_start = max(0, math.floor((start - ASTER_SETTLEMENT_UNCERTAINTY_SECONDS) / HOUR) * HOUR)
            query_end = math.ceil((end + ASTER_SETTLEMENT_UNCERTAINTY_SECONDS) / HOUR) * HOUR
        else:
            expected = _settlements(start, end)
            if not expected:
                return []
            # All legs crossing the same settlement set share a market query.
            # Hyperliquid timestamps can follow the nominal hour by milliseconds.
            query_start, query_end = expected[0] - 1, expected[-1] + 2
        key = (venue, market, int(query_start * 1000), int(query_end * 1000), query_end)
        cached = self._cached(key, end)
        if cached is not None:
            return cached
        if venue == "hyperliquid":
            body, _ = await self._request(venue, "POST", HL_URL,
                                          payload={"type": "fundingHistory", "coin": market,
                                                   "startTime": int(query_start * 1000) + 1,
                                                   "endTime": int(query_end * 1000)})
            if not isinstance(body, list):
                raise ValueError("Hyperliquid funding history shape")
            rows = body
        elif venue in LIGHTER_URLS:
            body, _ = await self._request(venue, "GET", LIGHTER_URLS[venue] + "/fundings",
                                          params={"market_id": int(market), "resolution": "1h",
                                                  "start_timestamp": int(query_start) + 1,
                                                  "end_timestamp": int(query_end), "count_back": 0})
            rows = body.get("fundings")
            if not isinstance(rows, list):
                raise ValueError("Lighter funding history shape")
        elif venue == "aster":
            rows = []
            cursor, last = int(query_start * 1000), int(query_end * 1000)
            for _ in range(20):
                body, _ = await self._request(venue, "GET", ASTER_URL + "/fundingRate",
                                              params={"symbol": market, "startTime": cursor,
                                                      "endTime": last, "limit": 1000})
                if not isinstance(body, list):
                    raise ValueError("Aster funding history shape")
                rows.extend(body)
                if len(body) < 1000:
                    break
                next_cursor = int(body[-1]["fundingTime"]) + 1
                if next_cursor <= cursor:
                    raise ValueError("Aster funding pagination did not advance")
                cursor = next_cursor
            else:
                raise ValueError("Aster funding history exceeds page cap")
        else:
            raise ValueError(f"unsupported venue {venue}")
        if len(rows) > self.max_cache_events:
            raise ValueError("funding history exceeds bounded event limit")
        self._cache(key, rows)
        return rows

    async def cashflows(self, position: dict) -> dict:
        """Return funding for closed legs, never substituting zero for unknown.

        `cashflow_usd` is None if any event or reference is missing. When
        `estimated` is true when the dollar conversion uses a bounded public
        price sample or the empirically inferred per-unit Lighter value. The
        settled rate history is always required.
        Stablecoin collateral is assumed at USD par for this paper calculation.
        """
        events: list[dict] = []
        missing: list[dict] = []
        estimated = False
        for leg in position.get("legs", []):
            if not isinstance(leg, dict):
                missing.append({"venue": None, "market": None, "reason": "leg is not an object"})
                continue
            try:
                venue, market, side = str(leg["venue"]), str(leg["market"]), str(leg["side"]).lower()
                qty = _finite(leg["quantity"], positive=True)
                start = _finite(leg["entry_time"])
                if leg.get("exit_time") is None:
                    raise ValueError("exit_time missing")
                end = _finite(leg["exit_time"])
                if end < start or side not in ("long", "short"):
                    raise ValueError("invalid interval or side")
                if venue not in (*LIGHTER_URLS, "hyperliquid", "aster"):
                    raise ValueError("unsupported venue")
            except (KeyError, TypeError, ValueError) as exc:
                missing.append({"venue": leg.get("venue"), "market": leg.get("market"), "reason": str(exc)})
                continue
            hourly_crossings = _settlements(start, end)
            expected = hourly_crossings if venue != "aster" else []
            if venue != "aster" and not expected:
                continue
            try:
                rows = await self._history(venue, market, start, end)
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError, TypeError, KeyError) as exc:
                missing.append({"venue": venue, "market": market, "reason": f"funding_history: {exc}"})
                continue
            by_time: dict[int, dict] = {}
            seen_aster_times: list[int] = []
            try:
                for row in rows:
                    if not isinstance(row, dict):
                        raise ValueError("funding row is not an object")
                    if venue == "hyperliquid":
                        if row.get("coin") is not None and str(row["coin"]) != market:
                            raise ValueError("Hyperliquid funding market mismatch")
                        raw = _finite(row["time"]) / 1000
                        timestamp = int(raw // HOUR) * HOUR
                        if abs(raw - timestamp) > 2:
                            raise ValueError("Hyperliquid non-hourly timestamp")
                    elif venue in LIGHTER_URLS:
                        timestamp = int(_finite(row["timestamp"]))
                    else:
                        if row.get("symbol") is not None and str(row["symbol"]) != market:
                            raise ValueError("Aster funding market mismatch")
                        timestamp = int(_finite(row["fundingTime"]) / 1000)
                        seen_aster_times.append(timestamp)
                    if venue == "aster" and (abs(timestamp - start) <= ASTER_SETTLEMENT_UNCERTAINTY_SECONDS
                                              or abs(timestamp - end) <= ASTER_SETTLEMENT_UNCERTAINTY_SECONDS):
                        missing.append({"venue": venue, "market": market, "time": timestamp,
                                        "reason": "settlement_sequence_uncertain_15s"})
                    if start < timestamp <= end:
                        if timestamp in by_time:
                            raise ValueError("duplicate settlement")
                        by_time[timestamp] = row
                if venue != "aster":
                    for timestamp in expected:
                        if timestamp not in by_time:
                            missing.append({"venue": venue, "market": market, "time": timestamp,
                                            "reason": "settlement_rate_missing"})
                else:
                    # Aster may charge up to 15 seconds from the nominal time,
                    # including events just outside the position's timestamp
                    # interval. An empty response near an hour is therefore
                    # incomplete unless a prior nextFundingTime proves no event.
                    candidate_hours = _settlements(start - ASTER_SETTLEMENT_UNCERTAINTY_SECONDS - 0.001,
                                                   end + ASTER_SETTLEMENT_UNCERTAINTY_SECONDS)
                    for hour in candidate_hours:
                        if (not any(abs(timestamp - hour) <= ASTER_SETTLEMENT_UNCERTAINTY_SECONDS
                                    for timestamp in seen_aster_times)
                                and not self._aster_hour_proven(market, hour, start, end)):
                            missing.append({"venue": venue, "market": market, "time": hour,
                                            "reason": "aster_empty_hour_schedule_unverified"})
            except (KeyError, TypeError, ValueError) as exc:
                missing.append({"venue": venue, "market": market, "reason": f"invalid_history: {exc}"})
                continue
            for timestamp, row in sorted(by_time.items()):
                try:
                    if venue == "hyperliquid":
                        rate = _finite(row["fundingRate"])
                    elif venue == "aster":
                        rate = _finite(row["fundingRate"])
                    else:
                        magnitude = _finite(row["rate"])
                        direction = str(row["direction"]).lower()
                        if magnitude < 0 or direction not in ("long", "short"):
                            raise ValueError("invalid Lighter rate/direction")
                        rate = magnitude / 100 * (1 if direction == "long" else -1)
                    # Positive signed rate means a long pays a short.
                    sign = -1 if side == "long" else 1
                    quality = "exact"
                    price = None
                    if venue in LIGHTER_URLS and row.get("value") is not None:
                        per_unit = _finite(row["value"])
                        if per_unit < 0:
                            raise ValueError("negative Lighter funding value")
                        if rate == 0 and per_unit != 0:
                            raise ValueError("nonzero Lighter value with zero rate")
                        cash = sign * (1 if rate >= 0 else -1) * qty * per_unit
                        source = "settled_lighter_value_inferred_per_unit"
                        quality = "estimated"
                        estimated = True
                    elif rate == 0:
                        cash = 0.0
                        source = "zero_settled_rate"
                    else:
                        ref = self._reference(venue, market, timestamp)
                        if ref is None:
                            missing.append({"venue": venue, "market": market, "time": timestamp,
                                            "reason": "settlement_reference_missing"})
                            continue
                        delta, sampled_at, price, kind = ref
                        quality = "estimated"
                        source = f"sampled_{kind}_price"
                        cash = sign * qty * price * rate
                        estimated = True
                    events.append({"venue": venue, "market": market, "side": side,
                                   "time": timestamp, "quantity": qty, "rate_fraction": rate,
                                   "reference_price": price, "cashflow_usd": cash,
                                   "quality": quality, "source": source,
                                   "reference_time": sampled_at if price is not None else None,
                                   "reference_skew_seconds": delta if price is not None else None})
                except (KeyError, TypeError, ValueError) as exc:
                    missing.append({"venue": venue, "market": market, "time": timestamp,
                                    "reason": f"invalid_settlement: {exc}"})
        complete = not missing
        return {"complete": complete,
                "cashflow_usd": sum(event["cashflow_usd"] for event in events) if complete else None,
                "estimated": estimated, "events": events, "missing": missing}

    def dump_state(self) -> dict:
        """JSON-safe bounded cache for monitor checkpoints."""
        return {"version": 1,
                "references": [{"venue": v, "market": m, "time": ts, "price": px, "kind": kind}
                               for (v, m, _), (ts, px, kind) in self._references.items()],
                "aster_schedules": [{"market": market, "hour": hour,
                                     "observed_at": observed_at, "next_funding_time": next_time}
                                    for (market, hour), (observed_at, next_time) in self._aster_schedules.items()],
                "responses": [{"venue": key[0], "market": key[1], "start_ms": key[2],
                               "end_ms": key[3], "end": key[4], "fetched": fetched, "rows": rows}
                              for key, (fetched, rows) in self._responses.items()]}

    def load_state(self, state: dict) -> None:
        if state.get("version") != 1:
            return
        for row in state.get("references", [])[-self.max_cache_events:]:
            try:
                self.observe_reference(row["venue"], row["market"], row["time"], row["price"], row.get("kind", "oracle"))
            except (KeyError, TypeError, ValueError):
                continue
        for row in state.get("aster_schedules", [])[-self.max_cache_events:]:
            try:
                key = (str(row["market"]), int(row["hour"]))
                self._aster_schedules[key] = (_finite(row["observed_at"]),
                                              _finite(row["next_funding_time"]))
            except (KeyError, TypeError, ValueError):
                continue
        for row in state.get("responses", []):
            try:
                key = (str(row["venue"]), str(row["market"]), int(row["start_ms"]),
                       int(row["end_ms"]), _finite(row["end"]))
                fetched = _finite(row["fetched"])
                rows = row["rows"]
                if isinstance(rows, list) and len(rows) <= self.max_cache_events:
                    self._responses[key] = (fetched, rows)
            except (KeyError, TypeError, ValueError):
                continue
        while sum(max(1, len(item[1])) for item in self._responses.values()) > self.max_cache_events:
            self._responses.popitem(last=False)
