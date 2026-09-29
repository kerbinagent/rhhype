#!/usr/bin/env python3
"""Stream public capture frames into generation-aware reconstructed full books."""

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.maker_capture import BoundedGzip, HARD_BYTES, SizeCapReached  # noqa: E402
from scripts.paper_streams import STATE_LIMIT, StreamManager  # noqa: E402
from scripts.analyze_maker_equity import plan_markets  # noqa: E402

SECOND = 1_000_000_000
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 200_000
TARGETS = (25, 50, 100, 250, 1000)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def selected_markets(manifest):
    result = []
    for venue, assets in manifest["selected_markets"].items():
        for asset, market in assets.items():
            result.append({"venue": venue, "asset": asset, "market": str(market)})
    return result


def rh_ticker_reset_required(row, prior_generation):
    if row.get("venue") != "rh_lighter":
        return False
    if row.get("kind") in ("connection_close", "invalid_json", "connection_error"):
        return True
    return (row.get("kind") == "connection_open" and prior_generation is not None
            and prior_generation != row.get("generation"))


class BookRebuilder:
    """Reuse the production book decoder but attach the archived wire clocks."""

    def __init__(self, markets, emit):
        self.markets = {(m["venue"], str(m["market"])): m for m in markets}
        self.emit = emit
        self.current = None
        self.counts = Counter()
        self.last_generation = {}
        self.latest = {}
        self.manager = StreamManager(None, markets, self._book, self._status,
                                     max_levels=STATE_LIMIT, prefer_bbo=False)

    def _status(self, venue, changes):
        if changes.get("reason"):
            self.counts[f"decoder_status:{venue}:{changes['reason']}"] += 1

    def _book(self, event):
        row = self.current
        if row is None:
            raise RuntimeError("book decoder emitted outside a captured frame")
        venue, market = event["venue"], str(event["market"])
        identity = self.markets.get((venue, market))
        if identity is None:
            raise RuntimeError("decoded book market not in frozen selection")
        receipt = row.get("receipt_utc_ns")
        source = (row.get("annotation") or {}).get("source_max_ns")
        if not isinstance(receipt, int) or receipt <= 0:
            raise ValueError("missing archived book receipt time")
        engine_time = event.get("engine_time")
        source_mismatch = (isinstance(source, int) and engine_time is not None and
                           abs(source / SECOND - float(engine_time)) > 0.000001)
        if event.get("valid") and (not isinstance(source, int) or source <= 0 or
                                   source > receipt or source_mismatch):
            # A future source time prevents a causal quote, even if the feed's
            # price/nonce parser accepted the frame.
            self.manager.states.pop((venue, market), None)
            event = dict(event, valid=False, reason="invalid_source_or_clock", bids=[], asks=[])
        bids, asks = event.get("bids", []), event.get("asks", [])
        out = {"venue": venue, "asset": identity["asset"], "market": market,
               "generation": row.get("generation"), "feed": row.get("channel"),
               "receipt_utc_ns": receipt, "source_utc_ns": source,
               "receipt_monotonic_ns": row.get("receipt_monotonic_ns"),
               "sequence": event.get("sequence"), "valid": bool(event.get("valid")),
               "reason": event.get("reason"), "bids": bids, "asks": asks,
               "level_count": {"bids": len(bids), "asks": len(asks)}}
        self.emit(out)
        self.latest[(venue, identity["asset"])] = out
        self.counts[f"{venue}|{identity['asset']}|{'valid' if out['valid'] else 'invalid'}"] += 1

    def _invalidate_venue(self, venue, reason, generation):
        # A disconnect invalidates the *last published event* as well as the
        # decoder's internal state. HL snapshots do not live in states.
        for (v, market) in self.markets:
            if v != venue:
                continue
            self.manager._invalidate((v, market), reason, generation)
            self.manager.hl_last.pop((v, market), None)
            self.manager.hl_block_l2.pop((v, market), None)

    def process(self, row):
        self.current = row
        kind, venue, generation = row.get("kind"), row.get("venue"), row.get("generation")
        if venue not in ("hyperliquid", "lighter", "rh_lighter"):
            return
        if kind == "connection_open":
            prior = self.last_generation.get(venue)
            if prior is not None and prior != generation:
                self._invalidate_venue(venue, "generation_change", prior)
            self.last_generation[venue] = generation
            return
        if kind != "frame":
            if kind in ("connection_close", "invalid_json", "connection_error"):
                self._invalidate_venue(venue, kind, generation)
            return
        feed = row.get("channel")
        if (venue == "hyperliquid" and feed != "l2Book") or (
                venue != "hyperliquid" and feed != "order_book"):
            return  # BBO/ticker never refresh or splice the reconstructed book.
        market = str(row.get("market"))
        key = (venue, market)
        if key not in self.markets:
            self.counts["unknown_book_market"] += 1
            return
        if not isinstance(generation, str) or not generation:
            raise ValueError("book frame missing generation")
        prior = self.last_generation.get(venue)
        if prior is not None and prior != generation:
            self._invalidate_venue(venue, "generation_change", prior)
        self.last_generation[venue] = generation
        annotation = row.get("annotation") or {}
        if annotation.get("quality") not in ("wire_ok", "wire_ok_snapshot") or annotation.get("source_regression_within_channel"):
            self.manager._invalidate(key, annotation.get("reason") or "capture_annotation_invalid", generation)
            return
        if venue != "hyperliquid" and (row.get("payload") or {}).get("type") == "update/order_book":
            prior_state = self.manager.states.get(key)
            if prior_state is None or prior_state.get("generation") != generation:
                self.manager._invalidate(key, "delta_without_snapshot", generation)
                return
        before = self.counts[f"{venue}|{self.markets[key]['asset']}|valid"]
        self.manager.process_message(venue, row["payload"], generation)
        latest = self.latest.get((venue, self.markets[key]["asset"]))
        if latest and latest.get("receipt_utc_ns") == row.get("receipt_utc_ns") and not latest["valid"]:
            self.manager.states.pop(key, None)
            if latest.get("reason") == "invalid_source_or_clock":
                self.manager.hl_last.pop(key, None)
                self.manager.hl_block_l2.pop(key, None)
        if self.counts[f"{venue}|{self.markets[key]['asset']}|valid"] == before:
            self.counts[f"{venue}|{self.markets[key]['asset']}|no_valid_publish"] += 1


