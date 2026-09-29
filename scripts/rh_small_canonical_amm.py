#!/usr/bin/env python3
"""Bounded read-only canonical RH token/USDG AMM quote screen.

Five predeclared rounds; no wallet, signing, transactions, or route execution.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.request
from decimal import Decimal
from pathlib import Path

from Crypto.Hash import keccak

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import robinhood_probe as rh  # noqa: E402

INDEX = ROOT / "data/raw/robinhood_all_pools_20260929T035521Z.json"
OUT_ROOT = ROOT / "data/raw/rh_small_canonical_amm"
ASSETS = ("NVDA", "AAPL", "MSFT", "TSLA")
SIZES = (100, 250, 500, 1000)
ROUNDS = 5
INTERVAL = 65
MAX_BYTES = 8_000_000
MAX_QUOTE_CALLS_PER_ROUND = 64
USDG = rh.USDG.lower()
HL_INFO = "https://api.hyperliquid.xyz/info"


def now_ms():
    return time.time_ns() // 1_000_000


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def total_bytes(directory):
    return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())


def capped_write(directory, path, body, append=False):
    encoded = body.encode() if isinstance(body, str) else body
    old = path.stat().st_size if path.exists() and not append else 0
    if total_bytes(directory) - old + len(encoded) > MAX_BYTES:
        raise RuntimeError("8MB total output cap reached; stop without dropping evidence")
    with path.open("ab" if append else "wb") as f:
        f.write(encoded)


def save(directory, name, value):
    capped_write(directory, directory / name, json.dumps(value, separators=(",", ":"), default=str) + "\n")


def log(directory, value):
    capped_write(directory, directory / "quotes.jsonl",
                 json.dumps(value, separators=(",", ":"), default=str) + "\n", append=True)


def choose_pools(index):
    """Freeze highest archived-liquidity direct USDG pool in each v3/v4 class."""
    entries = {a["symbol"]: a for a in index["assets"]}
    result = {}
    for symbol in ASSETS:
        a = entries[symbol]
        token = a["contractAddress"].lower()
        pairs = [p for p in a["pairs"] if p.get("chainId") == "robinhood"
                 and p.get("dexId") == "uniswap"
                 and p.get("baseToken", {}).get("address", "").lower() == token
                 and p.get("quoteToken", {}).get("address", "").lower() == USDG]
        selected = []
        for version in ("v3", "v4"):
            candidates = [p for p in pairs if version in p.get("labels", [])]
            if not candidates:
                raise ValueError(f"missing {symbol} {version} direct USDG pool")
            selected.append(max(candidates, key=lambda p: Decimal(str(p.get("liquidity", {}).get("usd") or 0))))
        result[symbol] = {"token": token, "pools": [
            {"version": v, "address": p["pairAddress"],
             "archived_index_liquidity_usd": p.get("liquidity", {}).get("usd")}
            for v, p in zip(("v3", "v4"), selected)]}
    return result


def read_hl_once(payload):
    data = json.dumps(payload).encode()
    request = urllib.request.Request(HL_INFO, data=data,
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "rhhype-research/0.1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def hl_fee_metadata(body, symbol):
    meta, ctxs = body
    if meta.get("collateralToken") != 0 or len(meta["universe"]) != len(ctxs):
        raise ValueError("HL xyz collateral or metadata shape changed")
    for asset, ctx in zip(meta["universe"], ctxs):
        if asset["name"] != "xyz:" + symbol:
            continue
        if asset.get("isDelisted"):
            raise ValueError(f"HL {symbol} delisted")
        scale = Decimal(str(asset.get("deployerFeeScale", 1)))
        growth = asset.get("growthMode") == "enabled"
        factor = (scale + 1 if scale < 1 else 2 * scale) * (Decimal("0.1") if growth else 1)
        return {"market": asset["name"], "sz_decimals": asset["szDecimals"],
                "size_step": str(Decimal(10) ** -int(asset["szDecimals"])),
                "deployer_fee_scale": str(scale), "growth_mode": asset.get("growthMode"),
                "base_public_taker_bps": "4.5", "derived_taker_bps": str(Decimal("4.5") * factor),
                "day_notional_volume_usd": ctx.get("dayNtlVlm")}
    raise ValueError(f"HL xyz:{symbol} missing")


def pool_key_id(token, fee, spacing):
    currencies = sorted((USDG, token.lower()))
    encoded = "".join(map(rh.word, (*currencies, fee, spacing, 0)))
    return "0x" + keccak.new(digest_bits=256, data=bytes.fromhex(encoded)).hexdigest()


def verify_pool(pool, token, block):
    address = pool["address"]
    if pool["version"] == "v3":
        def read(selector):
            return int(rh.eth_call(address, selector, block), 16)
        token0 = "0x" + rh.word(read("0x0dfe1681"))[-40:]
        token1 = "0x" + rh.word(read("0xd21220a7"))[-40:]
        factory = "0x" + rh.word(read("0xc45a0155"))[-40:]
        fee = read("0xddca3f43")
        if {token0.lower(), token1.lower()} != {USDG, token.lower()} or factory.lower() != rh.V3_FACTORY.lower():
            raise ValueError(f"v3 identity mismatch {address}")
        return {**pool, "token0": token0, "token1": token1, "factory": factory,
                "fee": fee, "verified_block": block}
    for fee, spacing in ((100, 1), (500, 10), (3000, 60), (10000, 200)):
        if pool_key_id(token, fee, spacing).lower() == address.lower():
            return {**pool, "fee": fee, "tick_spacing": spacing,
                    "currencies": sorted((USDG, token.lower())), "hooks": "0x" + "0"*40,
                    "verified_block": block}
    raise ValueError(f"v4 PoolKey mismatch {address}")


def quote_call(pool, token, side, budget, token_mid, block):
    """Direct single-pool quoter, exact-input; AMM fee is in the quoter result."""
    start = now_ms()
    amount_in = int(Decimal(budget) * 10**6) if side == "buy" else int(Decimal(budget) / token_mid * 10**18)
    if amount_in <= 0:
        raise ValueError("zero exact input")
    token_in, token_out = (USDG, token) if side == "buy" else (token, USDG)
    if pool["version"] == "v3":
        calldata = "0x" + rh.QUOTE_SELECTOR + "".join(map(rh.word,
                     (token_in, token_out, amount_in, pool["fee"], 0)))
        answer = rh.eth_call(rh.V3_QUOTER, calldata, block).removeprefix("0x")
    else:
        currencies = pool["currencies"]
        zero_for_one = token_in.lower() == currencies[0]
        calldata = "0x" + rh.V4_QUOTE_SELECTOR + "".join(map(rh.word,
                     (32, *currencies, pool["fee"], pool["tick_spacing"], 0,
                      int(zero_for_one), amount_in, 256, 0)))
        answer = rh.eth_call(rh.V4_QUOTER, calldata, block).removeprefix("0x")
    received = now_ms()
    amount_out = int(answer[:64], 16)
    if amount_out <= 0:
        raise ValueError("zero quoter output")
    token_qty = Decimal(amount_out) / 10**18 if side == "buy" else Decimal(amount_in) / 10**18
    usd = Decimal(amount_in) / 10**6 if side == "buy" else Decimal(amount_out) / 10**6
    return {"pool": pool["address"], "version": pool["version"], "side": side,
            "budget_usd": budget, "request_ms": start, "received_ms": received,
            "amount_in_raw": str(amount_in), "amount_out_raw": str(amount_out),
            "token_qty": str(token_qty), "usd_amount": str(usd),
            "effective_usdg_per_token": str(usd / token_qty),
            "initialized_ticks_crossed": int(answer[128:192], 16) if pool["version"] == "v3" and len(answer) >= 192 else None}


def walk_hl(levels, qty):
    remain = Decimal(qty)
    value = Decimal(0)
    for level in levels:
        take = min(remain, Decimal(str(level["sz"])))
        if take > 0:
            value += take * Decimal(str(level["px"]))
            remain -= take
        if remain <= 0:
            return value
    return None


def score_one(quote, book, multiplier, meta, block_ms):
    q_token = Decimal(quote["token_qty"])
    q_share = q_token * multiplier
    lot = Decimal(meta["size_step"])
    exact_lot = q_share % lot == 0
    side = quote["side"]
    levels = book["levels"][0 if side == "buy" else 1]
    hl_value = walk_hl(levels, q_share)
    quote_usd = Decimal(quote["usd_amount"])
    hl_fee = (hl_value * Decimal(meta["derived_taker_bps"]) / 10_000) if hl_value is not None else None
    gross = ((hl_value - quote_usd) if side == "buy" else (quote_usd - hl_value)) if hl_value is not None else None
    reserve = max(quote_usd, hl_value) * Decimal("5") / 10_000 if hl_value is not None else None
    book_time = book.get("time")
    source_skew = abs(int(book_time) - block_ms) if isinstance(book_time, int) else None
    receipt_skew = abs(quote["received_ms"] - book["_received_ms"])
    return {**quote, "underlying_shares": str(q_share), "hl_exact_lot": exact_lot,
            "hl_lot": str(lot), "hl_walk_value_usdc": str(hl_value) if hl_value is not None else None,
            "entry_gross_gap_usd_at_parity": str(gross) if gross is not None else None,
            "hl_entry_fee_usdc": str(hl_fee) if hl_fee is not None else None,
            "modeled_5bp_reserve_usd": str(reserve) if reserve is not None else None,
            "entry_gap_after_one_hl_fee_and_reserve": str(gross-hl_fee-reserve) if gross is not None else None,
            "hl_source_vs_block_ms": source_skew, "hl_receipt_vs_quote_ms": receipt_skew,
            "near_time_2s": source_skew is not None and source_skew <= 2000 and receipt_skew <= 2000,
            "hl_market": meta["market"]}


def collect_asset(symbol, plan, multiplier, hl_meta, round_number):
    started = now_ms()
    block = rh.rpc("eth_getBlockByNumber", ["latest", False])
    block_tag = block["number"]
    block_ms = int(block["timestamp"], 16) * 1000
    reference = rh.get_json(f"https://api.robinhood.com/rhj/prices/{symbol}")
    reference_received = now_ms()
    ref = reference["quotes"][0]
    mid = (Decimal(ref["tokenBid"]) + Decimal(ref["tokenAsk"])) / 2
    jobs = [(p, side, budget) for p in plan["pools"] for side in ("buy", "sell") for budget in SIZES]
    if len(jobs) != 16:
        raise ValueError("per-asset quote call count changed")
    with cf.ThreadPoolExecutor(max_workers=4) as workers:
        futures = [(p, side, budget, workers.submit(quote_call, p, plan["token"], side,
                    budget, mid, block_tag)) for p, side, budget in jobs]
        quotes = []
        for p, side, budget, future in futures:
            try:
                quotes.append(future.result())
            except Exception as exc:
                quotes.append({"pool": p["address"], "side": side, "budget_usd": budget,
                               "error": f"{type(exc).__name__}: {exc}"})
    hl_started = now_ms()
    book = read_hl_once({"type": "l2Book", "coin": hl_meta["market"]})
    book["_received_ms"] = now_ms()
    scored = [score_one(q, book, multiplier, hl_meta, block_ms) if "error" not in q else q
              for q in quotes]
    return {"round": round_number, "symbol": symbol, "started_ms": started,
            "ended_ms": now_ms(), "block_number": block_tag, "block_time_ms": block_ms,
            "reference_received_ms": reference_received, "reference_token_bid": ref["tokenBid"],
            "reference_token_ask": ref["tokenAsk"], "current_multiplier": str(multiplier),
            "hl_book_started_ms": hl_started, "hl_book_received_ms": book["_received_ms"],
            "hl_book_source_ms": book.get("time"), "hl_book": book,
            "quotes": scored}


def main():
    index = json.loads(INDEX.read_text())
    selected = choose_pools(index)
    out = OUT_ROOT / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=False)
    frozen = {"assets": ASSETS, "sizes_usd": SIZES, "rounds": ROUNDS,
              "interval_seconds": INTERVAL, "max_total_output_bytes": MAX_BYTES,
              "max_eth_calls_per_round": MAX_QUOTE_CALLS_PER_ROUND,
              "hl_l2_calls_per_round": 4, "selection_rule": "highest archived USDG direct Uniswap pool in each v3/v4 class, two per asset",
              "source_index": str(INDEX.relative_to(ROOT)), "source_index_sha256": sha(INDEX),
              "script_sha256": sha(Path(__file__)),
              "selected": selected, "read_only": True,
              "notes": "single-pool exact-input quotes; fee included; no split, gas, conversion, order or executable-profit claim"}
    save(out, "frozen-plan.json", frozen)
    manifest = {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "rounds_requested": ROUNDS, "rounds_completed": 0, "status": "preflight",
                "read_only": True, "errors": []}
    save(out, "manifest.json", manifest)
    try:
        registry = rh.get_json(rh.ASSETS)
        hl_raw = read_hl_once({"type": "metaAndAssetCtxs", "dex": "xyz"})
        block = rh.rpc("eth_getBlockByNumber", ["latest", False])
        static_block = block["number"]
        save(out, "registry-preflight.json", registry)
        save(out, "hl-meta-preflight.json", hl_raw)
        by_symbol = {a["tokenSymbol"]: a for a in registry["assets"]}
        for symbol, item in selected.items():
            deployment = next((d for d in by_symbol[symbol]["deployments"] if d["chainId"] == 4663), None)
            if not deployment or deployment["contractAddress"].lower() != item["token"]:
                raise ValueError(f"canonical registry address mismatch {symbol}")
            item["multiplier"] = by_symbol[symbol]["currentMultiplier"]
            item["hl"] = hl_fee_metadata(hl_raw, symbol)
            item["pools"] = [verify_pool(pool, item["token"], static_block) for pool in item["pools"]]
        if rh.rpc("eth_getCode", [rh.V3_QUOTER, static_block]) == "0x" or rh.rpc("eth_getCode", [rh.V4_QUOTER, static_block]) == "0x":
            raise ValueError("verified quoter bytecode missing")
        for token in (rh.USDG, *(item["token"] for item in selected.values())):
            expected_decimals = 6 if token.lower() == USDG else 18
            if int(rh.eth_call(token, "0x313ce567", static_block), 16) != expected_decimals:
                raise ValueError(f"token decimals mismatch {token}")
        save(out, "verified-plan.json", selected)
        manifest["status"] = "preflight_verified_waiting_hl_rate_window"
        manifest["preflight_ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        save(out, "manifest.json", manifest)
        print(f"PREFLIGHT_VERIFIED out={out} waiting=65s", flush=True)
        time.sleep(INTERVAL)  # Keep the HL metadata request outside the four-L2-call minute.
        for round_number in range(ROUNDS):
            round_start = time.monotonic()
            fresh_registry = rh.get_json(rh.ASSETS)
            fresh_by_symbol = {a["tokenSymbol"]: a for a in fresh_registry["assets"]}
            round_multiplier = {}
            for symbol, item in selected.items():
                a = fresh_by_symbol[symbol]
                deployment = next((d for d in a["deployments"] if d["chainId"] == 4663), None)
                if not deployment or deployment["contractAddress"].lower() != item["token"]:
                    raise ValueError(f"canonical registry address changed during round {round_number}: {symbol}")
                round_multiplier[symbol] = Decimal(str(a["currentMultiplier"]))
            log(out, {"round": round_number, "type": "registry_multipliers",
                      "received_ms": now_ms(), "multipliers": {k: str(v) for k, v in round_multiplier.items()}})
            calls = 0
            for symbol in ASSETS:
                calls += 16
                if calls > MAX_QUOTE_CALLS_PER_ROUND:
                    raise RuntimeError("quote-call cap exceeded")
                try:
                    row = collect_asset(symbol, selected[symbol], round_multiplier[symbol],
                                        selected[symbol]["hl"], round_number)
                except Exception as exc:
                    row = {"round": round_number, "symbol": symbol,
                           "error": f"{type(exc).__name__}: {exc}", "received_ms": now_ms()}
                    manifest["errors"].append(row)
                log(out, row)
            manifest["rounds_completed"] = round_number + 1
            manifest["status"] = "sampling"
            manifest["updated_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            save(out, "manifest.json", manifest)
            print(f"round={round_number+1}/{ROUNDS} elapsed_s={time.monotonic()-round_start:.1f} bytes={total_bytes(out)}", flush=True)
            if round_number + 1 < ROUNDS:
                time.sleep(max(0, INTERVAL - (time.monotonic() - round_start)))
        manifest["status"] = "complete"
    except Exception as exc:
        manifest["status"] = "stopped_error"
        manifest["errors"].append({"error": f"{type(exc).__name__}: {exc}", "at_ms": now_ms()})
        raise
    finally:
        manifest["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            save(out, "manifest.json", manifest)
        except RuntimeError:
            print("manifest could not fit within 8MB cap", file=sys.stderr)
        print(f"OUTPUT={out} status={manifest['status']}", flush=True)


if __name__ == "__main__":
    main()
