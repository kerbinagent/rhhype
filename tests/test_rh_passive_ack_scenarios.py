"""Causal synthetic fixtures only; no network, capture, or archive replay."""

from decimal import Decimal
import unittest

from scripts.rh_maker_engine import Config, NS
from scripts.rh_passive_ack_scenarios import (
    AckScenario, AssumedAckPassiveExitBranch, BASE_SCENARIO, LONGER_LATENCY_SCENARIO,
)
from scripts.rh_passive_retirement_guard import RetirementGuardPassiveExitBranch
from tests.test_rh_maker_engine import DIAG, META, T, book, trade


def make_branch(policy="control10s", scenario=BASE_SCENARIO, **cfg):
    hold = 60 * NS if policy.endswith("60s") else 10 * NS
    return AssumedAckPassiveExitBranch(
        Config("BTC", Decimal("1000"), "fixed_best", hold_ns=hold, **cfg), META,
        exit_policy=policy, scenario=scenario,
    )


def admit(branch):
    branch.process(book("rh_lighter", T))
    branch.process(book("hyperliquid", T), DIAG)
    assert branch.quote is not None


def refresh(branch, at, **rh_kwargs):
    branch.process(book("rh_lighter", at, **rh_kwargs))
    branch.process(book("hyperliquid", at))


def cancel_no_flow(branch):
    admit(branch)
    branch.tick(T + 300_000_000)
    branch._request_cancel(T + 400_000_000, "synthetic_cancel")
    refresh(branch, T + NS)
    refresh(branch, T + 2_500_000_000)
    assert branch.quote.canceled_ns == T + 700_000_000


def passive_cycle_start(branch):
    admit(branch)
    branch.process(trade(T + 500_000_000, tid="entry"))
    branch.process(book("hyperliquid", T + 700_000_000))
    refresh(branch, T + 1_500_000_000)
    refresh(branch, T + 2_800_000_000)
    assert branch.passive_ask is not None


