#!/usr/bin/env python3
"""Bounded streaming adapter from public RH/HL capture frames to replay events.

No orders, fills, inferred trade-nonce continuity, timestamp shifts, or P&L.
"""

import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from scripts.maker_book_archive import BookRebuilder, selected_markets, sha256
from scripts.maker_capture import parse_epoch_ns

ROOT = Path(__file__).resolve().parents[1]
MAX_RAW_BYTES = 512_000_000
MAX_DECODED_BYTES = 4 * 1024 * 1024 * 1024
MAX_RECORDS = 2_000_000
MAX_LINE_BYTES = 8 * 1024 * 1024
MAX_DURATION_NS = 3001 * 1_000_000_000
MAX_IDS = 1_000_000


def _epoch_ns(value):
    if not isinstance(value, str):
        raise ValueError("manifest timestamp must be ISO8601 text")
    d = datetime.fromisoformat(value)
    if d.tzinfo is None:
        raise ValueError("manifest timestamp must include UTC offset")
    epoch = datetime.fromisoformat("1970-01-01T00:00:00+00:00")
    delta = d - epoch
    return ((delta.days * 86400 + delta.seconds) * 1_000_000_000
            + delta.microseconds * 1000)


def _read_manifest(directory):
    path = Path(directory) / "manifest.json"
    if path.stat().st_size > 1_000_000:
        raise ValueError("capture manifest exceeds 1 MB bound")
    body = json.loads(path.read_text())
    start, stop = _epoch_ns(body["started_utc"]), _epoch_ns(body["ended_utc"])
    if stop < start or stop - start > MAX_DURATION_NS:
        raise ValueError("capture duration exceeds 3001-second bound")
    count = body.get("payload_records")
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= MAX_RECORDS:
        raise ValueError("capture record count exceeds 2-million bound")
    selected = body.get("selected_markets")
    if not isinstance(selected, dict) or not {"hyperliquid", "rh_lighter"}.issubset(selected):
        raise ValueError("capture lacks HL or RH market selection")
    if any(not isinstance(assets, dict) or len(assets) > 100 for assets in selected.values()):
        raise ValueError("capture market selection exceeds bound")
    return body, path, start, stop


def _digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _archive_size(directory, limit):
    total = 0
    entries = 0
    for path in Path(directory).rglob("*"):
        entries += 1
        if entries > 256 or path.is_symlink():
            raise ValueError("capture archive has too many entries or a symlink")
        if path.is_file():
            total += path.stat().st_size
            if total > limit:
                raise ValueError("capture archive exceeds raw-byte bound")
    return total


