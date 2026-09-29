"""Streaming adapter contract: ordered books, RH flow, invalidation, and bounds."""

import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.rh_maker_events import iter_events


BASE = 1_790_000_000_000_000_000


def row(kind, receipt, *, venue="rh_lighter", generation="rh:1", market=None,
        channel=None, payload=None, annotation=None):
    return {"kind": kind, "venue": venue, "generation": generation,
            "receipt_utc_ns": receipt, "market": market, "channel": channel,
            "payload": payload, "annotation": annotation}


def trade(trade_id, ms, *, side=False, market=15):
    return {"type": "trade", "trade_id_str": str(trade_id), "market_id": market,
            "is_maker_ask": side, "timestamp": ms,
            "price": "100.5", "size": "2.0"}


def snapshot(receipt):
    source_us = (receipt - 20_000_000) // 1000
    return row("frame", receipt, market="15", channel="order_book",
               annotation={"quality": "wire_ok_snapshot", "source_max_ns": source_us * 1000},
               payload={"type": "subscribed/order_book", "channel": "order_book:15",
                        "order_book": {"nonce": 1, "last_updated_at": source_us,
                                       "bids": [{"price": "100", "size": "3"},
                                                {"price": "99", "size": "4"}],
                                       "asks": [{"price": "101", "size": "5"}]}})


def trade_frame(receipt, trades, typ="update/trade", *, quality="wire_ok"):
    return row("frame", receipt, market="15", channel="trade",
               annotation={"quality": quality, "source_max_ns": receipt - 50_000_000},
               payload={"type": typ, "channel": "trade:15", "nonce": 77,
                        "trades": trades, "liquidation_trades": []})


def fixture(folder, rows, **overrides):
    folder = Path(folder)
    folder.mkdir(exist_ok=True)
    raw = b"".join(json.dumps(x, separators=(",", ":")).encode() + b"\n" for x in rows)
    gz = gzip.compress(raw, mtime=0)
    (folder / "frames.jsonl.gz").write_bytes(gz)
    start = datetime.fromtimestamp(BASE / 1e9, timezone.utc).isoformat()
    stop = datetime.fromtimestamp(BASE / 1e9 + 30, timezone.utc).isoformat()
    manifest = {"started_utc": start, "ended_utc": stop, "payload_records": len(rows),
                "selected_markets": {"hyperliquid": {"BTC": "BTC"},
                                     "rh_lighter": {"NVDA": "15"}},
                "frames_sha256": hashlib.sha256(gz).hexdigest(),
                "end_reason": "duration_limit", "truncated": False}
    manifest.update(overrides)
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


