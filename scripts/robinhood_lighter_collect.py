#!/usr/bin/env python3
"""Read-only RH-domain Lighter and immediately paired Hyperliquid L2 snapshots.

Default: 20 rounds, 60 seconds, 30 RH books per round (below the public 60/minute cap).
This is the *Robinhood Chain Lighter instance*, not Lighter Core.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import json
import pathlib
import time
import requests


ROOT = pathlib.Path(__file__).resolve().parents[1]
RH = "https://api.rh.lighter.xyz/api/v1"
HL = "https://api.hyperliquid.xyz/info"
ISSUER_ASSETS = "https://api.robinhood.com/rhj/assets"
PERPS = ("BTC", "ETH", "SOL", "HYPE", "ZEC", "XAU", "XAG", "NVDA", "AAPL", "TSLA",
         "META", "GOOGL", "AMZN", "MSFT", "AMD", "COIN", "PLTR", "MU", "SNDK", "XRP", "SPY", "QQQ")
SPOTS = ("SPY", "QQQ", "NVDA", "AAPL", "TSLA", "META", "GOOGL", "AMZN")
HL_ALIASES = {"XAU": "xyz:GOLD", "XAG": "xyz:SILVER"}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def get(url, params=None):
    response = requests.get(url, params=params, timeout=18)
    response.raise_for_status()
    return response.json()


def latest_registry():
    """Use the issuer's full registry snapshot, not a filtered scan plan."""
    return sorted((ROOT / "data/raw").glob("robinhood_snapshot_*.json"))[-1]


def build_plan(details, registry_path):
    registry_body = json.loads(registry_path.read_text())
    assets = registry_body.get("assets") or registry_body["registry"]["assets"]
    registry = {r["tokenSymbol"]: r for r in assets}
    inv = list(csv.DictReader(open(sorted((ROOT / "data/raw/hyperliquid").glob("*/inventory.csv"))[-1])))
    active = {r["coin"] for r in inv if r.get("active") == "True" and r.get("venue") == "perp"}
    perps = {r["symbol"]: r for r in details["order_book_details"] if r["status"] == "active"}
    spots = {r["symbol"]: r for r in details["spot_order_book_details"] if r["status"] == "active"}
    plan = []
    for kind, bases, meta in (("perp", PERPS, perps), ("spot", SPOTS, spots)):
        for base in bases:
            symbol = base if kind == "perp" else base + "/USDG"
            market = meta.get(symbol)
            if market is None:
                continue
            hl_coin = HL_ALIASES.get(base, base if base in active else "xyz:" + base)
            if hl_coin not in active:
                hl_coin = None
            reg = registry.get(base, {})
            deployments = [d for d in reg.get("deployments", []) if d.get("chainId") == 4663]
            plan.append({"kind": kind, "asset": base, "market": symbol,
                         "market_id": market["market_id"], "hl_market": hl_coin,
                         "stock_token_address": deployments[0]["contractAddress"] if kind == "spot" and deployments else None,
                         "stock_token_multiplier_shares_per_token": reg.get("currentMultiplier") if kind == "spot" else None,
                         "rh_taker_fee_metadata": market.get("taker_fee"),
                         "rh_maker_fee_metadata": market.get("maker_fee"),
                         "rh_volume_24h_quote": market.get("daily_quote_token_volume"),
                         "rh_min_base_amount": market.get("min_base_amount"),
                         "rh_size_decimals": market.get("supported_size_decimals")})
    return plan


def sample(market, round_no):
    row = {"round": round_no, **market, "request_start_ms": int(time.time()*1000)}
    try:
        response = requests.get(RH + "/orderBookOrders",
                                params={"market_id": market["market_id"], "limit": 250}, timeout=18)
        row["rh_received_ms"] = int(time.time()*1000)
        row["rh_http_status"] = response.status_code
        response.raise_for_status()
        body = response.json()
        if body.get("code") != 200:
            raise ValueError(f"RH API code {body.get('code')}")
        row["rh_body"] = body
    except Exception as exc:
        row["rh_error"] = f"{type(exc).__name__}: {exc}"
        row.setdefault("rh_received_ms", int(time.time()*1000))
        return row
    if market["hl_market"]:
        try:
            response = requests.post(HL, json={"type": "l2Book", "coin": market["hl_market"]}, timeout=18)
            row["hl_received_ms"] = int(time.time()*1000)
            row["hl_http_status"] = response.status_code
            response.raise_for_status()
            body = response.json()
            if body.get("coin") != market["hl_market"]:
                raise ValueError("HL market identity mismatch")
            row["hl_body"] = body
            row["hl_venue_time_ms"] = body.get("time")
            row["quote_receipt_skew_ms"] = row["hl_received_ms"] - row["rh_received_ms"]
        except Exception as exc:
            row["hl_error"] = f"{type(exc).__name__}: {exc}"
            row.setdefault("hl_received_ms", int(time.time()*1000))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()
    output = args.out or ROOT / "data/raw/comparators/rh_lighter" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    details = get(RH + "/orderBookDetails")
    # Fetch the complete issuer registry for every run. A filtered scan plan can
    # omit stock symbols, and multipliers can change after corporate actions.
    try:
        issuer_assets = get(ISSUER_ASSETS)
        if not issuer_assets.get("assets"):
            raise ValueError("issuer registry missing assets")
        registry_path = output / "issuer_assets.json"
        write(registry_path, issuer_assets)
        registry_source = ISSUER_ASSETS
    except (requests.RequestException, ValueError):
        registry_path = latest_registry()
        registry_source = str(registry_path)
    plan = build_plan(details, registry_path)
    write(output / "markets.json", details)
    write(output / "plan.json", plan)
    manifest = {"started_utc": utc(), "rh_api": RH, "hl_api": HL, "rh_chain_id": 4663,
                "lighter_rh_app_chain_id": 466324, "lighter_core_separate": True,
                "registry_source": registry_source, "registry_snapshot": str(registry_path),
                "rounds_requested": args.rounds,
                "interval_seconds": args.interval, "rh_markets_per_round": len(plan),
                "rounds_completed": 0, "rh_errors": 0, "hl_errors": 0,
                "read_only": True,
                "spot_unit_note": "base size is canonical token amount per RH assetDetails/orderBooks; price per token inferred, not explicit in API docs"}
    write(output / "manifest.json", manifest)
    print(output, "RH markets", len(plan), flush=True)
    start = time.monotonic()
    with (output / "paired_books.jsonl").open("a") as fh, concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i in range(args.rounds):
            delay = start + i*args.interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            rows = list(pool.map(lambda m: sample(m, i), plan))
            for row in rows:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            fh.flush()
            manifest["rounds_completed"] = i + 1
            manifest["rh_errors"] += sum("rh_error" in r for r in rows)
            manifest["hl_errors"] += sum("hl_error" in r for r in rows)
            manifest["updated_utc"] = utc()
            write(output / "manifest.json", manifest)
            print("RH round", i+1, "/", args.rounds, "rh_errors", sum("rh_error" in r for r in rows),
                  "hl_errors", sum("hl_error" in r for r in rows), flush=True)
    manifest["finished_utc"] = utc()
    write(output / "manifest.json", manifest)


if __name__ == "__main__":
    main()
