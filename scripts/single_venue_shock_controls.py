"""Exploratory local-shock comparison with fixed earlier ordinary observations.

Reuses the original detector, raw adapter and depth walker. No orders, portfolio
simulation, live requests, fitted parameters or independent-sample claims.
"""
from collections import Counter, defaultdict
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts import single_venue_broad_relative as broad
from scripts.audit_single_venue_study import clock, pair, NS, VS
from scripts.single_venue_depth_strategy import Detector
from scripts.single_venue_residual_profile import exactmid, sweep
from scripts.single_venue_strategy import dec, rounded
from scripts.single_venue_broad_quotes import distribution

PLAN = ROOT / "reports/experiment-storage/single-venue-shock-controls-adapter-fix-v1.json"
OUTPUT = ROOT / "reports/single-venue-research/shock-controls.json.gz"
DELAY = 400_000_000
HOLD = 10 * NS


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spread_bucket(value):
    return "below1" if value < 1 else "1to3" if value < 3 else "3to10" if value < 10 else "atleast10"


def select_control(anchors, signal):
    """Use decision-time features only; never inspect a candidate's outcome."""
    target = signal["t"] - 30 * NS
    timed = [a for a in anchors if abs(a["t"] - target) <= 2 * NS]
    quiet = [a for a in timed if a["quiet_at_decision"]]
    wanted = spread_bucket(signal["pre"]["spreads"][signal["venue"]])
    eligible = [a for a in quiet if a["spread_bucket"] == wanted]
    if not timed:
        return None, "no_control_in_fixed_time_band"
    if not quiet:
        return None, "control_band_has_recent_shock"
    if not eligible:
        return None, "control_spread_bucket_differs"
    return min(eligible, key=lambda a: (abs(a["t"] - target), a["t"])), "selected"


class QuoteProfiles:
    """Bounded delayed round-trip quote observations, with all missing cases."""

    def __init__(self, metadata):
        self.metadata = metadata
        self.books = defaultdict(dict)
        self.pending = defaultdict(list)
        self.rows = []

    def request(self, asset, venue, direction, now, label):
        book = self.books[asset][venue]
        market = self.metadata[venue][asset]
        qty = rounded(D(100) / (dec(book["asks"][0][0]) * D("1.01")), market["qty_step"])
        row = dict(id=len(self.rows), label=label, asset=asset, venue=venue,
                   direction=direction, decision_ns=now, quantity=str(qty),
                   status="pending_entry", due_ns=now + DELAY,
                   generation=book["generation"])
        assert len(self.rows) < 30_000, "profile count cap"
        self.rows.append(row)
        if qty < dec(market["min_qty"]) or qty * dec(book["bids"][0][0]) < dec(market["min_notional"]):
            row["status"] = "native_minimum_reject"
        else:
            self.pending[asset, venue].append(row)
        return row

    def process(self, event):
        kind, now = event["type"], event["received_ns"]
        if kind == "end":
            for rows in self.pending.values():
                for row in rows:
                    row["failed_stage"] = row["status"]
                    row["status"] = "unresolved_at_end"
            self.pending.clear()
            return
        asset, venue = event["asset"], event["venue"]
        key = asset, venue
        if kind == "invalidate":
            self.books[asset].pop(venue, None)
            for row in self.pending.pop(key, []):
                row["failed_stage"] = row["status"]
                row["status"] = "invalidated"
        if kind != "book":
            return
        self.books[asset][venue] = event
        keep = []
        for row in self.pending[key]:
            due = row["due_ns"]
            if now < due or event["source_ns"] < due:
                keep.append(row)
                continue
            failure = None
            if now > due + 2 * NS or not clock(event, now):
                failure = "missing_first_eligible"
            elif event["generation"] != row["generation"]:
                failure = "generation_changed"
            entry = row["status"] == "pending_entry"
            side = row["direction"] if entry else -row["direction"]
            qty = dec(row["quantity"])
            value = sweep(event, side, qty) if failure is None else None
            if failure is None and value is None:
                failure = "insufficient_depth"
            if failure is None and entry and value > D(100):
                failure = "entry_quote_above_cap"
            if failure:
                row["failed_stage"], row["status"] = row["status"], failure
                continue
            other = next(v for v in VS if v != venue)
            reference = exactmid(self.books[asset][other]) if pair(self.books[asset], now) else None
            observation = dict(received_ns=now, source_ns=event["source_ns"],
                               value=str(value), midpoint=str(exactmid(event)),
                               reference_midpoint=str(reference) if reference is not None else None)
            if entry:
                row.update(entry=observation, status="pending_exit", due_ns=now + HOLD + DELAY)
                keep.append(row)
                continue
            prior, sign = row["entry"], D(row["direction"])
            entry_value = dec(prior["value"])
            quote = sign * (value - entry_value) / entry_value * 10000
            row.update(exit=observation, status="matched", quote_bps=str(quote),
                       midpoint_bps=str(sign * (exactmid(event) - dec(prior["midpoint"])) / dec(prior["midpoint"]) * 10000),
                       entry_delay_ms=str(D(prior["received_ns"] - row["decision_ns"]) / 1_000_000),
                       holding_seconds=str(D(now - prior["received_ns"]) / NS))
            if reference is not None and prior["reference_midpoint"] is not None:
                common = sign * qty * (reference - dec(prior["reference_midpoint"])) / entry_value * 10000
                row.update(reference_bps=str(common), quote_minus_reference_bps=str(quote - common))
        self.pending[key] = keep


