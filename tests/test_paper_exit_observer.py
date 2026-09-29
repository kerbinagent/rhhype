"""Exit-request evidence is durable and cannot alter the base paper economics."""

import copy
import unittest

from tests.test_paper_engine import book, pair
from paper_engine import EngineConfig, PaperEngine
from paper_exit_observer import ObservedPaperEngine


def opened(cls=ObservedPaperEngine, *, take_profit=0.1):
    cfg = EngineConfig(holding_seconds=5, strategies=("standard",),
                       capital_rate=0, take_profit_usd=take_profit)
    engine = cls([pair()], cfg, now=1000)
    engine.receive(book("hyperliquid", "BTC", 1000, 99.99, 100))
    engine.receive(book("rh_lighter", 1, 1000, 102, 102.01))
    engine.tick(1000)
    engine.receive(book("hyperliquid", "BTC", 1000.2, 99.99, 100))
    engine.receive(book("rh_lighter", 1, 1000.5, 102, 102.01))
    p = next(iter(engine.positions.values()))
    assert p["status"] == "OPEN"
    return engine, p


def without_observation(value):
    if isinstance(value, dict):
        return {k: without_observation(v) for k, v in value.items()
                if k != "exit_request_observation"}
    if isinstance(value, list):
        return [without_observation(v) for v in value]
    return value


