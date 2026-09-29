#!/usr/bin/env python3
"""Read-only Hyperliquid market census and representative 30-day history.

Uses only the public /info API. No keys, wallet endpoints, or exchange actions.
"""

import argparse
import csv
import datetime as dt
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.hyperliquid.xyz/info"
ROOT = Path(__file__).resolve().parents[1] / "data" / "raw" / "hyperliquid"
UTC = dt.timezone.utc
FIELDS = ["snapshot_utc", "venue", "dex", "coin", "category", "active", "day_volume_usd", "open_interest_units", "open_interest_usd", "mark_px", "oracle_px", "funding_hourly", "max_leverage", "sz_decimals", "margin_mode", "collateral_token", "deployer_fee_scale", "spot_fee_share", "growth_mode", "spot_base", "spot_quote", "spot_index"]


def stamp():
    return dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def number(x):
    try:
        return float(x)
    except (ValueError, TypeError):
        return 0.0


def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)


class Client:
    def __init__(self, run_dir, pause):
        self.run_dir = run_dir
        self.pause = pause
        self.errors = []
        self.calls = 0

    def get(self, payload, relpath, required=False):
        out = self.run_dir / relpath
        if out.exists():
            return json.loads(out.read_text())
        body = json.dumps(payload, separators=(",", ":")).encode()
        request = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "User-Agent": "rhhype-research/1.0"})
        last = None
        for attempt in range(5):
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    result = json.load(response)
                write_json(out, result)
                self.calls += 1
                time.sleep(self.pause)
                return result
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                    break
                time.sleep(min(12, 0.8 * (2 ** attempt) + random.random()))
        self.errors.append({"request": payload, "path": relpath, "error": last, "at_utc": dt.datetime.now(UTC).isoformat()})
        print(f"ERROR {payload}: {last}", file=sys.stderr, flush=True)
        if required:
            raise RuntimeError(f"required API request failed: {payload}: {last}")
        return None


