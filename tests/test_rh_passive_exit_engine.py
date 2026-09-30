"""Synthetic lifecycle checks; no public capture or private order is touched."""

import unittest
from decimal import Decimal

from scripts.rh_maker_engine import Config, NS
from scripts.rh_passive_exit_engine import PassiveExitBranch
from tests.test_rh_maker_engine import DIAG, META, T, book, trade


def branch(policy="passive_best10s", *, adverse=None, **cfg):
    hold = 60 * NS if policy.endswith("60s") else 10 * NS
    config = Config("BTC", Decimal("1000"), "fixed_best", hold_ns=hold, **cfg)
    return PassiveExitBranch(config, META, exit_policy=policy,
                             exit_adverse_bps=adverse)


def matched_entry(b):
    b.process(book("rh_lighter", T))
    b.process(book("hyperliquid", T), DIAG)
    b.process(book("rh_lighter", T + 400_000_000))
    b.process(trade(T + 500_000_000, qty=1.5, tid="entry"))
    b.process(book("hyperliquid", T + 700_000_000))
    b.process(book("rh_lighter", T + 900_000_000))
    assert b.rh_pos == 1 and b.hl_pos == -1


def activate_exit(b, *, rh_asks=None):
    # Entry cancel due at .8 s, but late entry flow remains possible until
    # 2.8 s. The passive ask must not overlap that window.
    b.process(book("rh_lighter", T + 2_800_000_000, asks=rh_asks))
    b.process(book("hyperliquid", T + 2_800_000_000))
    if b.passive_ask is not None:
        b.process(book("rh_lighter", T + 3_200_000_000, asks=rh_asks))
        b.process(book("hyperliquid", T + 3_200_000_000))