class AssumedAckScenariosTests(unittest.TestCase):
    def test_flow_before_first_advanced_book_uses_prior_raw_queue(self):
        branch = make_branch()
        admit(branch)
        branch.process(trade(T + 350_000_000, qty=0.6))
        self.assertIsNone(branch.unknown_reason)
        self.assertEqual(branch.quote.activated_ns, T + 300_000_000)
        self.assertEqual(branch.quote.activated_source_ns, T + 300_000_000)
        self.assertEqual(branch.rh_pos, Decimal("0.1"))
        self.assertEqual(branch.quote.ahead_same, 0)
        self.assertEqual(branch.quote.remaining, Decimal("0.9"))
        self.assertEqual(branch.hedges[0].due_ns, T + 500_000_000)
        evidence = branch.summary()["assumed_ack_evidence"][0]
        self.assertEqual(evidence["anchor_received_ns"], T)
        self.assertEqual(evidence["processed_receipt_ns"], T + 350_000_000)
        self.assertEqual(evidence["timer_boundary_ns"], T + 300_000_000)

    def test_current_book_and_later_old_source_book_cannot_anchor(self):
        branch = make_branch()
        admit(branch)
        branch.process(book("rh_lighter", T + 300_000_000,
                            bids=[[100, 10], [99.9, 10]]))
        self.assertEqual(branch.quote.ahead_same, Decimal("0.5"))
        self.assertEqual(branch.unknown_reason, "assumed_ack_anchor_late_revision")
        self.assertEqual(branch.summary()["assumed_ack_evidence"][0]["anchor_received_ns"], T)

        missing = make_branch()
        admit(missing)
        missing.raw_rh_anchor = None
        missing.process(book("rh_lighter", T + 400_000_000, source=T + 200_000_000))
        self.assertEqual(missing.unknown_reason, "assumed_ack_anchor_unavailable")
        self.assertIsNone(missing.quote.activated_ns)

    def test_pre_due_print_cannot_deplete_and_books_give_no_cancellation_credit(self):
        branch = make_branch()
        admit(branch)
        branch.process(trade(T + 350_000_000, source=T + 250_000_000,
                             qty=100, tid="pre-due"))
        self.assertEqual(branch.quote.ahead_same, Decimal("0.5"))
        self.assertEqual(branch.rh_pos, 0)
        branch.process(book("rh_lighter", T + 400_000_000,
                            bids=[[100, 0.1], [99.9, 10]]))
        self.assertEqual(branch.quote.ahead_same, Decimal("0.5"))
        branch.process(trade(T + 500_000_000, price=99.9, qty=0.6, tid="through"))
        self.assertEqual(branch.rh_pos, Decimal("0.1"))
        self.assertEqual(branch.cash_rh, Decimal("-10"))
        self.assertEqual(branch.quote.ahead_same, 0)

    def test_cancel_pre_post_and_exact_source_time(self):
        for relation in ("pre", "post", "tie"):
            with self.subTest(relation=relation):
                branch = make_branch()
                admit(branch)
                branch.process(trade(T + 350_000_000, qty=0.6, tid="first"))
                branch.process(book("hyperliquid", T + 520_000_000))
                source = T + {"pre": 600_000_000, "post": 660_000_000,
                              "tie": 650_000_000}[relation]
                branch.process(trade(T + 700_000_000, source=source, qty=0.5, tid="late"))
                self.assertEqual(branch.quote.canceled_ns, T + 650_000_000)
                if relation == "tie":
                    self.assertEqual(branch.unknown_reason, "cancel_fill_same_source_time")
                else:
                    self.assertIsNone(branch.unknown_reason)
                    self.assertEqual(branch.rh_pos, Decimal("0.6" if relation == "pre" else "0.1"))

    def test_current_callback_retirement_and_reconnect_flow_invalidate_old_episode(self):
        branch = make_branch()
        cancel_no_flow(branch)
        event = trade(T + 2_700_000_000, source=T + 600_000_000, qty=0.01)
        event["generation"] = "reconnected"
        branch.process(event)
        self.assertEqual(branch.unknown_reason, "late_retired_quote_flow_generation_ambiguous")
        self.assertTrue(branch.episodes[0]["execution_unknown"])
        self.assertIsNone(branch.summary()["episodes"][0]["fee_only_net"])
        self.assertIsNone(branch.summary()["complete_net"])
        self.assertEqual((branch.rh_pos, branch.hl_pos), (0, 0))

    def test_duplicate_old_print_is_not_new_tombstone_flow(self):
        branch = make_branch()
        admit(branch)
        original = trade(T + 350_000_000, qty=0.5, tid="already-consumed")
        branch.process(original)
        branch._request_cancel(T + 400_000_000, "synthetic_cancel")
        refresh(branch, T + NS)
        refresh(branch, T + 2_500_000_000)
        branch.tick(T + 2_700_000_000)
        repeated = {**original, "received_ns": T + 2_800_000_000}
        branch.process(repeated)
        self.assertIsNone(branch.unknown_reason)
        self.assertFalse(branch.episodes[0].get("execution_unknown", False))
        self.assertEqual(branch.summary()["trade_ids_retained"], 1)
        branch.process({**repeated, "qty": 0.6})
        self.assertEqual(branch.unknown_reason, "assumed_ack_trade_id_conflict")
        self.assertTrue(branch.episodes[0]["execution_unknown"])

    def test_coverage_expiry_precedes_incoming_fresh_book(self):
        branch = make_branch()
        admit(branch)
        branch.process(book("rh_lighter", T + 2_100_000_000))
        self.assertEqual(branch.unknown_reason, "assumed_ack_coverage_gap_open_obligation")
        self.assertEqual(branch.now_ns, T + 2_100_000_000)
        self.assertIsNone(branch.summary()["complete_net"])

    def test_accounting_depletion_is_not_public_coverage_or_insertion_queue(self):
        branch = make_branch()
        admit(branch)
        branch.books["rh"].bids.clear()
        branch.books["hl"].asks.clear()
        branch.tick(T + 300_000_000)
        self.assertIsNone(branch.unknown_reason)
        self.assertEqual(branch.quote.ahead_same, Decimal("0.5"))
        self.assertEqual(branch.raw_rh_anchor.bids[0][1], Decimal("0.5"))

    def test_long_tick_orders_rest_cancel_reconciliation_and_is_idempotent(self):
        branch = make_branch(quote_rest_ns=100_000_000)
        admit(branch)
        branch.tick(T + 1_500_000_000)
        self.assertIsNone(branch.unknown_reason)
        self.assertEqual(branch.quote.cancel_due_ns, T + 700_000_000)
        self.assertEqual(branch.quote.canceled_ns, T + 700_000_000)
        first = branch.summary()
        branch.tick(T + 1_500_000_000)
        self.assertEqual(branch.summary(), first)
        times = [row["ns"] for row in branch.audit if row["event"] in
                 ("assumed_activation", "cancel_requested", "assumed_cancel")]
        self.assertEqual(times, [T + 300_000_000, T + 400_000_000, T + 700_000_000])
        for row in branch.audit:
            if row["event"] in ("assumed_activation", "cancel_requested", "assumed_cancel"):
                self.assertEqual(row["processed_receipt_ns"], T + 1_500_000_000)

    def test_historical_cancel_inside_parent_tick_settles_before_timeout(self):
        branch = make_branch()
        admit(branch)
        branch.tick(T + 300_000_000)
        # A targeted hook fixture reproduces the inherited backdated-request
        # risk without claiming coverage over an actually missing stream.
        branch._timer_boundary = T + 10 * NS
        branch._request_cancel(T + NS, "historical_rest")
        branch._timer_boundary = None
        self.assertEqual(branch.quote.canceled_ns, T + 1_300_000_000)
        self.assertIsNone(branch.unknown_reason)

    def test_post_only_reject_is_unknown_and_cannot_reactivate(self):
        branch = make_branch()
        admit(branch)
        branch.process(book("rh_lighter", T + 200_000_000,
                            bids=[[99.9, 10]], asks=[[100, 10]]))
        branch.tick(T + 300_000_000)
        self.assertEqual(branch.unknown_reason, "assumed_post_only_reject_unresolved")
        branch.process(book("rh_lighter", T + 400_000_000))
        self.assertIsNone(branch.quote.activated_ns)
        self.assertEqual(branch.rh_pos, 0)

        passive = make_branch("passive_best10s")
        passive_cycle_start(passive)
        passive.process(book("rh_lighter", T + 3 * NS,
                             bids=[[100.4, 10]], asks=[[100.5, 10]]))
        passive.tick(T + 3_100_000_000)
        self.assertEqual(passive.unknown_reason, "assumed_post_only_reject_unresolved")
        self.assertEqual((passive.rh_pos, passive.hl_pos), (1, -1))
        self.assertIsNone(passive.summary()["complete_net"])

    def test_full_passive_cycle_preserves_four_fees_and_all_costs(self):
        branch = make_branch("passive_best10s")
        passive_cycle_start(branch)
        branch.process(trade(T + 3_300_000_000, side="buy", price=100.4, qty=11, tid="exit"))
        self.assertEqual(branch.passive_ask.activated_ns, T + 3_100_000_000)
        self.assertEqual(branch.rh_pos, 0)
        self.assertEqual(branch.passive_buys[0].due_ns, T + 3_450_000_000)
        branch.process(book("hyperliquid", T + 3_500_000_000))
        refresh(branch, T + 4_500_000_000)
        branch.tick(T + 5_600_000_000)
        result = branch.summary()
        self.assertIsNone(result["unknown_reason"])
        self.assertEqual(result["fee_only_complete_net"], "0.209775")
        self.assertEqual(Decimal(result["complete_net"]), Decimal("0.209775")
                         - Decimal(result["reserve_cost"]) - Decimal(result["capital_cost"]))
        self.assertEqual((branch.rh_pos, branch.hl_pos), (0, 0))
        episode = result["episodes"][0]
        self.assertEqual(episode["entry_hl_qty"], "1.0")
        self.assertEqual(episode["passive_exit_maker_qty"], "1")
        self.assertTrue(episode["execution_assumed"])
        self.assertEqual(episode["assumed_exit_ack"]["anchor_received_ns"], T + 2_800_000_000)

    def test_passive_cancel_tie_and_partial_contingent_buy_remain_obligations(self):
        branch = make_branch("passive_best10s")
        passive_cycle_start(branch)
        branch.process(trade(T + 3_300_000_000, side="buy", price=100.4, qty=10.5, tid="partial"))
        self.assertEqual(branch.rh_pos, Decimal("0.5"))
        branch.process(book("hyperliquid", T + 3_500_000_000,
                            asks=[[100.3, 0.1], [110, 10]]))
        self.assertEqual(branch.hl_pos, Decimal("-0.9"))
        self.assertEqual(branch.fallback_reason, "partial_or_zero_passive_hl_buy")
        self.assertIsNone(branch.summary()["complete_net"])
        branch.process(trade(T + 3_700_000_000, source=T + 3_600_000_000,
                             side="buy", price=100.4, qty=0.5, tid="tie"))
        self.assertEqual(branch.unknown_reason, "passive_cancel_fill_same_source_time")

    def test_stress_effective_premium_delays_and_every_audit_label(self):
        config = Config("BTC", Decimal("1000"), "fixed_best", tier="premium")
        branch = AssumedAckPassiveExitBranch(config, META, exit_policy="control10s",
                                             scenario=LONGER_LATENCY_SCENARIO)
        self.assertEqual(config.maker_latency_ns, 100_000_000)
        self.assertEqual(branch.cfg.maker_latency_ns, 300_000_000)
        self.assertEqual(branch.cfg.cancel_latency_ns, 300_000_000)
        admit(branch)
        branch.tick(T + 300_000_000)
        for row in branch.audit:
            self.assertEqual(row["scenario_id"], "assumed_ack_plus_200ms")
            self.assertTrue(row["execution_assumed"])
            self.assertFalse(row["private_ack_observed"])
        self.assertFalse(branch.summary()["guaranteed_profit_bound"])
        self.assertFalse(branch.summary()["actual_fills_observed"])

    def test_caps_backwards_invalidation_and_generation_are_unknown(self):
        branch = make_branch(scenario=AckScenario("bounded", max_trade_ids=1))
        admit(branch)
        branch.process(trade(T + 350_000_000, qty=0.1, tid="one"))
        branch.process(trade(T + 400_000_000, qty=0.1, tid="two"))
        self.assertEqual(branch.unknown_reason, "assumed_ack_trade_id_cap")
        for case in ("backwards", "invalid", "generation"):
            with self.subTest(case=case):
                branch = make_branch()
                admit(branch)
                if case == "backwards":
                    event = book("rh_lighter", T - 1)
                    reason = "backward_receipt_time"
                elif case == "invalid":
                    event = {"type": "invalidate", "venue": "rh_lighter", "asset": "BTC",
                             "received_ns": T + 200_000_000}
                    reason = "coverage_gap_open_obligation"
                else:
                    event = {**book("rh_lighter", T + 200_000_000), "generation": "new"}
                    reason = "book_generation_changed_during_obligation"
                branch.process(event)
                self.assertEqual(branch.unknown_reason, reason)
                self.assertIsNone(branch.summary()["complete_net"])

    def test_identical_anchor_fixture_agrees_with_corrected_strict_economics(self):
        scenario = make_branch()
        strict = RetirementGuardPassiveExitBranch(
            Config("BTC", Decimal("1000"), "fixed_best"), META, exit_policy="control10s")
        for branch in (scenario, strict):
            admit(branch)
            branch.process(book("rh_lighter", T + 300_000_000))
            branch._request_cancel(T + 400_000_000, "synthetic_cancel")
            branch.process(book("rh_lighter", T + 700_000_000))
            refresh(branch, T + NS)
            refresh(branch, T + 2_500_000_000)
            branch.tick(T + 2_700_000_000)
        for key in ("complete_net", "cash_known", "fees_rh", "fees_hl",
                    "capital_cost", "reserve_cost", "rh_position", "hl_position"):
            self.assertEqual(scenario.summary()[key], strict.summary()[key])
        self.assertEqual(len(scenario.episodes), 1)
        self.assertEqual(list(scenario._ack_evidence), [(1, "entry")])

    def test_id_cap_or_missing_id_still_invalidates_matching_retired_episode(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                branch = make_branch(scenario=AckScenario("bounded", max_trade_ids=1))
                admit(branch)
                branch.process(trade(T + 350_000_000, qty=0.5, tid="old-consumed"))
                branch._request_cancel(T + 400_000_000, "synthetic_cancel")
                refresh(branch, T + NS)
                refresh(branch, T + 2_500_000_000)
                event = trade(T + 2_700_000_000, source=T + 600_000_000,
                              qty=0.01, tid="" if missing else "new-late")
                branch.process(event)
                self.assertEqual(branch.unknown_reason, "assumed_ack_trade_identity_or_clock_invalid"
                                 if missing else "assumed_ack_trade_id_cap")
                self.assertTrue(branch.episodes[0]["execution_unknown"])
                self.assertIsNone(branch.summary()["episodes"][0]["fee_only_net"])

    def test_late_pre_due_revision_invalidates_a_completed_old_episode(self):
        branch = make_branch()
        cancel_no_flow(branch)
        branch.tick(T + 2_700_000_000)
        self.assertIsNotNone(branch.summary()["complete_net"])
        branch.process(book("rh_lighter", T + 2_800_000_000,
                            source=T + 200_000_000,
                            bids=[[100, 0.4], [99.9, 10]]))
        self.assertEqual(branch.unknown_reason, "assumed_ack_anchor_late_revision")
        self.assertTrue(branch.episodes[0]["execution_unknown"])
        self.assertIsNone(branch.summary()["complete_net"])

    def test_passive_pre_cancel_delayed_print_and_post_cancel_exclusion(self):
        for source, expected_rh in ((3_500_000_000, "0"), (3_650_000_000, "0.5")):
            with self.subTest(source=source):
                branch = make_branch("passive_best10s")
                passive_cycle_start(branch)
                branch.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                                     qty=10.5, tid="first-exit"))
                branch.process(book("hyperliquid", T + 3_500_000_000))
                branch.process(trade(T + 3_700_000_000, source=T + source,
                                     side="buy", price=100.4, qty=0.5, tid="late-exit"))
                self.assertIsNone(branch.unknown_reason)
                self.assertEqual(branch.rh_pos, Decimal(expected_rh))
                self.assertEqual(branch.passive_ask.canceled_ns, T + 3_600_000_000)

    def test_partial_hedge_unwinds_at_loss_and_cannot_complete_unmatched_inventory(self):
        branch = make_branch()
        admit(branch)
        branch.process(trade(T + 350_000_000, tid="entry-full"))
        branch.process(book("hyperliquid", T + 550_000_000,
                            bids=[[100.2, 0.1], [90, 10]]))
        self.assertEqual(branch.hl_pos, Decimal("-0.1"))
        self.assertEqual(branch.exit_requested_ns, T + 550_000_000)
        branch.process(book("hyperliquid", T + 800_000_000,
                            asks=[[105, 10], [106, 10]]))
        branch.process(book("rh_lighter", T + NS,
                            bids=[[95, 10], [94.9, 10]], asks=[[96, 10]]))
        refresh(branch, T + 2 * NS)
        branch.tick(T + 2_650_000_000)
        result = branch.summary()
        self.assertIsNone(result["unknown_reason"])
        self.assertEqual((branch.rh_pos, branch.hl_pos), (0, 0))
        self.assertLess(Decimal(result["complete_net"]), 0)
        self.assertGreater(Decimal(result["fees_hl"]), 0)

    def test_hedge_timeout_and_hold_fallback_use_ordered_inherited_timers(self):
        branch = make_branch(max_book_age_ns=10 * NS)
        admit(branch)
        branch.process(trade(T + 350_000_000, tid="unhedged"))
        branch.tick(T + 3_500_000_000)
        self.assertIsNone(branch.unknown_reason)
        self.assertFalse(branch.hedges)
        self.assertEqual(branch.exit_requested_ns, T + 3_350_000_000)
        timeout = next(row for row in branch.audit if row["event"] == "hedge_timeout")
        self.assertEqual(timeout["ns"], T + 3_350_000_001)
        self.assertEqual(timeout["processed_receipt_ns"], T + 3_500_000_000)

        passive = make_branch("passive_best10s")
        passive_cycle_start(passive)
        for elapsed in (4_500_000_000, 6 * NS, 7_500_000_000, 9 * NS,
                        10_500_000_000, 12 * NS):
            refresh(passive, T + elapsed)
        passive.tick(T + 13 * NS)
        self.assertIsNone(passive.unknown_reason)
        self.assertEqual(passive.fallback_requested_ns, T + 10_700_000_000)
        self.assertEqual(passive.passive_ask.canceled_ns, T + 11 * NS)
        self.assertEqual(set(passive.exits), {"rh", "hl"})
        self.assertIsNone(passive.summary()["complete_net"])

    def test_funding_boundary_and_capture_end_stay_unknown(self):
        branch = make_branch("passive_best10s")
        offset = 3600 * NS - NS - T
        for event, diag in ((book("rh_lighter", T), None),
                            (book("hyperliquid", T), DIAG),
                            (trade(T + 500_000_000), None),
                            (book("hyperliquid", T + 700_000_000), None),
                            (book("rh_lighter", T + 1_100_000_000), None)):
            event["received_ns"] += offset
            event["source_ns"] += offset
            branch.process(event, diag)
        self.assertTrue(branch.funding_unknown)
        self.assertIsNone(branch.summary()["complete_net"])
        branch.process({"type": "end", "received_ns": 3601 * NS})
        self.assertEqual(branch.unknown_reason, "capture_end_with_open_obligation")
        self.assertTrue(branch.audit[-1]["execution_assumed"])

    def test_conflicting_id_invalidates_full_closed_episode_without_tombstone(self):
        for trade_id, side, price, qty in (("entry", "sell", 100, 1.6),
                                           ("exit", "buy", 100.4, 11.1)):
            with self.subTest(trade_id=trade_id):
                branch = make_branch("passive_best10s")
                passive_cycle_start(branch)
                branch.process(trade(T + 3_300_000_000, side="buy", price=100.4, qty=11, tid="exit"))
                branch.process(book("hyperliquid", T + 3_500_000_000))
                refresh(branch, T + 4_500_000_000)
                branch.tick(T + 5_600_000_000)
                self.assertFalse(branch.retired_quotes)
                self.assertFalse(branch._retired_passive)
                self.assertIsNotNone(branch.summary()["complete_net"])
                source = T + (500_000_000 if trade_id == "entry" else 3_300_000_000)
                branch.process(trade(T + 5_700_000_000, source=source,
                                     side=side, price=price, qty=qty, tid=trade_id))
                self.assertEqual(branch.unknown_reason, "assumed_ack_trade_id_conflict")
                self.assertTrue(branch.episodes[0]["execution_unknown"])
                self.assertIsNone(branch.summary()["episodes"][0]["fee_only_net"])
                self.assertEqual(branch._trade_episodes[trade_id], (1,))

    def test_reconnect_retransmission_is_duplicate_under_explicit_id_assumption(self):
        branch = make_branch()
        admit(branch)
        original = trade(T + 350_000_000, qty=0.5, tid="native-stable")
        branch.process(original)
        branch._request_cancel(T + 400_000_000, "synthetic_cancel")
        refresh(branch, T + NS)
        refresh(branch, T + 2_500_000_000)
        branch.tick(T + 2_700_000_000)
        branch.process({**original, "received_ns": T + 2_800_000_000,
                        "generation": "reconnected"})
        self.assertIsNone(branch.unknown_reason)
        self.assertFalse(branch.episodes[0].get("execution_unknown", False))
        self.assertEqual(branch.summary()["trade_ids_retained"], 1)
        self.assertTrue(branch.summary()["native_trade_ids_stable_across_generations_assumed"])
        row = branch.audit[-1]
        self.assertEqual(row["event"], "assumed_duplicate_trade_generation")
        self.assertEqual(row["first_generation"], "g")
        self.assertEqual(row["duplicate_generation"], "reconnected")

    def test_null_boolean_container_and_negative_native_ids_are_invalid(self):
        for native_id in (None, True, False, [], {}, -1, "", " ", "x" * 129):
            with self.subTest(native_id=native_id):
                branch = make_branch()
                admit(branch)
                branch.process({**trade(T + 350_000_000), "trade_id": native_id})
                self.assertEqual(branch.unknown_reason, "assumed_ack_trade_identity_or_clock_invalid")
                self.assertEqual(branch.rh_pos, 0)
                self.assertIsNone(branch.summary()["complete_net"])

    def test_late_revision_after_unrelated_branch_unknown_invalidates_old_episode(self):
        branch = make_branch()
        cancel_no_flow(branch)
        branch.tick(T + 2_700_000_000)
        branch.process(trade(T + 2_750_000_000, qty=0.01, tid=""))
        reason = "assumed_ack_trade_identity_or_clock_invalid"
        self.assertEqual(branch.unknown_reason, reason)
        self.assertFalse(branch.episodes[0].get("execution_unknown", False))
        branch.process(book("rh_lighter", T + 2_800_000_000,
                            source=T + 200_000_000,
                            bids=[[100, 0.4], [99.9, 10]]))
        self.assertEqual(branch.unknown_reason, reason)
        self.assertTrue(branch.episodes[0]["execution_unknown"])
        self.assertEqual(branch.episodes[0]["execution_unknown_reason"],
                         "assumed_ack_anchor_late_revision")
        self.assertIsNone(branch.summary()["episodes"][0]["fee_only_net"])
        self.assertEqual(branch.summary()["assumed_ack_evidence"][0]["late_revision"]["received_ns"],
                         T + 2_800_000_000)

    def test_equal_source_late_revision_cannot_hide_clock_resolution_ambiguity(self):
        branch = make_branch()
        admit(branch)
        branch.process(book("rh_lighter", T + 350_000_000, source=T,
                            bids=[[100, 0.4], [99.9, 10]]))
        self.assertEqual(branch.unknown_reason, "assumed_ack_anchor_late_revision")
        self.assertEqual(branch.quote.ahead_same, Decimal("0.5"))
        self.assertEqual(branch.rh_pos, 0)

    def test_normal_late_partial_exit_evidence_after_halt_invalidates_old_episode(self):
        branch = make_branch("passive_best10s")
        passive_cycle_start(branch)
        branch.process(trade(T + 3_300_000_000, side="buy", price=100.4,
                             qty=10.5, tid="partial-exit"))
        branch.process(book("hyperliquid", T + 3_500_000_000))
        for elapsed in (4_500_000_000, 6 * NS, 7_500_000_000, 9 * NS,
                        10_500_000_000, 12 * NS):
            refresh(branch, T + elapsed)
        self.assertEqual((branch.rh_pos, branch.hl_pos), (0, 0))
        self.assertEqual(len(branch._retired_passive), 1)
        self.assertFalse(branch.episodes[0].get("execution_unknown", False))
        self.assertIsNotNone(branch.summary()["complete_net"])
        branch.process(trade(T + 12_100_000_000, tid=""))
        reason = "assumed_ack_trade_identity_or_clock_invalid"
        self.assertEqual(branch.unknown_reason, reason)
        cash = (branch.cash_rh, branch.cash_hl)
        branch.process(trade(T + 12_200_000_000, source=T + 3_500_000_000,
                             side="buy", price=100.4, qty=0.01, tid="new-delayed-exit"))
        self.assertEqual(branch.unknown_reason, reason)
        self.assertEqual((branch.cash_rh, branch.cash_hl), cash)
        self.assertTrue(branch.episodes[0]["execution_unknown"])
        self.assertEqual(branch.episodes[0]["execution_unknown_reason"],
                         "retired_passive_quote_late_flow")
        self.assertIsNone(branch.summary()["episodes"][0]["fee_only_net"])


if __name__ == "__main__":
    unittest.main()
