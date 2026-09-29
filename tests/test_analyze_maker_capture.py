"""Focused checks for the stopped public-feed replay's conservative gates."""

import unittest
from collections import Counter

from scripts.analyze_maker_capture import (
    SECOND, discard_prequote_trades, eligible_flow, first_future_quote, require_contiguous_capture,
    trade_from_payload,
)


class MakerCaptureAnalysisTests(unittest.TestCase):
    def test_future_quote_skips_pre_horizon_source_and_stops_at_wait_limit(self):
        target = 10 * SECOND
        quotes = [
            {"receipt_ns": target + 100_000_000, "source_ns": target - 100_000_000},
            {"receipt_ns": target + 400_000_000, "source_ns": target + 100_000_000},
            {"receipt_ns": target + 1_200_000_000, "source_ns": target + SECOND},
        ]
        times = [q["receipt_ns"] for q in quotes]
        self.assertIs(first_future_quote(quotes, times, target), quotes[1])
        self.assertIsNone(first_future_quote(quotes, times, target + 500_000_000,
                                              max_wait_ns=500_000_000))

    def test_trade_flow_requires_more_than_displayed_queue_and_no_reuse(self):
        arrival = 10 * SECOND
        trades = [
            {"source_ns": arrival + SECOND, "receipt_ns": arrival + SECOND, "id": 1,
             "buy_aggressor": False, "price": 100.0, "qty": 1.0},
            {"source_ns": arrival + SECOND, "receipt_ns": arrival + SECOND, "id": 1,
             "buy_aggressor": False, "price": 100.0, "qty": 1.0},
            {"source_ns": arrival + 2 * SECOND, "receipt_ns": arrival + 2 * SECOND, "id": 2,
             "buy_aggressor": False, "price": 100.0, "qty": 0.4},
        ]
        source_times = [t["source_ns"] for t in trades]
        result = eligible_flow(trades, source_times, arrival, arrival + 5 * SECOND,
                               "buy", 100.0, ahead=1.0, qty=1.0)
        self.assertAlmostEqual(result["trade_flow_qty"], 1.4)
        self.assertTrue(result["possible_partial"])
        self.assertFalse(result["possible_full"])
        self.assertEqual(result["first_partial_source_ns"], arrival + 2 * SECOND)

    def test_missing_hyperliquid_trade_identity_is_rejected(self):
        raw = {"coin": "BTC", "side": "B", "time": 10_000, "px": "100", "sz": "1"}
        self.assertIsNone(trade_from_payload("hyperliquid", "BTC", raw, 11 * SECOND))
        raw.update(tid=7, hash="0xabc")
        self.assertIsNotNone(trade_from_payload("hyperliquid", "BTC", raw, 11 * SECOND))

    def test_first_trade_frame_before_first_quote_is_filtered_after_discovery(self):
        trades = {("hyperliquid", "BTC"): [{"source_ns": 8 * SECOND},
                                           {"source_ns": 11 * SECOND}]}
        first_quotes = {("hyperliquid", "BTC"): 10 * SECOND}
        counts = Counter()
        discard_prequote_trades(trades, first_quotes, counts)
        self.assertEqual([t["source_ns"] for t in trades[("hyperliquid", "BTC")]], [11 * SECOND])
        self.assertEqual(counts["hyperliquid|BTC|prequote_trade_replays"], 1)

    def test_replay_rejects_generation_change_and_bad_trade(self):
        data = {"manifest": {"generations": [{"venue": v} for v in
                                           ("hyperliquid", "lighter", "rh_lighter")],
                             "invalidations": {}},
                "counts": Counter(), "unknown_trade_market": 0, "bad_trade_fields": Counter()}
        require_contiguous_capture(data)
        data["manifest"]["generations"].append({"venue": "hyperliquid"})
        with self.assertRaisesRegex(RuntimeError, "generations"):
            require_contiguous_capture(data)
        data["manifest"]["generations"].pop()
        data["bad_trade_fields"][("lighter", "BTC")] = 1
        with self.assertRaisesRegex(RuntimeError, "invalidation"):
            require_contiguous_capture(data)
        data["bad_trade_fields"].clear()
        data["manifest"]["errors"] = [{"venue": "lighter", "error": "disconnected"}]
        with self.assertRaisesRegex(RuntimeError, "invalidation"):
            require_contiguous_capture(data)


if __name__ == "__main__":
    unittest.main()