def fresh(event, anchor):
    return (event is not None and event.get("valid") and
            isinstance(event.get("receipt_utc_ns"), int) and
            isinstance(event.get("source_utc_ns"), int) and
            event["receipt_utc_ns"] <= anchor and event["source_utc_ns"] <= anchor and
            0 <= anchor - event["receipt_utc_ns"] <= SECOND and
            0 <= anchor - event["source_utc_ns"] <= 2 * SECOND)


def full_depth(levels, q):
    return sum(float(row[1]) for row in levels) + 1e-12 >= q


def quantity(asset, target, best_ask):
    step = Decimal("0.001") if asset == "NVDA" else Decimal("0.01")
    price = Decimal(str(best_ask))
    if price <= 0:
        return None
    qty = (Decimal(target) / price / step).to_integral_value(rounding=ROUND_FLOOR) * step
    return float(qty) if qty > 0 else None


def order_eligible(qty, price, market):
    if qty is None:
        return False
    q, p, step = Decimal(str(qty)), Decimal(str(price)), Decimal(str(market["step"]))
    maximum = market.get("max_qty")
    return (q > 0 and p > 0 and step > 0 and q % step == 0
            and q >= Decimal(str(market["min_qty"]))
            and q * p >= Decimal(str(market["min_notional"]))
            and (maximum is None or q <= Decimal(str(maximum))))