def summarize(events, counts, assets):
    rows = []
    for asset in assets:
        for venue in VS:
            selected = [e for e in events if (e["asset"], e["venue"]) == (asset, venue)]
            outcomes = [e["event_profile"] for e in selected]
            c = counts[asset, venue]
            assert c["within_window"] == c["same_episode"] + c["selected_episode"]
            assert c["selected_episode"] == len(selected)
            matched = [o for o in outcomes if o["status"] == "matched"]
            differences = []
            for event in selected:
                shock, control = event["event_profile"], event["control_profile"]
                if control is not None and shock["status"] == control["status"] == "matched":
                    row = dict(quote_bps=dec(shock["quote_bps"]) - dec(control["quote_bps"]))
                    if "quote_minus_reference_bps" in shock and "quote_minus_reference_bps" in control:
                        row["quote_minus_reference_bps"] = dec(shock["quote_minus_reference_bps"]) - dec(control["quote_minus_reference_bps"])
                    differences.append(row)
            rows.append(dict(asset=asset, venue=venue, counts=dict(c),
                             event_outcomes=dict(Counter(o["status"] for o in outcomes)),
                             control_selection=dict(Counter(e["control_selection"] for e in selected)),
                             control_outcomes=dict(Counter(e["control_profile"]["status"] for e in selected if e["control_profile"] is not None)),
                             long_events=sum(o["direction"] == 1 for o in outcomes),
                             short_events=sum(o["direction"] == -1 for o in outcomes),
                             event_quote_bps=distribution([dec(o["quote_bps"]) for o in matched]),
                             event_quote_minus_reference_bps=distribution([dec(o["quote_minus_reference_bps"]) for o in matched if "quote_minus_reference_bps" in o]),
                             paired_quote_difference_bps=distribution([o["quote_bps"] for o in differences]),
                             paired_residual_difference_bps=distribution([o["quote_minus_reference_bps"] for o in differences if "quote_minus_reference_bps" in o]),
                             event_positive_after_extra_bps={str(bp):sum(dec(o["quote_bps"]) > bp for o in matched) for bp in (0,1,2,5)}))
    return rows


