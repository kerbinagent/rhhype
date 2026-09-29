#!/usr/bin/env python3
"""Read-only Robinhood Chain venue snapshot; no keys, signing, or trades.

Run: python scripts/robinhood_probe.py
Writes timestamped JSON under data/raw and a concise table to stdout.
"""

import datetime as dt
import argparse
import json
import pathlib
import time
import urllib.request
import urllib.error
from decimal import Decimal
from Crypto.Hash import keccak  # Ethereum Keccak-256; provided by pycryptodome


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw"
RPC = "https://rpc.mainnet.chain.robinhood.com"
ASSETS = "https://api.robinhood.com/rhj/assets"
DEX = "https://api.dexscreener.com/latest/dex/tokens/"
SYMBOLS = ("AAPL", "NVDA", "GOOGL", "MSFT", "TSLA", "AMZN", "META", "QQQ", "SPY", "P")
HISTORY_SYMBOLS = ("AAPL", "NVDA", "GOOGL", "MSFT", "TSLA", "AMZN", "META", "QQQ", "SPY")
USDG = "0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168"
V3_FACTORY = "0x1f7d7550B1b028f7571E69A784071F0205FD2EfA"
V3_QUOTER = "0x33e885eD0Ec9bF04EcfB19341582aADCb4c8A9E7"
QUOTE_SELECTOR = "c6a5026a"  # quoteExactInputSingle((address,address,uint256,uint24,uint160))
V4_QUOTER = "0x8Dc178eFB8111BB0973Dd9d722ebeFF267c98F94"
V4_QUOTE_SELECTOR = "aa9d21cb"  # quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))
MULTIPLIER_TOPIC = "0x2205df4534432b2f60654a3fdb48737ffdaf3e9edb1a498bd985bc026b15b055"
CANCEL_TOPIC = "0x" + keccak.new(digest_bits=256, data=b"UIMultiplierUpdateCancelled(uint256,uint256)").hexdigest()


