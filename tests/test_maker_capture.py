import asyncio
import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.maker_capture import (BoundedGzip, Capture, FeedQuality, capture,
                                   SizeCapReached, parse_epoch_ns,
                                   select_markets, subscriptions)


MS = 1_790_700_000_000
US = MS * 1000


def lighter_book(kind, *, nonce, begin=None, source=US):
    body = {"nonce": nonce, "last_updated_at": source, "bids": [], "asks": []}
    if begin is not None:
        body["begin_nonce"] = begin
    return {"type": kind, "channel": "order_book:1", "order_book": body}


class MakerCaptureTests(unittest.TestCase):
    def test_timestamp_units_and_bad_values(self):
        self.assertEqual(parse_epoch_ns(MS, "ms"), parse_epoch_ns(US, "us"))
        self.assertEqual(parse_epoch_ns(str(MS), "ms"), MS * 1_000_000)
        for value in (None, True, "1.7907e12", "", 0, -1, 123.4):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_epoch_ns(value, "ms")

    def test_cap_stops_before_a_partial_frame_and_gzip_stays_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.jsonl.gz"
            row = {"payload": "x" * 500}
            one = gzip.compress(json.dumps(row, separators=(",", ":")).encode() + b"\n", mtime=0)
            writer = BoundedGzip(path, total_cap=64 + len(one) + 1, reserve=64)
            writer.write(row)
            with self.assertRaises(SizeCapReached):
                writer.write(row)
            writer.close()
            self.assertEqual(path.stat().st_size, len(one))
            with gzip.open(path, "rt") as f:
                self.assertEqual([json.loads(x) for x in f], [row])

    def test_concatenated_gzip_records_stream_as_ndjson(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.jsonl.gz"
            writer = BoundedGzip(path, total_cap=5_000, reserve=100)
            writer.write({"seq": 1})
            writer.write({"seq": 2})
            writer.close()
            with gzip.open(path, "rt") as f:
                self.assertEqual([json.loads(x)["seq"] for x in f], [1, 2])

    def test_capture_records_size_end_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = BoundedGzip(Path(tmp) / "frames.jsonl.gz", total_cap=400, reserve=100)
            c = Capture(writer, {"hyperliquid": {"BTC": "BTC"}}, 600, 400)
            for _ in range(100):
                if not c.record({"kind": "frame", "venue": "hyperliquid", "market": "BTC",
                                 "channel": "bbo", "payload": "random" * 100}):
                    break
            writer.close()
            self.assertEqual(c.end_reason, "compressed_size_cap")
            self.assertTrue(c.stop.is_set())
            self.assertEqual(c.dropped_on_cap, 1)
            self.assertLessEqual(writer.bytes_written, 300)

    def test_lighter_gap_invalidates_until_fresh_snapshot(self):
        q = FeedQuality()
        venue, gen = "lighter", "g1"
        self.assertEqual(q.inspect(venue, lighter_book("subscribed/order_book", nonce=10), gen)["quality"],
                         "wire_ok_snapshot")
        good = q.inspect(venue, lighter_book("update/order_book", nonce=12, begin=10), gen)
        self.assertEqual(good["quality"], "wire_ok")
        self.assertEqual(good["source_min_ns"], US * 1000)
        gap = q.inspect(venue, lighter_book("update/order_book", nonce=15, begin=13), gen)
        self.assertEqual(gap["reason"], "nonce_gap")
        self.assertFalse(gap["book_frame_ok"])
        late = q.inspect(venue, lighter_book("update/order_book", nonce=16, begin=15), gen)
        self.assertEqual(late["reason"], "delta_without_snapshot")
        self.assertEqual(q.inspect(venue, lighter_book("subscribed/order_book", nonce=16), gen)["quality"],
                         "wire_ok_snapshot")
        self.assertEqual(q.inspect(venue, lighter_book("update/order_book", nonce=17, begin=16), gen)["quality"],
                         "wire_ok")

    def test_malformed_book_time_and_null_bbo_invalidate(self):
        q = FeedQuality()
        bad = q.inspect("lighter", lighter_book("subscribed/order_book", nonce=1, source="wrong"), "g1")
        self.assertEqual(bad["reason"], "malformed_book_time_or_nonce")
        self.assertFalse(bad["book_frame_ok"])
        empty = q.inspect("hyperliquid", {"channel": "bbo", "data": {
            "coin": "BTC", "time": MS, "bbo": [None, {"px": "10", "sz": "1", "n": 1}]}}, "g1")
        self.assertEqual(empty["reason"], "empty_book_side")
        self.assertFalse(empty["book_frame_ok"])
        good = q.inspect("hyperliquid", {"channel": "bbo", "data": {
            "coin": "BTC", "time": MS + 1, "bbo": [
                {"px": "9", "sz": "1", "n": 1}, {"px": "10", "sz": "1", "n": 1}]}}, "g1")
        self.assertTrue(good["book_frame_ok"])

    def test_bad_trade_time_marks_generation_gap(self):
        q = FeedQuality()
        base = {"type": "update/trade", "channel": "trade:1", "trades": [{"timestamp": "bad"}]}
        self.assertEqual(q.inspect("rh_lighter", base, "g1")["reason"], "malformed_trade_time")
        base["trades"] = [{"timestamp": MS}]
        self.assertEqual(q.inspect("rh_lighter", base, "g1")["quality"], "gap_after_bad_trade")
        self.assertEqual(q.inspect("rh_lighter", base, "g2")["quality"], "wire_ok")

    def test_source_regression_is_per_channel_and_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = BoundedGzip(Path(tmp) / "frames.jsonl.gz", total_cap=5_000, reserve=100)
            c = Capture(writer, {"hyperliquid": {"BTC": "BTC"}}, 2, 5_000)
            a = {"market": "BTC", "channel": "bbo", "source_max_ns": 200}
            c.note_source_order("hyperliquid", "g1", a)
            older_l2 = {"market": "BTC", "channel": "l2Book", "source_max_ns": 100}
            c.note_source_order("hyperliquid", "g1", older_l2)
            self.assertNotIn("source_regression_within_channel", older_l2)
            older_bbo = {"market": "BTC", "channel": "bbo", "source_max_ns": 150}
            c.note_source_order("hyperliquid", "g1", older_bbo)
            self.assertTrue(older_bbo["source_regression_within_channel"])
            new_gen = {"market": "BTC", "channel": "bbo", "source_max_ns": 150}
            c.note_source_order("hyperliquid", "g2", new_gen)
            self.assertNotIn("source_regression_within_channel", new_gen)
            writer.close()

    def test_plan_and_subscriptions_are_public_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "markets.json"
            path.write_text(json.dumps({"pairs": [
                {"asset": asset, "hl": {"venue": "hyperliquid", "market": asset, "asset": asset},
                 "other": {"venue": venue, "market": 1 if asset == "BTC" else 0, "asset": asset}}
                for asset in ("BTC", "ETH") for venue in ("lighter", "rh_lighter")]}))
            markets, digest = select_markets(path)
            self.assertEqual(len(digest), 64)
            self.assertEqual(markets["lighter"], {"BTC": "1", "ETH": "0"})
            messages = [m for v, a in markets.items() for m in subscriptions(v, a)]
            self.assertEqual(len(messages), 18)
            text = json.dumps(messages).lower()
            self.assertNotIn("sendtx", text)
            self.assertNotIn("order\"", text)
            self.assertIn("trade/1", text)

    def test_offline_run_writes_bounded_manifest(self):
        async def fake_venue_loop(self, venue):
            self.record({"kind": "frame", "venue": venue, "market": "BTC", "channel": "bbo",
                         "payload": {"channel": "bbo"}})
            self.finish("offline_test")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "capture"
            args = SimpleNamespace(out=out, markets=Path(tmp) / "markets.json",
                                   seconds=2, max_bytes=80_000)
            with patch.object(Capture, "venue_loop", fake_venue_loop):
                asyncio.run(capture(args, {"hyperliquid": {"BTC": "BTC", "ETH": "ETH"}}, "abc"))
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["end_reason"], "offline_test")
            self.assertFalse(manifest["truncated"])
            self.assertLessEqual((out / "frames.jsonl.gz").stat().st_size
                                 + (out / "manifest.json").stat().st_size, args.max_bytes)
            with gzip.open(out / "frames.jsonl.gz", "rt") as f:
                self.assertEqual(len(f.readlines()), 1)


if __name__ == "__main__":
    unittest.main()
