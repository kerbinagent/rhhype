#!/usr/bin/env python3
"""Long-running, read-only asyncio spread monitor. See research/monitor.md."""
from __future__ import annotations

import argparse
import asyncio
import collections
from decimal import Decimal, ROUND_FLOOR
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
from pathlib import Path
import signal
import shutil
import sys
import sqlite3
import time

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
HL = "https://api.hyperliquid.xyz/info"
BASE = {"rh_lighter": "https://api.rh.lighter.xyz/api/v1",
        "lighter": "https://mainnet.zklighter.elliot.ai/api/v1",
        "aster": "https://fapi.asterdex.com/fapi/v3"}
# Only native and xyz perps are matched; no ETF/index, ADS/common-share,
# stock-token/share, or thousand-token substitutions are inferred.
ALIASES = {"GOLD": "XAU", "SILVER": "XAG", "PLATINUM": "XPT",
           "PALLADIUM": "XPD", "CL": "WTI", "SP500": "US500",
           "XYZ100": "US100", "JPY": "USDJPY", "EUR": "EURUSD",
           "GBP": "GBPUSD", "SKHX": "SKHYNIXUSD", "SMSN": "SAMSUNGUSD"}
# Published September 29, 2026. Group B overrides RWA classification where
# documentation lists a symbol in both; retain the higher fee conservatively.
ASTER_GROUP_B = set("1000NEXUSDT AEONUSDT ASTEROIDUSDT AVLUSDT BAYUSDT BASECATUSDT BLENDUSDT B3USDT CARDSUSDT CATEUSDT DELTAUSDT FONEUSDT MEMEUSDT MARSCOINUSDT NESUSDT OUSDT OKBUSDT PENGUINUSDT PUNDIAIUSDT RTXUSDT SKHYNIXUSDT".split())


def aster_fee(symbol, is_rwa, general=4.0, rwa=1.25, group_b=10.0):
    if symbol in ASTER_GROUP_B:
        return group_b, "crypto_group_b_or_conflicting_classification"
    if is_rwa:
        return rwa, "rwa"
    return general, "crypto_general"


LOG = logging.getLogger("monitor")


def utc(ts=None):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).isoformat()


def atomic_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n")
    os.replace(tmp, path)


def number(value):
    x = float(value)
    if not math.isfinite(x):
        raise ValueError("Non-finite number")
    return x


def common_step(a, b):
    """Exact intersection of two decimal quantity grids, including non-powers of ten."""
    a, b = Decimal(str(a)), Decimal(str(b))
    if a <= 0 or b <= 0:
        raise ValueError("Invalid lot step")
    scale = 10 ** max(0, -a.as_tuple().exponent, -b.as_tuple().exponent)
    return Decimal(math.lcm(int(a * scale), int(b * scale))) / scale


def parse_book(venue, body):
    if venue == "hyperliquid":
        bids, asks = body["levels"]
        extract = lambda x: (number(x["px"]), number(x["sz"]))
    elif venue in ("lighter", "rh_lighter"):
        if body.get("code") != 200:
            raise ValueError("Lighter response code != 200")
        bids, asks = body["bids"], body["asks"]
        extract = lambda x: (number(x["price"]), number(x["remaining_base_amount"]))
    else:
        bids, asks = body["bids"], body["asks"]
        extract = lambda x: (number(x[0]), number(x[1]))
    bids = sorted((extract(x) for x in bids), reverse=True)
    asks = sorted(extract(x) for x in asks)
    if any(p <= 0 or q < 0 for p, q in bids + asks):
        raise ValueError("Invalid book level")
    bids = [(p, q) for p, q in bids if q > 0]
    asks = [(p, q) for p, q in asks if q > 0]
    if not bids or not asks or bids[0][0] >= asks[0][0]:
        raise ValueError("Empty or crossed book")
    return bids, asks


def walk(book, quantity):
    remaining, total = quantity, 0.0
    for price, size in book:
        take = min(size, remaining)
        total += take * price
        remaining -= take
        if remaining <= quantity * 1e-12:
            return total
    return None


def affordable_quantity(asks, budget):
    quantity = 0.0
    for price, size in asks:
        take = min(size, budget / price)
        quantity += take
        budget -= take * price
        if budget <= 1e-10:
            return quantity
    return None