class RhMakerEventsTest(unittest.TestCase):
    def test_books_backlog_dedup_bad_batch_disconnect_and_end(self):
        ms = BASE // 1_000_000
        rows = [row("connection_open", BASE, market=None),
                snapshot(BASE + 100_000_000),
                trade_frame(BASE + 200_000_000, [trade(1, ms - 1000)], "subscribed/trade"),
                trade_frame(BASE + 300_000_000, [trade(2, ms + 250, side=False)]),
                trade_frame(BASE + 400_000_000, [trade(2, ms + 250, side=False)]),
                trade_frame(BASE + 500_000_000, [trade(3, ms + 450, side=True, market=999)]),
                trade_frame(BASE + 600_000_000, [trade(4, ms + 550, side=False)]),
                row("connection_close", BASE + 700_000_000)]
        with tempfile.TemporaryDirectory() as d:
            path = fixture(Path(d) / "capture", rows)
            events = list(iter_events(path))
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[0], "control")
        books = [e for e in events if e["type"] == "book"]
        self.assertEqual(len(books), 1)
        self.assertEqual(len(books[0]["bids"]), 2)
        self.assertEqual((books[0]["received_ns"], books[0]["source_ns"]),
                         (BASE + 100_000_000, BASE + 80_000_000))
        flow = [e for e in events if e["type"] == "trade"]
        self.assertEqual(len(flow), 1)
        self.assertEqual((flow[0]["side"], flow[0]["trade_id"], flow[0]["source_ns"]),
                         ("sell", 2, BASE + 250_000_000))
        reasons = [e["reason"] for e in events if e["type"] == "invalidate"]
        self.assertTrue(any(x.startswith("bad_trade_fields") for x in reasons))
        self.assertIn("connection_close", reasons)
        end = events[-1]
        self.assertEqual(end["type"], "end")
        self.assertTrue(end["raw_sha_verified"])
        self.assertEqual(end["counts"]["ignored_subscribed_trade_rows"], 1)
        self.assertEqual(end["counts"]["duplicate_trade_ids"], 1)
        self.assertEqual(end["counts"]["suppressed_trade_frames_after_gap"], 1)

    def test_backward_receipt_and_bad_digest_fail_closed(self):
        rows = [row("connection_open", BASE + 200), row("connection_close", BASE + 100)]
        with tempfile.TemporaryDirectory() as d:
            path = fixture(Path(d) / "capture", rows)
            with self.assertRaisesRegex(ValueError, "moved backward"):
                list(iter_events(path))
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                list(iter_events(path, expected_raw_sha256="0" * 64))

    def test_dedup_capacity_invalidates_before_partial_batch(self):
        ms = BASE // 1_000_000
        rows = [row("connection_open", BASE),
                trade_frame(BASE + 300_000_000,
                            [trade(1, ms + 250), trade(2, ms + 250)])]
        with tempfile.TemporaryDirectory() as d:
            path = fixture(Path(d) / "capture", rows)
            events = list(iter_events(path, max_ids=1))
        self.assertFalse([e for e in events if e["type"] == "trade"])
        self.assertTrue(any(e.get("reason") == "dedup_capacity_exceeded" for e in events))

    def test_declared_duration_and_line_bounds(self):
        with tempfile.TemporaryDirectory() as d:
            path = fixture(Path(d) / "capture", [row("connection_open", BASE)],
                           ended_utc=datetime.fromtimestamp(BASE / 1e9 + 4000, timezone.utc).isoformat())
            with self.assertRaisesRegex(ValueError, "duration"):
                list(iter_events(path))

    def test_error_and_generation_end_invalidate_books_and_trade_flow(self):
        ms = BASE // 1_000_000
        rows = [row("connection_open", BASE), snapshot(BASE + 100_000_000),
                trade_frame(BASE + 200_000_000, [trade(1, ms + 150)]),
                row("invalid_json", BASE + 300_000_000),
                trade_frame(BASE + 400_000_000, [trade(2, ms + 350)]),
                row("generation_invalidated", BASE + 500_000_000)]
        with tempfile.TemporaryDirectory() as d:
            events = list(iter_events(fixture(Path(d) / "capture", rows)))
        self.assertEqual(len([e for e in events if e["type"] == "trade"]), 1)
        for reason in ("invalid_json", "generation_invalidated"):
            self.assertTrue(any(e["type"] == "invalidate" and e["scope"] == "book"
                                and e["reason"] == reason for e in events))
            self.assertTrue(any(e["type"] == "invalidate" and e["scope"] == "trade"
                                and e["reason"] == reason for e in events))
        self.assertEqual(events[-1]["counts"]["suppressed_trade_frames_after_gap"], 1)

    def test_source_ahead_trade_invalidates_whole_batch(self):
        ms = BASE // 1_000_000
        rows = [row("connection_open", BASE),
                trade_frame(BASE + 200_000_000,
                            [trade(1, ms + 100), trade(2, ms + 300)])]
        with tempfile.TemporaryDirectory() as d:
            events = list(iter_events(fixture(Path(d) / "capture", rows)))
        self.assertFalse([e for e in events if e["type"] == "trade"])
        self.assertEqual(events[-1]["counts"]["rejected_source_ahead_trade_batches"], 1)


if __name__ == "__main__":
    unittest.main()
