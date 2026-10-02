"""Synthetic clock, economic and missing-data contracts for the peer diagnostic.

No retained capture or market outcome is opened by these tests.
"""
from __future__ import annotations

import copy
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import peer_cross_asset_diagnostic as s


NS = 1_000_000_000
BASE = 1_000 * NS  # Entire synthetic block is clear of UTC funding boundaries.
TARGETS = ("ETH",)


def timestamp(seconds):
    return BASE + int(D(str(seconds)) * NS)


def metadata(**changes):
    market = dict(qty_step="0.01", min_qty="0.01", min_notional="1",
                  max_quote="100000", price_tick="0.000000000001",
                  taker_fee_bps="0", contract_multiplier="1")
    market.update(changes)
    return {"lighter": {asset: copy.deepcopy(market) for asset in ("BTC", "ETH")}}


def book(seconds, asset="ETH", midpoint="100", **changes):
    mid = D(str(midpoint))
    row = dict(type="book", asset=asset, venue="lighter",
               received_ns=timestamp(seconds), source_ns=timestamp(seconds),
               generation="core:1", sequence=int(D(str(seconds)) * 1000),
               valid=True, clock_valid=True,
               bids=[[str(mid - D("0.01")), "10"]],
               asks=[[str(mid + D("0.01")), "10"]])
    row.update(changes)
    return row


def trade(seconds, asset="ETH", ident=1, **changes):
    row = dict(type="trade", asset=asset, venue="lighter",
               received_ns=timestamp(seconds), source_ns=timestamp(seconds),
               generation="core:1", trade_id=ident, qty="0.01",
               price="100", buy_aggressor=True, clock_valid=True)
    row.update(changes)
    return row


def invalidation(seconds, asset="ETH", scope="book", **changes):
    row = dict(type="invalidate", asset=asset, venue="lighter",
               received_ns=timestamp(seconds), source_ns=None,
               generation="core:1", scope=scope, reason="synthetic_gap")
    row.update(changes)
    return row


def end(seconds=128):
    return dict(type="end", received_ns=timestamp(seconds), source_ns=None,
                started_ns=BASE, stopped_ns=timestamp(seconds))


def parameters(**changes):
    result = copy.deepcopy(s.PARAMS)
    result["anchor_stop_second"] = 127
    result.update(changes)
    return result


def decision_stream(*, direction=1, stop=127, changes=None, target_mid="100"):
    rows = [dict(type="control", asset=None, venue="lighter",
                 received_ns=BASE, source_ns=None, generation="core:1",
                 control="connection_open"), trade(1)]
    for second in range(1, stop + 1):
        leader = D("100") if second < 127 else D("100") * (D(direction) * D("0.0012")).exp()
        for asset, mid in (("BTC", leader), ("ETH", target_mid)):
            row = book(second, asset, mid)
            if changes:
                row = changes(second, asset, row)
            if row is not None:
                rows.append(row)
    rows.append(end(stop + 1))
    return sorted(rows, key=lambda row: row["received_ns"])


def decision(rows=None, *, params=None, meta=None):
    return s.decision_pass(rows if rows is not None else decision_stream(),
                           meta or metadata(), BASE,
                           params=params or parameters(), targets=TARGETS)


def feature(seconds=100, *, ident=1, direction=1, **changes):
    row = dict(id=ident, t=timestamp(seconds), asset="ETH", direction=direction,
               target_return_bps=D("0"), leader_return_bps=D("0"),
               c0_bps=D("2"), volatility_bps=D("0"), trade_count=0,
               quantity="0.99", generation="core:1", decision_midpoint=D("100"))
    row.update(changes)
    return row


def selection(*, seconds=100, direction=1, control=None):
    f = feature(seconds, direction=direction)
    return dict(events=[dict(id=0, episode_id=0, asset="ETH", direction=direction,
                             decision_ns=timestamp(seconds), features=f,
                             control=control, control_selection="selected" if control else "none")])


def outcomes(rows, *, direction=1, meta=None, params=None):
    return s.outcome_pass(rows, meta or metadata(), selection(direction=direction),
                          params=params or parameters())


def profiles(result):
    return {row["delay_ms"]: row for row in result["profiles"] if row["role"] == "event"}


