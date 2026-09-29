#!/usr/bin/env python3
"""Closed-hour, out-of-sample funding and basis analysis of public venue data.

Read-only spot backfill is optional; no credentials or trading endpoints are used.
"""

import argparse
import bisect
import csv
import datetime as dt
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parents[1]
HOUR = 3_600_000
DAY = 24 * HOUR
UTC = dt.timezone.utc
DEFAULT_HL = HERE / "data/raw/hyperliquid/20260929T034903Z"
DEFAULT_COMPS = HERE / "data/raw/comparators/20260929T035055Z"
DEFAULT_OUT = HERE / "data/derived/history_20260929T035055Z"
DEFAULT_RH = HERE / "data/raw/robinhood_history_complete_20260929T040036Z.json"
RH_LIGHTER_HISTORY = HERE / "data/raw/comparators/rh_lighter/20260929T040726Z/history"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def iso_ms(s):
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def iso(t):
    return dt.datetime.fromtimestamp(t / 1000, UTC).isoformat()


def floor_hour(t):
    return t // HOUR * HOUR


def raw_hl_pages(hl, coin, kind, spot=False):
    if spot:
        files = sorted((hl / "spot_history" / coin).glob("candles_*.json"))
    else:
        files = sorted((hl / "history" / coin.replace(":", "_")).glob(f"{kind}_*.json"))
    return [item for f in files for item in read(f)]


def hl_funding(hl, coin):
    return {floor_hour(int(x["time"])): float(x["fundingRate"]) for x in raw_hl_pages(hl, coin, "funding")}


def hl_candles(hl, coin, spot=False):
    return {int(x["t"]): float(x["c"]) for x in raw_hl_pages(hl, coin, "candles", spot)}


def comp_funding(root, venue, coin):
    if venue == "rh_lighter":
        root, venue = RH_LIGHTER_HISTORY, "rh_lighter_history"
    path_venue = "" if venue == "rh_lighter_history" else venue
    f = root / path_venue / "fundings_30d" / f"{coin}.json"
    if not f.exists():
        return {}
    a = read(f)
    if venue in ("lighter", "rh_lighter_history"):
        # Lighter `rate` is a percent per hour, not a fraction. A `short`
        # direction means the short pays, hence a negative long-pays rate.
        return {int(x["timestamp"]) * 1000: float(x["rate"]) / 100 * (1 if x["direction"] == "long" else -1)
                for x in a["fundings"]}
    if venue == "aster":
        return {int(x["fundingTime"]): float(x["fundingRate"]) for x in a}
    if venue == "dydx":
        return {floor_hour(iso_ms(x["effectiveAt"])): float(x["rate"]) for x in a["historicalFunding"]}
    raise ValueError(venue)


def comp_candles(root, venue, coin):
    if venue == "rh_lighter":
        root, venue = RH_LIGHTER_HISTORY, "rh_lighter_history"
    path_venue = "" if venue == "rh_lighter_history" else venue
    f = root / path_venue / "candles_30d" / f"{coin}.json"
    if not f.exists():
        return {}
    a = read(f)
    if venue in ("lighter", "rh_lighter_history"):
        return {int(x["t"]): float(x["c"]) for x in a["c"]}
    if venue == "aster":
        return {int(x[0]): float(x[4]) for x in a}
    if venue == "dydx":
        return {iso_ms(x["startedAt"]): float(x["close"]) for x in a["candles"]}
    raise ValueError(venue)


def comp_candle_volumes(root, venue, coin):
    if venue == "rh_lighter":
        root, venue = RH_LIGHTER_HISTORY, "rh_lighter_history"
    path_venue = "" if venue == "rh_lighter_history" else venue
    f = root / path_venue / "candles_30d" / f"{coin}.json"
    if not f.exists():
        return {}
    a = read(f)
    if venue in ("lighter", "rh_lighter_history"):
        return {int(x["t"]): float(x["V"]) for x in a["c"]}
    if venue == "aster":
        return {int(x[0]): float(x[7]) for x in a}
    if venue == "dydx":
        return {iso_ms(x["startedAt"]): float(x["usdVolume"]) for x in a["candles"]}
    raise ValueError(venue)