def _trade(row, raw, expected_market):
    if not isinstance(raw, dict) or raw.get("type") != "trade":
        raise ValueError("RH ordinary trade object missing")
    if str(raw.get("market_id")) != expected_market:
        raise ValueError("RH trade market identity mismatch")
    if not isinstance(raw.get("is_maker_ask"), bool):
        raise ValueError("RH trade aggressor side missing")
    ident = raw.get("trade_id_str", raw.get("trade_id"))
    if isinstance(ident, bool) or not isinstance(ident, (str, int)) or not str(ident).isdigit():
        raise ValueError("RH trade ID missing or malformed")
    trade_id = int(ident)
    if trade_id < 0:
        raise ValueError("RH trade ID negative")
    try:
        price, qty = float(raw["price"]), float(raw["size"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("RH trade price or size malformed") from exc
    if not (math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0):
        raise ValueError("RH trade price or size nonpositive")
    source = parse_epoch_ns(raw["timestamp"], "ms")
    receipt = row["receipt_utc_ns"]
    if source > receipt:
        raise ValueError("RH trade source time ahead of receipt")
    buy_aggressor = raw["is_maker_ask"]
    return {"type": "trade", "kind": "trade", "venue": "rh_lighter",
            "market": expected_market, "generation": row["generation"],
            "received_ns": receipt, "receipt_ns": receipt,
            "receipt_monotonic_ns": row.get("receipt_monotonic_ns"),
            "source_ns": source, "clock_valid": True,
            "price": price, "qty": qty, "trade_id": trade_id,
            "side": "buy" if buy_aggressor else "sell",
            "buy_aggressor": buy_aggressor,
            "trade_nonce_observed": (row.get("payload") or {}).get("nonce")}


def _book_event(event):
    common = {"venue": event["venue"], "asset": event["asset"],
              "market": event["market"], "generation": event["generation"],
              "received_ns": event["receipt_utc_ns"],
              "receipt_ns": event["receipt_utc_ns"],
              "receipt_monotonic_ns": event.get("receipt_monotonic_ns"),
              "source_ns": event["source_utc_ns"], "sequence": event["sequence"]}
    if not event["valid"]:
        return {"type": "invalidate", "kind": "invalidate", **common,
                "scope": "book", "reason": event.get("reason") or "book_invalid",
                "clock_valid": False}
    return {"type": "book", "kind": "book", **common,
            "valid": True, "clock_valid": True, "bids": event["bids"],
            "asks": event["asks"], "feed": event["feed"],
            "level_count": event["level_count"]}


def _invalidate(venue, asset, market, generation, receipt, scope, reason):
    return {"type": "invalidate", "kind": "invalidate",
            "venue": venue, "asset": asset, "market": market,
            "generation": generation, "received_ns": receipt,
            "receipt_ns": receipt, "source_ns": None,
            "scope": scope, "reason": reason, "clock_valid": False}


def iter_events(capture_dir, *, expected_raw_sha256=None,
                max_raw_bytes=MAX_RAW_BYTES, max_decoded_bytes=MAX_DECODED_BYTES,
                max_records=MAX_RECORDS, max_ids=MAX_IDS):
    """Yield book/trade/invalidation/control/end events in archive receipt order.

    Expected gzip SHA must be supplied or present in capture manifest. Any
    malformed input raises; no end marker is then emitted, so consumers fail.
    """
    manifest, manifest_path, start_ns, stop_ns = _read_manifest(capture_dir)
    frames_path = Path(capture_dir) / "frames.jsonl.gz"
    if max_raw_bytes > MAX_RAW_BYTES or max_decoded_bytes > MAX_DECODED_BYTES or max_records > MAX_RECORDS:
        raise ValueError("requested bounds exceed hard limits")
    if max_ids <= 0 or max_ids > MAX_IDS:
        raise ValueError("invalid trade dedup bound")
    archive_bytes = _archive_size(capture_dir, max_raw_bytes)
    expected = (expected_raw_sha256 or manifest.get("frames_sha256") or
                manifest.get("gzip_sha256") or manifest.get("raw_gzip_sha256"))
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected.lower()):
        raise ValueError("expected raw gzip SHA-256 required for verified replay")
    digest = _digest(frames_path)
    if digest.lower() != expected.lower():
        raise ValueError("capture gzip SHA-256 mismatch")
    markets = selected_markets(manifest)
    identities = {(m["venue"], str(m["market"])): m["asset"] for m in markets}
    rh_markets = {str(mid): asset for asset, mid in manifest["selected_markets"]["rh_lighter"].items()}
    pending = []
    rebuilder = BookRebuilder(markets, pending.append)
    counts = Counter()
    ids = defaultdict(set)
    ids_total = 0
    bad_trade_generations = set()
    seen_generation = {}
    prior_receipt = None
    max_receipt_gap_ns = 0
    max_trade_source_lag_ns = 0
    decoded_bytes = 0
    with gzip.open(frames_path, "rb") as f:
        while True:
            line = f.readline(MAX_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
                raise ValueError("captured NDJSON line exceeds 8 MB bound")
            decoded_bytes += len(line)
            counts["decoded_records"] += 1
            if decoded_bytes > max_decoded_bytes or counts["decoded_records"] > max_records or (
                    counts["decoded_records"] > manifest["payload_records"]):
                raise ValueError("decoded capture exceeds bounded replay limits")
            row = json.loads(line)
            receipt = row.get("receipt_utc_ns")
            if isinstance(receipt, bool) or not isinstance(receipt, int) or receipt <= 0:
                raise ValueError("record receipt time missing or malformed")
            if receipt < start_ns or receipt > stop_ns + 1_000:
                raise ValueError("record receipt time outside capture interval")
            if prior_receipt is not None and receipt < prior_receipt:
                raise ValueError("record receipt time moved backward")
            if prior_receipt is not None:
                gap = receipt - prior_receipt
                max_receipt_gap_ns = max(max_receipt_gap_ns, gap)
                if gap > 10 * 1_000_000_000:
                    counts["receipt_gaps_over_10s"] += 1
            prior_receipt = receipt
            venue, generation = row.get("venue"), row.get("generation")
            kind = row.get("kind")
            if venue in ("hyperliquid", "rh_lighter", "lighter") and (
                    not isinstance(generation, str) or not generation):
                raise ValueError("record generation missing")
            if kind == "connection_open" and venue == "rh_lighter":
                prior_gen = seen_generation.get(venue)
                if prior_gen is not None and prior_gen != generation:
                    ids_total -= sum(len(s) for (v, _, g), s in ids.items() if v == venue and g == prior_gen)
                    for key in list(ids):
                        if key[0] == venue and key[2] == prior_gen:
                            del ids[key]
                    bad_trade_generations = {key for key in bad_trade_generations
                                             if not (key[0] == venue and key[2] == prior_gen)}
                seen_generation[venue] = generation
            terminal_kinds = ("connection_close", "connection_error", "invalid_json",
                              "generation_invalidated")
            if kind in terminal_kinds and venue == "rh_lighter":
                counts[f"rh_{kind}"] += 1
            # The frozen full-book decoder predates generation_invalidated.
            # Feed it a close so its HL snapshot and RH delta state are cleared.
            rebuild_row = (dict(row, kind="connection_close")
                           if kind == "generation_invalidated" else row)
            rebuilder.process(rebuild_row)
            for book in pending:
                normalized = _book_event(book)
                if kind == "generation_invalidated" and normalized["type"] == "invalidate":
                    normalized["reason"] = kind
                counts[f"yield_{normalized['type']}_{normalized['venue']}"] += 1
                if normalized["type"] == "invalidate":
                    counts[f"book_invalidation:{normalized['reason']}"] += 1
                elif isinstance(normalized.get("source_ns"), int):
                    lag = receipt - normalized["source_ns"]
                    if lag > 10 * 1_000_000_000:
                        counts["book_source_lag_over_10s"] += 1
                yield normalized
            pending.clear()
            if kind in ("connection_open", *terminal_kinds):
                counts[f"control_{kind}"] += 1
                yield {"type": "control", "kind": "control", "venue": venue,
                       "generation": generation, "received_ns": receipt,
                       "receipt_ns": receipt, "source_ns": None,
                       "control": kind}
                if kind in terminal_kinds and venue == "rh_lighter":
                    for market, asset in rh_markets.items():
                        bad_trade_generations.add((venue, market, generation))
                        counts["yield_invalidate_trade"] += 1
                        yield _invalidate(venue, asset, market, generation, receipt,
                                          "trade", kind)
                elif kind == "connection_open" and venue == "rh_lighter" and prior_gen is not None and prior_gen != generation:
                    for market, asset in rh_markets.items():
                        counts["yield_invalidate_trade"] += 1
                        yield _invalidate(venue, asset, market, prior_gen, receipt,
                                          "trade", "generation_change")
                continue
            if kind != "frame" or venue != "rh_lighter" or row.get("channel") != "trade":
                if kind == "frame" and venue == "hyperliquid" and row.get("channel") == "trades":
                    counts["ignored_hl_trade_frames"] += 1
                continue
            market = str(row.get("market"))
            asset = rh_markets.get(market)
            if asset is None:
                counts["unknown_rh_trade_market"] += 1
                for m, a in rh_markets.items():
                    bad_trade_generations.add((venue, m, generation))
                    counts["yield_invalidate_trade"] += 1
                    yield _invalidate(venue, a, m, generation, receipt, "trade",
                                      "unknown_trade_market")
                continue
            key = (venue, market, generation)
            payload = row.get("payload") or {}
            if payload.get("type") == "subscribed/trade":
                counts["ignored_subscribed_trade_frames"] += 1
                backlog, liquidations = payload.get("trades"), payload.get("liquidation_trades")
                if not isinstance(backlog, list) or not isinstance(liquidations, list):
                    bad_trade_generations.add(key)
                    counts["invalid_trade_batches"] += 1
                    counts["yield_invalidate_trade"] += 1
                    yield _invalidate(venue, asset, market, generation, receipt, "trade",
                                      "malformed_subscribed_trade_batch")
                    continue
                counts["ignored_subscribed_trade_rows"] += len(backlog)
                counts["ignored_liquidations"] += len(liquidations)
                continue
            if key in bad_trade_generations:
                counts["suppressed_trade_frames_after_gap"] += 1
                continue
            annotation = row.get("annotation") or {}
            if payload.get("type") != "update/trade" or annotation.get("quality") != "wire_ok" or (
                    annotation.get("source_regression_within_channel")):
                bad_trade_generations.add(key)
                counts["invalid_trade_batches"] += 1
                counts["yield_invalidate_trade"] += 1
                yield _invalidate(venue, asset, market, generation, receipt, "trade",
                                  annotation.get("reason") or "trade_frame_invalid")
                continue
            raw_trades, liquidations = payload.get("trades"), payload.get("liquidation_trades")
            if not isinstance(raw_trades, list) or not isinstance(liquidations, list):
                bad_trade_generations.add(key)
                counts["invalid_trade_batches"] += 1
                counts["yield_invalidate_trade"] += 1
                yield _invalidate(venue, asset, market, generation, receipt, "trade",
                                  "malformed_trade_batch")
                continue
            counts["ignored_liquidations"] += len(liquidations)
            try:
                parsed = [_trade(row, raw, market) for raw in raw_trades]
                if len({t["trade_id"] for t in parsed}) != len(parsed):
                    raise ValueError("duplicate ID within trade batch")
            except (KeyError, TypeError, ValueError) as exc:
                bad_trade_generations.add(key)
                counts["invalid_trade_batches"] += 1
                counts["yield_invalidate_trade"] += 1
                if "source time ahead of receipt" in str(exc):
                    counts["rejected_source_ahead_trade_batches"] += 1
                yield _invalidate(venue, asset, market, generation, receipt, "trade",
                                  f"bad_trade_fields:{str(exc)[:80]}")
                continue
            unseen = {t["trade_id"] for t in parsed if t["trade_id"] not in ids[key]}
            if ids_total + len(unseen) > max_ids:
                bad_trade_generations.add(key)
                counts["dedup_capacity_exceeded"] += 1
                counts["yield_invalidate_trade"] += 1
                yield _invalidate(venue, asset, market, generation, receipt, "trade",
                                  "dedup_capacity_exceeded")
                continue
            for trade in parsed:
                trade["asset"] = asset
                ident = trade["trade_id"]
                if ident in ids[key]:
                    counts["duplicate_trade_ids"] += 1
                    continue
                ids[key].add(ident)
                ids_total += 1
                counts["yield_trade"] += 1
                lag = receipt - trade["source_ns"]
                max_trade_source_lag_ns = max(max_trade_source_lag_ns, lag)
                if lag > 10 * 1_000_000_000:
                    counts["trade_source_lag_over_10s"] += 1
                yield trade
    if counts["decoded_records"] != manifest["payload_records"]:
        raise ValueError("decoded record count does not match capture manifest")
    if _digest(frames_path) != digest:
        raise ValueError("capture gzip changed during replay")
    reason = manifest.get("end_reason") or "unknown"
    truncated = bool(manifest.get("truncated")) or reason in ("compressed_size_cap", "raw_size_cap")
    yield {"type": "end", "kind": "end", "received_ns": stop_ns,
           "receipt_ns": stop_ns, "source_ns": None,
           "started_ns": start_ns, "stopped_ns": stop_ns,
           "reason": reason, "truncated": truncated,
           "counts": dict(counts), "decoded_bytes": decoded_bytes,
           "archive_bytes": archive_bytes,
           "max_receipt_gap_ns": max_receipt_gap_ns,
           "max_trade_source_lag_ns": max_trade_source_lag_ns,
           "book_decoder_counts": dict(rebuilder.counts),
           "book_status_counts": {v: dict(c) for v, c in rebuilder.manager.counters.items()},
           "raw_gzip_sha256": digest, "raw_sha_verified": True,
           "manifest_sha256": sha256(manifest_path),
           "adapter_sha256": sha256(Path(__file__)),
           "book_decoder_sha256": sha256(ROOT / "scripts/maker_book_archive.py")}
