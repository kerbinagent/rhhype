"""Snapshot/delta reconstruction and clock/depth guards for book archives."""

import unittest
import gzip
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import scripts.maker_book_archive as archive
from scripts.maker_book_archive import BookRebuilder, SECOND, evaluate_anchor, fresh, quantity, order_eligible, rh_ticker_reset_required


BASE = 1_790_000_000 * SECOND


def lighter_row(kind, nonce, bids, asks, *, begin=None, source_us=None, receipt_ns=None,
                generation="rh:1", venue="rh_lighter", market="15"):
    source_us = source_us or BASE // 1000
    receipt_ns = receipt_ns or BASE + 50_000_000
    body = {"nonce": nonce, "last_updated_at": source_us,
            "bids": bids, "asks": asks}
    if begin is not None:
        body["begin_nonce"] = begin
    return {"kind": "frame", "venue": venue, "market": market, "channel": "order_book",
            "generation": generation, "receipt_utc_ns": receipt_ns,
            "receipt_monotonic_ns": 1,
            "annotation": {"quality": "wire_ok_snapshot" if kind == "subscribed/order_book" else "wire_ok",
                           "source_max_ns": source_us * 1000},
            "payload": {"type": kind, "channel": f"order_book:{market}", "order_book": body}}


class BookArchiveTest(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.rebuilder = BookRebuilder([
            {"venue": "rh_lighter", "market": "15", "asset": "NVDA"},
            {"venue": "hyperliquid", "market": "xyz:NVDA", "asset": "NVDA"}],
            self.events.append)

    def test_snapshot_delta_full_levels_and_nonce_gap(self):
        snap = lighter_row("subscribed/order_book", 1,
                           [{"price": "100", "size": "2"}, {"price": "99", "size": "3"}],
                           [{"price": "101", "size": "4"}, {"price": "102", "size": "5"}])
        self.rebuilder.process(snap)
        self.assertEqual(self.events[-1]["bids"], [(100.0, 2.0), (99.0, 3.0)])
        delta = lighter_row("update/order_book", 2,
                            [{"price": "100", "size": "0"}, {"price": "98", "size": "6"}],
                            [{"price": "101", "size": "7"}], begin=1,
                            source_us=BASE // 1000 + 100000, receipt_ns=BASE + 150_000_000)
        self.rebuilder.process(delta)
        self.assertEqual(self.events[-1]["bids"], [(99.0, 3.0), (98.0, 6.0)])
        self.assertEqual(self.events[-1]["asks"], [(101.0, 7.0), (102.0, 5.0)])
        bad = lighter_row("update/order_book", 4, [], [], begin=3,
                          source_us=BASE // 1000 + 200000, receipt_ns=BASE + 250_000_000)
        self.rebuilder.process(bad)
        self.assertFalse(self.events[-1]["valid"])
        self.assertEqual(self.events[-1]["reason"], "nonce_gap")
        after = lighter_row("update/order_book", 5, [], [], begin=4,
                            source_us=BASE // 1000 + 300000, receipt_ns=BASE + 350_000_000)
        self.rebuilder.process(after)
        self.assertFalse(self.events[-1]["valid"])
        self.assertEqual(self.events[-1]["reason"], "delta_without_snapshot")

    def test_ticker_does_not_refresh_book_and_generation_resets(self):
        snap = lighter_row("subscribed/order_book", 1,
                           [{"price": "100", "size": "2"}], [{"price": "101", "size": "4"}])
        self.rebuilder.process(snap)
        n = len(self.events)
        self.rebuilder.process({"kind": "frame", "venue": "rh_lighter", "market": "15",
                                "channel": "ticker", "generation": "rh:1", "receipt_utc_ns": BASE + SECOND,
                                "annotation": {"quality": "wire_ok", "source_max_ns": BASE + SECOND},
                                "payload": {"type": "update/ticker"}})
        self.assertEqual(len(self.events), n)
        self.rebuilder.process({"kind": "connection_open", "venue": "rh_lighter",
                                "generation": "rh:2", "receipt_utc_ns": BASE + 2 * SECOND})
        self.assertFalse(self.events[-1]["valid"])
        self.assertEqual(self.events[-1]["reason"], "generation_change")
        self.assertTrue(rh_ticker_reset_required({"kind": "connection_open", "venue": "rh_lighter",
                                                  "generation": "rh:2"}, "rh:1"))
        self.assertFalse(rh_ticker_reset_required({"kind": "connection_open", "venue": "rh_lighter",
                                                   "generation": "rh:2"}, "rh:2"))

    def test_disconnect_invalidates_cached_rh_and_hl_books(self):
        snap = lighter_row("subscribed/order_book", 1,
                           [{"price": "100", "size": "2"}], [{"price": "101", "size": "4"}])
        self.rebuilder.process(snap)
        self.assertTrue(fresh(self.rebuilder.latest[("rh_lighter", "NVDA")], BASE + 100_000_000))
        self.rebuilder.process({"kind": "connection_close", "venue": "rh_lighter",
                                "generation": "rh:1", "receipt_utc_ns": BASE + 150_000_000})
        self.assertFalse(fresh(self.rebuilder.latest[("rh_lighter", "NVDA")], BASE + 200_000_000))
        self.assertEqual(self.rebuilder.latest[("rh_lighter", "NVDA")]["reason"], "connection_close")
        hl = {"kind": "frame", "venue": "hyperliquid", "market": "xyz:NVDA",
              "channel": "l2Book", "generation": "hl:1", "receipt_utc_ns": BASE + 10_000_000,
              "annotation": {"quality": "wire_ok", "source_max_ns": BASE},
              "payload": {"channel": "l2Book", "data": {"coin": "xyz:NVDA",
                          "time": BASE // 1_000_000,
                          "levels": [[{"px": "100", "sz": "2", "n": 1}],
                                     [{"px": "101", "sz": "4", "n": 1}]]}}}
        self.rebuilder.process(hl)
        self.assertTrue(self.rebuilder.latest[("hyperliquid", "NVDA")]["valid"])
        self.rebuilder.process({"kind": "connection_close", "venue": "hyperliquid",
                                "generation": "hl:1", "receipt_utc_ns": BASE + 150_000_000})
        self.assertFalse(fresh(self.rebuilder.latest[("hyperliquid", "NVDA")], BASE + 200_000_000))

    def test_hl_only_l2_and_clock_guard(self):
        self.rebuilder.process({"kind": "frame", "venue": "hyperliquid", "market": "xyz:NVDA",
                                "channel": "bbo", "generation": "hl:1", "receipt_utc_ns": BASE,
                                "annotation": {"quality": "wire_ok", "source_max_ns": BASE},
                                "payload": {"channel": "bbo"}})
        self.assertFalse(self.events)
        row = {"kind": "frame", "venue": "hyperliquid", "market": "xyz:NVDA",
               "channel": "l2Book", "generation": "hl:1", "receipt_utc_ns": BASE + 10_000_000,
               "annotation": {"quality": "wire_ok", "source_max_ns": BASE},
               "payload": {"channel": "l2Book", "data": {"coin": "xyz:NVDA",
                           "time": BASE // 1_000_000,
                           "levels": [[{"px": "100", "sz": "2", "n": 1}],
                                      [{"px": "101", "sz": "4", "n": 1}]]}}}
        self.rebuilder.process(row)
        self.assertTrue(self.events[-1]["valid"])
        self.assertEqual(self.events[-1]["feed"], "l2Book")
        self.assertEqual(self.events[-1]["source_utc_ns"], BASE)
        payload2 = {"channel": "l2Book", "data": {**row["payload"]["data"],
                    "time": BASE // 1_000_000 + 20}}
        row2 = dict(row, receipt_utc_ns=BASE + 20_000_000,
                    annotation={"quality": "wire_ok", "source_max_ns": BASE + 30_000_000},
                    payload=payload2)
        self.rebuilder.process(row2)
        self.assertFalse(self.events[-1]["valid"])
        self.assertEqual(self.events[-1]["reason"], "invalid_source_or_clock")

    def test_anchor_depth_sizes_and_freshness(self):
        book = {"valid": True, "generation": "g", "receipt_utc_ns": BASE,
                "source_utc_ns": BASE - 100_000_000,
                "bids": [[100, .5], [99, 1.0]], "asks": [[101, .25], [102, 1.0]],
                "level_count": {"bids": 2, "asks": 2}}
        ticker = {"valid": True, "receipt_utc_ns": BASE,
                  "source_utc_ns": BASE - 100_000_000}
        meta = {"NVDA": {"step": ".0001", "min_qty": ".04", "min_notional": 10},
                "XAG": {"step": ".01", "min_qty": ".15", "min_notional": 10}}
        z = evaluate_anchor(BASE + 100_000_000,
                            {("rh_lighter", "NVDA"): book},
                            {("rh_lighter", "NVDA"): ticker}, meta)
        nvda = z[0]
        self.assertTrue(nvda["book_fresh"])
        self.assertTrue(nvda["ticker_fresh"])
        self.assertTrue(nvda["targets"]["100"]["bid_full_available"])
        self.assertFalse(nvda["targets"]["100"]["ask_top_available"])
        self.assertTrue(nvda["targets"]["100"]["ask_full_available"])
        self.assertFalse(fresh(book, BASE + 2 * SECOND))
        self.assertAlmostEqual(quantity("NVDA", 100, 101), .99)
        self.assertFalse(order_eligible(.01, 101, meta["NVDA"]))

    def test_bounded_reader_rejects_declared_count_and_long_line(self):
        plan = Path(__file__).resolve().parents[1] / "reports/maker-equity-v2/market-plan.json"
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "input"
            folder.mkdir()
            manifest = {"truncated": False, "errors": [],
                        "configured_total_compressed_bytes": 25_000_000,
                        "payload_records": archive.MAX_RECORDS + 1,
                        "selected_markets": {"hyperliquid": {"NVDA": "xyz:NVDA", "XAG": "xyz:SILVER"},
                                             "lighter": {"NVDA": "110", "XAG": "93"},
                                             "rh_lighter": {"NVDA": "15", "XAG": "41"}},
                        "market_plan": str(plan), "market_plan_sha256": archive.sha256(plan),
                        "started_utc": "2026-09-29T20:22:56+00:00",
                        "ended_utc": "2026-09-29T20:29:56+00:00"}
            (folder / "frames.jsonl.gz").write_bytes(gzip.compress(b""))
            (folder / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "record count"):
                archive.reconstruct(folder, Path(d) / "output")
            manifest["payload_records"] = 1
            (folder / "manifest.json").write_text(json.dumps(manifest))
            (folder / "frames.jsonl.gz").write_bytes(gzip.compress(b"x" * 64 + b"\n"))
            with patch.object(archive, "MAX_RECORD_BYTES", 32):
                with self.assertRaisesRegex(ValueError, "bounded frame size"):
                    archive.reconstruct(folder, Path(d) / "output2")


if __name__ == "__main__":
    unittest.main()
