import copy
from decimal import Decimal as D
import unittest
from scripts import single_venue_directional_response as s


def book(t, venue, midpoint=100, **changes):
    result = dict(type="book", asset="BTC", venue=venue,
                  received_ns=round(t * s.NS), source_ns=round(t * s.NS),
                  sequence=round(t * s.NS), generation=venue + ":1",
                  valid=True, clock_valid=True,
                  bids=[[midpoint - .01, 10]], asks=[[midpoint + .01, 10]])
    result.update(changes)
    return result


META = {v: {"BTC": dict(qty_step=".01", min_qty=".01", min_notional="1",
                       taker_fee_bps="0")} for v in s.VS}


def seed(profiles, t=0):
    for venue in s.VS:
        profiles.process(book(t, venue))


def signal(t=0, target="lighter"):
    other = next(v for v in s.VS if v != target)
    return dict(asset="BTC", venue=target, mover_venue=other, direction=1,
                t=round(t * s.NS), generations={v: v + ":1" for v in s.VS},
                target_decision_midpoint="100", unmatched_move_bps="4")


def observed_event(detector, premium=1, source_future=False, source_unchanged=False):
    for t in (121, 121.9):
        for venue in s.VS:
            clocks = dict(source_ns=121 * s.NS, sequence=121 * s.NS) if source_unchanged else {}
            detector.process(book(t, venue, 100 * (premium if venue == "rh_lighter" else 1), **clocks))
    changes = dict(source_ns=round(122.1 * s.NS)) if source_future else {}
    if source_unchanged:
        changes = dict(source_ns=121 * s.NS, sequence=121 * s.NS)
    return detector.process(book(122, "lighter", 100.04, **changes))


