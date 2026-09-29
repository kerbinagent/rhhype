#!/usr/bin/env python3
"""Read-only 30-day RH Lighter candles and hourly funding, with paced public requests."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import time
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://api.rh.lighter.xyz/api/v1"
PERPS = ("BTC", "SOL", "HYPE", "XAU", "XAG", "SPY", "NVDA", "AAPL")
SPOTS = ("SPY/USDG", "NVDA/USDG")


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=pathlib.Path, default=sorted((ROOT / "data/raw/comparators/rh_lighter").glob("*/"))[-1])
    p.add_argument("--perps", nargs="*", default=list(PERPS))
    p.add_argument("--spots", nargs="*", default=list(SPOTS))
    p.add_argument("--append", action="store_true", help="Preserve previous manifest entries and add only selected markets")
    args = p.parse_args()
    run = args.run
    details = json.loads((run / "markets.json").read_text())
    markets = {r["symbol"]: r["market_id"] for key in ("order_book_details", "spot_order_book_details") for r in details[key]}
    now = int(time.time())
    begin = now - 30 * 86400
    jobs = []
    perps = tuple(args.perps)
    spots = tuple(args.spots)
    for symbol in perps + spots:
        mid = markets[symbol]
        key = symbol.replace("/", "_")
        jobs += [
            (f"candles_30d/{key}", "candles", dict(market_id=mid, resolution="1h", start_timestamp=begin, end_timestamp=now, count_back=720)),
            (f"candles_30d_older/{key}", "candles", dict(market_id=mid, resolution="1h", start_timestamp=begin, end_timestamp=now-18*86400, count_back=300)),
        ]
        if symbol in perps:
            jobs.append((f"fundings_30d/{key}", "fundings", dict(market_id=mid, resolution="1h", start_timestamp=begin, end_timestamp=now, count_back=720)))
    manifest_path = run / "history/manifest.json"
    if args.append and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest.setdefault("appended_runs", []).append({"started_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
                                                        "perps":perps,"spots":spots,"public_requests":len(jobs)})
        manifest["public_requests"] += len(jobs)
    else:
        manifest = {"started_utc":dt.datetime.now(dt.timezone.utc).isoformat(), "api":API,
                    "endpoints":{}, "errors":{}, "public_requests":len(jobs), "pace_seconds":4.5}
    save(run / "history/manifest.json", manifest)
    session = requests.Session()
    for idx,(label,endpoint,params) in enumerate(jobs):
        if idx: time.sleep(4.5)
        url = API + "/" + endpoint
        try:
            response = session.get(url, params=params, timeout=18)
            response.raise_for_status()
            body = response.json()
            if body.get("code") != 200:
                raise ValueError(f"API code {body.get('code')}")
            save(run / "history" / (label+".json"), body)
            manifest["endpoints"][label] = response.url
            print("OK", label, flush=True)
        except Exception as e:
            manifest["errors"][label] = {"url":url,"params":params,"error":str(e)}
            print("ERROR", label, e, flush=True)
        save(run / "history/manifest.json", manifest)
    for symbol in perps + spots:
        key = symbol.replace("/", "_")
        recent = run / "history/candles_30d" / (key + ".json")
        older = run / "history/candles_30d_older" / (key + ".json")
        if recent.exists() and older.exists():
            newer = json.loads(recent.read_text())
            prev = json.loads(older.read_text())
            bars = {bar["t"]:bar for bar in prev.get("c",[]) + newer.get("c",[])}
            newer["c"] = [bars[t] for t in sorted(bars)][-720:]
            save(recent, newer)
    manifest["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save(run / "history/manifest.json", manifest)


if __name__ == "__main__":
    main()
