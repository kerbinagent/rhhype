import unittest
from collections import Counter
from decimal import Decimal as D
from unittest.mock import patch
from scripts import single_venue_shock_controls as s


def book(t, venue, mid=100, **kwargs):
    result = dict(type="book", asset="BTC", venue=venue,
                  received_ns=round(t*s.NS), source_ns=round(t*s.NS),
                  bids=[[mid-.01,10]], asks=[[mid+.01,10]],
                  valid=True, clock_valid=True, generation=1)
    result.update(kwargs)
    return result


META = {v:{"BTC":dict(qty_step=".01",min_qty=".01",min_notional="1")} for v in s.VS}


def seed(profiles, t=0):
    for venue in s.VS:
        profiles.process(book(t, venue))


class FixedDetector:
    def __init__(self):
        self.counts = Counter()

    def process(self, event):
        if not event.get("shock"):
            return []
        return [dict(rule="depth_fade",t=event["received_ns"],venue=event["venue"],
                     direction=-1,pre=dict(spreads={event["venue"]:2.0}))]


class ShockControlsTest(unittest.TestCase):
    def test_control_selection_ignores_returns_and_has_no_fallback(self):
        signal = dict(t=100*s.NS,venue="lighter",pre=dict(spreads={"lighter":2.0}))
        def anchor(t, quiet=True, spread="1to3", outcome="matched"):
            return dict(t=round(t*s.NS),quiet_at_decision=quiet,spread_bucket=spread,
                        profiles={"-1":dict(status=outcome,quote_bps="999")})
        closest = anchor(69.9,outcome="missing_first_eligible")
        winner = anchor(70.8)
        selected, reason = s.select_control([winner,closest,anchor(70,quiet=False)],signal)
        self.assertIs(selected, closest)
        self.assertEqual(reason,"selected")
        self.assertEqual(s.select_control([anchor(67)],signal)[1],"no_control_in_fixed_time_band")
        self.assertEqual(s.select_control([anchor(70,spread="3to10")],signal)[1],"control_spread_bucket_differs")

    def test_shared_move_has_no_positive_local_residual(self):
        profiles = s.QuoteProfiles(META)
        seed(profiles)
        row = profiles.request("BTC","lighter",1,0,"shock")
        profiles.process(book(.4,"lighter",source_ns=399_000_000))
        self.assertEqual(row["status"],"pending_entry")
        profiles.process(book(.5,"rh_lighter"))
        profiles.process(book(.5,"lighter"))
        self.assertEqual(row["entry"]["received_ns"],500_000_000)
        profiles.process(book(10.9,"rh_lighter",100.1))
        profiles.process(book(10.9,"lighter",100.1))
        self.assertEqual(row["status"],"matched")
        self.assertGreater(D(row["quote_bps"]),7)
        self.assertLess(D(row["quote_minus_reference_bps"]),0)
        self.assertLess(abs(D(row["quote_bps"])-D(row["reference_bps"])-D(row["quote_minus_reference_bps"])),D("1e-20"))

    def test_first_bad_book_not_retried_and_cap_enforced(self):
        profiles = s.QuoteProfiles(META)
        seed(profiles)
        bad = profiles.request("BTC","lighter",1,0,"shock")
        capped = profiles.request("BTC","rh_lighter",1,0,"shock")
        profiles.process(book(.4,"lighter",valid=False))
        profiles.process(book(.4,"rh_lighter",103))
        profiles.process(book(.5,"lighter"))
        self.assertEqual(bad["status"],"missing_first_eligible")
        self.assertEqual(capped["status"],"entry_quote_above_cap")

    def test_reference_loss_retains_local_and_own_invalidation_terminates(self):
        profiles = s.QuoteProfiles(META)
        seed(profiles)
        local = profiles.request("BTC","lighter",-1,0,"shock")
        other = profiles.request("BTC","rh_lighter",-1,0,"shock")
        profiles.process(book(.4,"lighter"))
        profiles.process(dict(type="invalidate",asset="BTC",venue="rh_lighter",received_ns=s.NS))
        profiles.process(book(10.8,"lighter",99.9))
        self.assertEqual(local["status"],"matched")
        self.assertNotIn("reference_bps",local)
        self.assertEqual(other["status"],"invalidated")
        unfinished = profiles.request("BTC","lighter",1,11*s.NS,"ordinary")
        profiles.process(dict(type="end",received_ns=12*s.NS))
        self.assertEqual(unfinished["status"],"unresolved_at_end")

    def test_episode_spacing_crosses_venues_and_control_uses_past_only(self):
        events=[dict(type="control",asset=None,venue="lighter",received_ns=0)]
        for t,venue in ((20,None),(50,"lighter"),(55,"rh_lighter"),(85,"rh_lighter")):
            order = tuple(v for v in s.VS if v != venue) + (venue,) if venue else s.VS
            for v in order:
                events.append(book(t,v,shock=v==venue))
            if t == 20:
                events.append(book(20.1,"lighter"))
        events.append(dict(type="end",received_ns=600*s.NS))
        with patch.object(s,"Detector",FixedDetector):
            result=s.diagnose(events,META,0,["BTC"])
        self.assertEqual(len(result["events"]),2)
        self.assertEqual(result["non_market_events"],{"control":1})
        first,second=result["events"]
        self.assertEqual(first["control_anchor"]["t"],round(20.1*s.NS))
        self.assertEqual(first["control_profile"]["direction"],-1)
        self.assertIsNone(second["control_profile"])
        self.assertEqual(second["control_selection"],"control_band_has_recent_shock")
        rh=next(r for r in result["rows"] if r["venue"]=="rh_lighter")
        self.assertEqual(rh["counts"]["same_episode"],1)


if __name__=="__main__":
    unittest.main()