def get_json(url, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"User-Agent": "rhhype-research/0.1", "Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def rpc(method, params):
    result = get_json(RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if "error" in result:
        raise RuntimeError(result["error"])
    return result["result"]


def word(value):
    return f"{value:064x}" if isinstance(value, int) else value.removeprefix("0x").lower().zfill(64)


def eth_call(address, data, block_tag):
    return rpc("eth_call", [{"to": address, "data": data}, block_tag])


def quote_v3_pool(pool, token, amount_usd, block_tag):
    """Simulate both sides against one verified Uniswap v3 token/USDG pool.

    Sell quantity is pegged to Robinhood's token mid, passed by caller as amount_usd / mid.
    Here amount_usd is a tuple (USD notional, token mid).
    """
    usd, token_mid = amount_usd
    read = lambda selector: int(eth_call(pool, selector, block_tag), 16)
    token0 = "0x" + word(read("0x0dfe1681"))[-40:]
    token1 = "0x" + word(read("0xd21220a7"))[-40:]
    factory = "0x" + word(read("0xc45a0155"))[-40:]
    fee = read("0xddca3f43")
    liquidity = read("0x1a686502")
    if {token0.lower(), token1.lower()} != {USDG.lower(), token.lower()}:
        raise RuntimeError(f"Pool token mismatch: {pool}: {token0} {token1}")
    if factory.lower() != V3_FACTORY.lower():
        raise RuntimeError(f"Pool factory mismatch: {pool}: {factory}")
    if rpc("eth_getCode", [V3_QUOTER, block_tag]) == "0x":
        raise RuntimeError("Quoter not deployed")
    result = {"pool": pool, "token0": token0, "token1": token1, "factory": factory,
              "fee": fee, "activeLiquidity": str(liquidity), "blockTag": block_tag, "quotes": []}
    for side in ("buy", "sell"):
        token_in, token_out = (USDG, token) if side == "buy" else (token, USDG)
        amount_in = int(usd * 10**6) if side == "buy" else int((usd / token_mid) * 10**18)
        calldata = "0x" + QUOTE_SELECTOR + "".join(map(word, (token_in, token_out, amount_in, fee, 0)))
        answer = eth_call(V3_QUOTER, calldata, block_tag).removeprefix("0x")
        amount_out = int(answer[:64], 16)
        token_quantity = Decimal(amount_out) / 10**18 if side == "buy" else Decimal(amount_in) / 10**18
        paid_usd = Decimal(amount_in) / 10**6 if side == "buy" else Decimal(amount_out) / 10**6
        result["quotes"].append({"side": side, "targetUsd": str(usd), "amountInRaw": str(amount_in),
                                 "amountOutRaw": str(amount_out), "tokenQuantity": str(token_quantity),
                                 "usdAmount": str(paid_usd), "effectiveUsdPerToken": str(paid_usd / token_quantity),
                                 "initializedTicksCrossed": int(answer[128:192], 16)})
    return result


def quote_v4_pool(pool_id, token, amount_usd, block_tag):
    """Quote a standard Uniswap v4 USDG pool after verifying its PoolKey hash.

    Try standard no-hook fee/tick-spacing pairs and verify the exact PoolId.
    A different PoolKey is rejected rather than silently misquoted.
    """
    usd, token_mid = amount_usd
    currencies = sorted((USDG.lower(), token.lower()))
    hooks = 0
    fee, tick_spacing = 0, 0
    for candidate_fee, candidate_spacing in ((100, 1), (500, 10), (3000, 60), (10000, 200)):
        encoded_key = "".join(map(word, (*currencies, candidate_fee, candidate_spacing, hooks)))
        computed_id = "0x" + keccak.new(digest_bits=256, data=bytes.fromhex(encoded_key)).hexdigest()
        if computed_id.lower() == pool_id.lower():
            fee, tick_spacing = candidate_fee, candidate_spacing
            break
    if fee == 0:
        raise RuntimeError(f"Unknown v4 PoolKey for {pool_id}; not a standard no-hook fee tier")
    if rpc("eth_getCode", [V4_QUOTER, block_tag]) == "0x":
        raise RuntimeError("v4 Quoter not deployed")
    result = {"poolId": pool_id, "currencies": currencies, "fee": fee, "tickSpacing": tick_spacing,
              "hooks": "0x" + "0" * 40, "quoter": V4_QUOTER, "blockTag": block_tag, "quotes": []}
    for side in ("buy", "sell"):
        token_in = USDG if side == "buy" else token
        amount_in = int(usd * 10**6) if side == "buy" else int((usd / token_mid) * 10**18)
        zero_for_one = token_in.lower() == currencies[0]
        # ABI: offset to tuple; five PoolKey words; direction; amount; offset to
        # dynamic hookData; empty byte-string length.
        calldata = "0x" + V4_QUOTE_SELECTOR + "".join(map(word, (32, *currencies, fee,
                    tick_spacing, hooks, int(zero_for_one), amount_in, 256, 0)))
        answer = eth_call(V4_QUOTER, calldata, block_tag).removeprefix("0x")
        amount_out = int(answer[:64], 16)
        token_quantity = Decimal(amount_out) / 10**18 if side == "buy" else Decimal(amount_in) / 10**18
        paid_usd = Decimal(amount_in) / 10**6 if side == "buy" else Decimal(amount_out) / 10**6
        result["quotes"].append({"side": side, "targetUsd": str(usd), "amountInRaw": str(amount_in),
                                 "amountOutRaw": str(amount_out), "tokenQuantity": str(token_quantity),
                                 "usdAmount": str(paid_usd), "effectiveUsdPerToken": str(paid_usd / token_quantity)})
    return result


def scan_all_pools():
    """Index every canonical token individually; Dexscreener caps pairs per call."""
    started = dt.datetime.now(dt.timezone.utc)
    assets = get_json(ASSETS)["assets"]
    output = {"collectedAtUtc": started.isoformat(), "sourceRegistry": ASSETS,
              "sourceDexTemplate": DEX + "{contractAddress}",
              "note": "Dexscreener returns at most 30 pairs per token; liquidity is indexer-estimated and not executable depth.",
              "assets": []}
    for index, asset in enumerate(assets, 1):
        deployment = next((d for d in asset["deployments"] if d["chainId"] == 4663), None)
        if deployment is None:
            continue
        address = deployment["contractAddress"]
        dex_url = DEX + address
        try:
            dex = get_json(dex_url)
            pairs = [p for p in dex.get("pairs") or [] if p.get("chainId") == "robinhood"
                     and address.lower() in (p.get("baseToken", {}).get("address", "").lower(),
                                             p.get("quoteToken", {}).get("address", "").lower())]
            pairs.sort(key=lambda p: p.get("liquidity", {}).get("usd") or 0, reverse=True)
            entry = {"symbol": asset["tokenSymbol"], "name": asset["tokenName"],
                     "contractAddress": address, "currentMultiplier": asset["currentMultiplier"],
                     "dexUrl": dex_url, "pairs": pairs}
        except Exception as exc:
            entry = {"symbol": asset["tokenSymbol"], "contractAddress": address,
                     "dexUrl": dex_url, "error": str(exc)}
        output["assets"].append(entry)
        if index % 25 == 0:
            print(f"scanned {index}/{len(assets)}", flush=True)
        time.sleep(0.25)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("robinhood_all_pools_" + started.strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"saved {path.relative_to(ROOT)}")
    print("symbol,contract,top_usdg_dex,version,pool,indexed_liquidity_usd,volume_h24_usd")
    for a in output["assets"]:
        usdg = [p for p in a.get("pairs", []) if p.get("quoteToken", {}).get("symbol") == "USDG"
                and p.get("baseToken", {}).get("address", "").lower() == a["contractAddress"].lower()]
        if not usdg:
            continue
        p = max(usdg, key=lambda p: p.get("liquidity", {}).get("usd") or 0)
        print(",".join(map(str, (a["symbol"], a["contractAddress"], p.get("dexId"),
                                "/".join(p.get("labels", [])), p.get("pairAddress"),
                                p.get("liquidity", {}).get("usd", 0), p.get("volume", {}).get("h24", 0)))))


def multiplier_history(since_block=0):
    """Reconstruct full ERC-8056 schedules from genesis logs, not archival state."""
    collected = dt.datetime.now(dt.timezone.utc)
    registry = get_json(ASSETS)
    assets = {a["tokenSymbol"]: a for a in registry["assets"]}
    latest = int(rpc("eth_blockNumber", []), 16)
    output = {"collectedAtUtc": collected.isoformat(), "rpc": RPC,
              "sourceRegistry": ASSETS, "fromBlock": since_block, "toBlock": latest,
              "eventSignature": "UIMultiplierUpdated(uint256,uint256,uint256)",
              "eventTopic": MULTIPLIER_TOPIC, "cancelTopic": CANCEL_TOPIC,
              "note": "Each update becomes effective at effectiveAtTimestamp, which can be later than the emitting block timestamp; logs are queried from genesis through the latest block.",
              "symbols": {}}
    def logs(query):
        delay = 2
        for attempt in range(6):
            try:
                answer = rpc("eth_getLogs", [query])
                time.sleep(0.5)
                return answer
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == 5:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 30)
        raise RuntimeError("Unreachable log retry")

    for symbol in HISTORY_SYMBOLS:
        asset = assets[symbol]
        address = next(d["contractAddress"] for d in asset["deployments"] if d["chainId"] == 4663)
        events = []
        for topic in (MULTIPLIER_TOPIC, CANCEL_TOPIC):
            for first in range(since_block, latest + 1, 9_999_999):
                last = min(first + 9_999_998, latest)
                query = {"fromBlock": hex(first), "toBlock": hex(last), "address": address,
                         "topics": [topic]}
                events.extend(logs(query))
        parsed = []
        for event in events:
            chunks = [int(event["data"][2+i:2+i+64], 16) for i in range(0, len(event["data"]) - 2, 64)]
            base = {"blockNumber": int(event["blockNumber"], 16), "transactionHash": event["transactionHash"],
                    "logIndex": int(event["logIndex"], 16), "raw": event}
            if event["topics"][0].lower() == MULTIPLIER_TOPIC.lower():
                base.update({"type": "update", "oldMultiplierRaw": str(chunks[0]),
                             "newMultiplierRaw": str(chunks[1]), "effectiveAtTimestamp": chunks[2]})
            else:
                base.update({"type": "cancel", "cancelledMultiplierRaw": str(chunks[0]),
                             "cancelledEffectiveAtTimestamp": chunks[1]})
            parsed.append(base)
        parsed.sort(key=lambda event: (event["blockNumber"], event["logIndex"]))
        now = int(collected.timestamp())
        active = [e for e in parsed if e["type"] == "update" and e["effectiveAtTimestamp"] <= now]
        expected_current = Decimal(active[-1]["newMultiplierRaw"]) / 10**18 if active else None
        current = Decimal(asset["currentMultiplier"])
        matches = expected_current is None or expected_current == current
        output["symbols"][symbol] = {"address": address, "currentMultiplier": str(current),
                                     "lastEffectiveEventMultiplier": str(expected_current) if expected_current else None,
                                     "lastEffectiveEventMatchesCurrent": matches,
                                     "events": parsed}
        print(symbol, len(parsed), "events", "anchor_match", matches, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / ("robinhood_multipliers_" + collected.strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps(output, indent=2) + "\n")
    print(f"saved {path.relative_to(ROOT)}")


def main():
    started = dt.datetime.now(dt.timezone.utc)
    registry = get_json(ASSETS)
    assets = {a["tokenSymbol"]: a for a in registry["assets"]}
    chain_id = int(rpc("eth_chainId", []), 16)
    if chain_id != 4663:
        raise RuntimeError(f"Unexpected chain id: {chain_id}")
    block = rpc("eth_getBlockByNumber", ["latest", False])
    snapshot = {
        "collectedAtUtc": started.isoformat(),
        "sources": {"rpc": RPC, "assets": ASSETS, "dex": DEX, "prices": "https://api.robinhood.com/rhj/prices/{symbol}"},
        "chainId": chain_id,
        "blockNumber": int(block["number"], 16),
        "blockTimestampUtc": dt.datetime.fromtimestamp(int(block["timestamp"], 16), dt.timezone.utc).isoformat(),
        "registry": registry,
        "selected": {},
    }
    print("symbol,contract,token_bid,token_ask,top_usdg_pool,version,pool_price_usd,indexed_liquidity_usd,volume_h24_usd")
    for symbol in SYMBOLS:
        asset = assets.get(symbol)
        if not asset:
            print(f"{symbol},MISSING")
            continue
        deployment = next((d for d in asset["deployments"] if d["chainId"] == chain_id), None)
        if not deployment:
            print(f"{symbol},NO_MAINNET_DEPLOYMENT")
            continue
        address = deployment["contractAddress"]
        if rpc("eth_getCode", [address, "latest"]) == "0x":
            raise RuntimeError(f"Registry token has no code: {symbol} {address}")
        price_url = f"https://api.robinhood.com/rhj/prices/{symbol}"
        quote = get_json(price_url)
        dex_url = DEX + address
        dex = get_json(dex_url)
        pairs = [p for p in dex.get("pairs") or [] if p.get("chainId") == "robinhood"
                 and address.lower() in (p.get("baseToken", {}).get("address", "").lower(),
                                         p.get("quoteToken", {}).get("address", "").lower())]
        usdg = [p for p in pairs if p.get("quoteToken", {}).get("symbol") == "USDG"
                and p.get("baseToken", {}).get("address", "").lower() == address.lower()]
        usdg.sort(key=lambda p: float(p.get("liquidity", {}).get("usd") or 0), reverse=True)
        top = usdg[0] if usdg else {}
        q = next((q for q in quote.get("quotes", []) if q.get("tokenSymbol") == symbol), {})
        selected = {"asset": asset, "quote": quote, "dex": dex,
                    "priceUrl": price_url, "dexUrl": dex_url}
        v3 = next((p for p in usdg if p.get("dexId") == "uniswap" and "v3" in p.get("labels", [])), None)
        if v3 and q.get("tokenBid") and q.get("tokenAsk"):
            mid = (Decimal(q["tokenBid"]) + Decimal(q["tokenAsk"])) / 2
            selected["v3QuoterAddress"] = V3_QUOTER
            notionals = (1000, 10000, 100000) if symbol == "NVDA" else (10000,)
            selected["v3Quotes"] = [quote_v3_pool(v3["pairAddress"], address, (Decimal(usd), mid),
                                                  hex(snapshot["blockNumber"])) for usd in notionals]
        v4 = next((p for p in usdg if p.get("dexId") == "uniswap" and "v4" in p.get("labels", [])), None)
        if v4 and q.get("tokenBid") and q.get("tokenAsk"):
            mid = (Decimal(q["tokenBid"]) + Decimal(q["tokenAsk"])) / 2
            try:
                selected["v4Quotes"] = [quote_v4_pool(v4["pairAddress"], address, (Decimal(10000), mid),
                                                       hex(snapshot["blockNumber"]))]
            except RuntimeError as exc:
                selected["v4QuoteError"] = str(exc)
        snapshot["selected"][symbol] = selected
        print(",".join(map(str, (symbol, address, q.get("tokenBid", ""), q.get("tokenAsk", ""),
                                top.get("pairAddress", ""), "/".join(top.get("labels", [])),
                                top.get("priceUsd", ""), top.get("liquidity", {}).get("usd", ""),
                                top.get("volume", {}).get("h24", "")))))
        time.sleep(0.2)
    OUT.mkdir(parents=True, exist_ok=True)
    name = "robinhood_snapshot_" + started.strftime("%Y%m%dT%H%M%SZ") + ".json"
    path = OUT / name
    path.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all-pools", action="store_true", help="scan all registry tokens against Dexscreener")
    parser.add_argument("--multiplier-history", action="store_true", help="collect ERC-8056 multiplier events from genesis")
    parser.add_argument("--since-block", type=int, default=0, help="first block for multiplier log scan")
    args = parser.parse_args()
    if args.multiplier_history:
        multiplier_history(args.since_block)
    elif args.all_pools:
        scan_all_pools()
    else:
        main()