class PassiveExitTests(unittest.TestCase):
    def test_api_and_hold_policy_match(self):
        with self.assertRaises(ValueError):
            PassiveExitBranch(Config("BTC", Decimal("1000"), "fixed_best"),
                              META, exit_policy="passive_target60s")
        with self.assertRaises(ValueError):
            branch(adverse=Decimal("-0.1"))
        self.assertEqual(branch("control10s").exit_policy, "control10s")

    def test_no_bid_ask_overlap_and_late_entry_is_still_hedged(self):
        b = branch()
        b.process(book("rh_lighter", T))
        b.process(book("hyperliquid", T), DIAG)
        b.process(book("rh_lighter", T + 400_000_000))
        b.process(trade(T + 500_000_000, qty=1, tid="entry"))  # 0.5 behind queue.
        b.process(book("hyperliquid", T + 700_000_000))
        b.process(book("rh_lighter", T + 900_000_000))
        b.process(book("rh_lighter", T + 1_500_000_000))
        self.assertIsNone(b.passive_ask)
        b.process(trade(T + 1_600_000_000, source=T + 750_000_000,
                        qty=0.5, tid="late_entry"))
        self.assertEqual(b.rh_pos, Decimal("1"))
        self.assertEqual(len(b.hedges), 1)
        b.process(book("hyperliquid", T + 1_800_000_000))
        self.assertEqual(b.hl_pos, -1)
        activate_exit(b)
        self.assertIsNotNone(b.passive_ask)
        self.assertEqual(b.passive_ask.qty, 1)

    def test_full_passive_roundtrip_four_fees_and_separate_reserve(self):
        b = branch()
        matched_entry(b)
        activate_exit(b)
        self.assertEqual(b.passive_ask.price, Decimal("100.4"))
        self.assertEqual(b.passive_ask.ahead_same, Decimal("10"))
        b.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                        qty=11, tid="exit"))
        self.assertEqual(b.rh_pos, 0)
        self.assertEqual(b.hl_pos, -1)
        self.assertEqual(len(b.passive_buys), 1)
        b.process(book("hyperliquid", T + 3_500_000_000))
        self.assertEqual(b.hl_pos, 0)
        b.process(book("rh_lighter", T + 3_700_000_000))
        b.tick(T + 5_700_000_000)
        s = b.summary()
        self.assertIsNone(s["unknown_reason"])
        self.assertEqual(s["fee_only_complete_net"], "0.209775")
        self.assertEqual(Decimal(s["stressed_complete_net"]),
                         Decimal(s["fee_only_complete_net"])
                         - Decimal(s["reserve_cost"])
                         - Decimal(s["capital_cost"]))
        e = s["episodes"][0]
        self.assertEqual(e["entry_hl_qty"], "1.0")
        self.assertEqual(e["passive_exit_maker_qty"], "1")
        self.assertEqual(e["cohort_id"], "BTC:1000:standard:100000000000")
        self.assertEqual(s["counts"].get("exit_requested", 0), 0)

    def test_deadline_waits_cancel_and_late_window_before_taker(self):
        b = branch()
        matched_entry(b)
        activate_exit(b)
        due = T + 10_700_000_000
        b.tick(due)
        self.assertEqual(b.fallback_requested_ns, due)
        self.assertNotIn("rh", b.exits)
        self.assertNotIn("hl", b.exits)
        b.process(book("rh_lighter", due + 400_000_000))
        self.assertIsNotNone(b.passive_ask.canceled_ns)
        self.assertNotIn("rh", b.exits)
        b.tick(due + 2_299_000_000)
        self.assertNotIn("rh", b.exits)
        b.tick(due + 2_300_000_000)
        self.assertIn("rh", b.exits)
        self.assertIn("hl", b.exits)
        self.assertEqual(b.counts["passive_fallback_reconciled"], 1)

    def test_preactivation_and_retired_delayed_flow_unknown(self):
        b = branch()
        matched_entry(b)
        b.process(book("rh_lighter", T + 2_800_000_000))
        b.process(book("hyperliquid", T + 2_800_000_000))
        self.assertIsNotNone(b.passive_ask)
        b.process(trade(T + 3_150_000_000, source=T + 3_120_000_000,
                        side="buy", price=100.4, tid="pre"))
        self.assertEqual(b.unknown_reason,
                         "passive_eligible_flow_before_activation_snapshot")

        c = branch()
        matched_entry(c)
        activate_exit(c)
        c._request_passive_cancel(T + 3_300_000_000, "test")
        c.process(book("rh_lighter", T + 3_700_000_000))
        c.tick(T + 10_700_000_000)
        c.process(book("rh_lighter", T + 11_200_000_000))
        c.process(book("hyperliquid", T + 11_200_000_000))
        self.assertEqual(len(c.episodes), 1)
        self.assertEqual(len(c._retired_passive), 1)
        c.process(trade(T + 11_300_000_000, source=T + 3_400_000_000,
                        side="buy", price=100.4, tid="late", qty=11))
        self.assertEqual(c.unknown_reason, "retired_passive_quote_late_flow")
        self.assertTrue(c.episodes[0]["execution_unknown"])

    def test_partial_first_hl_buy_keeps_short_and_rescue_is_guarded(self):
        b = branch()
        matched_entry(b)
        activate_exit(b)
        b.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                        qty=11, tid="exit"))
        b.process(book("hyperliquid", T + 3_500_000_000,
                       asks=[[100.3, 0.4], [102, 10]]))
        self.assertEqual(b.hl_pos, Decimal("-0.6"))
        self.assertEqual(b.rh_pos, 0)
        self.assertEqual(b.counts["passive_hl_buy_result"], 1)
        self.assertNotIn("hl", b.exits)  # RH cancel and late-flow reconciliation first.
        b.process(book("rh_lighter", T + 3_700_000_000))
        b.tick(T + 5_600_000_000)
        self.assertIn("hl", b.exits)
        self.assertNotIn("rh", b.exits)

    def test_two_buys_consume_distinct_eligible_ask_levels(self):
        b = branch()
        matched_entry(b)
        activate_exit(b)
        b.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                        qty=10.5, tid="first"))
        b.process(trade(T + 3_320_000_000, side="buy", price=100.4,
                        qty=.5, tid="second"))
        self.assertEqual(len(b.passive_buys), 2)
        b.process(book("hyperliquid", T + 3_500_000_000,
                       asks=[[100.3, .5], [100.31, .5]]))
        self.assertEqual(b.hl_pos, 0)
        self.assertEqual(b.counts["passive_hl_buy_result"], 2)
        self.assertEqual(b._episode_passive_hl_buy_value, Decimal("100.305"))
        self.assertEqual(b.books["hl"].asks, [])
        self.assertFalse(b._fresh_pair(T + 3_500_000_000))

    def test_target_abstains_when_calibration_missing_or_cap_exceeded(self):
        b = branch("passive_target10s")
        matched_entry(b)
        activate_exit(b)
        self.assertIsNone(b.passive_ask)
        self.assertEqual(b.counts["passive_target_abstain"], 1)
        c = branch("passive_target10s", adverse=Decimal("100"))
        matched_entry(c)
        activate_exit(c)
        self.assertIsNone(c.passive_ask)
        self.assertIn("target_above_5bp_ask_cap",
                      [row.get("reason") for row in c.audit if row["event"] == "passive_target_abstain"])


if __name__ == "__main__":
    unittest.main()