def diagnose(stream, metadata, start, assets):
    profiles = QuoteProfiles(metadata)
    detectors = {a: Detector() for a in assets}
    counts = defaultdict(Counter)
    anchors = defaultdict(list)
    last_anchor, last_shock, last_episode = {}, {}, {}
    observed_since = {a:start for a in assets}
    shock_times = defaultdict(list)
    non_market_events = Counter()
    selected, ended = [], False
    for event in stream:
        kind, now = event["type"], event["received_ns"]
        if kind != "end" and event.get("asset") not in detectors:
            assert kind == "control", "unexpected event without selected market"
            non_market_events[kind] += 1
            continue
        profiles.process(event)
        if kind == "end":
            for detector in detectors.values():
                detector.process(event)
            ended = True
            continue
        asset, venue = event["asset"], event["venue"]
        if kind == "invalidate":
            observed_since[asset] = now
        detector = detectors[asset]
        signals = [s for s in detector.process(event) if s["rule"] == "depth_fade"]
        for signal in signals:
            target_venue = signal["venue"]
            c = counts[asset, target_venue]
            c["raw_shocks"] += 1
            last_shock[asset] = now
            shock_times[asset].append(now)
            if not 3 * NS <= now - start < 570 * NS:
                c["outside_window"] += 1
                continue
            c["within_window"] += 1
            if asset in last_episode and now - last_episode[asset] < 30 * NS:
                c["same_episode"] += 1
                continue
            last_episode[asset] = now
            c["selected_episode"] += 1
            anchor, reason = select_control(anchors[asset, target_venue], signal)
            control = anchor["profiles"][str(signal["direction"])] if anchor else None
            selected.append(dict(asset=asset, venue=target_venue, signal=signal,
                                 control_selection=reason,
                                 control_anchor={k:v for k,v in anchor.items() if k != "profiles"} if anchor else None,
                                 control_profile=control,
                                 event_profile=profiles.request(asset, target_venue, signal["direction"], now, "shock")))
            assert len(selected) <= 2000, "selected event cap"
        key = asset, venue
        if kind != "book" or not 3 * NS <= now - start < 570 * NS or not pair(profiles.books[asset], now):
            continue
        if key in last_anchor and now - last_anchor[key] < NS:
            continue
        last_anchor[key] = now
        c = counts[key]
        c["control_anchors"] += 1
        book = profiles.books[asset][venue]
        spread = float((dec(book["asks"][0][0]) - dec(book["bids"][0][0])) / exactmid(book) * 10000)
        quiet = (now - observed_since[asset] >= 15 * NS and
                 (asset not in last_shock or now - last_shock[asset] >= 15 * NS))
        anchor = dict(t=now, spread_bps=spread, spread_bucket=spread_bucket(spread),
                      quiet_at_decision=quiet, profiles={})
        if quiet:
            c["quiet_control_anchors"] += 1
            anchor["profiles"] = {str(side):profiles.request(asset, venue, side, now, "ordinary") for side in (1,-1)}
        anchors[key].append(anchor)
    assert ended
    assert all(not o["status"].startswith("pending") for o in profiles.rows)
    for event in selected:
        for name in ("event_profile", "control_profile"):
            profile = event[name]
            if profile is not None and profile["status"] == "matched":
                profile["subsequent_observed_shocks_through_exit"] = sum(
                    profile["decision_ns"] < t <= profile["exit"]["received_ns"]
                    for t in shock_times[event["asset"]])
    references = [e["control_profile"]["id"] for e in selected if e["control_profile"] is not None]
    return dict(rows=summarize(selected, counts, assets), events=selected,
                ordinary_profile_outcomes=dict(Counter(p["status"] for p in profiles.rows if p["label"] == "ordinary")),
                reused_control_profiles=sum(n-1 for n in Counter(references).values()),
                non_market_events=dict(non_market_events),
                detector_counts={a:dict(d.counts) for a,d in detectors.items()},
                dependence="30-second first-event spacing per asset across both venues; cross-asset and session dependence remains. Controls may contain subsequent shocks; no future filtering.")


def main():
    broad.verify()
    plan = json.loads(PLAN.read_bytes())
    for pin in plan["pins"]:
        assert sha(ROOT / pin["path"]) == pin["sha256"], pin["path"]
    results = []
    for window in plan["windows"]:
        directory = ROOT / window["capture"]
        manifest = json.loads((directory / "manifest.json").read_bytes())
        assert manifest["end_reason"] == "duration_limit" and not manifest["truncated"]
        assert sha(directory / "frames.jsonl.gz") == window["raw_sha256"]
        assert sha(directory / "metadata/normalized.json") == window["metadata_sha256"]
        metadata = json.loads((directory / "metadata/normalized.json").read_bytes())["markets"]
        assert all(dec(m["taker_fee_bps"]) == 0 for markets in metadata.values() for m in markets.values())
        start = broad.events._epoch_ns(manifest["started_utc"])
        result = diagnose(broad.broad_events(directory, expected_manifest_sha256=window["manifest_sha256"],
                                           max_raw_bytes=broad.HARD_BYTES), metadata, start, broad.ASSETS)
        result.update(window=window["index"], started_utc=manifest["started_utc"], ended_utc=manifest["ended_utc"])
        results.append(result)
        print(json.dumps(dict(window=window["index"], selected_episodes=len(result["events"]),
                              matched=sum(e["event_profile"]["status"] == "matched" for e in result["events"]))), flush=True)
    output = dict(plan_sha256=sha(PLAN), scope=plan["scope"], windows=results)
    blob = gzip.compress((json.dumps(output, indent=2, allow_nan=False)+"\n").encode(), mtime=0)
    assert len(blob) <= plan["output_caps"]["gzip"]
    assert not OUTPUT.exists()
    OUTPUT.write_bytes(blob)
    print(json.dumps(dict(output_bytes=len(blob), plan_sha256=sha(PLAN))))


if __name__ == "__main__":
    main()