def evaluate_anchor(anchor, latest_book, latest_ticker, market_meta):
    out = []
    for asset in ("NVDA", "XAG"):
        key = ("rh_lighter", asset)
        book, ticker = latest_book.get(key), latest_ticker.get(key)
        bvalid, tvalid = fresh(book, anchor), fresh(ticker, anchor)
        item = {"anchor_utc_ns": anchor, "venue": "rh_lighter", "asset": asset,
                "book_fresh": bool(bvalid), "ticker_fresh": bool(tvalid),
                "book_generation": book.get("generation") if book else None,
                "book_receipt_utc_ns": book.get("receipt_utc_ns") if book else None,
                "book_source_utc_ns": book.get("source_utc_ns") if book else None}
        if bvalid:
            bids, asks = book["bids"], book["asks"]
            item["best_bid"] = bids[0][0]
            item["best_ask"] = asks[0][0]
            item["level_count"] = book["level_count"]
            item["targets"] = {}
            for target in TARGETS:
                q = quantity(asset, target, asks[0][0])
                bm, am = (order_eligible(q, bids[0][0], market_meta[asset]),
                          order_eligible(q, asks[0][0], market_meta[asset]))
                item["targets"][str(target)] = {"qty": q,
                    "bid_order_eligible": bm, "ask_order_eligible": am,
                    "bid_top_available": bm and bids[0][1] + 1e-12 >= q,
                    "ask_top_available": am and asks[0][1] + 1e-12 >= q,
                    "bid_full_available": bm and full_depth(bids, q),
                    "ask_full_available": am and full_depth(asks, q)}
        out.append(item)
    return out


