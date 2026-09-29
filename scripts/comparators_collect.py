#!/usr/bin/env python3
"""Collect read-only public comparator DEX data for the Hyperliquid survey.

Usage: python scripts/comparators_collect.py [--out data/raw/comparators]
No API keys, signing, orders, or external Python packages are required.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import time
import urllib.error
import urllib.parse
import urllib.request


LIGHTER = "https://mainnet.zklighter.elliot.ai/api/v1"
ASTER = "https://fapi.asterdex.com/fapi/v3"
DYDX = "https://indexer.dydx.trade/v4"
GMX = "https://arbitrum.gmxapi.io/v1"

# These are research candidates, not an assertion of liquidity or contract parity.
CANDIDATES = (
    "BTC", "ETH", "SOL", "HYPE", "BNB", "XRP", "DOGE", "SUI", "ZEC",
    "XAU", "XAG", "SILVER", "BRENTOIL", "WTIOIL", "EURUSD", "GBPUSD", "USDJPY", "SPY", "QQQ",
    "NVDA", "AAPL", "TSLA", "GOOGL", "AMZN", "META",
)
HISTORY = ("BTC", "ETH", "SOL", "HYPE", "ZEC", "XAU", "XAG", "BRENTOIL", "EURUSD", "SPY", "NVDA")
LIVE_CANDIDATES = ("BTC", "ETH", "SOL", "HYPE", "ZEC", "NVDA", "TSLA", "XAU", "XAG", "BRENTOIL", "WTIOIL", "EUR")


def get(url: str, params: dict | None = None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "rhhype-public-research/0.1"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def write_json(path: pathlib.Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def task(label, url, params=None):
    try:
        return label, {"url": url + ("?" + urllib.parse.urlencode(params) if params else ""), "data": get(url, params)}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return label, {"url": url, "error": f"{type(exc).__name__}: {exc}"}


def live_sample(spec):
    venue, base, symbol, url, params = spec
    started_ms = int(time.time() * 1000)
    try:
        body = get(url, params)
        error = None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        body = None
        error = f"{type(exc).__name__}: {exc}"
    received_ms = int(time.time() * 1000)
    venue_time_ms = body.get("T") if venue == "aster" and isinstance(body, dict) else None
    return venue, base, {"venue": venue, "market": symbol, "asset": base,
                         "request_start_ms": started_ms, "received_ms": received_ms,
                         "venue_time_ms": venue_time_ms, "body": body, "error": error}


def run_live(args):
    latest = sorted(p for p in args.out.iterdir() if (p / "manifest.json").exists())[-1]
    coverage = {r["base"]: r for r in json.loads((latest / "coverage.json").read_text())}
    aster = json.loads((latest / "aster/markets.json").read_text())["symbols"]
    aster_names = {r["symbol"] for r in aster if r.get("status") == "TRADING"}
    dydx = json.loads((latest / "dydx/markets.json").read_text())["markets"]
    specs = []
    for base in LIVE_CANDIDATES:
        a_symbol = coverage.get(base, {}).get("aster") or next(
            (x for x in (base + "USDT", base + "USD1") if x in aster_names), None)
        d_symbol = coverage.get(base, {}).get("dydx") or (base + "-USD" if base + "-USD" in dydx else None)
        if a_symbol:
            specs.append(("aster", base, a_symbol, ASTER + "/depth", {"symbol": a_symbol, "limit": 500}))
        if d_symbol:
            specs.append(("dydx", base, d_symbol, DYDX + "/orderbooks/perpetualMarket/" + d_symbol, None))
    run_dir = args.out / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_live")
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"source_inventory": str(latest), "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "rounds_requested": args.live_rounds, "interval_seconds": args.live_interval,
                "markets": [{"venue": v, "asset": b, "market": s, "url": u} for v, b, s, u, _ in specs],
                "rounds_completed": 0}
    write_json(run_dir / "manifest.json", manifest)
    epoch = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for round_no in range(args.live_rounds):
            wait = epoch + round_no * args.live_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            for venue, base, row in pool.map(live_sample, specs):
                row["round"] = round_no
                output = run_dir / venue / (base + ".jsonl")
                output.parent.mkdir(parents=True, exist_ok=True)
                with output.open("a") as fh:
                    fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            manifest["rounds_completed"] = round_no + 1
            manifest["last_round_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            write_json(run_dir / "manifest.json", manifest)
            print("LIVE", round_no + 1, "/", args.live_rounds, flush=True)
    manifest["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_json(run_dir / "manifest.json", manifest)
    print("SAVED", run_dir, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/raw/comparators"))
    parser.add_argument("--live-rounds", type=int, default=0, help="Repeat Aster/dYdX orderbook snapshots")
    parser.add_argument("--live-interval", type=float, default=30.0)
    args = parser.parse_args()
    if args.live_rounds:
        run_live(args)
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.out / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    started = int(time.time())
    manifest = {"collected_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "endpoints": {}, "errors": {}}

    initial = [
        ("lighter/markets", LIGHTER + "/orderBookDetails", None),
        ("lighter/funding_now", LIGHTER + "/funding-rates", None),
        ("aster/markets", ASTER + "/exchangeInfo", None),
        ("aster/ticker_24h", ASTER + "/ticker/24hr", None),
        ("dydx/markets", DYDX + "/perpetualMarkets", None),
        ("gmx/tickers", GMX + "/markets/tickers", None),
        ("gmx/markets", GMX + "/markets/info", None),
        ("gmx/rates", GMX + "/rates", None),
    ]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for label, result in pool.map(lambda x: task(*x), initial):
            if "error" in result:
                manifest["errors"][label] = result
                print("ERROR", label, result["error"])
            else:
                results[label] = result["data"]
                manifest["endpoints"][label] = result["url"]
                write_json(run_dir / (label + ".json"), result["data"])
                print("OK", label)

    lighter = {r["symbol"]: r for r in results.get("lighter/markets", {}).get("order_book_details", [])
               if r.get("status") == "active" and r.get("market_type") == "perp"}
    aster = {r["symbol"]: r for r in results.get("aster/markets", {}).get("symbols", [])
             if r.get("status") == "TRADING" and r.get("contractType") == "PERPETUAL"}
    dydx = {k: v for k, v in results.get("dydx/markets", {}).get("markets", {}).items()
            if v.get("status") == "ACTIVE"}
    gmx = results.get("gmx/tickers", [])
    if not isinstance(gmx, list):
        gmx = []

    coverage = []
    for base in CANDIDATES:
        aster_symbol = next((s for s in (base + "USDT", base + "USD1") if s in aster), None)
        d_candidate = "EUR-USD" if base == "EURUSD" else base + "-USD"
        dydx_symbol = d_candidate if d_candidate in dydx else None
        gmx_symbols = [r.get("symbol") for r in gmx if r.get("symbol", "").split("/")[0] == base]
        coverage.append({"base": base, "lighter": lighter.get(base, {}).get("market_id"),
                         "aster": aster_symbol, "dydx": dydx_symbol, "gmx": gmx_symbols})
    write_json(run_dir / "coverage.json", coverage)

    start_ms = (started - 30 * 86400) * 1000
    query = []
    for row in coverage:
        base = row["base"]
        if row["lighter"] is not None:
            query.append((f"lighter/books/{base}", LIGHTER + "/orderBookOrders",
                          {"market_id": row["lighter"], "limit": 250}))
            if base in HISTORY:
                query.append((f"lighter/candles_30d/{base}", LIGHTER + "/candles",
                              {"market_id": row["lighter"], "resolution": "1h",
                               "start_timestamp": started - 30 * 86400,
                               "end_timestamp": started, "count_back": 720}))
                # The endpoint returns at most 500 hourly bars even with a 720-hour window.
                query.append((f"lighter/candles_30d_older/{base}", LIGHTER + "/candles",
                              {"market_id": row["lighter"], "resolution": "1h",
                               "start_timestamp": started - 30 * 86400,
                               "end_timestamp": started - 18 * 86400, "count_back": 300}))
                query.append((f"lighter/fundings_30d/{base}", LIGHTER + "/fundings",
                              {"market_id": row["lighter"], "resolution": "1h",
                               "start_timestamp": started - 30 * 86400,
                               "end_timestamp": started, "count_back": 720}))
        if row["aster"]:
            symbol = row["aster"]
            query.append((f"aster/books/{base}", ASTER + "/depth", {"symbol": symbol, "limit": 500}))
            if base in HISTORY:
                query.append((f"aster/candles_30d/{base}", ASTER + "/klines",
                              {"symbol": symbol, "interval": "1h", "startTime": start_ms, "limit": 1000}))
                query.append((f"aster/fundings_30d/{base}", ASTER + "/fundingRate",
                              {"symbol": symbol, "startTime": start_ms, "limit": 1000}))
        if row["dydx"]:
            symbol = row["dydx"]
            query.append((f"dydx/books/{base}", DYDX + "/orderbooks/perpetualMarket/" + symbol, None))
            if base in HISTORY:
                query.append((f"dydx/candles_30d/{base}", DYDX + "/candles/perpetualMarkets/" + symbol,
                              {"resolution": "1HOUR", "limit": 730}))
                query.append((f"dydx/fundings_30d/{base}", DYDX + "/historicalFunding/" + symbol,
                              {"limit": 730}))

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for label, result in pool.map(lambda x: task(*x), query):
            if "error" in result:
                manifest["errors"][label] = result
                print("ERROR", label, result["error"])
            else:
                manifest["endpoints"][label] = result["url"]
                write_json(run_dir / (label + ".json"), result["data"])
                print("OK", label)

    for base in HISTORY:
        recent_file = run_dir / "lighter/candles_30d" / (base + ".json")
        older_file = run_dir / "lighter/candles_30d_older" / (base + ".json")
        if recent_file.exists() and older_file.exists():
            recent = json.loads(recent_file.read_text())
            older = json.loads(older_file.read_text())
            bars = {bar["t"]: bar for bar in older.get("c", []) + recent.get("c", [])}
            recent["c"] = [bars[t] for t in sorted(bars)][-720:]
            write_json(recent_file, recent)

    manifest["finished_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    manifest["coverage"] = {"lighter_active_perps": len(lighter), "aster_active_perps": len(aster),
                            "dydx_active_perps": len(dydx), "gmx_tickers": len(gmx),
                            "candidate_bases": len(CANDIDATES), "history_bases": list(HISTORY)}
    write_json(run_dir / "manifest.json", manifest)
    print("SAVED", run_dir, "success", len(manifest["endpoints"]), "errors", len(manifest["errors"]))


if __name__ == "__main__":
    main()
