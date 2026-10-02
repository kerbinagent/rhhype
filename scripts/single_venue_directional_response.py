"""One fixed exploratory receipt-observed directional-response diagnostic.

Only completed, pinned historical archives are accepted. No network, orders,
clock-offset fitting, parameter search or claims of true venue leadership.
"""
from collections import Counter, defaultdict, deque
from decimal import Decimal as D
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts import single_venue_broad_relative as broad
from scripts.audit_single_venue_study import clock, pair, NS, VS
from scripts.single_venue_shock_controls import QuoteProfiles, DELAY, HOLD
from scripts.single_venue_residual_profile import exactmid, sweep
from scripts.single_venue_strategy import dec
from scripts.single_venue_broad_quotes import distribution

PLAN = ROOT / "reports/experiment-storage/single-venue-directional-response-v1.json"
OUTPUT = ROOT / "reports/single-venue-research/directional-response.json.gz"
SOURCE_TEST_BYTES, PROTOCOL_BYTES = 49152, 16384
GZIP_BYTES, READOUT_BYTES = 180224, 16384
EVENT_CAP = 2000
WINDOW_PATHS = ("reports/single-venue-broad/capture",
                "reports/single-venue-broad-relative/capture")
PARAMETERS = dict(admission_start_seconds=122, admission_stop_seconds=480,
                  observed_move_bps=3, target_max_move_fraction=.5,
                  evaluation_seconds=1, prior_tolerance_ms=250,
                  episode_spacing_seconds=30, delay_ms=400, hold_seconds=10)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signed_log(side, later, earlier):
    return D(str(side * 10000 * math.log(float(later) / float(earlier))))


class ReceiptMoves:
    """Past-only paired midpoint changes, sampled once per receipt second."""

    def __init__(self, start):
        self.start = start
        self.books = defaultdict(dict)
        self.points = defaultdict(lambda: deque(maxlen=40))
        self.last_point = {}
        self.last_second = {}
        self.counts = defaultdict(Counter)

    def process(self, event):
        kind = event["type"]
        if kind == "end":
            return []
        asset, venue, now = event["asset"], event["venue"], event["received_ns"]
        if kind == "invalidate":
            self.books[asset].pop(venue, None)
            self.points[asset].clear()
            self.last_point.pop(asset, None)
            return []
        if kind != "book":
            return []
        books = self.books[asset]
        books[venue] = event
        fresh = pair(books, now)
        prior = next((p for p in reversed(self.points[asset]) if p["t"] <= now - NS), None)
        current = None
        if fresh:
            current = dict(t=now, mids={v: exactmid(books[v]) for v in VS},
                           sources={v: books[v]["source_ns"] for v in VS},
                           generations={v: books[v]["generation"] for v in VS},
                           sequences={v: books[v]["sequence"] for v in VS})
            if asset not in self.last_point or now - self.last_point[asset] >= 100_000_000:
                self.points[asset].append(current)
                self.last_point[asset] = now
        second = (now - self.start) // NS
        if not 122 <= second < 480 or self.last_second.get(asset) == second:
            return []
        # The first callback in a scheduled second is the only evaluation;
        # a later good pair cannot replace its failed observation.
        self.last_second[asset] = second
        for target in VS:
            self.counts[asset, target]["scheduled_evaluations"] += 1
        reason = None
        if not fresh:
            reason = "nonfresh_pair"
        elif prior is None or now - NS - prior["t"] > 250_000_000:
            reason = "missing_prior"
        elif current["generations"] != prior["generations"]:
            reason = "prior_generation_changed"
        elif any(current["sources"][v] <= prior["sources"][v]
                 or current["sequences"][v] == prior["sequences"][v] for v in VS):
            reason = "source_not_advanced"
        if reason:
            for target in VS:
                self.counts[asset, target][reason] += 1
            return []
        moves = {v: signed_log(1, current["mids"][v], prior["mids"][v]) for v in VS}
        signals = []
        for target in VS:
            mover = next(v for v in VS if v != target)
            counts = self.counts[asset, target]
            counts["usable_prior"] += 1
            if abs(moves[mover]) < D(3):
                counts["below_move_threshold"] += 1
                continue
            counts["large_observed_moves"] += 1
            if abs(moves[target]) > abs(moves[mover]) / 2:
                counts["response_not_lagging"] += 1
                continue
            counts["observable_lags"] += 1
            side = 1 if moves[mover] > 0 else -1
            signals.append(dict(asset=asset, venue=target, mover_venue=mover,
                                direction=side, t=now, prior_ns=prior["t"],
                                prior_sources=prior["sources"], sources=current["sources"],
                                prior_sequences=prior["sequences"], sequences=current["sequences"],
                                generations=current["generations"],
                                target_decision_midpoint=str(current["mids"][target]),
                                mover_move_bps=str(moves[mover]), target_move_bps=str(moves[target]),
                                unmatched_move_bps=str(side * (moves[mover] - moves[target]))))
        return signals