class CalendarAndFeaturesTests(unittest.TestCase):
    def test_calendar_emits_silent_seconds_and_full_denominator(self):
        result = decision([end(600)], params=copy.deepcopy(s.PARAMS))
        self.assertEqual(result["scheduled_snapshot_ticks"], 534)
        self.assertEqual(result["leader_counts"]["scheduled_signal_ticks"], 408)
        self.assertEqual(result["events"], [])
        self.assertEqual(result["episodes"], [])
        self.assertTrue(result["ended"])

    def test_equal_receipt_group_precedes_tick_independent_of_asset_order(self):
        rows = decision_stream()
        first = decision(rows)
        second = decision(sorted(rows, key=lambda row: (row["received_ns"], row.get("asset") or "")))
        self.assertEqual(len(first["events"]), 1)
        self.assertEqual(len(second["events"]), 1)
        self.assertEqual(first["events"][0]["decision_ns"], timestamp(127))
        self.assertEqual(first["events"][0]["features"], second["events"][0]["features"])

    def test_later_target_callback_cannot_repair_failed_scheduled_anchor(self):
        rows = decision_stream(changes=lambda t, a, b: None if (t, a) == (127, "ETH") else b)
        rows.insert(-1, book("127.001"))
        result = decision(rows)
        self.assertEqual(len(result["episodes"]), 1)
        self.assertEqual(result["events"], [])

    def test_shared_cooldown_consumed_when_all_targets_fail(self):
        rows = decision_stream(stop=128, changes=lambda t, a, b: None if (t, a) == (127, "ETH") else b)
        result = decision(rows, params=parameters(anchor_stop_second=128))
        self.assertEqual([row["t"] for row in result["episodes"]], [timestamp(127)])
        self.assertEqual(result["events"], [])

    def test_positive_and_negative_leader_moves_follow_same_direction(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                result = decision(decision_stream(direction=direction))
                self.assertEqual(len(result["events"]), 1)
                self.assertEqual(result["events"][0]["direction"], direction)
                self.assertEqual(result["events"][0]["control"]["t"], timestamp(61))

    def test_leader_and_target_threshold_edges_in_both_directions(self):
        for direction in (1, -1):
            for magnitude, accepted in (("9.999999", False), ("10.000001", True)):
                with self.subTest(direction=direction, magnitude=magnitude):
                    changed_mid = D("100") * (D(direction) * D(magnitude) / 10000).exp()
                    def alter(t, asset, row):
                        return book(t, asset, changed_mid) if (t, asset) == (127, "BTC") else row
                    result = decision(decision_stream(changes=alter))
                    self.assertEqual(bool(result["episodes"]), accepted)
            for magnitude, accepted in (("1.999999", True), ("2.000001", False)):
                with self.subTest(direction=direction, target_magnitude=magnitude):
                    changed_mid = D("100") * (D(direction) * D(magnitude) / 10000).exp()
                    def alter(t, asset, row):
                        return book(t, asset, changed_mid) if (t, asset) == (127, "ETH") else row
                    result = decision(decision_stream(direction=direction, changes=alter))
                    self.assertEqual(bool(result["events"]), accepted)

    def test_market_sequences_are_never_compared_across_assets(self):
        def alter(t, asset, row):
            row["sequence"] += 1_000_000 if asset == "BTC" else 10
            return row
        self.assertEqual(len(decision(decision_stream(changes=alter))["events"]), 1)

    def test_saved_feature_provenance_contains_only_decision_and_prior_clocks(self):
        result = decision()
        evidence = result["events"][0]["features"]["book_provenance"]
        self.assertEqual(set(evidence), {"target_current", "target_prior", "leader_current", "leader_prior"})
        for name, second in (("target_current", 127), ("leader_current", 127),
                             ("target_prior", 117), ("leader_prior", 117)):
            row = evidence[name]
            self.assertEqual(row["received_ns"], timestamp(second))
            self.assertEqual(row["source_ns"], timestamp(second))
            self.assertEqual(row["sequence"], second * 1000)
            self.assertEqual(row["generation"], "core:1")
            self.assertLessEqual(row["received_ns"], timestamp(127))
        self.assertEqual(D(evidence["target_current"]["midpoint"]), D(100))
        self.assertEqual(D(evidence["target_current"]["best_bid"]), D("99.99"))
        self.assertEqual(D(evidence["target_current"]["best_ask"]), D("100.01"))
        rows = decision_stream(stop=128, changes=lambda t, a, b: book(t, a, "999") if (t, a) == (128, "ETH") else b)
        later = decision(rows, params=parameters(anchor_stop_second=128))
        self.assertEqual(later["events"][0]["features"]["book_provenance"], evidence)

    def test_quiet_control_attempts_explain_missing_feature_support(self):
        valid = decision()
        missing = decision([row for row in decision_stream() if row["type"] != "trade"])
        for direction in ("1", "-1"):
            counts = valid["control_counts"]["ETH"][direction]
            self.assertEqual(counts["calendar_anchors"], 67)
            self.assertEqual(counts["quiet_leader_feature_attempts"], 66)
            self.assertEqual(counts["eligible_control_feature"], 66)
            failures = missing["control_counts"]["ETH"][direction]
            self.assertEqual(failures["quiet_leader_feature_attempts"], 66)
            self.assertEqual(failures["feature_failure:trade_coverage_missing"], 66)
            self.assertEqual(failures.get("eligible_control_feature", 0), 0)

    def test_compact_feature_history_does_not_replace_current_full_depth_for_cost(self):
        def two_levels(t, asset, row):
            if asset == "ETH":
                row["asks"] = [["100.01", "0.5"], ["100.02", "0.5"]]
                row["bids"] = [["99.99", "0.5"], ["99.98", "0.5"]]
            return row
        row = decision(decision_stream(changes=two_levels))["events"][0]
        self.assertEqual(D(row["features"]["quantity"]), D("0.99"))
        entry = D("0.5") * D("100.01") + D("0.49") * D("100.02")
        close = D("0.5") * D("99.99") + D("0.49") * D("99.98")
        self.assertEqual(row["features"]["c0_bps"], (entry - close) / entry * D(10000))

    def test_source_sequence_generation_and_skew_are_not_interchangeable(self):
        cases = dict(source_future=dict(source_ns=timestamp("127.001")),
                     source_not_advanced=dict(source_ns=timestamp(117)),
                     sequence_not_advanced=dict(sequence=117000),
                     generation_changed=dict(generation="core:2"),
                     intermarket_skew=dict(source_ns=timestamp("126.899")),
                     source_too_old=dict(source_ns=timestamp("126.499")))
        for name, changes in cases.items():
            with self.subTest(case=name):
                def alter(t, asset, row):
                    if (t, asset) == (127, "ETH"):
                        row.update(changes)
                    return row
                self.assertEqual(decision(decision_stream(changes=alter))["events"], [])

    def test_volatility_requires_all_sixty_one_consecutive_target_snapshots(self):
        for missing in (67, 100, 126):
            with self.subTest(missing=missing):
                rows = decision_stream(changes=lambda t, a, b: None if (t, a) == (missing, "ETH") else b)
                self.assertEqual(decision(rows)["events"], [])
        valid = decision()
        self.assertEqual(valid["events"][0]["features"]["volatility_bps"], D(0))

    def test_trade_coverage_is_unknown_until_first_print_and_poisoned_by_gap(self):
        rows = [row for row in decision_stream() if row["type"] != "trade"]
        self.assertEqual(decision(rows)["events"], [])
        rows.append(trade(68))
        rows.sort(key=lambda row: row["received_ns"])
        self.assertEqual(decision(rows)["events"], [])
        rows = decision_stream()
        rows.append(invalidation(100, scope="trade"))
        rows.sort(key=lambda row: row["received_ns"])
        self.assertEqual(decision(rows)["events"], [])

    def test_generation_change_cannot_inherit_old_trade_coverage(self):
        def change_generation(t, asset, row):
            if asset == "ETH" and t >= 61:
                row["generation"] = "core:2"
            return row
        rows = decision_stream(changes=change_generation)
        rows.append(dict(type="control", asset=None, venue="lighter", received_ns=timestamp(61),
                         source_ns=None, generation="core:2", control="connection_open"))
        rows.append(trade(68, generation="core:2"))
        rows.sort(key=lambda row: row["received_ns"])
        self.assertEqual(decision(rows)["events"], [])

    def test_incomplete_or_regressed_stream_has_no_result(self):
        with self.assertRaises(ValueError):
            decision(decision_stream()[:-1])
        with self.assertRaises(ValueError):
            decision([book(2), book(1), end(128)])


class ComparatorTests(unittest.TestCase):
    def test_closed_control_age_bounds_and_nearest_unused_anchor(self):
        event = feature(300, ident=9)
        candidates = [feature(120, ident=1), feature(234, ident=2),
                      feature(235, ident=3), feature(119, ident=4)]
        selected, reason = s.select_control(candidates, event, set())
        self.assertEqual((selected["id"], reason), (2, "selected"))
        selected, _ = s.select_control(candidates, event, {("ETH", 1, timestamp(234))})
        self.assertEqual(selected["id"], 1)

    def test_same_asset_direction_and_exclusive_quiet_leader_threshold(self):
        event = feature(300)
        for changes in (dict(asset="SOL"), dict(direction=-1), dict(leader_return_bps=D("1")),
                        dict(leader_return_bps=D("-1")), dict(target_return_bps=D("2.001"))):
            with self.subTest(changes=changes):
                result, _ = s.select_control([feature(234, **changes)], event, set())
                self.assertIsNone(result)
        row, _ = s.select_control([feature(234, leader_return_bps=D("0.999"))], event, set())
        self.assertIsNotNone(row)

    def test_calipers_are_inclusive_relative_to_event_and_zero_requires_zero(self):
        event = feature(300, target_return_bps=D("1"), c0_bps=D("2"),
                        volatility_bps=D("4"), trade_count=4)
        edge = feature(234, target_return_bps=D("2"), c0_bps=D("2.5"),
                       volatility_bps=D("5"), trade_count=5)
        self.assertIsNotNone(s.select_control([edge], event, set())[0])
        for key, value in (("target_return_bps", D("2.0001")), ("c0_bps", D("2.5001")),
                           ("volatility_bps", D("5.0001")), ("trade_count", 6)):
            with self.subTest(key=key):
                bad = dict(edge, **{key: value})
                self.assertIsNone(s.select_control([bad], event, set())[0])
        zero = feature(300)
        for key in ("volatility_bps", "trade_count"):
            self.assertIsNone(s.select_control([feature(234, **{key: D("0.001")})], zero, set())[0])

    def test_selected_missing_outcome_is_never_replaced(self):
        event = feature(300)
        nearest = feature(234, ident=1, outcome={"status": "missing_exit", "net_cash": "-999"})
        earlier = feature(230, ident=2, outcome={"status": "matched", "net_cash": "999"})
        selected, _ = s.select_control([earlier, nearest], event, set())
        self.assertEqual(selected["id"], 1)
        nearest["outcome"] = {"status": "matched", "net_cash": "999999"}
        self.assertEqual(s.select_control([earlier, nearest], event, set())[0]["id"], 1)


class NativeAndQuoteTests(unittest.TestCase):
    def test_native_decision_sizes_once_and_prices_full_quantity_both_sides(self):
        market = metadata(taker_fee_bps="1")["lighter"]["ETH"]
        native, failure = s.native_decision(book(100), market, 1)
        self.assertIsNone(failure)
        self.assertEqual(D(native["quantity"]), D("0.99"))
        entry, close = D("0.99") * D("100.01"), D("0.99") * D("99.99")
        expected = (entry - close + (entry + close) / D(10000)) / entry * D(10000)
        self.assertAlmostEqual(float(native["c0_bps"]), float(expected), places=10)

    def test_decision_minimum_limit_and_depth_fail_closed(self):
        cases = [(metadata(min_qty="1.00"), book(100)),
                 (metadata(min_notional="100"), book(100)),
                 (metadata(max_quote="98"), book(100)),
                 (metadata(), book(100, asks=[["100.01", "0.5"]]))]
        for meta, quote in cases:
            with self.subTest(meta=meta, quote=quote):
                native, failure = s.native_decision(quote, meta["lighter"]["ETH"], 1)
                self.assertIsNotNone(failure)

    def test_both_delays_hold_sixty_seconds_from_actual_entry(self):
        rows = [book(100), book("100.4", source_ns=timestamp("100.399")),
                book("100.5"), book("100.9"), book("160.8", midpoint="100.10"),
                book("160.9", midpoint="100.11"), book("161.7", midpoint="100.12"), end(162)]
        result = profiles(outcomes(rows))
        self.assertEqual(result[400]["entry"]["received_ns"], timestamp("100.5"))
        self.assertEqual(result[800]["entry"]["received_ns"], timestamp("100.9"))
        self.assertEqual(result[400]["exit"]["received_ns"], timestamp("160.9"))
        self.assertEqual(result[800]["exit"]["received_ns"], timestamp("161.7"))
        self.assertEqual(result[400]["exit"]["due_ns"], timestamp("160.9"))

    def test_long_and_short_cash_charge_own_leg_notionals(self):
        for direction, close_mid in ((1, "100.11"), (-1, "99.89")):
            with self.subTest(direction=direction):
                rows = [book(100), book("100.4"), book("100.8"),
                        book("160.8", midpoint=close_mid), book("161.6", midpoint=close_mid), end(162)]
                row = profiles(outcomes(rows, direction=direction, meta=metadata(taker_fee_bps="2")))[400]
                self.assertEqual(row["status"], "matched")
                entry = D("0.99") * (D("100.01") if direction == 1 else D("99.99"))
                close = D("0.99") * (D("100.10") if direction == 1 else D("99.90"))
                gross = D(direction) * (close - entry)
                fees = (entry + close) * D("0.0002")
                self.assertEqual(D(row["gross_cash"]), gross)
                self.assertEqual(D(row["fee_cash"]), fees)
                self.assertEqual(D(row["net_cash"]), gross - fees)

    def test_first_bad_eligible_book_is_terminal_without_retry(self):
        rows = [book(100), book("100.4", valid=False), book("100.5"),
                book("100.8"), book("160.8", midpoint="110"), end(162)]
        row = profiles(outcomes(rows))[400]
        self.assertNotEqual(row["status"], "matched")
        self.assertNotIn("entry", row)

    def test_delayed_cap_depth_and_native_exit_failure_keep_obligations(self):
        for endpoint in (book("100.4", midpoint="103"),
                         book("100.4", asks=[["100.01", "0.5"]])):
            row = profiles(outcomes([book(100), endpoint, book("100.8"), end(101)]))[400]
            self.assertNotEqual(row["status"], "matched")
            self.assertNotIn("entry", row)
        row = profiles(outcomes([book(100), book("100.4"), book("100.8"),
                                 book("160.8", midpoint="0.5"), end(162)]))[400]
        self.assertNotEqual(row["status"], "matched")
        self.assertIn("entry", row)
        self.assertNotIn("net_cash", row)

    def test_silent_or_source_before_due_market_expires_on_global_tick(self):
        for rows in ([book(100), book(103, "BTC"), end(104)],
                     [book(100), book("100.4", source_ns=timestamp("100.399")),
                      book(103, "BTC"), end(104)]):
            with self.subTest(rows=rows):
                result = profiles(outcomes(rows))
                self.assertEqual(result[400]["status"], "missing_entry")
                self.assertEqual(result[800]["status"], "missing_entry")

    def test_exact_deadline_book_is_eligible_but_one_nanosecond_later_is_not(self):
        good = profiles(outcomes([book(100), book("102.4"), book("162.8", midpoint="100.1"), end(163)]))[400]
        self.assertEqual(good["status"], "matched")
        late = book("102.400000001")
        bad = profiles(outcomes([book(100), late, end(103)]))[400]
        self.assertEqual(bad["status"], "missing_entry")

    def test_trade_gap_or_btc_book_gap_does_not_cancel_target_quote(self):
        for gap in (invalidation(101, scope="trade"), invalidation(101, "BTC")):
            with self.subTest(gap=gap):
                rows = [book(100), book("100.4"), book("100.8"), gap,
                        book("160.8", midpoint="100.1"), book("161.6", midpoint="100.1"), end(162)]
                self.assertEqual(profiles(outcomes(rows))[400]["status"], "matched")
        own = profiles(outcomes([book(100), book("100.4"), invalidation(101), end(102)]))[400]
        self.assertEqual(own["status"], "invalidated")

    def test_eof_preserves_entry_and_exit_stage_obligations(self):
        pending_entry = profiles(outcomes([book(100), end("100.2")]))[400]
        pending_exit = profiles(outcomes([book(100), book("100.4"), end(101)]))[400]
        self.assertEqual(pending_entry["status"], "unresolved_at_end")
        self.assertEqual(pending_entry["failed_stage"], "pending_entry")
        self.assertEqual(pending_exit["status"], "unresolved_at_end")
        self.assertEqual(pending_exit["failed_stage"], "pending_exit")
        self.assertIn("entry", pending_exit)
        self.assertNotIn("net_cash", pending_exit)

    def test_capture_end_invalidation_preserves_eof_obligation(self):
        rows = [book(100), book("100.4"),
                invalidation(101, reason="capture_end"), end(101)]
        row = profiles(outcomes(rows))[400]
        self.assertEqual(row["status"], "unresolved_at_end")
        self.assertEqual(row["failed_stage"], "pending_exit")
        self.assertIn("entry", row)

    def test_actual_boundary_crossing_leaves_funding_and_total_net_unknown(self):
        rows = [book(2599), book("2599.4"), book("2599.8"),
                book("2659.8", midpoint="100.1"), book("2660.6", midpoint="100.1"), end(2661)]
        result = s.outcome_pass(rows, metadata(), selection(seconds=2599), params=parameters())
        for row in profiles(result).values():
            self.assertEqual(row["status"], "funding_unknown")
            self.assertIn("gross_cash", row)
            self.assertNotIn("net_cash", row)
            self.assertNotIn("net_quote_bps", row)


class SummaryAndDecisionTests(unittest.TestCase):
    @staticmethod
    def summary_fixture(episodes):
        """Each tuple is (asset, event bp, control bp or None), by episode."""
        chosen = dict(events=[], episodes=[], target_counts={asset: {} for asset in s.TARGETS})
        quoted = dict(profiles=[])
        for episode_id, members in enumerate(episodes):
            chosen["episodes"].append(dict(id=episode_id, t=timestamp(127 + 90 * episode_id)))
            for asset, event_bps, control_bps in members:
                ident = len(chosen["events"])
                chosen["events"].append(dict(id=ident, episode_id=episode_id, asset=asset))
                for delay in (400, 800):
                    for role, value in (("event", event_bps), ("control", control_bps)):
                        if value is None:
                            continue
                        quoted["profiles"].append(dict(event_id=ident, episode_id=episode_id,
                            asset=asset, role=role, delay_ms=delay, status="matched",
                            decision_ns=timestamp(127 + 90 * episode_id - (66 if role == "control" else 0)),
                            entry={}, exit={}, net_quote_bps=D(str(value))))
        return chosen, quoted

    def test_episode_weighting_includes_unmatched_absolute_events(self):
        chosen, quoted = self.summary_fixture([
            [("ETH", 1, 0), ("SOL", 1, 0), ("HYPE", 1, 0)],
            [("ETH", 10, 0)], [("ETH", 100, None)]])
        result = s.summarize(chosen, quoted)
        for arm in result["arms"]:
            self.assertEqual(arm["absolute_event_mean_bps"], D(37))
            self.assertEqual(arm["matched_event_mean_bps"], D("5.5"))
            self.assertEqual(arm["paired_mean_delta_bps"], D("5.5"))
            self.assertEqual(arm["distinct_paired_btc_episodes"], 2)
        eth = next(row for row in result["rows"] if row["asset"] == "ETH" and row["delay_ms"] == 400)
        self.assertEqual(eth["complete_events_without_complete_control"], 1)
        self.assertEqual(eth["unmatched_event_mean_bps"], D(100))
        self.assertEqual(len(result["rows"]), 18)  # All nine assets, including empty rows.

    def positive_results(self):
        chosen, quoted = self.summary_fixture([[("ETH", 2, 0)]] * 3)
        summary = s.summarize(chosen, quoted)
        return [dict(window=index, summary=copy.deepcopy(summary)) for index in (1, 2)]

    def test_synthetic_survivor_is_only_followup_proposal_not_promotion(self):
        verdict = s.evaluate_results(self.positive_results())
        self.assertEqual(verdict["classification"], "propose_frozen_untouched_followup")
        self.assertTrue(verdict["followup_proposal"])
        self.assertFalse(verdict["strategy_promotion"])

    def test_one_missing_requested_profile_or_underpowered_arm_is_inconclusive(self):
        for field, value in (("all_requested_profiles_matched", False),
                             ("distinct_paired_btc_episodes", 2)):
            with self.subTest(field=field):
                result = self.positive_results()
                result[1]["summary"]["arms"][1][field] = value
                self.assertEqual(s.evaluate_results(result)["classification"], "inconclusive_coverage")
        chosen, quoted = self.summary_fixture([[("ETH", 2, 0)]] * 3)
        failed = next(row for row in quoted["profiles"] if row["role"] == "control" and row["delay_ms"] == 800)
        failed["status"] = "missing_exit"
        failed.pop("net_quote_bps")
        self.assertFalse(s.summarize(chosen, quoted)["arms"][1]["all_requested_profiles_matched"])

    def test_negative_eight_hundred_ms_arm_parks_even_when_primary_is_positive(self):
        result = self.positive_results()
        result[0]["summary"]["arms"][1]["absolute_event_mean_bps"] = D("-0.01")
        self.assertEqual(s.evaluate_results(result)["classification"], "park_observed_version")

    def test_single_episode_driving_sign_does_not_pass_followup_gate(self):
        chosen, quoted = self.summary_fixture([[("ETH", 10, 0)], [("ETH", -1, 0)], [("ETH", -1, 0)]])
        summary = s.summarize(chosen, quoted)
        self.assertGreater(summary["arms"][0]["absolute_event_mean_bps"], 0)
        verdict = s.evaluate_results([dict(window=index, summary=copy.deepcopy(summary)) for index in (1, 2)])
        self.assertEqual(verdict["classification"], "park_observed_version")
        self.assertFalse(verdict["all_leave_one_episode_out_means_positive"])


class BoundaryAndPublicationTests(unittest.TestCase):
    def test_funding_guard_includes_both_boundary_endpoints(self):
        hour = 3600 * NS
        span = 65_600_000_000
        self.assertTrue(s.funding_touches(hour))
        self.assertTrue(s.funding_touches(hour - span))
        self.assertFalse(s.funding_touches(hour - span - 1))
        self.assertFalse(s.funding_touches(hour + 1))

    def test_exclusive_publication_never_overwrites_existing_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "evidence.txt"
            s.publish_exclusive(path, b"original\n")
            with self.assertRaises(FileExistsError):
                s.publish_exclusive(path, b"replacement\n")
            self.assertEqual(path.read_bytes(), b"original\n")

    def fixture_plan(self, directory):
        """Tiny synthetic files for hash guards; never a retained market capture."""
        pins = []
        for index, relative in enumerate(s.DEPENDENCIES):
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"synthetic source {index}\n".encode())
            pins.append(dict(path=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        windows = []
        for index, relative in enumerate(("reports/single-venue-broad/capture",
                                           "reports/single-venue-broad-relative/capture"), 1):
            capture = directory / relative
            (capture / "metadata").mkdir(parents=True)
            manifest = dict(end_reason="duration_limit", truncated=False, selected_markets=s.SELECTED,
                            started_utc="1970-01-01T00:16:40+00:00", ended_utc="1970-01-01T00:26:40+00:00")
            (capture / "manifest.json").write_text(json.dumps(manifest))
            # These are synthetic bytes inspected only by hash verification.
            (capture / "frames.jsonl.gz").write_bytes(b"synthetic hash input; not a wire archive")
            (capture / "metadata/normalized.json").write_text(json.dumps(dict(markets=metadata())))
            windows.append(dict(index=index, capture=relative,
                                manifest_sha256=s.digest(capture / "manifest.json"),
                                raw_sha256=s.digest(capture / "frames.jsonl.gz"),
                                metadata_sha256=s.digest(capture / "metadata/normalized.json")))
        plan = dict(schema="peer-cross-asset-v1", status="frozen-before-outcomes",
                    params=copy.deepcopy(s.PARAMS), bounds=copy.deepcopy(s.BOUNDS),
                    venue=s.VENUE, leader="BTC", targets=list(s.TARGETS), selected=s.SELECTED,
                    source_pins=pins, windows=windows, interpretation="synthetic unit fixture")
        path = directory / "protocol.json"
        path.write_text(json.dumps(plan))
        return path, s.digest(path), plan

    @staticmethod
    def consume_decisions(stream, *args, **kwargs):
        list(stream)
        return dict(events=[], episodes=[], leader_counts={"scheduled": 408},
                    target_counts={asset: {"scheduled": 408} for asset in s.TARGETS})

    @staticmethod
    def consume_outcomes(stream, *args, **kwargs):
        list(stream)
        return dict(profiles=[])

    @staticmethod
    def synthetic_archive(window, terminals):
        footer = end(600)
        footer.update(decoded_bytes=0, archive_bytes=0, counts={}, metadata_sha256={},
                      raw_gzip_sha256="synthetic", manifest_sha256="synthetic",
                      max_receipt_gap_ns=0, adapter_sha256="synthetic", book_decoder_sha256="synthetic")
        terminals.append(footer)
        yield footer

    def test_external_protocol_or_source_hash_failure_prevents_archive_and_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            with patch.object(s, "ROOT", directory):
                path, digest, plan = self.fixture_plan(directory)
                with patch.object(s, "archive_stream") as archive, patch.object(s, "publish_exclusive") as publish:
                    with self.assertRaisesRegex(ValueError, "external protocol SHA256 differs"):
                        s.run(path, "0" * 64, directory / "result.gz", directory / "readout.txt")
                    archive.assert_not_called()
                    publish.assert_not_called()
                    (directory / plan["source_pins"][0]["path"]).write_bytes(b"changed source")
                    with self.assertRaisesRegex(ValueError, "source pin differs"):
                        s.run(path, digest, directory / "result.gz", directory / "readout.txt")
                    archive.assert_not_called()
                    publish.assert_not_called()

    def test_input_hash_failure_prevents_archive_and_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            with patch.object(s, "ROOT", directory):
                path, digest, plan = self.fixture_plan(directory)
                changed = directory / plan["windows"][0]["capture"] / "metadata/normalized.json"
                changed.write_bytes(b"changed metadata")
                with patch.object(s, "archive_stream") as archive, patch.object(s, "publish_exclusive") as publish:
                    with self.assertRaisesRegex(ValueError, "input pin differs"):
                        s.run(path, digest, directory / "result.gz", directory / "readout.txt")
                    archive.assert_not_called()
                    publish.assert_not_called()

    def test_final_reverification_failure_prevents_both_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            with patch.object(s, "ROOT", directory):
                path, digest, plan = self.fixture_plan(directory)
                completed_outcome_passes = 0
                def finish_synthetic_outcomes(stream, *args, **kwargs):
                    nonlocal completed_outcome_passes
                    result = self.consume_outcomes(stream, *args, **kwargs)
                    completed_outcome_passes += 1
                    if completed_outcome_passes == 2:
                        (directory / plan["source_pins"][0]["path"]).write_bytes(b"source changed after final pass")
                    return result
                with patch.object(s, "archive_stream", side_effect=self.synthetic_archive), \
                        patch.object(s, "decision_pass", side_effect=self.consume_decisions), \
                        patch.object(s, "outcome_pass", side_effect=finish_synthetic_outcomes), \
                        patch.object(s, "publish_exclusive") as publish:
                    with self.assertRaisesRegex(ValueError, "source pin differs"):
                        s.run(path, digest, directory / "result.gz", directory / "readout.txt")
                    publish.assert_not_called()

    def test_output_caps_reject_before_any_publication(self):
        for capped in ("output_gzip_bytes", "readout_bytes"):
            with self.subTest(capped=capped), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary).resolve()
                limits = dict(s.BOUNDS, **{capped: 1})
                with patch.object(s, "ROOT", directory), patch.object(s, "BOUNDS", limits):
                    path, digest, _ = self.fixture_plan(directory)
                    with patch.object(s, "archive_stream", side_effect=self.synthetic_archive), \
                            patch.object(s, "decision_pass", side_effect=self.consume_decisions), \
                            patch.object(s, "outcome_pass", side_effect=self.consume_outcomes), \
                            patch.object(s, "publish_exclusive") as publish:
                        with self.assertRaisesRegex(ValueError, "output exceeds"):
                            s.run(path, digest, directory / "result.gz", directory / "readout.txt")
                        publish.assert_not_called()

    def test_input_configuration_restored_after_normal_exit_and_exception(self):
        modules = {s.ordinary: ("HARD_BYTES", "METADATA_MAX_BYTES", "MAX_DECODED_BYTES", "MAX_RECORDS", "MAX_TRADE_IDS"),
                   s.capture: ("SELECTED", "HARD_BYTES", "METADATA_MAX_BYTES")}
        original = {module: {name: getattr(module, name) for name in names} for module, names in modules.items()}
        selected = {"lighter": {"ETH": "0"}}
        limits = dict(s.BOUNDS, raw_bytes_per_capture=12345, metadata_bytes_per_capture=1234,
                      decoded_bytes_per_pass_per_capture=23456, records_per_pass_per_capture=345,
                      trade_ids_per_capture=456)
        for failure in (False, True):
            with self.subTest(failure=failure):
                try:
                    with s.adapter_configuration(selected, limits):
                        self.assertIs(s.capture.SELECTED, selected)
                        self.assertEqual(s.ordinary.MAX_RECORDS, 345)
                        rebuilt = s.ordinary.BookRebuilder([
                            dict(venue="lighter", market="0", asset="ETH")], lambda event: None)
                        self.assertEqual(rebuilt.manager.max_levels, 5000)
                        if failure:
                            raise RuntimeError("synthetic interruption")
                except RuntimeError:
                    self.assertTrue(failure)
                for module, saved in original.items():
                    for name, value in saved.items():
                        self.assertEqual(getattr(module, name), value)

    def test_nonfinite_output_never_serializes_as_a_false_economic_number(self):
        with self.assertRaises(ValueError):
            s.encode({"net_cash": float("nan")})


if __name__ == "__main__":
    unittest.main()