def census(client):
    snapshot_utc = dt.datetime.now(UTC).isoformat()
    dexes = client.get({"type": "perpDexs"}, "perp_dexs.json", required=True)
    categories = client.get({"type": "perpCategories"}, "perp_categories.json") or []
    annotations = client.get({"type": "perpConciseAnnotations"}, "perp_annotations.json") or []
    cats = dict(categories)
    anns = dict(annotations)
    rows = []
    for dex_obj in dexes:
        dex = dex_obj["name"] if dex_obj else ""
        label = dex or "native"
        response = client.get({"type": "metaAndAssetCtxs", "dex": dex}, f"meta_and_ctxs/{label}.json")
        if not response:
            continue
        meta, ctxs = response
        collateral = meta.get("collateralToken", "")
        for asset, ctx in zip(meta["universe"], ctxs):
            coin = asset["name"]
            mark = number(ctx.get("markPx"))
            oi = number(ctx.get("openInterest"))
            rows.append({"snapshot_utc": snapshot_utc, "venue": "perp", "dex": dex, "coin": coin,
                         "category": cats.get(coin) or (anns.get(coin) or {}).get("category") or ("crypto" if not dex else "unclassified"),
                         "active": not asset.get("isDelisted", False), "day_volume_usd": number(ctx.get("dayNtlVlm")),
                         "open_interest_units": oi, "open_interest_usd": oi * mark, "mark_px": mark,
                         "oracle_px": ctx.get("oraclePx", ""), "funding_hourly": ctx.get("funding", ""),
                         "max_leverage": asset.get("maxLeverage", ""), "sz_decimals": asset.get("szDecimals", ""),
                         "margin_mode": asset.get("marginMode", ""), "collateral_token": collateral,
                         "deployer_fee_scale": asset.get("deployerFeeScale", ""), "spot_fee_share": "", "growth_mode": asset.get("growthMode", ""),
                         "spot_base": "", "spot_quote": "", "spot_index": ""})
        print(f"{label}: {len(meta['universe'])} perp markets", flush=True)
    response = client.get({"type": "spotMetaAndAssetCtxs"}, "spot_meta_and_ctxs.json", required=True)
    meta, ctxs = response
    tokens = {t["index"]: t for t in meta["tokens"]}
    # Spot contexts include historical/inactive pair IDs omitted from universe.
    # Their `coin` key, not array position, is the stable join key.
    spot_ctx_by_coin = {ctx["coin"]: ctx for ctx in ctxs if "coin" in ctx}
    for row in rows:
        if row["venue"] == "perp" and isinstance(row["collateral_token"], int):
            row["collateral_token"] = tokens.get(row["collateral_token"], {}).get("name", row["collateral_token"])
    for asset in meta["universe"]:
        ctx = spot_ctx_by_coin.get(asset["name"], {})
        base = tokens.get(asset["tokens"][0], {}).get("name", "")
        quote = tokens.get(asset["tokens"][1], {}).get("name", "")
        rows.append({"snapshot_utc": snapshot_utc, "venue": "spot", "dex": "", "coin": asset["name"], "category": "spot", "active": True,
                     "day_volume_usd": number(ctx.get("dayNtlVlm")), "open_interest_units": "", "open_interest_usd": "",
                     "mark_px": ctx.get("markPx", ""), "oracle_px": "", "funding_hourly": "", "max_leverage": "",
                     "sz_decimals": tokens.get(asset["tokens"][0], {}).get("szDecimals", ""), "margin_mode": "",
                     "collateral_token": "", "deployer_fee_scale": "", "spot_fee_share": tokens.get(asset["tokens"][0], {}).get("deployerTradingFeeShare", ""), "growth_mode": "", "spot_base": base,
                     "spot_quote": quote, "spot_index": asset.get("index", "")})
    with (client.run_dir / "inventory.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    write_json(client.run_dir / "census_summary.json", {
        "collected_at_utc": dt.datetime.now(UTC).isoformat(), "perp_dex_count": len(dexes),
        "perp_market_count": sum(r["venue"] == "perp" for r in rows),
        "spot_market_count": sum(r["venue"] == "spot" for r in rows),
        "active_perp_count": sum(r["venue"] == "perp" and r["active"] for r in rows),
        "dex_names": [d["name"] if d else "" for d in dexes]})
    return rows


def select(rows, per_category=5):
    perps = [r for r in rows if r["venue"] == "perp" and r["active"] and r["day_volume_usd"] > 0]
    explicit = {"BTC", "ETH", "SOL", "HYPE", "NVDA", "TSLA", "HOOD", "AAPL", "GOOG", "GOOGL", "GOLD", "SILVER", "OIL", "SPX", "SP500", "USA500", "XYZ100", "EURUSD", "USDJPY", "US10Y", "10Y"}
    selected = {r["coin"]: r for r in perps if r["coin"].split(":")[-1] in explicit}
    by_cat = {}
    for r in perps:
        by_cat.setdefault(r["category"], []).append(r)
    for category, members in by_cat.items():
        members.sort(key=lambda r: (r["day_volume_usd"], r["open_interest_usd"]), reverse=True)
        for r in members[:per_category]:
            selected[r["coin"]] = r
    return sorted(selected.values(), key=lambda r: (r["category"], -r["day_volume_usd"]))