class ResponseProfiles(QuoteProfiles):
    """Reuse local lifecycle unchanged; freeze the control at each endpoint."""

    def control(self, row, stage, due, now):
        asset, target = row["asset"], row["venue"]
        other = row["mover_venue"]
        books, qty = self.books[asset], dec(row["quantity"])
        book = books.get(other)
        result = dict(status="missing_pair", endpoint_ns=now, execution_due_ns=due)
        if not pair(books, now):
            return result
        if book["source_ns"] < due:
            result["status"] = "source_before_due"
            return result
        if book["generation"] != row["mover_generation"]:
            result["status"] = "generation_changed"
            return result
        market = self.metadata[other][asset]
        if qty % dec(market["qty_step"]) != 0:
            result["status"] = "native_grid_reject"
            return result
        if qty < dec(market["min_qty"]) or qty * dec(book["bids"][0][0]) < dec(market["min_notional"]):
            result["status"] = "native_minimum_reject"
            return result
        side = row["direction"] if stage == "entry" else -row["direction"]
        value = sweep(book, side, qty)
        if value is None:
            result["status"] = "insufficient_depth"
        elif stage == "entry" and value > D(100):
            result["status"] = "entry_quote_above_cap"
        else:
            result.update(status="matched", value=str(value), midpoint=str(exactmid(book)),
                          received_ns=book["received_ns"], source_ns=book["source_ns"],
                          generation=book["generation"], sequence=book["sequence"])
        return result

    def process(self, event):
        before = []
        if event["type"] == "book":
            for row in self.pending[event["asset"], event["venue"]]:
                before.append((row, row["status"], row["due_ns"]))
        super().process(event)
        for row, status, due in before:
            if status == "pending_entry" and row["status"] == "pending_exit":
                row["entry_control"] = self.control(row, "entry", due, event["received_ns"])
                row["consumed_before_entry_bps"] = str(signed_log(
                    row["direction"], row["entry"]["midpoint"], row["decision_midpoint"]))
            elif status == "pending_exit" and row["status"] == "matched":
                row["exit_control"] = self.control(row, "exit", due, event["received_ns"])
                entry, exit_ = dec(row["entry"]["value"]), dec(row["exit"]["value"])
                fee = dec(self.metadata[row["venue"]][row["asset"]]["taker_fee_bps"])
                row["fee_bps"] = str(fee * (entry + exit_) / entry)
                row["net_quote_bps"] = str(dec(row["quote_bps"]) - dec(row["fee_bps"]))
                row["remaining_midpoint_bps"] = str(signed_log(
                    row["direction"], row["exit"]["midpoint"], row["entry"]["midpoint"]))
                a, b = row["entry_control"], row["exit_control"]
                if a["status"] == b["status"] == "matched":
                    a_value, b_value = dec(a["value"]), dec(b["value"])
                    fee = dec(self.metadata[row["mover_venue"]][row["asset"]]["taker_fee_bps"])
                    control = D(row["direction"]) * (b_value - a_value) / a_value * 10000
                    control -= fee * (a_value + b_value) / a_value
                    row["control_net_quote_bps"] = str(control)
                    row["quote_excess_bps"] = str(dec(row["net_quote_bps"]) - control)
                    row["midpoint_excess_bps"] = str(dec(row["remaining_midpoint_bps"]) - signed_log(
                        row["direction"], b["midpoint"], a["midpoint"]))

    def signal(self, signal):
        asset, target, now = signal["asset"], signal["venue"], signal["t"]
        row = self.request(asset, target, signal["direction"], now, "directional_response")
        row.update(mover_venue=signal["mover_venue"],
                   mover_generation=signal["generations"][signal["mover_venue"]],
                   decision_midpoint=signal["target_decision_midpoint"],
                   cost_plausible=False, cost_status=row["status"])
        if row["status"] == "pending_entry":
            book = self.books[asset][target]
            qty, side = dec(row["quantity"]), row["direction"]
            entry, exit_ = sweep(book, side, qty), sweep(book, -side, qty)
            if entry is None or exit_ is None:
                row["cost_status"] = "insufficient_depth"
            elif entry > D(100):
                row["cost_status"] = "entry_quote_above_cap"
            else:
                fee = dec(self.metadata[target][asset]["taker_fee_bps"])
                cost = D(side) * (entry - exit_) / entry * 10000 + fee * (entry + exit_) / entry
                row.update(cost_status="measured", immediate_roundtrip_cost_bps=str(cost),
                           cost_plausible=dec(signal["unmatched_move_bps"]) > cost)
        return row