def evaluate(pair, hl, other, args, now=None):
    """Both directions, equal orderable base units, full depth, own-leg fees."""
    now = time.time() if now is None else now
    skew = abs(hl["received"] - other["received"])
    if skew > args.max_skew or any(now - b["received"] > args.max_age for b in (hl, other)):
        raise ValueError("receipt_stale_or_skew")
    for b in (hl, other):
        if b["engine_time"] is not None:
            age = now - b["engine_time"]
            if age > args.max_age or age < -2:
                raise ValueError("engine_stale_or_future")
    hb, ha = hl["levels"]
    ob, oa = other["levels"]
    hm, om = (hb[0][0] + ha[0][0]) / 2, (ob[0][0] + oa[0][0]) / 2
    if abs(om / hm - 1) > args.max_divergence_bps / 10000:
        raise ValueError("midpoint_divergence_quarantined")
    rows = []
    for buy, sell, bb, sb in ((pair["hl"], pair["other"], hl, other),
                              (pair["other"], pair["hl"], other, hl)):
        step = common_step(buy["step"], sell["step"])
        for target in args.notionals:
            affordable = affordable_quantity(bb["levels"][1], target)
            if affordable is None:
                continue
            qd = (Decimal(str(affordable)) / step).to_integral_value(rounding=ROUND_FLOOR) * step
            q = float(qd)
            if q <= 0 or any(q < m["min_qty"] or q > m.get("max_qty", math.inf) for m in (buy, sell)):
                continue
            cost, proceeds = walk(bb["levels"][1], q), walk(sb["levels"][0], q)
            if cost is None or proceeds is None:
                continue
            if cost > target + 1e-8 or cost < buy["min_notional"] or proceeds < sell["min_notional"]:
                continue
            fees = (cost * buy["fee_bps"] + proceeds * sell["fee_bps"]) / 10000
            exit_reserve = fees if args.reserve_exit_fees else 0.0
            extra = cost * args.extra_cost_bps / 10000 + args.fixed_cost_usd
            net = proceeds - cost - fees
            budget = net - exit_reserve - extra
            route = f'{pair["asset"]}|{buy["venue"]}:{buy["market"]}|{sell["venue"]}:{sell["market"]}'
            rows.append({"timestamp": max(hl["received"], other["received"]), "utc": utc(max(hl["received"], other["received"])),
                         "route": route, "asset": pair["asset"], "category": pair["category"],
                         "buy": f'{buy["venue"]}:{buy["market"]}', "sell": f'{sell["venue"]}:{sell["market"]}',
                         "target_notional_usd": target, "base_quantity": str(qd),
                         "buy_cost_usd": cost, "sell_proceeds_usd": proceeds,
                         "buy_vwap": cost / q, "sell_vwap": proceeds / q,
                         "buy_fee_bps": buy["fee_bps"], "sell_fee_bps": sell["fee_bps"],
                         "entry_fees_usd": fees, "net_entry_usd": net, "net_entry_bps": net / cost * 10000,
                         "estimated_exit_fee_reserve_usd": exit_reserve, "additional_cost_reserve_usd": extra,
                         "budgeted_edge_usd": budget, "budgeted_edge_bps": budget / cost * 10000,
                         "buy_collateral": buy["collateral"], "sell_collateral": sell["collateral"],
                         "receipt_skew_ms": skew * 1000,
                         "hl_engine_age_ms": (now - hl["engine_time"]) * 1000 if hl["engine_time"] else None,
                         "other_engine_age_ms": (now - other["engine_time"]) * 1000 if other["engine_time"] else None,
                         "other_engine_freshness_known": other["engine_time"] is not None,
                         "metadata_utc": pair["metadata_utc"], "stablecoin_parity_assumed": True})
    return rows


