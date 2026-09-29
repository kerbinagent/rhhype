#!/usr/bin/env python3
"""Read-only live Robinhood/Hyperliquid sample for additional exact-ticker equities.

Uses the canonical Robinhood registry, public Dexscreener pool index, onchain
Uniswap v3/v4 quoters, and public Hyperliquid xyz books. No signing or orders.
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import pathlib
import time
from decimal import Decimal

import robinhood_probe as rh


ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN_SEVEN = {"AAPL", "NVDA", "GOOGL", "MSFT", "TSLA", "AMZN", "META"}
HL_INFO = "https://api.hyperliquid.xyz/info"


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def pool_candidates(asset):
    token = asset["contractAddress"].lower()
    found = [p for p in asset.get("pairs", []) if p.get("chainId") == "robinhood"
             and p.get("dexId") == "uniswap"
             and p.get("baseToken", {}).get("address", "").lower() == token
             and p.get("quoteToken", {}).get("address", "").lower() == rh.USDG.lower()
             and ("v3" in p.get("labels", []) or "v4" in p.get("labels", []))
             and (p.get("liquidity", {}).get("usd") or 0) >= 100000
             and (p.get("volume", {}).get("h24") or 0) >= 100000]
    found.sort(key=lambda p: p.get("liquidity", {}).get("usd") or 0, reverse=True)
    return found[:3]


def quote(pool, token, mid, block_tag, usd=10000):
    args = (pool["pairAddress"], token, (Decimal(usd), mid), block_tag)
    return rh.quote_v3_pool(*args) if "v3" in pool.get("labels", []) else rh.quote_v4_pool(*args)


def plan_from_sources(only_symbol=None):
    source = sorted((ROOT / "data/raw").glob("robinhood_all_pools_*.json"))[-1]
    indexed = json.loads(source.read_text())
    hl = rh.get_json(HL_INFO, {"type": "metaAndAssetCtxs", "dex": "xyz"})
    hl_ctx = {m["name"][4:]: ctx for m, ctx in zip(hl[0]["universe"], hl[1])
              if m["name"].startswith("xyz:") and Decimal(ctx.get("dayNtlVlm") or "0") >= 1000000}
    registry = rh.get_json(rh.ASSETS)
    by_symbol = {a["tokenSymbol"]: a for a in registry["assets"]}
    block = rh.rpc("eth_getBlockByNumber", ["latest", False])
    block_tag = block["number"]
    plan = []
    for asset in indexed["assets"]:
        symbol = asset["symbol"]
        if (only_symbol and symbol != only_symbol) or (not only_symbol and symbol in MAIN_SEVEN) or symbol not in hl_ctx:
            continue
        candidates = pool_candidates(asset)
        if not candidates:
            continue
        token = asset["contractAddress"]
        current = by_symbol.get(symbol)
        if not current or not any(d["chainId"] == 4663 and d["contractAddress"].lower() == token.lower()
                              for d in current["deployments"]):
            continue
        raw_quote = rh.get_json(f"https://api.robinhood.com/rhj/prices/{symbol}")
        q = raw_quote["quotes"][0]
        mid = (Decimal(q["tokenBid"]) + Decimal(q["tokenAsk"])) / 2
        successful, errors = [], []
        for pool in candidates:
            try:
                value = quote(pool, token, mid, block_tag)
                successful.append({"pool": pool, "quote": value})
            except Exception as exc:
                errors.append({"pool": pool["pairAddress"], "error": f"{type(exc).__name__}: {exc}"})
        if not successful:
            continue
        buy = min(successful, key=lambda x: Decimal(x["quote"]["quotes"][0]["effectiveUsdPerToken"]))
        sell = max(successful, key=lambda x: Decimal(x["quote"]["quotes"][1]["effectiveUsdPerToken"]))
        selected = {x["pool"]["pairAddress"].lower(): x["pool"] for x in (buy, sell)}
        plan.append({"symbol": symbol, "name": asset["name"], "token": token,
                     "multiplier": current["currentMultiplier"], "hl_market": "xyz:" + symbol,
                     "hl_day_notional_volume": hl_ctx[symbol]["dayNtlVlm"],
                     "selected_pools": list(selected.values()),
                     "best_buy_pool": buy["pool"]["pairAddress"], "best_sell_pool": sell["pool"]["pairAddress"],
                     "initial_quotes": successful, "rejected_candidates": errors})
    return plan, str(source.relative_to(ROOT)), block_tag


def collect(asset, round_number):
    row = {"round": round_number, "symbol": asset["symbol"], "start_ms": int(time.time() * 1000),
           "pool": asset["best_buy_pool"], "selected_pool": {"buy": asset["best_buy_pool"],
                                                              "sell": asset["best_sell_pool"]},
           "multiplier": asset["multiplier"]}
    try:
        block = rh.rpc("eth_getBlockByNumber", ["latest", False])
        row["block_number"] = int(block["number"], 16)
        row["block_time_ms"] = int(block["timestamp"], 16) * 1000
        row["reference_quote"] = rh.get_json(f"https://api.robinhood.com/rhj/prices/{asset['symbol']}")
        q = row["reference_quote"]["quotes"][0]
        mid = (Decimal(q["tokenBid"]) + Decimal(q["tokenAsk"])) / 2
        row["quoter"] = [quote(p, asset["token"], mid, block["number"]) for p in asset["selected_pools"]]
        row["quotes_received_ms"] = int(time.time() * 1000)
        row["hl_start_ms"] = int(time.time() * 1000)
        row["hl_book"] = rh.get_json(HL_INFO, {"type": "l2Book", "coin": asset["hl_market"]})
        row["hl_received_ms"] = int(time.time() * 1000)
        row["gas_price_wei"] = int(rh.rpc("eth_gasPrice", []), 16)
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["end_ms"] = int(time.time() * 1000)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--only", help="sample one exact ticker, including a main-seven ticker")
    args = parser.parse_args()
    out = ROOT / "data/raw/robinhood_universe_live" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True)
    plan, source, initial_block = plan_from_sources(args.only)
    save(out / "plan.json", plan)
    manifest = {"started_utc": utc(), "source": source, "initial_block": initial_block,
                "rounds_requested": args.rounds, "interval_seconds": args.interval,
                "symbols": [a["symbol"] for a in plan], "rounds_completed": 0, "errors": 0,
                "read_only": True}
    save(out / "manifest.json", manifest)
    print(out, manifest["symbols"], flush=True)
    with (out / "quotes.jsonl").open("a") as file, cf.ThreadPoolExecutor(max_workers=5) as workers:
        for round_number in range(args.rounds):
            started = time.monotonic()
            try:
                registry = rh.get_json(rh.ASSETS)
                file.write(json.dumps({"round": round_number, "type": "registry",
                                       "received_ms": int(time.time() * 1000), "body": registry}) + "\n")
                multipliers = {a["tokenSymbol"]: a["currentMultiplier"] for a in registry["assets"]}
                for asset in plan:
                    asset["multiplier"] = multipliers[asset["symbol"]]
                rows = list(workers.map(lambda asset: collect(asset, round_number), plan))
            except Exception as exc:
                rows = [{"round": round_number, "error": str(exc)}]
            for row in rows:
                file.write(json.dumps(row, separators=(",", ":")) + "\n")
            file.flush()
            manifest["rounds_completed"] = round_number + 1
            manifest["errors"] += sum("error" in row for row in rows)
            manifest["updated_utc"] = utc()
            save(out / "manifest.json", manifest)
            print(f"round {round_number+1}/{args.rounds}: {time.monotonic()-started:.1f}s errors={sum('error' in row for row in rows)}", flush=True)
            if round_number + 1 < args.rounds:
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
    manifest["finished_utc"] = utc()
    save(out / "manifest.json", manifest)


if __name__ == "__main__":
    main()