class DirectionalResponseTest(unittest.TestCase):
    def test_receipt_causality_source_advancement_and_stationary_premium(self):
        plain, premium = s.ReceiptMoves(0), s.ReceiptMoves(0)
        a, b = observed_event(plain), observed_event(premium, premium=1.002)
        self.assertEqual(len(a), 1)
        self.assertEqual((a[0]["venue"], a[0]["direction"]), ("rh_lighter", 1))
        self.assertEqual((b[0]["venue"], b[0]["direction"]), ("rh_lighter", 1))
        self.assertAlmostEqual(float(a[0]["mover_move_bps"]), float(b[0]["mover_move_bps"]))
        self.assertAlmostEqual(float(a[0]["target_move_bps"]), float(b[0]["target_move_bps"]))
        self.assertLess(a[0]["prior_ns"], a[0]["t"])
        future, unchanged = s.ReceiptMoves(0), s.ReceiptMoves(0)
        self.assertEqual(observed_event(future, source_future=True), [])
        self.assertEqual(observed_event(unchanged, source_unchanged=True), [])
        self.assertEqual(unchanged.counts["BTC", "rh_lighter"]["source_not_advanced"], 1)
        # Future market movement cannot rewrite the saved direction/features.
        saved = copy.deepcopy(a)
        plain.process(book(123, "rh_lighter", 90))
        self.assertEqual(a, saved)

    def test_same_time_control_failures_keep_local_and_never_substitute(self):
        cases = ("matched", "native_grid_reject", "native_minimum_reject",
                 "source_before_due", "entry_quote_above_cap")
        for expected in cases:
            with self.subTest(expected=expected):
                metadata = copy.deepcopy(META)
                if expected == "native_grid_reject":
                    metadata["rh_lighter"]["BTC"]["qty_step"] = ".04"
                if expected == "native_minimum_reject":
                    metadata["rh_lighter"]["BTC"]["min_qty"] = "2"
                profiles = s.ResponseProfiles(metadata)
                seed(profiles)
                row = profiles.signal(signal())
                mover_t = .3 if expected == "source_before_due" else .4
                mover_mid = 103 if expected == "entry_quote_above_cap" else 100
                profiles.process(book(mover_t, "rh_lighter", mover_mid))
                profiles.process(book(.4, "lighter"))
                self.assertEqual(row["entry_control"]["status"], expected)
                frozen = copy.deepcopy(row["entry_control"])
                profiles.process(book(.5, "rh_lighter"))
                self.assertEqual(row["entry_control"], frozen)
                profiles.process(book(10.8, "rh_lighter", 100.1))
                profiles.process(book(10.8, "lighter", 100.1))
                self.assertEqual(row["status"], "matched")
                self.assertGreater(D(row["net_quote_bps"]), 0)
                self.assertEqual("quote_excess_bps" in row, expected == "matched")
                if expected == "matched":
                    self.assertAlmostEqual(float(row["quote_excess_bps"]), 0)
        # A failing first eligible local book is terminal, not retried.
        profiles = s.ResponseProfiles(META)
        seed(profiles)
        row = profiles.signal(signal())
        profiles.process(book(.4, "lighter", valid=False))
        profiles.process(book(.5, "lighter"))
        self.assertEqual(row["status"], "missing_first_eligible")

    def test_delay_consumption_is_separate_from_remaining_movement(self):
        profiles = s.ResponseProfiles(META)
        seed(profiles)
        row = profiles.signal(signal())
        self.assertTrue(row["cost_plausible"])
        self.assertAlmostEqual(float(row["immediate_roundtrip_cost_bps"]), 2, places=3)
        profiles.process(book(.4, "lighter", 100.02, source_ns=399_000_000))
        self.assertEqual(row["status"], "pending_entry")
        profiles.process(book(.5, "rh_lighter", 100.04))
        profiles.process(book(.5, "lighter", 100.03))
        self.assertAlmostEqual(float(row["consumed_before_entry_bps"]), 3, places=2)
        self.assertEqual(row["entry"]["received_ns"], 500_000_000)
        profiles.process(book(10.9, "rh_lighter", 100.04))
        profiles.process(book(10.9, "lighter", 100.035))
        self.assertEqual(row["status"], "matched")
        self.assertAlmostEqual(float(row["remaining_midpoint_bps"]), .5, places=2)
        self.assertLess(D(row["net_quote_bps"]), 0)
        self.assertEqual(row["exit_control"]["execution_due_ns"], 10_900_000_000)

    def test_episode_spacing_is_shared_across_venue_assignments(self):
        events = [dict(type="control", asset=None, venue="lighter", received_ns=0)]
        for t, mover in ((122, "lighter"), (127, "rh_lighter"), (153, "rh_lighter")):
            for prior in (t - 1, t - .1):
                events.extend(book(prior, venue) for venue in s.VS)
            events.append(book(t, mover, 100.05))
        events.append(dict(type="end", received_ns=600 * s.NS))
        result = s.diagnose(events, META, 0, ["BTC"])
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual([e["signal"]["venue"] for e in result["events"]], ["rh_lighter", "lighter"])
        target = next(r for r in result["rows"] if r["venue"] == "lighter")
        self.assertEqual(target["counts"]["same_episode"], 1)
        self.assertEqual(target["counts"]["selected_episode"], 1)
        self.assertEqual(result["non_market_events"], {"control": 1})

    def test_lifecycle_controls_empty_rows_and_terminal_reconciliation(self):
        markers = [dict(type="control", asset=None, venue="lighter", received_ns=0),
                   dict(type="end", received_ns=600 * s.NS)]
        result = s.diagnose(markers, META, 0, ["BTC"])
        self.assertEqual(len(result["rows"]), 2)
        self.assertEqual(result["events"], [])
        with self.assertRaises(AssertionError):
            s.diagnose(markers[:1], META, 0, ["BTC"])
        profiles = s.ResponseProfiles(META)
        seed(profiles)
        row = profiles.signal(signal())
        profiles.process(dict(type="invalidate", asset="BTC", venue="rh_lighter", received_ns=1))
        profiles.process(book(.4, "lighter"))
        self.assertEqual(row["entry_control"]["status"], "missing_pair")
        profiles.process(book(10.8, "lighter", 100.1))
        self.assertEqual(row["status"], "matched")
        self.assertNotIn("quote_excess_bps", row)
        unfinished = profiles.signal(signal(11))
        profiles.process(dict(type="end", received_ns=12 * s.NS))
        self.assertEqual(unfinished["status"], "unresolved_at_end")
        invalidated = s.ResponseProfiles(META)
        seed(invalidated)
        row = invalidated.signal(signal())
        invalidated.process(dict(type="invalidate", asset="BTC", venue="lighter", received_ns=1))
        self.assertEqual(row["status"], "invalidated")


if __name__ == "__main__":
    unittest.main()
