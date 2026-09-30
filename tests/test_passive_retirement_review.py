"""Review reproducer for frozen v1: no engine mutation or public replay.

The expected failure records the required safety invariant until a separate
audit guard or future engine enforces it. The characterization tests explain
why existing delayed-flow tests, which retire with an earlier tick, miss it.
"""

import unittest
from decimal import Decimal

from scripts.rh_maker_engine import Config
from scripts.rh_passive_exit_engine import PassiveExitBranch
from scripts.rh_passive_retirement_guard import RetirementGuardPassiveExitBranch
from tests.test_rh_maker_late_flow_guard import META, T, book, start, trade


def canceled_live_quote(branch_type=PassiveExitBranch, policy="control10s", **config_overrides):
    branch = branch_type(
        Config("BTC", Decimal("1000"), "fixed_best", **config_overrides), META,
        exit_policy=policy,
    )
    start(branch)
    branch.tick(T + 5_300_000_000)
    branch.process(book("rh_lighter", T + 5_700_000_000))
    assert branch.quote.cancel_due_ns == T + 5_600_000_000
    assert branch.quote.canceled_ns == T + 5_700_000_000
    assert branch.quote.remaining == 1
    assert not branch.retired_quotes
    return branch


def delayed_old_sell():
    return trade(T + 7_700_000_000, T + 5_500_000_000,
                 "sell", 100, qty=0.01, tid="same-callback-retirement")


class FrozenPassiveRetirementReview(unittest.TestCase):
    def test_characterizes_same_callback_retirement_missed_by_frozen_guard(self):
        branch = canceled_live_quote()
        branch.process(delayed_old_sell())
        result = branch.summary()
        self.assertIsNone(branch.quote)
        self.assertEqual(len(branch.retired_quotes), 1)
        self.assertEqual(result["unknown_reason"], None)
        self.assertEqual(result["complete_net"], "0")
        self.assertFalse(branch.episodes[0].get("execution_unknown", False))
        # Newly created evidence still fails the guard's strict receipt >
        # retired_ns condition at this same callback, even if checked again.
        self.assertIsNone(branch._late_retired_match(delayed_old_sell()))

    def test_separate_earlier_tick_detects_the_identical_source_evidence(self):
        branch = canceled_live_quote()
        branch.tick(T + 7_600_000_000)
        branch.process(delayed_old_sell())
        self.assertEqual(branch.unknown_reason, "late_retired_quote_flow")
        self.assertIsNone(branch.summary()["complete_net"])
        self.assertTrue(branch.episodes[0]["execution_unknown"])

    @unittest.expectedFailure
    def test_safety_invariant_same_callback_old_flow_cannot_complete_as_zero(self):
        branch = canceled_live_quote()
        branch.process(delayed_old_sell())
        self.assertIsNone(branch.summary()["complete_net"])
        self.assertTrue(branch.episodes[0]["execution_unknown"])


class CorrectedPassiveRetirementReview(unittest.TestCase):
    def test_same_callback_old_flow_is_unknown_for_control_and_passive(self):
        for policy in ("control10s", "passive_best10s"):
            with self.subTest(policy=policy):
                branch = canceled_live_quote(RetirementGuardPassiveExitBranch, policy)
                branch.process(delayed_old_sell())
                result = branch.summary()
                self.assertEqual(result["unknown_reason"], "late_retired_quote_flow")
                self.assertIsNone(result["complete_net"])
                self.assertTrue(branch.episodes[0]["execution_unknown"])
                self.assertEqual(branch.episodes[0]["late_retired_flow"]["receipt_ns"],
                                 T + 7_700_000_000)
                self.assertEqual((branch.rh_pos, branch.hl_pos,
                                  branch.cash_rh, branch.cash_hl), (0, 0, 0, 0))
                self.assertEqual(result["late_retired_flow_count"], 1)
                self.assertEqual(result["retirement_guard_revision"],
                                 "entry-same-receipt-v1")
                self.assertFalse(result["frozen_v1_result"])

    def test_same_callback_reconnect_and_cancel_endpoint_stay_unknown(self):
        branch = canceled_live_quote(RetirementGuardPassiveExitBranch)
        event = delayed_old_sell()
        event["generation"] = "reconnected"
        event["source_ns"] = T + 5_600_000_000
        branch.process(event)
        self.assertEqual(branch.unknown_reason,
                         "late_retired_quote_flow_generation_ambiguous")
        self.assertIsNone(branch.summary()["complete_net"])

    def test_nonqualifying_trade_preserves_original_ledger(self):
        for changes in ({"side": "buy"}, {"price": 100.1},
                        {"source_ns": T + 5_700_000_000}, {"asset": "ETH"}):
            with self.subTest(changes=changes):
                original = canceled_live_quote()
                corrected = canceled_live_quote(RetirementGuardPassiveExitBranch)
                event = {**delayed_old_sell(), **changes}
                original.process(event)
                corrected.process(event)
                original_summary = original.summary()
                corrected_summary = corrected.summary()
                corrected_summary.pop("retirement_guard_revision")
                corrected_summary.pop("frozen_v1_result")
                self.assertEqual(corrected_summary, original_summary)

    def test_repeat_evidence_does_not_duplicate_unknown_or_economics(self):
        branch = canceled_live_quote(RetirementGuardPassiveExitBranch)
        branch.process(delayed_old_sell())
        first = branch.summary()
        branch.process(delayed_old_sell())
        self.assertEqual(branch.summary(), first)

    def test_retirement_audit_cap_cannot_leave_finalized_episode_known(self):
        branch = canceled_live_quote(RetirementGuardPassiveExitBranch, max_audit=4)
        self.assertIsNone(branch.unknown_reason)
        branch.process(delayed_old_sell())
        self.assertEqual(branch.unknown_reason, "audit_cap")
        self.assertIsNone(branch.summary()["complete_net"])
        self.assertTrue(branch.episodes[0]["execution_unknown"])
        self.assertEqual(branch.episodes[0]["execution_unknown_reason"],
                         "late_retired_quote_flow")
        self.assertEqual((branch.rh_pos, branch.hl_pos,
                          branch.cash_rh, branch.cash_hl), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