def summarize(selected, counts, assets):
    rows = []
    for asset in assets:
        for target in VS:
            observations = [e["profile"] for e in selected if (e["signal"]["asset"], e["signal"]["venue"]) == (asset, target)]
            c = counts[asset, target]
            assert c["scheduled_evaluations"] == sum(c[k] for k in (
                "nonfresh_pair", "missing_prior", "prior_generation_changed", "source_not_advanced", "usable_prior"))
            assert c["usable_prior"] == c["below_move_threshold"] + c["large_observed_moves"]
            assert c["large_observed_moves"] == c["response_not_lagging"] + c["observable_lags"]
            assert c["observable_lags"] == c["same_episode"] + c["selected_episode"]
            assert c["selected_episode"] == len(observations)
            subsets = {}
            for label, subset in (("all_selected", observations), ("cost_plausible", [o for o in observations if o["cost_plausible"]])):
                matched = [o for o in subset if o["status"] == "matched"]
                subsets[label] = dict(count=len(subset), outcomes=dict(Counter(o["status"] for o in subset)),
                    cost_statuses=dict(Counter(o["cost_status"] for o in subset)),
                    controls={stage:dict(Counter(o.get(stage + "_control", {}).get("status", "endpoint_not_reached") for o in subset)) for stage in ("entry", "exit")},
                    complete_control_pairs=sum("quote_excess_bps" in o for o in matched),
                    positive_after_extra_bps={str(bp):sum(dec(o["net_quote_bps"]) > bp for o in matched) for bp in (0, 1, 2, 5)},
                    **{field:distribution([dec(o[field]) for o in subset if field in o]) for field in (
                        "net_quote_bps", "quote_excess_bps", "midpoint_excess_bps", "consumed_before_entry_bps",
                        "remaining_midpoint_bps", "entry_delay_ms", "holding_seconds")})
            rows.append(dict(asset=asset, venue=target, mover_venue=next(v for v in VS if v != target),
                             counts=dict(c), long_events=sum(o["direction"] == 1 for o in observations),
                             short_events=sum(o["direction"] == -1 for o in observations), subsets=subsets))
    return rows


def diagnose(stream, metadata, start, assets):
    profiles, detector = ResponseProfiles(metadata), ReceiptMoves(start)
    selected, last_episode, non_market, ended = [], {}, Counter(), False
    for event in stream:
        kind, now = event["type"], event["received_ns"]
        if kind != "end" and event.get("asset") not in assets:
            assert kind == "control", "unexpected non-market event"
            non_market[kind] += 1
            continue
        profiles.process(event)
        if kind == "end":
            ended = True
            continue
        for signal in detector.process(event):
            asset, target = signal["asset"], signal["venue"]
            counts = detector.counts[asset, target]
            if asset in last_episode and now - last_episode[asset] < 30 * NS:
                counts["same_episode"] += 1
                continue
            last_episode[asset] = now
            counts["selected_episode"] += 1
            assert len(selected) < EVENT_CAP, "selected event cap"
            selected.append(dict(signal=signal, profile=profiles.signal(signal)))
    assert ended, "complete adapter terminal event required"
    assert all(not o["status"].startswith("pending") for o in profiles.rows)
    return dict(rows=summarize(selected, detector.counts, assets), events=selected,
                non_market_events=dict(non_market),
                dependence="First lag event per asset across both roles every30seconds; cross-asset and session dependence remains.",
                interpretation="Exploratory receipt-observed responses; same-time controls are conditional quotes, not causal leadership or paper cash.")


def main():
    broad.verify()
    plan = json.loads(PLAN.read_bytes())
    assert PLAN.stat().st_size <= PROTOCOL_BYTES
    assert plan["categories_bytes"] == dict(source_tests=SOURCE_TEST_BYTES, protocol=PROTOCOL_BYTES,
                                            output=GZIP_BYTES + READOUT_BYTES)
    assert plan["output_caps"] == dict(gzip=GZIP_BYTES, readout=READOUT_BYTES)
    assert sum((ROOT / p).stat().st_size for p in (
        "scripts/single_venue_directional_response.py", "tests/test_single_venue_directional_response.py")) <= SOURCE_TEST_BYTES
    assert [(w["index"], w["capture"]) for w in plan["windows"]] == list(enumerate(WINDOW_PATHS, 1))
    assert DELAY == 400_000_000 and HOLD == 10 * NS
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
        assert len(result["rows"]) == 20
        result.update(window=window["index"], started_utc=manifest["started_utc"], ended_utc=manifest["ended_utc"])
        results.append(result)
        print(json.dumps(dict(window=window["index"], selected_episodes=len(result["events"]))), flush=True)
    output = dict(plan_sha256=sha(PLAN), scope=plan["scope"], parameters=PARAMETERS, windows=results)
    blob = gzip.compress((json.dumps(output, indent=2, allow_nan=False) + "\n").encode(), mtime=0)
    assert len(blob) <= GZIP_BYTES and not OUTPUT.exists()
    OUTPUT.write_bytes(blob)
    print(json.dumps(dict(output_bytes=len(blob), plan_sha256=sha(PLAN))))


if __name__ == "__main__":
    main()