def history(client, rows, days, per_category):
    selection_path = client.run_dir / "history_selection.json"
    if selection_path.exists():
        previous = json.loads(selection_path.read_text())
        start, end = previous["start_time_ms"], previous["end_time_ms"]
    else:
        end = int(time.time() * 1000)
        start = end - days * 86400_000
    chosen = select(rows, per_category)
    write_json(client.run_dir / "history_selection.json", {"start_time_ms": start, "end_time_ms": end, "days": days, "coins": chosen})
    summary = []
    metrics = []
    for ix, row in enumerate(chosen, 1):
        coin = row["coin"]
        key = safe(coin)
        stats = {"coin": coin, "category": row["category"], "funding_rows": 0, "candle_rows": 0,
                 "funding_first_ms": None, "funding_last_ms": None, "candle_first_ms": None, "candle_last_ms": None}
        for kind in ("funding", "candles"):
            cursor = start
            seen = set()
            all_rows = []
            page = 0
            while cursor <= end and page < 10:
                if kind == "funding":
                    payload = {"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": end}
                else:
                    payload = {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": cursor, "endTime": end}}
                response = client.get(payload, f"history/{key}/{kind}_{page:02d}.json")
                if response is None:
                    break
                if not isinstance(response, list) or not response:
                    break
                for item in response:
                    t = item.get("time") if kind == "funding" else item.get("t")
                    if isinstance(t, int) and start <= t <= end and t not in seen:
                        all_rows.append(item)
                        seen.add(t)
                last = max((item.get("time") if kind == "funding" else item.get("t")) or 0 for item in response)
                page += 1
                if last < cursor or len(response) < 500:
                    break
                cursor = last + 1  # inclusive startTime; avoid duplicate boundary row
            all_rows.sort(key=lambda x: x.get("time") if kind == "funding" else x.get("t"))
            stats[f"{kind}_rows"] = len(all_rows)
            if all_rows:
                stats[f"{kind}_first_ms"] = all_rows[0].get("time") if kind == "funding" else all_rows[0].get("t")
                stats[f"{kind}_last_ms"] = all_rows[-1].get("time") if kind == "funding" else all_rows[-1].get("t")
            if kind == "funding":
                funding_rates = [number(item.get("fundingRate")) for item in all_rows]
            else:
                candle_times = [item["t"] for item in all_rows]
        summary.append(stats)
        metrics.append({"coin": coin, "category": row["category"], "day_volume_usd_snapshot": row["day_volume_usd"],
                        "open_interest_usd_snapshot": row["open_interest_usd"],
                        "funding_hours": len(funding_rates), "funding_sum_rate": sum(funding_rates),
                        "funding_mean_hourly_rate": sum(funding_rates) / len(funding_rates) if funding_rates else "",
                        "funding_positive_fraction": sum(v > 0 for v in funding_rates) / len(funding_rates) if funding_rates else "",
                        "candles": len(candle_times), "candle_missing_in_span":
                        (candle_times[-1] - candle_times[0]) // 3600_000 + 1 - len(candle_times) if candle_times else "",
                        "first_funding_ms": stats["funding_first_ms"], "last_funding_ms": stats["funding_last_ms"],
                        "first_candle_ms": stats["candle_first_ms"], "last_candle_ms": stats["candle_last_ms"]})
        print(f"history {ix}/{len(chosen)} {coin}: funding={stats['funding_rows']} candles={stats['candles_rows']}", flush=True)
        write_json(client.run_dir / "history_summary.json", summary)
        with (client.run_dir / "history_metrics.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(metrics[0]))
            writer.writeheader()
            writer.writerows(metrics)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=None, help="Resume an existing run directory")
    parser.add_argument("--census-only", action="store_true")
    parser.add_argument("--history-only", action="store_true")
    parser.add_argument("--days", type=int, default=31)
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument("--pause", type=float, default=0.18)
    args = parser.parse_args()
    run_dir = args.run_dir or ROOT / stamp()
    run_dir.mkdir(parents=True, exist_ok=True)
    client = Client(run_dir, args.pause)
    if args.history_only:
        with (run_dir / "inventory.csv").open(newline="") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            for col in ("day_volume_usd", "open_interest_usd"):
                r[col] = number(r[col])
            r["active"] = r["active"] == "True"
    else:
        rows = census(client)
    if not args.census_only:
        history(client, rows, args.days, args.per_category)
    write_json(run_dir / "errors.json", client.errors)
    write_json(run_dir / "manifest.json", {"api": API, "run_dir": str(run_dir), "completed_at_utc": dt.datetime.now(UTC).isoformat(),
                                             "new_api_calls": client.calls, "errors": len(client.errors), "history_days": args.days,
                                             "notes": "UTC timestamps; raw public API responses; cached files are reused on resume."})
    print(run_dir, flush=True)


if __name__ == "__main__":
    main()