class Store:
    """Bounded SQLite window, plus at most ten unique-route all-time records."""
    def __init__(self, path, config, window_seconds, max_rows, rank_by, episode_gap=600):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA journal_size_limit=4194304")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY, ts REAL, route TEXT, score REAL, payload TEXT);
            CREATE INDEX IF NOT EXISTS obs_time ON observations(ts);
            CREATE TABLE IF NOT EXISTS records (route TEXT PRIMARY KEY, score REAL, payload TEXT);
            CREATE TABLE IF NOT EXISTS signals (route TEXT PRIMARY KEY, positive INTEGER, last_ts REAL);
        """)
        signature = json.dumps(config, sort_keys=True)
        previous = self.get("config")
        if previous is not None and previous != config:
            self.db.close()
            raise ValueError("This output directory uses different ranking/fee/market settings. Choose a new --out directory.")
        self.set("config", json.loads(signature))
        self.window, self.max_rows, self.rank_by = window_seconds, max_rows, rank_by
        self.episode_gap = episode_gap
        self.totals = self.get("totals") or {"observations": 0, "positive_observations": 0, "cap_evictions": 0}
        for key in ("paper_1000_episodes", "paper_1000_net_entry_sum_usd", "paper_1000_budgeted_sum_usd", "paper_1000_positive_samples", "paper_1000_positive_sample_sum_usd"):
            self.totals.setdefault(key, 0)
        self.count = self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        self.prune(time.time())

    def get(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def add(self, rows):
        score_key = "budgeted_edge_" + self.rank_by
        for r in rows:
            score = r[score_key]
            payload = json.dumps(r, allow_nan=False, separators=(",", ":"))
            self.db.execute("INSERT INTO observations(ts,route,score,payload) VALUES (?,?,?,?)",
                            (r["timestamp"], r["route"], score, payload))
            self.count += 1
            self.totals["observations"] += 1
            self.totals["positive_observations"] += int(score > 0)
            if r["target_notional_usd"] == 1000:
                positive = r["budgeted_edge_usd"] > 0
                prior = self.db.execute("SELECT positive,last_ts FROM signals WHERE route=?", (r["route"],)).fetchone()
                if positive:
                    self.totals["paper_1000_positive_samples"] += 1
                    self.totals["paper_1000_positive_sample_sum_usd"] += r["budgeted_edge_usd"]
                    if not prior or not prior[0] or r["timestamp"] - prior[1] > self.episode_gap:
                        self.totals["paper_1000_episodes"] += 1
                        self.totals["paper_1000_net_entry_sum_usd"] += r["net_entry_usd"]
                        self.totals["paper_1000_budgeted_sum_usd"] += r["budgeted_edge_usd"]
                self.db.execute("INSERT OR REPLACE INTO signals VALUES (?,?,?)", (r["route"], int(positive), r["timestamp"]))
            if score > 0:
                self.db.execute("""INSERT INTO records VALUES (?,?,?) ON CONFLICT(route) DO UPDATE
                    SET score=excluded.score,payload=excluded.payload WHERE excluded.score>records.score""",
                    (r["route"], score, payload))
                self.db.execute("DELETE FROM records WHERE route NOT IN (SELECT route FROM records ORDER BY score DESC,route LIMIT 10)")
        self.prune(time.time())

    def prune(self, now):
        self.db.execute("DELETE FROM signals WHERE last_ts<?", (now - self.episode_gap,))
        self.db.execute("DELETE FROM signals WHERE route NOT IN (SELECT route FROM signals ORDER BY last_ts DESC LIMIT 10000)")
        self.db.execute("DELETE FROM observations WHERE ts<?", (now - self.window,))
        self.count = self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        excess = max(0, self.count - self.max_rows)
        if excess:
            self.db.execute("DELETE FROM observations WHERE id IN (SELECT id FROM observations ORDER BY ts,id LIMIT ?)", (excess,))
            self.count -= excess
            self.totals["cap_evictions"] += excess

    def snapshot(self, now):
        self.prune(now)
        rows = self.db.execute("""
            WITH ranked AS (
                SELECT route,payload,score,ROW_NUMBER() OVER (PARTITION BY route ORDER BY score DESC,ts DESC,id DESC) AS n
                FROM observations WHERE score>0
            ), tally AS (
                SELECT route,COUNT(*) AS samples,SUM(score>0) AS positive,MAX(ts) AS last_ts
                FROM observations GROUP BY route
            )
            SELECT r.payload,t.samples,t.positive,t.last_ts FROM ranked r JOIN tally t ON r.route=t.route
            WHERE r.n=1 ORDER BY r.score DESC,r.route LIMIT 10
        """).fetchall()
        top = [json.loads(r[0]) | {"window_observations": r[1], "window_positive_observations": r[2],
                                 "last_observed_utc": utc(r[3])} for r in rows]
        records = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM records ORDER BY score DESC,route")]
        oldest = self.db.execute("SELECT MIN(ts) FROM observations").fetchone()[0]
        self.set("totals", self.totals)
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return {"window_top10": top, "all_time_top10": records, "totals": self.totals.copy(),
                "retained_observations": self.count, "oldest_retained_utc": utc(oldest) if oldest else None,
                "configured_window_hours": self.window / 3600, "max_rows": self.max_rows}

    def close(self):
        self.set("totals", self.totals)
        self.db.commit()
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.close()


class Gate:
    """Paced host budget with shared exponential cooldown; no burst catch-up."""
    def __init__(self, rpm):
        self.spacing = 60 / rpm
        self.next = 0.0
        self.blocked_until = 0.0
        self.failures = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            while True:
                delay = max(self.next, self.blocked_until) - time.monotonic()
                if delay <= 0:
                    self.next = time.monotonic() + self.spacing
                    return
                await asyncio.sleep(delay)

    def failure(self, retry_after=0):
        self.failures = min(self.failures + 1, 8)
        delay = max(retry_after, min(120, 2 ** self.failures))
        self.blocked_until = max(self.blocked_until, time.monotonic() + delay)


class Client:
    def __init__(self, session, args, stats):
        self.session, self.stats = session, stats
        self.gates = {v: Gate(rpm) for v, rpm in {"hyperliquid": 180, "rh_lighter": 45,
                                                 "lighter": 45, "aster": 60}.items()}

    async def request(self, venue, url, payload=None, params=None):
        gate = self.gates[venue]
        await gate.acquire()
        try:
            async with self.session.request("POST" if payload is not None else "GET", url,
                                            json=payload, params=params) as response:
                if response.status != 200:
                    retry_after = response.headers.get("Retry-After", "0")
                    try:
                        retry_after = float(retry_after)
                    except ValueError:
                        retry_after = 0
                    gate.failure(max(30 if response.status in (405, 429) else 0, retry_after))
                    self.stats[f"{venue}_http_{response.status}"] += 1
                    raise RuntimeError(f"{venue} HTTP {response.status}")
                body = await response.json()
            gate.failures = 0
            self.stats[f"{venue}_requests_ok"] += 1
            return body, time.time()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            gate.failure()
            self.stats[f"{venue}_transport_errors"] += 1
            raise

    async def book(self, m):
        v = m["venue"]
        if v == "hyperliquid":
            body, received = await self.request(v, HL, {"type": "l2Book", "coin": m["market"]})
            if body.get("coin") != m["market"]:
                raise ValueError("HL book identity mismatch")
            engine = number(body["time"]) / 1000
        elif v == "aster":
            body, received = await self.request(v, BASE[v] + "/depth", params={"symbol": m["market"], "limit": 100})
            # E = response event time where returned; T = last book transaction time.
            engine = number(body.get("E") or body["T"]) / 1000 if body.get("E") or body.get("T") else None
        else:
            body, received = await self.request(v, BASE[v] + "/orderBookOrders", params={"market_id": m["market"], "limit": 100})
            engine = None  # This endpoint does not expose an engine timestamp.
        return {"levels": parse_book(v, body), "received": received, "engine_time": engine}


async def discover(client, args):
    """Fresh metadata; failure never silently substitutes the old research census."""
    hl = []
    metadata_utc = utc()
    for dex in ("", "xyz"):
        body, _ = await client.request("hyperliquid", HL, {"type": "metaAndAssetCtxs", "dex": dex})
        meta, ctxs = body
        if len(meta["universe"]) != len(ctxs):
            raise ValueError("HL metadata/context lengths differ")
        # The verified native and xyz domains use USDC token index 0.
        if meta.get("collateralToken") != 0:
            raise ValueError("HL collateral changed; mapping needs review")
        for a, c in zip(meta["universe"], ctxs):
            if a.get("isDelisted") or number(c["dayNtlVlm"]) < args.min_volume:
                continue
            symbol = a["name"].split(":")[-1]
            asset = ALIASES.get(symbol, symbol) if dex else symbol
            if args.assets and asset not in args.assets:
                continue
            scale = number(a.get("deployerFeeScale", 1))
            fee = args.hl_fee_bps
            if dex:
                fee *= (scale + 1 if scale < 1 else 2 * scale)
                fee *= 0.1 if a.get("growthMode") == "enabled" else 1
            hl.append({"venue": "hyperliquid", "market": a["name"], "asset": asset,
                       "category": "crypto" if not dex else "RWA/xyz", "fee_bps": fee,
                       "step": str(Decimal(10) ** -int(a["szDecimals"])), "min_qty": 0.0,
                       "min_notional": 10.0, "collateral": "USDC", "volume": number(c["dayNtlVlm"])})
    others, failed = [], []
    for venue in args.venues:
        try:
            if venue == "aster":
                exchange, _ = await client.request(venue, BASE[venue] + "/exchangeInfo")
                tickers, _ = await client.request(venue, BASE[venue] + "/ticker/24hr")
                volumes = {r["symbol"]: number(r["quoteVolume"]) for r in tickers}
                for a in exchange["symbols"]:
                    if a["status"] != "TRADING" or a["contractType"] != "PERPETUAL" or a["quoteAsset"] != "USDT":
                        continue
                    volume = volumes.get(a["symbol"], 0)
                    if volume < args.min_volume:
                        continue
                    filters = {f["filterType"]: f for f in a["filters"]}
                    lot = filters["LOT_SIZE"]  # Price-taking limit/IOC quantities.
                    fee, fee_class = aster_fee(a["symbol"], a.get("symbolType")==1, args.aster_fee_bps, args.aster_rwa_fee_bps, args.aster_group_b_fee_bps)
                    others.append({"venue": venue, "market": a["symbol"], "asset": a["baseAsset"],
                                   "fee_bps": fee, "fee_class": fee_class, "step": lot["stepSize"],
                                   "min_qty": number(lot["minQty"]), "max_qty": number(lot["maxQty"]),
                                   "min_notional": number(filters.get("MIN_NOTIONAL", {}).get("notional", 0)),
                                   "collateral": "USDT", "volume": volume})
            else:
                body, _ = await client.request(venue, BASE[venue] + "/orderBookDetails")
                if body.get("code") != 200:
                    raise ValueError("Lighter discovery response code != 200")
                fee = {"standard": 0, "plus": 0.5, "premium": 3.5 if venue == "rh_lighter" else 2.8}[args.lighter_tier]
                for a in body["order_book_details"]:
                    volume = number(a["daily_quote_token_volume"])
                    if a["status"] != "active" or volume < args.min_volume or a.get("market_type", "perp") != "perp":
                        continue
                    # Do not guess unit conversions for future scaled contracts.
                    if number(a.get("multiplier", 1)) != 1:
                        continue
                    others.append({"venue": venue, "market": a["market_id"], "asset": a["symbol"],
                                   "fee_bps": max(fee, number(a.get("taker_fee", 0)) * 100), "step": str(Decimal(10) ** -int(a["supported_size_decimals"])),
                                   "min_qty": number(a["min_base_amount"]), "min_notional": number(a.get("min_quote_amount", 0)),
                                   "collateral": "USDG" if venue == "rh_lighter" else "USDC", "volume": volume})
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, RuntimeError, TypeError, AttributeError, IndexError) as e:
            failed.append(venue)
            LOG.warning("Discovery disabled %s for this refresh: %s", venue, e)
    pairs = [{"asset": h["asset"], "category": h["category"], "hl": h, "other": o, "metadata_utc": metadata_utc, "metadata_timestamp": time.time()}
             for h in hl for o in others if h["asset"] == o["asset"]]
    pairs.sort(key=lambda p: (-min(p["hl"]["volume"], p["other"]["volume"]), p["asset"], p["other"]["venue"]))
    return pairs, failed


def render(snapshot):
    lines = ["# Live spread monitor", "", f"Updated: {snapshot['updated_utc']} · status: **{snapshot['status']}**", "",
             "Budgeted opening edges, not realized roundtrip P&L. Stablecoins assumed at parity.",
             "Costs: opening taker fees + configured closing-fee reserve + additional buffer. Funding and actual exit spreads are unmeasured.", "",
             f"Pairs: {snapshot['pairs']} · retained observations: {snapshot['retained_observations']:,} · rank: {snapshot['rank_by']}", ""]
    for key, title in (("window_top10", "Sliding-window top 10"), ("all_time_top10", "Best-ever top 10 (persists across restarts)")):
        lines += [f"## {title}", "", "| Asset | Buy → short | Size | Budgeted $ | Budgeted bp | Peak UTC |", "|---|---|---:|---:|---:|---|"]
        for r in snapshot[key]:
            lines.append(f"| {r['asset']} | {r['buy']} → {r['sell']} | ${r['target_notional_usd']:,.0f} | {r['budgeted_edge_usd']:.2f} | {r['budgeted_edge_bps']:.2f} | {r['utc']} |")
        if not snapshot[key]:
            lines += ["", "No positive observations after the configured cost budget."]
        lines += [""]
    lines += ["One best size/moment per directed pair. Peaks are historical observations, not current quotes.",
              f"$1,000 signal episodes: {snapshot['totals']['paper_1000_episodes']} · entry-edge sum after opening fees: ${snapshot['totals']['paper_1000_net_entry_sum_usd']:.2f} · entry-edge sum after configured reserves: ${snapshot['totals']['paper_1000_budgeted_sum_usd']:.2f}",
              "Window tallies, all-time counters, request errors and freshness diagnostics are in leaderboard.json.", ""]
    return "\n".join(lines)


def tui_lines(snapshot, output_dir, columns, rows):
    """Fit one terminal screen, including tiny windows; never rely on line wrapping."""
    width, height = max(1, columns - 1), max(1, rows - 1)
    if snapshot is None:
        lines = ["RHHYPE | Ctrl-C to exit", "Waiting for leaderboard.json ...", str(output_dir)]
    else:
        totals = snapshot["totals"]
        age = max(0, time.time() - snapshot.get("updated_timestamp", time.time()))
        records = snapshot["all_time_top10"]
        lines = [f"RHHYPE | {snapshot['status'].upper()} | {snapshot['pairs']} pairs | update {age:.0f}s | Ctrl-C exits",
                 f"$1k signals {totals['paper_1000_episodes']:,} | entry-edge sum ${totals['paper_1000_net_entry_sum_usd']:,.2f} | reserved ${totals['paper_1000_budgeted_sum_usd']:,.2f}",
                 "Closed-trade profit: NOT SIMULATED. Entry-edge sums are not trading P&L."]
        if width >= 75:
            lines.append(f"{'#':>2} {'Asset':<8} {'Buy -> short':<24} {'Size':>7} {'Net $*':>8} {'bp*':>7} {'Peak UTC':>12}")
        elif width >= 48:
            lines.append(f"{'#':>2} {'Asset':<10} {'Buy -> short':<20} {'Net $*':>9}")
        else:
            lines.append(f"{'#':>2} {'Asset':<10} {'Net $*':>9}")
        available = max(0, height - len(lines) - 2)
        for i, r in enumerate(records[:available], 1):
            route = r['buy'] + ' > ' + r['sell']
            for full, short in (('hyperliquid:xyz:', 'HL:'), ('hyperliquid:', 'HL:'), ('rh_lighter:', 'RH:'), ('lighter:', 'LC:'), ('aster:', 'AS:')):
                route = route.replace(full, short)
            if width >= 75:
                lines.append(f"{i:>2} {r['asset']:<8.8} {route:<24.24} {r['target_notional_usd']:>7,.0f} {r['budgeted_edge_usd']:>8.2f} {r['budgeted_edge_bps']:>7.2f} {r['utc'][5:16]:>12}")
            elif width >= 48:
                lines.append(f"{i:>2} {r['asset']:<10.10} {route:<20.20} {r['budgeted_edge_usd']:>9.2f}")
            else:
                lines.append(f"{i:>2} {r['asset']:<10.10} {r['budgeted_edge_usd']:>9.2f}")
        if not records and available:
            lines.append("No positive edges after costs yet.")
        if len(records) > available:
            lines.append(f"Showing {available}/{len(records)}. Enlarge terminal for all 10.")
        else:
            lines.append("* After fees + configured reserves. HL/RH/LC/AS = venues.")
        lines.append(f"Window {snapshot['retained_observations']:,}/{snapshot['max_rows']:,} | sampled {snapshot['process_stats'].get('paired_samples', 0):,} | rejected {snapshot['process_stats'].get('sample_rejections', 0):,}")
        if height >= 20:
            lines += ["Persistent positive quotes count once until nonpositive or data gap.",
                      "HL Hyperliquid | RH Robinhood Lighter | LC Core | AS Aster",
                      f"Unavailable: {','.join(snapshot['failed_discovery_venues']) or 'none'} | rank: {snapshot['rank_by']}",
                      f"Files: {output_dir}"]
    # Strip control characters supplied by external metadata before rendering.
    return ["".join(c if c.isprintable() else ' ' for c in line)[:width] for line in lines[:height]]


def draw_tui(snapshot, output_dir):
    size = shutil.get_terminal_size((80, 24))
    lines = tui_lines(snapshot, output_dir, size.columns, size.lines)
    sys.stdout.write("\033[H\033[2J" + "\n".join(lines))
    sys.stdout.flush()


def watch(args):
    if not sys.stdout.isatty():
        raise SystemExit("--watch needs a terminal; read leaderboard.json for non-interactive output")
    stopped = False
    def stop_view(signum, frame):
        nonlocal stopped
        stopped = True
    previous = {sig: signal.signal(sig, stop_view) for sig in (signal.SIGINT, signal.SIGTERM)}
    sys.stdout.write("\033[?1049h\033[?25l")
    try:
        while not stopped:
            try:
                snapshot = json.loads((args.out / "leaderboard.json").read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                snapshot = None
            draw_tui(snapshot, args.out)
            time.sleep(.5)
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


async def run(args, store):
    stats = collections.Counter()
    state = {"pairs": [], "last_metadata": 0.0, "failed_discovery_venues": [], "status": "starting", "cycles": {}}
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    latest_snapshot = None
    timeout = aiohttp.ClientTimeout(total=15)

    def publish():
        nonlocal latest_snapshot
        snap = store.snapshot(time.time()) | {"updated_utc": utc(), "updated_timestamp": time.time(), "status": state["status"],
            "rank_by": args.rank_by, "pairs": len(state["pairs"]), "cycles": state["cycles"],
            "metadata_age_seconds": time.time() - state["last_metadata"] if state["last_metadata"] else None,
            "failed_discovery_venues": state["failed_discovery_venues"], "process_stats": dict(stats),
            "cost_settings": {k: getattr(args, k) for k in ("lighter_tier", "hl_fee_bps", "aster_fee_bps", "aster_rwa_fee_bps", "aster_group_b_fee_bps", "reserve_exit_fees", "extra_cost_bps", "fixed_cost_usd")}}
        atomic_json(args.out / "leaderboard.json", snap)
        tmp = args.out / "leaderboard.md.tmp"
        tmp.write_text(render(snap))
        os.replace(tmp, args.out / "leaderboard.md")
        latest_snapshot = snap

    async with aiohttp.ClientSession(timeout=timeout, connector=aiohttp.TCPConnector(limit=32),
                                     headers={"User-Agent": "rhhype-monitor/1.0"}) as session:
        client = Client(session, args, stats)

        async def refresh():
            while True:
                try:
                    pairs, failed = await discover(client, args)
                    state.update(pairs=pairs, last_metadata=time.time(), failed_discovery_venues=failed,
                                 status="running" if pairs else "no_matching_markets")
                    atomic_json(args.out / "markets.json", {"updated_utc": utc(), "pairs": pairs, "failed_venues": failed})
                    LOG.info("Metadata refreshed: %d directed venue comparisons, %d assets; unavailable=%s", len(pairs), len({p['asset'] for p in pairs}), failed)
                    delay = min(args.refresh_seconds, 60) if failed or not pairs else args.refresh_seconds
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, RuntimeError, TypeError, AttributeError, IndexError) as e:
                    stats["discovery_failures"] += 1
                    LOG.warning("Metadata refresh failed: %s", e)
                    delay = 30
                await asyncio.sleep(delay)

        async def sample(pair):
            try:
                # Query comparator first, then immediately obtain its HL hedge.
                other = await client.book(pair["other"])
                hl = await client.book(pair["hl"])
                rows = evaluate(pair, hl, other, args)
                stats["paired_samples"] += 1
                if not rows:
                    stats["depth_or_lot_or_minimum_rejections"] += 1
                store.add(rows)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, RuntimeError, TypeError, AttributeError, IndexError) as e:
                stats["sample_rejections"] += 1
                if isinstance(e, ValueError):
                    stats[str(e)[:80]] += 1
                LOG.debug("Rejected %s / %s: %s", pair["asset"], pair["other"]["venue"], e)

        async def venue_loop(venue):
            while True:
                started = time.monotonic()
                if not state["last_metadata"] or time.time() - state["last_metadata"] > args.max_metadata_age:
                    await asyncio.sleep(1)
                    continue
                pairs = [p for p in state["pairs"] if p["other"]["venue"] == venue]
                queue = asyncio.Queue()
                for p in pairs:
                    queue.put_nowait(p)

                async def worker():
                    while not queue.empty():
                        p = queue.get_nowait()
                        if time.time() - p["metadata_timestamp"] <= args.max_metadata_age:
                            await sample(p)
                await asyncio.gather(*(worker() for _ in range(args.workers)))
                state["cycles"][venue] = state["cycles"].get(venue, 0) + 1
                await asyncio.sleep(max(1, args.interval - (time.monotonic() - started)))

        async def reporter():
            while True:
                if state["last_metadata"] and time.time() - state["last_metadata"] > args.max_metadata_age:
                    state["status"] = "paused_stale_metadata"
                publish()
                LOG.info("status=%s pairs=%d retained=%d sampled=%d rejected=%d", state["status"], len(state["pairs"]), store.count, stats["paired_samples"], stats["sample_rejections"])
                await asyncio.sleep(args.report_seconds)

        async def tui_loop():
            while True:
                draw_tui(latest_snapshot, args.out)
                await asyncio.sleep(.5)

        tasks = [asyncio.create_task(refresh()), asyncio.create_task(reporter())]
        if args.tui:
            tasks.append(asyncio.create_task(tui_loop()))
        tasks += [asyncio.create_task(venue_loop(v)) for v in args.venues]
        stopper = asyncio.create_task(stop.wait())
        timer = asyncio.create_task(asyncio.sleep(args.duration)) if args.duration else None
        try:
            # Any unexpected background failure terminates visibly, not a silent dead worker.
            await asyncio.wait(tasks + [stopper] + ([timer] if timer else []), return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task.done():
                    task.result()
        finally:
            for task in tasks + [stopper] + ([timer] if timer else []):
                task.cancel()
            await asyncio.gather(*tasks, stopper, *([timer] if timer else []), return_exceptions=True)
            state["status"] = "stopped"
            publish()
            LOG.info("Stopped; leaderboard and rolling state saved")


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=ROOT / "data/monitor")
    p.add_argument("--venues", nargs="+", choices=tuple(BASE), default=list(BASE))
    p.add_argument("--assets", nargs="+", help="Optional canonical symbols, e.g. BTC ETH NVDA XAG")
    p.add_argument("--notionals", nargs="+", type=float, default=[1000])
    p.add_argument("--min-volume", type=float, default=1000000, help="Minimum current 24h quote volume on each venue")
    p.add_argument("--window-hours", type=float, default=24)
    p.add_argument("--max-rows", type=int, default=100000, help="Hard retained observation cap; oldest rows discarded")
    p.add_argument("--rank-by", choices=("usd", "bps"), default="usd")
    p.add_argument("--lighter-tier", choices=("standard", "plus", "premium"), default="standard")
    p.add_argument("--hl-fee-bps", type=float, default=4.5, help="Native taker fee; live HIP-3 multiplier applied")
    p.add_argument("--aster-fee-bps", type=float, default=4, help="Aster general crypto taker fee")
    p.add_argument("--aster-rwa-fee-bps", type=float, default=1.25)
    p.add_argument("--aster-group-b-fee-bps", type=float, default=10)
    p.add_argument("--reserve-exit-fees", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--extra-cost-bps", type=float, default=5, help="Additional conversion/impact/financing buffer, charged once")
    p.add_argument("--fixed-cost-usd", type=float, default=0)
    p.add_argument("--interval", type=float, default=60, help="Minimum cycle time; rate limits can extend it")
    p.add_argument("--workers", type=int, default=3, help="Concurrent pair jobs per comparator venue")
    p.add_argument("--report-seconds", type=float, default=30)
    p.add_argument("--refresh-seconds", type=float, default=3600)
    p.add_argument("--max-metadata-age", type=float, default=7200)
    p.add_argument("--max-skew", type=float, default=5)
    p.add_argument("--max-age", type=float, default=5)
    p.add_argument("--max-divergence-bps", type=float, default=500)
    p.add_argument("--duration", type=float, default=0, help="Stop after seconds; 0 runs until SIGINT/SIGTERM")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--episode-gap", type=float, default=600, help="Seconds without a valid $1k observation before a fresh episode")
    p.add_argument("--tui", action=argparse.BooleanOptionalAction, default=sys.stdout.isatty(), help="Simple terminal display (automatic on a terminal)")
    p.add_argument("--watch", action="store_true", help="Read-only live TUI for an existing background run")
    args = p.parse_args(argv)
    for name in ("window_hours", "interval", "report_seconds", "refresh_seconds", "max_metadata_age", "max_skew", "max_age", "max_divergence_bps", "episode_gap"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            p.error(f"--{name.replace('_', '-')} must be finite and positive")
    for name in ("min_volume", "hl_fee_bps", "aster_fee_bps", "aster_rwa_fee_bps", "aster_group_b_fee_bps", "extra_cost_bps", "fixed_cost_usd", "duration"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) < 0:
            p.error(f"--{name.replace('_', '-')} must be finite and nonnegative")
    if args.max_rows < 10 or not 1 <= args.workers <= 8 or any(not math.isfinite(n) or n < 10 for n in args.notionals):
        p.error("Require max-rows >=10, workers 1–8, notionals finite and >=$10")
    if args.refresh_seconds >= args.max_metadata_age:
        p.error("refresh-seconds must be smaller than max-metadata-age")
    args.venues = sorted(set(args.venues))
    args.assets = sorted(set(args.assets)) if args.assets else None
    args.notionals = sorted(set(args.notionals) | {1000.0})
    if args.tui and not sys.stdout.isatty():
        p.error("--tui requires a terminal; use --no-tui for background execution")
    return args


def main():
    args = arguments()
    if args.watch:
        watch(args)
        return
    args.out.mkdir(parents=True, exist_ok=True)
    # Linux/WSL advisory lock; crash releases it automatically. PID is informational.
    with (args.out / "monitor.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another monitor already owns this --out directory")
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()) + "\n")
        lock.flush()
        handler = RotatingFileHandler(args.out / "monitor.log", maxBytes=2_000_000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(handler)
        if os.isatty(2) and not args.tui:
            LOG.addHandler(logging.StreamHandler())
        LOG.setLevel(logging.DEBUG if args.verbose else logging.INFO)
        config = {k: getattr(args, k) for k in ("venues", "assets", "notionals", "min_volume", "rank_by", "lighter_tier", "hl_fee_bps", "aster_fee_bps", "aster_rwa_fee_bps", "aster_group_b_fee_bps", "reserve_exit_fees", "extra_cost_bps", "fixed_cost_usd", "max_skew", "max_age", "max_divergence_bps", "episode_gap")}
        config["model_version"] = 3
        store = Store(args.out / "window.sqlite3", config, args.window_hours * 3600, args.max_rows, args.rank_by, args.episode_gap)
        atomic_json(args.out / "config.json", config | {"window_hours": args.window_hours, "max_rows": args.max_rows})
        try:
            if args.tui:
                sys.stdout.write("\033[?1049h\033[?25l")
            asyncio.run(run(args, store))
        except Exception:
            LOG.exception("Monitor failed")
            raise
        finally:
            try:
                store.close()
            finally:
                if args.tui:
                    sys.stdout.write("\033[?25h\033[?1049l")
                    sys.stdout.flush()


if __name__ == "__main__":
    main()