def fetch_spot(hl, pause):
    from hyperliquid_collect import Client

    inventory = list(csv.DictReader((hl / "inventory.csv").open()))
    selection = read(hl / "history_selection.json")
    spot_by_base = {x["spot_base"]: x["coin"] for x in inventory if x["venue"] == "spot" and x["spot_quote"] == "USDC"}
    client = Client(hl, pause)
    summary = []
    for base in ("UBTC", "UETH", "USOL", "HYPE", "UZEC"):
        coin = spot_by_base[base]
        cursor, end = selection["start_time_ms"], selection["end_time_ms"]
        seen = set()
        page = 0
        while cursor <= end and page < 10:
            payload = {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": cursor, "endTime": end}}
            a = client.get(payload, f"spot_history/{base}/candles_{page:02d}.json", required=True)
            if not a:
                break
            seen.update(x["t"] for x in a)
            last = max(x["t"] for x in a)
            page += 1
            if len(a) < 500:
                break
            cursor = last + 1
        summary.append({"base": base, "coin": coin, "pages": page, "distinct_candles": len(seen),
                        "first_ms": min(seen) if seen else None, "last_ms": max(seen) if seen else None})
        print("spot", base, coin, len(seen), flush=True)
    write(hl / "spot_history_summary.json", summary)
    write(hl / "spot_history_errors.json", client.errors)
    return summary


def fetch_rh_quote_candles(rh_path, out, pause=8.0):
    """Archive Gecko base-token prices denominated in the actual pool quote."""
    pools = read(rh_path)["pools"]
    target = out / "rh_quote_candles_raw.json"
    result = read(target) if target.exists() else {}
    crosscheck = out / "amzn_gecko_crosscheck_raw.json"
    if "AMZN" not in result and crosscheck.exists():
        amzn = read(crosscheck)["primary_token"]
        result["AMZN"] = {"url": amzn["url"], "response": amzn["response"]}
        write(target, result)
    for symbol in ("AAPL", "NVDA", "GOOGL", "MSFT", "TSLA", "AMZN", "META"):
        if symbol in result:
            continue
        url = pools[symbol]["url"].replace("currency=usd", "currency=token")
        request = urllib.request.Request(url, headers={"User-Agent": "rhhype-research/1.0", "Accept": "application/json"})
        last = None
        for attempt in range(6):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = json.load(response)
                result[symbol] = {"url": url, "response": body}
                write(target, result)
                print("RH quote candles", symbol, len(body["data"]["attributes"]["ohlcv_list"]), flush=True)
                break
            except Exception as exc:
                last = str(exc)
                time.sleep(min(60, 8 * 2 ** attempt))
        else:
            raise RuntimeError(f"RH quote candles {symbol}: {last}")
        time.sleep(pause)
    write(target, result)
    return result


def nearest_price(candles, event_time):
    # Funding settles at event_time for the immediately preceding closed hour.
    return candles.get(floor_hour(event_time) - HOUR)


def funding_summary(events, lo, hi):
    return sum(rate for t, rate in events.items() if lo < t <= hi)


def funding_dollars(events, candles, lo, hi):
    payment = 0.0
    missing = 0
    for t, rate in events.items():
        if lo < t <= hi:
            px = nearest_price(candles, t)
            if px is None:
                missing += 1
            else:
                payment += rate * px
    return payment, missing


def count_events(events, lo, hi):
    return sum(lo < t <= hi for t in events)


def fee_hl_taker_bps(inventory, coin):
    x = inventory[coin]
    scale = float(x["deployer_fee_scale"]) if x["deployer_fee_scale"] else None
    if scale is None:
        return 4.5
    mult = scale + 1 if scale < 1 else scale * 2
    growth = 0.1 if x["growth_mode"] == "enabled" else 1
    return 4.5 * mult * growth


def roundtrip_fee_bps(entry_prices, exit_prices, per_side_fees_bps, denominator):
    """Fee percent of each leg's own entry/exit notional, in initial-base bps."""
    if denominator is None or any(p is None for p in (*entry_prices, *exit_prices)):
        return None
    return sum(fee * (entry + exit) / denominator for fee, entry, exit
               in zip(per_side_fees_bps, entry_prices, exit_prices))


def pct(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    i = (len(ordered) - 1) * quantile
    lo = int(i)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (i - lo)


def rh_multiplier_at(symbol_data, timestamp_seconds):
    event_source = symbol_data.get("effectiveEvents", symbol_data.get("events", []))
    events = sorted((int(x["effectiveAtTimestamp"]), i, x) for i, x in enumerate(event_source)
                    if x.get("type") == "update" and x.get("effectiveAtTimestamp") is not None)
    if not events:
        return float(symbol_data["currentMultiplier"])
    times = [(e[0], e[1]) for e in events]
    idx = bisect.bisect_right(times, (timestamp_seconds, 10**12)) - 1
    raw = events[idx][2]["newMultiplierRaw"] if idx >= 0 else events[0][2]["oldMultiplierRaw"]
    return int(raw) / 1e18


def rh_session(hour_start):
    local = dt.datetime.fromtimestamp((hour_start + HOUR // 2) / 1000, ZoneInfo("America/New_York"))
    if local.weekday() >= 5:
        return "weekend"
    clock = local.hour * 60 + local.minute
    return "regular" if 9 * 60 + 30 <= clock < 16 * 60 else "offhours"


def rh_overnight(hour_start):
    local = dt.datetime.fromtimestamp((hour_start + HOUR // 2) / 1000, ZoneInfo("America/New_York"))
    clock = local.hour * 60 + local.minute
    # Stock overnight feed: Sunday 8 PM through Friday 4 AM ET segments.
    return (clock >= 20 * 60 and local.weekday() in (6, 0, 1, 2, 3)) or (clock < 4 * 60 and local.weekday() in (0, 1, 2, 3, 4))


def rh_summary_rows(hl, rh_path, multiplier_path, out, start, split, end):
    rh = read(rh_path)["pools"]
    quote_path = out / "rh_quote_candles_raw.json"
    quotes = read(quote_path) if quote_path.exists() else {}
    multipliers = read(multiplier_path)["symbols"]
    rows = []
    hourly = []
    for symbol in ("AAPL", "NVDA", "GOOGL", "MSFT", "TSLA", "AMZN", "META"):
        sd = multipliers[symbol]
        if not sd.get("lastEffectiveEventMatchesCurrent", True):
            raise ValueError(f"{symbol}: multiplier timeline does not anchor to registry current value")
        hc = hl_candles(hl, f"xyz:{symbol}")
        quote_bars = {int(bar[0]) * 1000: bar for bar in quotes.get(symbol, {}).get("response", {}).get("data", {}).get("attributes", {}).get("ohlcv_list", [])}
        effective_hours = {int(x["effectiveAtTimestamp"]) * 1000 // HOUR * HOUR
                           for x in sd.get("effectiveEvents", sd.get("events", []))
                           if x.get("type") == "update" and x.get("effectiveAtTimestamp") is not None}
        records = []
        for bar in rh[symbol]["ohlcv"]:
            t = int(bar[0]) * 1000
            if not (start <= t < end) or t not in hc or t in effective_hours:
                continue  # update inside an hourly candle can mix two token/share ratios
            mult = rh_multiplier_at(sd, int(bar[0]))
            if mult <= 0:
                continue
            share_px = float(bar[4]) / mult
            quote_bar = quote_bars.get(t)
            quote_share_px = float(quote_bar[4]) / mult if quote_bar else None
            hl_px = hc[t]
            spread = (share_px / hl_px - 1) * 1e4
            quote_spread = (quote_share_px / hl_px - 1) * 1e4 if quote_share_px else None
            record = {"symbol": symbol, "hour_utc": iso(t), "hour_ms": t, "session_et": rh_session(t),
                      "rh_token_close_usd": float(bar[4]), "rh_shares_per_token": mult,
                      "rh_share_close_usd": share_px, "hl_perp_close_usd": hl_px,
                      "signed_rh_minus_hl_bps": spread, "abs_basis_bps": abs(spread),
                      "rh_share_close_usdg": quote_share_px, "signed_rh_quote_minus_hl_bps": quote_spread,
                      "gecko_implied_usdg_usd_factor": float(bar[4]) / float(quote_bar[4]) if quote_bar and float(quote_bar[4]) else None,
                      "rh_pool_volume_usd_hour": float(bar[5]), "holdout": t >= split}
            records.append(record)
            hourly.append(record)
        if not records:
            continue
        bases = [r["signed_rh_minus_hl_bps"] for r in records]
        absbases = [abs(v) for v in bases]
        regular = [r["abs_basis_bps"] for r in records if r["session_et"] == "regular"]
        weekend = [r["abs_basis_bps"] for r in records if r["session_et"] == "weekend"]
        volume1000 = [r["abs_basis_bps"] for r in records if r["rh_pool_volume_usd_hour"] >= 1000]
        holdout = [r["signed_rh_minus_hl_bps"] for r in records if r["holdout"]]
        quote_records = [r for r in records if r["signed_rh_quote_minus_hl_bps"] is not None]
        quote_bases = [r["signed_rh_quote_minus_hl_bps"] for r in quote_records]
        quote_abs = [abs(v) for v in quote_bases]
        factors = [r["gecko_implied_usdg_usd_factor"] for r in quote_records]
        quote_holdout = [r["signed_rh_quote_minus_hl_bps"] for r in quote_records if r["holdout"]]
        quote_regular = [abs(r["signed_rh_quote_minus_hl_bps"]) for r in quote_records if r["session_et"] == "regular"]
        quote_weekend = [abs(r["signed_rh_quote_minus_hl_bps"]) for r in quote_records if r["session_et"] == "weekend"]
        rows.append({"symbol": symbol, "paired_hours": len(records), "coverage_fraction_of_720h": len(records) / 720,
                     "multiplier_update_hours_skipped": sum(start <= t < end for t in effective_hours),
                     "median_signed_basis_bps": statistics.median(bases), "p10_signed_basis_bps": pct(bases, 0.1),
                     "p90_signed_basis_bps": pct(bases, 0.9), "median_abs_basis_bps": statistics.median(absbases),
                     "p90_abs_basis_bps": pct(absbases, 0.9),
                     "share_hours_abs_gt_25bp": sum(v > 25 for v in absbases) / len(absbases),
                     "share_hours_abs_gt_50bp": sum(v > 50 for v in absbases) / len(absbases),
                     "regular_hours": len(regular), "regular_median_abs_bps": statistics.median(regular) if regular else None,
                     "weekend_hours": len(weekend), "weekend_median_abs_bps": statistics.median(weekend) if weekend else None,
                     "hours_rh_volume_ge_1000usd": len(volume1000),
                     "median_abs_bps_at_rh_volume_ge_1000usd": statistics.median(volume1000) if volume1000 else None,
                     "holdout_hours": len(holdout), "holdout_median_signed_basis_bps": statistics.median(holdout) if holdout else None})
        rows[-1].update({"quote_paired_hours": len(quote_records),
                         "quote_median_signed_basis_bps": statistics.median(quote_bases) if quote_bases else None,
                         "quote_median_abs_basis_bps": statistics.median(quote_abs) if quote_abs else None,
                         "quote_p90_abs_basis_bps": pct(quote_abs, 0.9),
                         "quote_hours_abs_gt_25bp": sum(v > 25 for v in quote_abs) / len(quote_abs) if quote_abs else None,
                         "quote_regular_median_abs_bps": statistics.median(quote_regular) if quote_regular else None,
                         "quote_weekend_median_abs_bps": statistics.median(quote_weekend) if quote_weekend else None,
                         "quote_holdout_median_signed_basis_bps": statistics.median(quote_holdout) if quote_holdout else None,
                         "gecko_usdg_usd_factor_median": statistics.median(factors) if factors else None,
                         "gecko_usdg_usd_factor_p90": pct(factors, 0.9)})
    return rows, hourly


def analyze_pair(hl, comp, inv, hl_coin, venue, other_coin, start, split, end, match_type, price_multiplier=1):
    hf = hl_funding(hl, hl_coin)
    hc = hl_candles(hl, hl_coin)
    cf = comp_funding(comp, venue, other_coin)
    cc = comp_candles(comp, venue, other_coin)
    cv = comp_candle_volumes(comp, venue, other_coin)
    if not cf or not cc:
        return None, []
    if venue in ("lighter", "rh_lighter", "dydx"):
        # These settle hourly. Compare only hours observed at both venues;
        # RH-domain Lighter begins one hour later than the common window.
        common_funding_hours = set(hf) & set(cf)
        hf = {t: rate for t, rate in hf.items() if t in common_funding_hours}
        cf = {t: rate for t, rate in cf.items() if t in common_funding_hours}
    hc = {t: p for t, p in hc.items() if start <= t < end}
    cc = {t: p * price_multiplier for t, p in cc.items() if start <= t < end}
    paired = sorted(set(hc) & set(cc))
    holdout_volumes = [cv[t] for t in paired if split <= t < end and t in cv]
    zero_volume_fraction = sum(v == 0 for v in holdout_volumes) / len(holdout_volumes) if holdout_volumes else None
    price_history_usable = zero_volume_fraction is not None and zero_volume_fraction <= 0.10
    train_h, train_c = funding_summary(hf, start, split), funding_summary(cf, start, split)
    side = -1 if train_h >= train_c else 1  # -1 short HL/long comparator
    train_edge = side * (train_c - train_h) * 1e4
    train_last7_edge = side * (funding_summary(cf, split - 7 * DAY, split) - funding_summary(hf, split - 7 * DAY, split)) * 1e4
    hold_h, hold_c = funding_summary(hf, split, end), funding_summary(cf, split, end)
    hold_edge = side * (hold_c - hold_h) * 1e4
    daily = []
    for i in range(10):
        lo, hi = split + i * DAY, split + (i + 1) * DAY
        day_edge = side * (funding_summary(cf, lo, hi) - funding_summary(hf, lo, hi)) * 1e4
        daily.append({"pair": f"{hl_coin}|{venue}:{other_coin}", "day": i + 1, "start_utc": iso(lo),
                      "funding_edge_bps": day_edge, "funding_positive": day_edge > 0})
    overnight_event_times = [t for t in cf if split < t <= end and rh_overnight(t - HOUR)] if venue == "rh_lighter" else []
    overnight_edge = side * sum(cf[t] - hf.get(t, 0) for t in overnight_event_times) * 1e4 if overnight_event_times else None
    entry = split - HOUR
    final = end - HOUR
    init_h, init_c = hc.get(entry), cc.get(entry)
    final_h, final_c = hc.get(final), cc.get(final)
    basis_bps = None
    if price_history_usable and all(p is not None for p in (init_h, init_c, final_h, final_c)):
        basis_bps = side * ((final_h - init_h) - (final_c - init_c)) / init_h * 1e4
    hpay, hmiss = funding_dollars(hf, hc, split, end)
    cpay, cmiss = funding_dollars(cf, cc, split, end)
    funding_cash_bps = side * (cpay - hpay) / init_h * 1e4 if init_h and hmiss == 0 and cmiss == 0 else None
    gross_bps = basis_bps + funding_cash_bps if basis_bps is not None and funding_cash_bps is not None else None
    hl_fee = fee_hl_taker_bps(inv, hl_coin)
    other_fee = {"lighter": 0, "rh_lighter": 0, "aster": 4, "dydx": 5}[venue]
    roundtrip_fee = roundtrip_fee_bps((init_h, init_c), (final_h, final_c), (hl_fee, other_fee), init_h)
    finance = 0.05 * 0.4 * 10 / 365 * 1e4
    # A shared ticker need not imply a deliverable/fungible contract. Only
    # major crypto pairs get the fixed-unit economic result; other classes
    # remain funding/price-reference diagnostics.
    fixed_unit = match_type == "same_underlying" and price_history_usable
    comparable_reference = price_history_usable and match_type in {"synthetic_equity_proxy", "commodity_proxy", "fx_quote_proxy", "index_reference_proxy"}
    return {
        "pair": f"{hl_coin}|{venue}:{other_coin}", "match_type": match_type, "hl_coin": hl_coin, "venue": venue,
        "other_coin": other_coin, "price_multiplier": price_multiplier, "paired_closed_candles": len(paired),
        "paired_holdout_candles": sum(split <= t < end for t in paired),
        "other_zero_volume_holdout_fraction": zero_volume_fraction,
        "price_history_usable": price_history_usable,
        "train_hl_events": count_events(hf, start, split), "train_other_events": count_events(cf, start, split),
        "holdout_hl_events": count_events(hf, split, end), "holdout_other_events": count_events(cf, split, end),
        "side_hl": "long" if side == 1 else "short", "train_funding_edge_bps": train_edge,
        "train_last7d_funding_edge_bps": train_last7_edge,
        "train_last7d_agrees_20d": train_last7_edge >= 0,
        "holdout_funding_edge_bps": hold_edge, "holdout_funding_win_days": sum(x["funding_positive"] for x in daily),
        "rh_overnight_funding_hours": len(overnight_event_times) if venue == "rh_lighter" else None,
        "rh_overnight_funding_edge_bps": overnight_edge,
        "worst_funding_day_bps": min(x["funding_edge_bps"] for x in daily),
        "basis_change_bps": basis_bps if fixed_unit else None,
        "estimated_funding_cash_bps": funding_cash_bps if fixed_unit else None,
        "gross_fixed_unit_bps": gross_bps if fixed_unit else None,
        "proxy_basis_change_bps": basis_bps if comparable_reference else None,
        "proxy_combined_change_bps": gross_bps if comparable_reference else None,
        "hl_taker_fee_bps_per_side": hl_fee, "other_taker_fee_bps_per_side": other_fee,
        "known_roundtrip_taker_fees_bps": roundtrip_fee,
        "gross_minus_known_fees_bps": gross_bps - roundtrip_fee if fixed_unit and gross_bps is not None and roundtrip_fee is not None else None,
        "illustrative_5pct_financing_40pct_capital_bps": finance if fixed_unit else None,
        "gross_minus_fees_financing_bps": gross_bps - roundtrip_fee - finance if fixed_unit and gross_bps is not None and roundtrip_fee is not None else None,
        "fee_sensitivity_10bps": gross_bps - 10 if fixed_unit and gross_bps is not None else None,
        "fee_sensitivity_20bps": gross_bps - 20 if fixed_unit and gross_bps is not None else None,
        "fee_sensitivity_40bps": gross_bps - 40 if fixed_unit and gross_bps is not None else None,
        "funding_price_missing_events": hmiss + cmiss,
    }, daily


def analyze_cash(hl, inv, base, spot_key, perp_coin, start, split, end):
    sf = hl_candles(hl, base, spot=True)
    pf = hl_candles(hl, perp_coin)
    fr = hl_funding(hl, perp_coin)
    sf = {t: v for t, v in sf.items() if start <= t < end}
    pf = {t: v for t, v in pf.items() if start <= t < end}
    paired = sorted(set(sf) & set(pf))
    entry, final = split - HOUR, end - HOUR
    if not all(t in sf and t in pf for t in (entry, final)):
        return None, []
    initial = sf[entry]
    basis = ((sf[final] - sf[entry]) - (pf[final] - pf[entry])) / initial * 1e4
    payment, missing = funding_dollars(fr, pf, split, end)
    fund_bps = payment / initial * 1e4 if missing == 0 else None
    gross = basis + fund_bps if fund_bps is not None else None
    daily = []
    for i in range(10):
        lo, hi = split + i * DAY, split + (i + 1) * DAY
        day_rate = funding_summary(fr, lo, hi) * 1e4
        daily.append({"pair": f"{spot_key}|{perp_coin}", "day": i + 1, "start_utc": iso(lo),
                      "funding_edge_bps": day_rate, "funding_positive": day_rate > 0})
    fee = roundtrip_fee_bps((sf[entry], pf[entry]), (sf[final], pf[final]),
                            (7, fee_hl_taker_bps(inv, perp_coin)), initial)
    finance = 0.05 * 1.2 * 10 / 365 * 1e4
    return {"pair": f"{spot_key}|{perp_coin}", "spot_base": base, "spot_coin": spot_key, "perp_coin": perp_coin,
            "paired_closed_candles": len(paired), "paired_holdout_candles": sum(split <= t < end for t in paired),
            "train_funding_bps": funding_summary(fr, start, split) * 1e4,
            "holdout_funding_bps": funding_summary(fr, split, end) * 1e4,
            "holdout_funding_win_days": sum(x["funding_positive"] for x in daily),
            "worst_funding_day_bps": min(x["funding_edge_bps"] for x in daily),
            "basis_change_bps": basis, "estimated_funding_cash_bps": fund_bps,
            "gross_fixed_unit_bps": gross, "known_roundtrip_taker_fees_bps": fee,
            "gross_minus_known_fees_bps": gross - fee if gross is not None else None,
            "illustrative_5pct_financing_120pct_capital_bps": finance,
            "gross_minus_fees_financing_bps": gross - fee - finance if gross is not None else None,
            "fee_sensitivity_10bps": gross - 10 if gross is not None else None,
            "fee_sensitivity_20bps": gross - 20 if gross is not None else None,
            "fee_sensitivity_40bps": gross - 40 if gross is not None else None,
            "funding_price_missing_events": missing}, daily


def analyze_rh_lighter_cash(symbol, multipliers, start, split, end):
    sd = multipliers[symbol]
    updates_in_holdout = [x for x in sd.get("effectiveEvents", sd.get("events", []))
                          if x.get("type") == "update" and split < int(x["effectiveAtTimestamp"]) * 1000 <= end]
    if updates_in_holdout:
        return None, []  # would require a dynamically rebalanced hedge ratio
    shares_per_token = rh_multiplier_at(sd, split // 1000)
    spot = comp_candles(DEFAULT_COMPS, "rh_lighter", f"{symbol}_USDG")
    spot_volume = comp_candle_volumes(DEFAULT_COMPS, "rh_lighter", f"{symbol}_USDG")
    perp = comp_candles(DEFAULT_COMPS, "rh_lighter", symbol)
    funding = comp_funding(DEFAULT_COMPS, "rh_lighter", symbol)
    entry, final = split - HOUR, end - HOUR
    if not all(t in spot and t in perp for t in (entry, final)):
        return None, []
    holdout_volumes = [spot_volume[t] for t in sorted(set(spot) & set(perp)) if split <= t < end and t in spot_volume]
    zero_fraction = sum(v == 0 for v in holdout_volumes) / len(holdout_volumes) if holdout_volumes else 1
    price_history_usable = zero_fraction <= 0.10
    initial = spot[entry]
    basis = ((spot[final] - spot[entry]) - shares_per_token * (perp[final] - perp[entry])) / initial * 1e4
    payment, missing = funding_dollars(funding, perp, split, end)
    fund_cash = shares_per_token * payment / initial * 1e4 if missing == 0 else None
    gross = basis + fund_cash if fund_cash is not None else None
    daily = []
    for i in range(10):
        lo, hi = split + i * DAY, split + (i + 1) * DAY
        day_rate = funding_summary(funding, lo, hi) * 1e4
        daily.append({"pair": f"rh_lighter:{symbol}_USDG|{symbol}", "day": i + 1, "start_utc": iso(lo),
                      "funding_edge_bps": day_rate, "funding_positive": day_rate > 0})
    finance = 0.05 * 1.2 * 10 / 365 * 1e4
    return {"pair": f"rh_lighter:{symbol}_USDG|{symbol}", "spot_token": symbol,
            "shares_per_token_at_entry": shares_per_token,
            "paired_closed_candles": len({t for t in spot if start <= t < end} & {t for t in perp if start <= t < end}),
            "paired_holdout_candles": len({t for t in spot if split <= t < end} & {t for t in perp if split <= t < end}),
            "train_funding_bps": funding_summary(funding, start, split) * 1e4,
            "holdout_funding_bps": funding_summary(funding, split, end) * 1e4,
            "holdout_funding_win_days": sum(x["funding_positive"] for x in daily),
            "worst_funding_day_bps": min(x["funding_edge_bps"] for x in daily),
            "spot_zero_volume_holdout_fraction": zero_fraction,
            "entry_spot_candle_quote_volume": spot_volume.get(entry), "exit_spot_candle_quote_volume": spot_volume.get(final),
            "price_history_usable": price_history_usable,
            "basis_change_bps": basis if price_history_usable else None,
            "estimated_funding_cash_bps": fund_cash if price_history_usable else None,
            "gross_fixed_token_bps": gross if price_history_usable else None,
            "raw_endpoint_formula_bps_for_audit_only": gross if not price_history_usable else None,
            "api_standard_roundtrip_taker_fees_bps": 0.0,
            "illustrative_5pct_financing_120pct_capital_bps": finance,
            "gross_minus_illustrative_financing_bps": gross - finance if gross is not None and price_history_usable else None,
            "funding_price_missing_events": missing}, daily


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hl", type=Path, default=DEFAULT_HL)
    ap.add_argument("--comparators", type=Path, default=DEFAULT_COMPS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--fetch-spot", action="store_true")
    ap.add_argument("--rh-history", type=Path, default=DEFAULT_RH)
    ap.add_argument("--rh-multipliers", type=Path, default=None)
    ap.add_argument("--fetch-rh-quote", action="store_true")
    ap.add_argument("--pause", type=float, default=0.6, help="Seconds between Hyperliquid spot history requests")
    args = ap.parse_args()
    if args.fetch_spot:
        fetch_spot(args.hl, max(args.pause, 0.55))
    if args.fetch_rh_quote:
        fetch_rh_quote_candles(args.rh_history, args.out)
    hl_manifest = read(args.hl / "history_selection.json")
    comp_manifest = read(args.comparators / "manifest.json")
    last_closed_start = min(floor_hour(hl_manifest["end_time_ms"]), floor_hour(iso_ms(comp_manifest["collected_at_utc"]))) - HOUR
    end = last_closed_start + HOUR
    start = end - 30 * DAY
    split = start + 20 * DAY
    inventory = {x["coin"]: x for x in csv.DictReader((args.hl / "inventory.csv").open()) if x["venue"] == "perp"}
    pair_specs = [
        (c, v, c, "same_underlying", 1) for c in ("BTC", "ETH", "SOL", "HYPE") for v in ("lighter", "aster", "dydx")
    ] + [
        ("BTC", "rh_lighter", "BTC", "same_underlying", 1),
        ("ETH", "rh_lighter", "ETH", "same_underlying", 1),
        ("SOL", "rh_lighter", "SOL", "same_underlying", 1),
        ("HYPE", "rh_lighter", "HYPE", "same_underlying", 1),
        ("ZEC", "lighter", "ZEC", "same_underlying", 1),
        ("ZEC", "aster", "ZEC", "same_underlying", 1),
        ("ZEC", "dydx", "ZEC", "same_underlying", 1),
        ("xyz:NVDA", "lighter", "NVDA", "synthetic_equity_proxy", 1),
        ("xyz:NVDA", "aster", "NVDA", "synthetic_equity_proxy", 1),
        ("xyz:NVDA", "rh_lighter", "NVDA", "synthetic_equity_proxy", 1),
        ("xyz:AAPL", "rh_lighter", "AAPL", "synthetic_equity_proxy", 1),
        ("xyz:META", "rh_lighter", "META", "synthetic_equity_proxy", 1),
        ("xyz:MSFT", "rh_lighter", "MSFT", "synthetic_equity_proxy", 1),
        ("xyz:GOLD", "lighter", "XAU", "commodity_proxy", 1),
        ("xyz:GOLD", "aster", "XAU", "commodity_proxy", 1),
        ("xyz:GOLD", "rh_lighter", "XAU", "commodity_proxy", 1),
        ("xyz:SILVER", "lighter", "XAG", "commodity_proxy", 1),
        ("xyz:SILVER", "aster", "XAG", "commodity_proxy", 1),
        ("xyz:SILVER", "dydx", "XAG", "commodity_proxy", 1),
        ("xyz:SILVER", "rh_lighter", "XAG", "commodity_proxy", 1),
        ("xyz:SP500", "lighter", "SPY", "index_etf_proxy", 10),
        ("xyz:SP500", "aster", "SPY", "index_etf_proxy", 10),
        ("xyz:SP500", "rh_lighter", "SPY", "index_etf_proxy", 10),
        ("xyz:SP500", "lighter", "US500", "index_reference_proxy", 1),
        ("xyz:XYZ100", "lighter", "US100", "index_reference_proxy", 1),
        ("xyz:BRENTOIL", "lighter", "BRENTOIL", "commodity_proxy", 1),
        ("xyz:EUR", "lighter", "EURUSD", "fx_quote_proxy", 1),
    ]
    pairs, daily = [], []
    for spec in pair_specs:
        row, days = analyze_pair(args.hl, args.comparators, inventory, *spec[:3], start, split, end, *spec[3:])
        if row:
            assert len(days) == 10
            assert abs(sum(d["funding_edge_bps"] for d in days) - row["holdout_funding_edge_bps"]) < 1e-7
            if row["gross_fixed_unit_bps"] is not None:
                assert abs(row["basis_change_bps"] + row["estimated_funding_cash_bps"] - row["gross_fixed_unit_bps"]) < 1e-7
            pairs.append(row)
            daily.extend(days)
    cash, cash_daily = [], []
    for base, spot, perp in (("UBTC", "@142", "BTC"), ("UETH", "@151", "ETH"), ("USOL", "@156", "SOL"),
                             ("HYPE", "@107", "HYPE"), ("UZEC", "@272", "ZEC")):
        row, days = analyze_cash(args.hl, inventory, base, spot, perp, start, split, end)
        if row:
            assert len(days) == 10
            assert abs(sum(d["funding_edge_bps"] for d in days) - row["holdout_funding_bps"]) < 1e-7
            if row["gross_fixed_unit_bps"] is not None:
                assert abs(row["basis_change_bps"] + row["estimated_funding_cash_bps"] - row["gross_fixed_unit_bps"]) < 1e-7
            cash.append(row)
            cash_daily.extend(days)
    rh_cash, rh_cash_daily = [], []
    if args.rh_multipliers:
        mults = read(args.rh_multipliers)["symbols"]
        for symbol in ("NVDA", "SPY"):
            row, days = analyze_rh_lighter_cash(symbol, mults, start, split, end)
            if row:
                assert abs(sum(d["funding_edge_bps"] for d in days) - row["holdout_funding_bps"]) < 1e-7
                if row["gross_fixed_token_bps"] is not None:
                    assert abs(row["basis_change_bps"] + row["estimated_funding_cash_bps"] - row["gross_fixed_token_bps"]) < 1e-7
                rh_cash.append(row)
                rh_cash_daily.extend(days)
    write_csv(args.out / "history_perp_pairs.csv", pairs, list(pairs[0]))
    write_csv(args.out / "history_cash_carry.csv", cash, list(cash[0]) if cash else ["pair"])
    write_csv(args.out / "history_rh_lighter_cash.csv", rh_cash, list(rh_cash[0]) if rh_cash else ["pair"])
    write_csv(args.out / "history_daily_funding.csv", daily + cash_daily + rh_cash_daily, ["pair", "day", "start_utc", "funding_edge_bps", "funding_positive"])
    rh_rows = []
    if args.rh_multipliers:
        rh_rows, rh_hourly = rh_summary_rows(args.hl, args.rh_history, args.rh_multipliers, args.out, start, split, end)
        write_csv(args.out / "history_robinhood_hl_basis.csv", rh_rows, list(rh_rows[0]))
        write_csv(args.out / "history_robinhood_hl_hourly.csv", rh_hourly, list(rh_hourly[0]))
    write(args.out / "history_manifest.json", {"source_hyperliquid": str(args.hl), "source_comparators": str(args.comparators),
        "window_start_utc": iso(start), "train_end_holdout_start_utc": iso(split), "window_end_exclusive_utc": iso(end),
        "closed_hours": 720, "train_hours": 480, "holdout_hours": 240, "pair_rows": len(pairs), "cash_rows": len(cash), "rh_lighter_cash_rows": len(rh_cash),
        "rh_basis_rows": len(rh_rows), "rh_multiplier_source": str(args.rh_multipliers) if args.rh_multipliers else None,
        "rate_sign": "positive means long pays short", "lighter_rate_unit": "percent per hour converted to fraction",
        "basis_price": "closing trade price of fully closed hour; not executable price",
        "funding_cash_price": "preceding-hour candle close proxy; true funding uses venue oracle/mark",
        "fee_assumptions": "Hyperliquid tier-0 and per-asset HIP-3 multiplier; Lighter Standard 0; Aster USDT tier-0 4bp; dYdX tier-0 5bp from archived on-chain fee params; fees charged on each leg's own entry and exit candle notional",
        "rh_lighter_source": str(RH_LIGHTER_HISTORY),
        "cash_financing_sensitivity": "5% annual simple cost on 120% of initial spot notional (100% spot plus 20% perp margin) for 10/365 year; illustrative, not a quoted borrow rate",
        "perp_financing_sensitivity": "5% annual simple cost on 40% of initial underlying notional (20% margin on each of two perp legs) for 10/365 year; illustrative, not a quoted borrow rate",
        "identity_checks": "All 10 daily funding rows sum to the reported holdout rate edge; fixed-unit gross equals basis change plus estimated funding cash."})
    print(args.out)
    print(f"pairs={len(pairs)} cash={len(cash)} window={iso(start)} to {iso(end)}", flush=True)


if __name__ == "__main__":
    main()