def reconstruct(source_dir, out_dir, output_cap=HARD_BYTES):
    manifest_path = Path(source_dir) / "manifest.json"
    frames_path = Path(source_dir) / "frames.jsonl.gz"
    manifest = json.loads(manifest_path.read_text())
    if frames_path.stat().st_size + manifest_path.stat().st_size > HARD_BYTES:
        raise ValueError("source capture exceeds its 25 MB hard cap")
    if (manifest.get("truncated") or manifest.get("errors") or
            manifest.get("configured_total_compressed_bytes", HARD_BYTES) > HARD_BYTES):
        raise ValueError("source capture is truncated or has recorded errors")
    if (not isinstance(manifest.get("payload_records"), int) or
            not 0 <= manifest["payload_records"] <= MAX_RECORDS):
        raise ValueError("source record count exceeds bounded replay")
    markets = selected_markets(manifest)
    if any(set(manifest["selected_markets"].get(v, {})) != {"NVDA", "XAG"}
           for v in ("hyperliquid", "lighter", "rh_lighter")):
        raise ValueError("this diagnostic expects the frozen NVDA/XAG capture")
    plan_path = Path(manifest["market_plan"])
    if sha256(plan_path) != manifest["market_plan_sha256"]:
        raise ValueError("frozen market plan hash mismatch")
    all_meta = plan_markets(plan_path, manifest["selected_markets"])
    rh_meta = {asset: all_meta[asset]["rh_lighter"] for asset in ("NVDA", "XAG")}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = BoundedGzip(out_dir / "book-events.jsonl.gz", total_cap=output_cap,
                         reserve=1_000_000)
    latest_ticker = {}
    first = int(datetime.fromisoformat(manifest["started_utc"]).timestamp() * SECOND)
    end = int(datetime.fromisoformat(manifest["ended_utc"]).timestamp() * SECOND)
    if end < first or end - first > 601 * SECOND:
        raise ValueError("source capture duration exceeds bounded replay")
    first_anchor = ((first + 3 * SECOND + 5 * SECOND - 1) // (5 * SECOND)) * 5 * SECOND
    anchors = iter(range(first_anchor, end - 5 * SECOND, 5 * SECOND))
    next_anchor = next(anchors, None)
    anchor_rows = []
    counts = Counter()
    decoded_bytes = 0
    prior_receipt = None
    rebuilder = BookRebuilder(markets, writer.write)
    reason = "complete"
    try:
        with gzip.open(frames_path, "rb") as f:
            while True:
                line = f.readline(MAX_RECORD_BYTES + 1)
                if not line:
                    break
                counts["decoded_records"] += 1
                decoded_bytes += len(line)
                if len(line) > MAX_RECORD_BYTES or not line.endswith(b"\n"):
                    raise ValueError("decoded record exceeds bounded frame size")
                if (decoded_bytes > MAX_DECODED_BYTES or
                        counts["decoded_records"] > MAX_RECORDS or
                        counts["decoded_records"] > manifest["payload_records"]):
                    raise ValueError("decoded capture exceeds bounded replay limits")
                row = json.loads(line)
                receipt = row.get("receipt_utc_ns")
                if not isinstance(receipt, int):
                    raise ValueError("captured record missing receipt")
                if prior_receipt is not None and receipt < prior_receipt:
                    raise ValueError("capture receipts are not monotonically ordered")
                prior_receipt = receipt
                while next_anchor is not None and next_anchor < receipt:
                    anchor_rows.extend(evaluate_anchor(next_anchor, rebuilder.latest, latest_ticker,
                                                       rh_meta))
                    next_anchor = next(anchors, None)
                if rh_ticker_reset_required(row, rebuilder.last_generation.get("rh_lighter")):
                    for asset in ("NVDA", "XAG"):
                        latest_ticker[("rh_lighter", asset)] = {"valid": False,
                            "receipt_utc_ns": receipt, "source_utc_ns": None}
                if row.get("kind") == "frame" and row.get("venue") == "rh_lighter" and row.get("channel") == "ticker":
                    annotation = row.get("annotation") or {}
                    market = str(row.get("market"))
                    asset = next((a for a, mid in manifest["selected_markets"]["rh_lighter"].items()
                                  if str(mid) == market), None)
                    if asset:
                        valid = annotation.get("quality") == "wire_ok" and not annotation.get("source_regression_within_channel")
                        latest_ticker[("rh_lighter", asset)] = {
                            "valid": valid, "receipt_utc_ns": receipt,
                            "source_utc_ns": annotation.get("source_max_ns") if valid else None}
                rebuilder.process(row)
        while next_anchor is not None:
            anchor_rows.extend(evaluate_anchor(next_anchor, rebuilder.latest, latest_ticker,
                                               rh_meta))
            next_anchor = next(anchors, None)
    except SizeCapReached:
        reason = "compressed_output_cap"
    finally:
        writer.close()
    counts.update(rebuilder.counts)
    counts["decoded_bytes"] = decoded_bytes
    if counts["decoded_records"] != manifest["payload_records"] and reason == "complete":
        raise ValueError("decoded source record count differs from capture manifest")
    if reason != "complete":
        raise RuntimeError("book reconstruction hit output cap; no diagnostic published")
    (out_dir / "rh-anchor-diagnostics.json").write_text(json.dumps(anchor_rows, separators=(",", ":")) + "\n")
    summary = {"source_manifest_sha256": sha256(manifest_path),
               "source_gzip_sha256": sha256(frames_path),
               "source_market_plan_sha256": manifest["market_plan_sha256"],
               "decoder_file_sha256": sha256(ROOT / "scripts/paper_streams.py"),
               "book_archive_file_sha256": sha256(Path(__file__)),
               "output_gzip_sha256": sha256(out_dir / "book-events.jsonl.gz"),
               "output_gzip_bytes": (out_dir / "book-events.jsonl.gz").stat().st_size,
               "output_cap_bytes": output_cap, "end_reason": reason,
               "record_counts": dict(counts), "book_events": writer.records,
               "anchor_rows": len(anchor_rows),
               "notes": ["Lighter snapshot and nonce-contiguous deltas reconstructed by paper_streams.StreamManager.",
                         "HL l2Book snapshots only; BBO is not spliced into L2 depth.",
                         "Ticker is used only for post hoc freshness comparison; it never refreshes a book.",
                         "Full-book events are public displayed state, not fills, queue position, or executable depth."],
               "rh_anchor_summary": summarize_anchors(anchor_rows)}
    (out_dir / "manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    if sum((out_dir / name).stat().st_size for name in
           ("book-events.jsonl.gz", "rh-anchor-diagnostics.json", "manifest.json")) > output_cap:
        raise RuntimeError("combined book archive outputs exceed hard cap")
    return summary


def summarize_anchors(rows):
    result = {}
    for asset in ("NVDA", "XAG"):
        a = [r for r in rows if r["asset"] == asset]
        c = Counter()
        for r in a:
            c["anchors"] += 1
            c["book_fresh"] += int(r["book_fresh"])
            c["ticker_fresh"] += int(r["ticker_fresh"])
            c["both_fresh"] += int(r["book_fresh"] and r["ticker_fresh"])
            if r["book_fresh"]:
                for target, z in r["targets"].items():
                    for field in ("bid_order_eligible", "ask_order_eligible",
                                  "bid_top_available", "ask_top_available",
                                  "bid_full_available", "ask_full_available"):
                        c[f"{target}:{field}"] += int(z[field])
        result[asset] = dict(c)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = reconstruct(args.capture, args.out)
    print(f"{args.out}: {report['book_events']} reconstructed events, {report['anchor_rows']} RH anchor rows")


if __name__ == "__main__":
    main()
