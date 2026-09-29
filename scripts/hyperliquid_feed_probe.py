#!/usr/bin/env python3
"""Bounded public Hyperliquid WebSocket quote-cadence probe; no trading calls."""

import argparse
import asyncio
import datetime as dt
import json
import statistics
import time
from pathlib import Path

import aiohttp


URL = "wss://api.hyperliquid.xyz/ws"
ROOT = Path(__file__).resolve().parents[1]


def iso_ms(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat()


def median_gap(values):
    ordered = sorted(set(values))
    gaps = [(b - a) / 1000 for a, b in zip(ordered, ordered[1:])]
    return round(statistics.median(gaps), 3) if gaps else None


def summarize(events):
    by_key = {}
    for e in events:
        by_key.setdefault((e["channel"], e.get("coin") or e.get("dex")), []).append(e)
    out = []
    for (channel, key), rows in sorted(by_key.items()):
        recv = [x["received_ms"] for x in rows]
        src = [x["source_ms"] for x in rows if x.get("source_ms")]
        ages = [(x["received_ms"] - x["source_ms"]) / 1000 for x in rows if x.get("source_ms")]
        out.append({"channel": channel, "key": key, "events": len(rows),
                    "receipt_median_gap_s": median_gap(recv),
                    "source_median_gap_s": median_gap(src),
                    "unique_source_timestamps": len(set(src)),
                    "median_receipt_minus_source_s": round(statistics.median(ages), 3) if ages else None,
                    "max_receipt_minus_source_s": round(max(ages), 3) if ages else None,
                    "first_received_utc": iso_ms(min(recv)), "last_received_utc": iso_ms(max(recv))})
    return out


async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=int, default=40)
    ap.add_argument("--coins", nargs="+", default=["BTC", "ETH", "xyz:SP500"])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if not 5 <= args.seconds <= 90 or not 1 <= len(args.coins) <= 5:
        ap.error("Require 5–90 seconds and 1–5 coins")
    subscriptions = [{"type": channel, "coin": coin} for coin in args.coins for channel in ("bbo", "l2Book")]
    subscriptions += [{"type": "allMids"}, {"type": "allMids", "dex": "xyz"}]
    events, controls, errors = [], [], []
    started = int(time.time() * 1000)
    timeout = aiohttp.ClientTimeout(total=args.seconds + 20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(URL, heartbeat=15, receive_timeout=10) as ws:
            for sub in subscriptions:
                await ws.send_json({"method": "subscribe", "subscription": sub})
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                try:
                    msg = await ws.receive(timeout=min(5, max(0.1, deadline - time.monotonic())))
                except asyncio.TimeoutError:
                    continue
                recv = int(time.time() * 1000)
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        errors.append(str(msg.data))
                        break
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    errors.append("non-JSON message")
                    continue
                channel = data.get("channel")
                body = data.get("data", {})
                if channel not in ("bbo", "l2Book", "allMids"):
                    controls.append({"received_ms": recv, "channel": channel, "data": body})
                    continue
                if not isinstance(body, dict):
                    errors.append("unexpected data format: " + str(channel))
                    continue
                e = {"received_ms": recv, "channel": channel}
                if channel == "allMids":
                    mids = body.get("mids", {})
                    e.update({"dex": body.get("dex", "unspecified"), "coins": len(mids),
                              "selected_mids": {k: mids[k] for k in args.coins if k in mids}})
                else:
                    e["coin"] = body.get("coin")
                    e["source_ms"] = body.get("time")
                    levels = body.get("bbo") if channel == "bbo" else body.get("levels")
                    if isinstance(levels, list) and len(levels) == 2:
                        bid = levels[0] if channel == "bbo" else (levels[0][0] if levels[0] else None)
                        ask = levels[1] if channel == "bbo" else (levels[1][0] if levels[1] else None)
                        e["bid"] = bid
                        e["ask"] = ask
                        if channel == "l2Book":
                            e["level_counts"] = [len(levels[0]), len(levels[1])]
                            e["visible_notional_usd"] = {
                                side: sum(float(x["px"]) * float(x["sz"]) for x in side_levels)
                                for side, side_levels in (("bid", levels[0]), ("ask", levels[1]))
                            }
                    else:
                        errors.append("missing levels: " + str(channel))
                events.append(e)
    result = {"started_utc": iso_ms(started), "ended_utc": iso_ms(int(time.time() * 1000)),
              "seconds_requested": args.seconds, "endpoint": URL, "subscriptions": subscriptions,
              "summary": summarize(events), "events": events, "control_messages": controls, "errors": errors,
              "note": "allMids lacks source timestamp and depth; bbo contains only one level per side; l2Book has up to 20 levels per side."}
    out = args.out or ROOT / "data/derived" / ("hyperliquid_feed_probe_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(out)
    for row in result["summary"]:
        print(row)
    print("events", len(events), "controls", len(controls), "errors", errors, "bytes", out.stat().st_size)


if __name__ == "__main__":
    asyncio.run(main())