class ExitObserverTests(unittest.TestCase):
    def test_max_hold_valid_mark_and_base_schedule_match(self):
        base, bp = opened(PaperEngine)
        observed, op = opened()
        for engine in (base, observed):
            engine.receive(book("hyperliquid", "BTC", 1005.3, 99.8, 100))
            engine.receive(book("rh_lighter", 1, 1005.4, 102, 102.3))
        requested = op["exit_due"]
        expected_mark = observed.liquidation(op, requested)
        base.tick(requested)
        observed.tick(requested)
        row = op["exit_request_observation"]
        self.assertEqual(row["capture_type"], "normal_request")
        self.assertEqual(row["closing_price_status"], "valid")
        self.assertEqual(row["mark_status"], "valid")
        self.assertEqual(row["captured_at"], requested)
        self.assertEqual(row["requested_at"], requested)
        self.assertAlmostEqual(row["net_liquidation_pnl_usd"], expected_mark)
        self.assertEqual(len(row["legs"]), 2)
        by_side = {leg["side"]: leg for leg in row["legs"]}
        self.assertAlmostEqual(row["requested_closing_liability_usd"],
                               by_side["short"]["exit_walk_value_usd"]
                               - by_side["long"]["exit_walk_value_usd"])
        self.assertTrue(all(leg["clock_valid"] and leg["walk_status"] == "valid"
                            for leg in row["legs"]))
        self.assertEqual(bp["exit_reason"], op["exit_reason"])
        self.assertEqual(base.ledgers, observed.ledgers)
        self.assertEqual(base.stats, observed.stats)
        self.assertEqual(without_observation(bp), without_observation(op))
        self.assertEqual(base.evidence[-1], observed.evidence[-1])
        self.assertIn("exit_request_observation", observed.transitions[-1])
        self.assertIn("exit_request_observation", observed.export_state()["positions"][op["id"]])

        for engine in (base, observed):
            engine.receive(book("hyperliquid", "BTC", requested + .3, 99.8, 100))
            engine.receive(book("rh_lighter", 1, requested + .6, 102, 102.3))
        self.assertEqual(base.ledgers, observed.ledgers)
        self.assertEqual(without_observation(bp), without_observation(op))
        for engine, p in ((base, bp), (observed, op)):
            engine.settle_funding(p["id"], {"complete": True, "cashflow_usd": 0,
                                            "estimated": False, "events": []}, requested + .7)
        self.assertEqual(base.ledgers, observed.ledgers)
        self.assertEqual(without_observation(base.finished[0]),
                         without_observation(observed.finished[0]))
        self.assertIn("exit_request_observation", observed.finished[0])

    def test_take_profit_observation_does_not_change_trigger(self):
        base, bp = opened(PaperEngine)
        observed, op = opened()
        for engine in (base, observed):
            engine.receive(book("hyperliquid", "BTC", 1001, 100.4, 100.41))
            engine.receive(book("rh_lighter", 1, 1001, 101.8, 101.81))
            engine.tick(1001)
        self.assertEqual((bp["exit_reason"], op["exit_reason"]),
                         ("take_profit", "take_profit"))
        self.assertEqual(without_observation(bp), without_observation(op))
        self.assertEqual(op["exit_request_observation"]["mark_status"], "valid")
        self.assertAlmostEqual(op["exit_request_observation"]["net_liquidation_pnl_usd"],
                               op["exit_trigger_pnl_usd"])

    def test_stale_or_depth_missing_is_unknown_not_zero(self):
        engine, p = opened()
        engine.books.clear()
        engine.tick(p["exit_due"])
        row = p["exit_request_observation"]
        self.assertEqual(row["closing_price_status"], "invalid_or_stale_book")
        self.assertIsNone(row["requested_closing_liability_usd"])
        self.assertIsNone(row["net_liquidation_pnl_usd"])
        self.assertEqual(p["exit_reason"], "max_hold")

        engine, p = opened()
        engine.receive(book("hyperliquid", "BTC", 1005.3, 99.8, 100, size=.01))
        engine.receive(book("rh_lighter", 1, 1005.4, 102, 102.3, size=.01))
        engine.tick(p["exit_due"])
        row = p["exit_request_observation"]
        self.assertEqual(row["closing_price_status"], "insufficient_depth")
        self.assertIsNone(row["requested_closing_liability_usd"])
        self.assertTrue(all(leg["walk_status"] == "insufficient_depth"
                            for leg in row["legs"]))

    def test_funding_unknown_keeps_valid_price_liability(self):
        engine, p = opened()
        for leg in p["legs"]:
            leg["entry_time"] = 3599.5
        p["exit_due"] = 3601
        engine.receive(book("hyperliquid", "BTC", 3601, 99.8, 100))
        engine.receive(book("rh_lighter", 1, 3601, 102, 102.3))
        engine.tick(3601)
        row = p["exit_request_observation"]
        self.assertEqual(row["closing_price_status"], "valid")
        self.assertIsNotNone(row["requested_closing_liability_usd"])
        self.assertEqual(row["mark_status"], "funding_unknown")
        self.assertIsNone(row["net_liquidation_pnl_usd"])

    def test_future_source_and_receipt_skew_cannot_make_valid_request_mark(self):
        engine, p = opened()
        engine.receive(book("hyperliquid", "BTC", 1005.3, 99.8, 100))
        rh = book("rh_lighter", 1, 1005.4, 102, 102.3)
        rh["engine_time"] = 1005.45  # Base valid_book permits this clock mismatch.
        engine.receive(rh)
        engine.tick(p["exit_due"])
        row = p["exit_request_observation"]
        self.assertEqual(row["closing_price_status"], "clock_order_invalid")
        self.assertIsNone(row["requested_closing_liability_usd"])

        engine, p = opened()
        engine.receive(book("hyperliquid", "BTC", 1003.9, 99.8, 100))
        engine.receive(book("rh_lighter", 1, 1005.4, 102, 102.3))
        engine.tick(p["exit_due"])
        row = p["exit_request_observation"]
        self.assertTrue(all(leg["book_valid"] for leg in row["legs"]))
        self.assertEqual(row["closing_price_status"], "receipt_skew")
        self.assertFalse(row["receipt_pair_skew_valid"])

    def test_entry_failure_is_explicitly_unpaired(self):
        cfg = EngineConfig(holding_seconds=5, strategies=("standard",), capital_rate=0)
        engine = ObservedPaperEngine([pair()], cfg, now=1000)
        engine.receive(book("hyperliquid", "BTC", 1000, 99.99, 100))
        engine.receive(book("rh_lighter", 1, 1000, 102, 102.01))
        engine.tick(1000)
        engine.receive(book("hyperliquid", "BTC", 1000.2, 99.99, 100, size=1))
        engine.receive(book("rh_lighter", 1, 1000.5, 102, 102.01))
        p = next(iter(engine.positions.values()))
        row = p["exit_request_observation"]
        self.assertEqual(row["capture_type"], "entry_failure_first_intent")
        self.assertEqual(row["closing_price_status"], "entry_failure_unpaired")
        self.assertIsNone(row["requested_closing_liability_usd"])

    def test_restored_retry_never_uses_retry_books_as_request_books(self):
        base, p = opened(PaperEngine)
        base.tick(p["exit_due"])
        state = copy.deepcopy(base.export_state())
        restored = ObservedPaperEngine([pair()], base.config, state=state,
                                       now=p["exit_due"] + .1)
        old_p = next(iter(restored.positions.values()))
        requested = old_p["exit_requested_at"]
        restored.receive(book("hyperliquid", "BTC", requested + .3, 99.8, 100,
                              generation=2))
        row = old_p["exit_request_observation"]
        self.assertEqual(row["capture_type"], "request_evidence_unavailable")
        self.assertEqual(row["requested_at"], requested)
        self.assertGreater(row["captured_at"], requested)
        self.assertEqual(row["legs"], [])
        self.assertIsNone(row["requested_closing_liability_usd"])
        first = copy.deepcopy(row)
        restored._exit_intent(old_p, old_p["legs"][0], requested + .5)
        self.assertEqual(old_p["exit_request_observation"], first)


if __name__ == "__main__":
    unittest.main()
