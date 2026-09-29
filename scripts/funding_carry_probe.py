#!/usr/bin/env python3
"""Read-only 48-hour settled-funding screen across HL, Lighter Core, and RH Lighter.

First 24 settled hours choose a direction. The following 24 hours are a small
holdout. Results are funding-only diagnostics, not executable profit estimates.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import time
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "reports/funding-carry"
HOUR_MS = 3_600_000
ASSETS = ("BTC", "ETH", "SOL", "HYPE", "ZEC", "COIN", "XAG", "NVDA")
HL_NAMES = {"COIN":"xyz:COIN", "XAG":"xyz:SILVER", "NVDA":"xyz:NVDA"}
URLS = {"hl":"https://api.hyperliquid.xyz/info",
        "lighter_core":"https://mainnet.zklighter.elliot.ai/api/v1",
        "rh_lighter":"https://api.rh.lighter.xyz/api/v1"}
EXTRA_RESERVE_BPS = 5.0  # monitor.py --extra-cost-bps, applied once per pair
FEE_CALIBRATION_DATE_UTC = "2026-09-29"


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def get_json(url, *, params=None, payload=None):
    if payload is None:
        response = requests.get(url, params=params, timeout=20)
    else:
        response = requests.post(url, json=payload, timeout=20)
    response.raise_for_status()
    return response.json(), response.url


def collect(out):
    now_ms = int(time.time()*1000)
    end_ms = (now_ms // HOUR_MS - 1) * HOUR_MS  # last fully settled hourly event
    start_ms = end_ms - 47*HOUR_MS
    manifest = {"started_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
                "window_first_event_utc":dt.datetime.fromtimestamp(start_ms/1000,dt.timezone.utc).isoformat(),
                "window_last_event_utc":dt.datetime.fromtimestamp(end_ms/1000,dt.timezone.utc).isoformat(),
                "event_hours_requested":48,"assets":ASSETS,"endpoints":{},"errors":{},"read_only":True,
                "fee_calibration_date_utc":FEE_CALIBRATION_DATE_UTC,
                "fee_note":"fixed scenario based on 2026-09-29 public schedule and archived HL market metadata; not refreshed or historically account-verified"}
    save_json(out / "raw/manifest.json", manifest)
    markets = {}
    for venue in ("lighter_core", "rh_lighter"):
        url = URLS[venue] + "/orderBookDetails"
        data, resolved = get_json(url)
        save_json(out / "raw" / venue / "markets.json", data)
        markets[venue] = {r["symbol"]:r for r in data["order_book_details"] if r["status"] == "active"}
        manifest["endpoints"][f"{venue}/markets"] = resolved
    for asset in ASSETS:
        coin = HL_NAMES.get(asset,asset)
        key = f"hl/{asset}"
        try:
            payload = {"type":"fundingHistory","coin":coin,"startTime":start_ms,"endTime":end_ms+HOUR_MS-1}
            data,_ = get_json(URLS["hl"],payload=payload)
            if not isinstance(data,list):raise ValueError("HL non-list response")
            save_json(out / "raw/hl" / (asset+".json"), data)
            manifest["endpoints"][key] = {"url":URLS["hl"],"body":payload}
        except Exception as exc:
            manifest["errors"][key] = str(exc)
        for venue in ("lighter_core","rh_lighter"):
            key = f"{venue}/{asset}"
            market = markets[venue].get(asset)
            if market is None:
                manifest["errors"][key] = "no active perp market"
                continue
            params = {"market_id":market["market_id"],"resolution":"1h",
                      "start_timestamp":start_ms//1000,
                      "end_timestamp":end_ms//1000+3599,"count_back":49}
            try:
                data,resolved = get_json(URLS[venue]+"/fundings",params=params)
                if data.get("code") != 200:raise ValueError(f"API code {data.get('code')}")
                save_json(out / "raw" / venue / (asset+".json"), data)
                manifest["endpoints"][key] = resolved
            except Exception as exc:
                manifest["errors"][key] = str(exc)
            time.sleep(1.2)  # margin under each domain's public rolling-minute limit
        print(asset,"completed",flush=True)
        save_json(out / "raw/manifest.json", manifest)
    manifest["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_json(out / "raw/manifest.json", manifest)
    return manifest


def rate_series(out, venue, asset, lo, hi):
    path = out / "raw" / venue / (asset+".json")
    if not path.exists():return {}
    data = json.loads(path.read_text())
    if venue == "hl":
        events = ((int(r["time"])//HOUR_MS*HOUR_MS,finite_rate(r["fundingRate"])) for r in data)
    else:
        # Lighter rate is PERCENT per hour, direction tells which side pays.
        events = ((int(r["timestamp"])*1000,lighter_signed_fraction(r))
                  for r in data["fundings"])
    series = {}
    for t,v in events:
        if not lo<=t<=hi:
            continue
        if t in series and not math.isclose(series[t],v,rel_tol=0,abs_tol=1e-15):
            raise ValueError(f"conflicting {venue} {asset} settled funding at {t}")
        series[t]=v
    return series


def finite_rate(value):
    rate=float(value)
    if not math.isfinite(rate):
        raise ValueError(f"nonfinite funding rate: {value}")
    return rate


def lighter_signed_fraction(event):
    """Return long-pays funding as a decimal fraction, from Lighter percent."""
    direction=event["direction"]
    if direction not in ("long","short"):
        raise ValueError(f"unknown Lighter funding payer: {direction}")
    return finite_rate(event["rate"]) / 100 * (1 if direction == "long" else -1)


def selected_side(train_differences_bps):
    """+1 means long HL/short venue; train data alone determines the side."""
    return 1 if sum(train_differences_bps) >= 0 else -1


def roundtrip_cost_bps(hl_taker_bps, venue_taker_bps, extra_cost_bps):
    """Monitor convention: entry fees + same exit-fee reserve + one extra cost."""
    four_fees = 2 * (hl_taker_bps + venue_taker_bps)
    return four_fees, four_fees + extra_cost_bps


def hl_fee_bps(asset):
    # Fixed 2026-09-29 scenario, not historical/account-specific verification.
    # Base taker 4.5bp. These xyz HIP-3 markets had 1x deployer fee scale
    # with growth mode enabled, giving 4.5*2*0.1=0.9bp/leg.
    return 0.9 if asset in ("COIN","XAG","NVDA") else 4.5


def analyze(out, extra_cost_bps=EXTRA_RESERVE_BPS, comparison_name="comparison.csv", write_hourly=True):
    manifest = json.loads((out / "raw/manifest.json").read_text())
    start = int(dt.datetime.fromisoformat(manifest["window_first_event_utc"]).timestamp()*1000)
    end = int(dt.datetime.fromisoformat(manifest["window_last_event_utc"]).timestamp()*1000)
    event_hours = [start+i*HOUR_MS for i in range(48)]
    rows, hourly = [], []
    for asset in ASSETS:
        hf = rate_series(out,"hl",asset,start,end)
        for venue in ("lighter_core","rh_lighter"):
            vf = rate_series(out,venue,asset,start,end)
            common = [t for t in event_hours if t in hf and t in vf]
            train = [t for t in event_hours[:24] if t in hf and t in vf]
            test = [t for t in event_hours[24:] if t in hf and t in vf]
            if not train or not test:
                rows.append({"asset":asset,"venue":venue,"status":"missing_settled_events",
                             "hl_events":len(hf),"venue_events":len(vf),"common_events":len(common)})
                continue
            train_differences = [(vf[t]-hf[t])*1e4 for t in train]
            train_raw = sum(train_differences)
            side = selected_side(train_differences)
            # side=+1 means long HL/short Lighter; funding receipt is venue-HL.
            test_edge = [side*(vf[t]-hf[t])*1e4 for t in test]
            train_edge = side*train_raw
            holdout_edge = sum(test_edge)
            fee_hl = hl_fee_bps(asset)
            for tier,fee_other in (("standard",0.0),("premium_base",2.8 if venue=="lighter_core" else 3.5)):
                fees,threshold=roundtrip_cost_bps(fee_hl,fee_other,extra_cost_bps)
                cumulative=0.0
                first_cross=None
                for i,bps in enumerate(test_edge,1):
                    cumulative+=bps
                    if first_cross is None and cumulative>=threshold:first_cross=i
                mean=holdout_edge/len(test_edge)
                linear_be=threshold/mean if mean>0 else None
                rows.append({"asset":asset,"venue":venue,"status":"complete" if len(train)==24 and len(test)==24 else "partial_hour_coverage",
                             "asset_class":"crypto" if asset in ("BTC","ETH","SOL","HYPE","ZEC") else "RWA_reference_review",
                             "hl_market":HL_NAMES.get(asset,asset),"venue_market":asset,
                             "direction":"long_HL_short_venue" if side==1 else "short_HL_long_venue",
                             "lighter_fee_tier":tier,"hl_fee_basis":"base_tier_fixed","fee_calibration_date_utc":FEE_CALIBRATION_DATE_UTC,
                             "fees_historical_or_account_verified":False,
                             "hl_events":len(hf),"venue_events":len(vf),"common_events":len(common),
                             "train_events":len(train),"holdout_events":len(test),
                             "train_funding_edge_bps":round(train_edge,4),
                             "holdout_funding_edge_bps":round(holdout_edge,4),
                             "holdout_positive_hours":sum(v>0 for v in test_edge),
                             "holdout_avg_bps_per_event":round(mean,5),
                             "four_taker_fees_bps":round(fees,4),
                             "extra_reserve_bps":extra_cost_bps,
                             "funding_break_even_threshold_bps":round(threshold,4),
                             "funding_less_threshold_bps":round(holdout_edge-threshold,4),
                             "first_break_even_event_in_holdout":first_cross,
                             "linear_break_even_hours_at_holdout_avg":round(linear_be,1) if linear_be is not None else None})
            for t,edge in zip(test,test_edge):
                hourly.append({"asset":asset,"venue":venue,"event_utc":dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).isoformat(),
                               "hl_long_pays_bps":round(hf[t]*1e4,6),"venue_long_pays_bps":round(vf[t]*1e4,6),
                               "selected_direction_funding_edge_bps":round(edge,6)})
    out.mkdir(parents=True,exist_ok=True)
    fields = sorted({k for row in rows for k in row})
    with (out / comparison_name).open("w",newline="") as fh:
        writer=csv.DictWriter(fh,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    if write_hourly:
        with (out / "holdout_hourly.csv").open("w",newline="") as fh:
            writer=csv.DictWriter(fh,fieldnames=list(hourly[0]) if hourly else ["asset"]);writer.writeheader();writer.writerows(hourly)
    print("analyzed",len(rows),"scenarios;",len(hourly),"holdout hourly rows")
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out",type=pathlib.Path,default=BASE)
    p.add_argument("--offline",action="store_true",help="recalculate from archived raw responses")
    p.add_argument("--extra-cost-bps",type=float,default=EXTRA_RESERVE_BPS,
                   help="one additional pair-level cost, matching monitor default 5bp")
    p.add_argument("--stress-extra-cost-bps",type=float,default=10.0,
                   help="separate stress-case pair-level cost")
    args=p.parse_args()
    if not args.offline:collect(args.out)
    analyze(args.out,args.extra_cost_bps)
    if args.stress_extra_cost_bps > args.extra_cost_bps:
        stress_name=f"comparison_stress_{args.stress_extra_cost_bps:g}bp.csv"
        analyze(args.out,args.stress_extra_cost_bps,stress_name,False)


if __name__=="__main__":main()
