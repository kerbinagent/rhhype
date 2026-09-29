import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from paper_impulse import ImpulseObserver
from impulse_observer import select_impulse_pairs


PAIR = 'BTC|hyperliquid:BTC|lighter:1'
META = {'asset':'BTC',
        'hl':{'venue':'hyperliquid','market':'BTC','step':'.01',
              'min_qty':.01,'min_notional':10,'fee_bps':0},
        'other':{'venue':'lighter','market':1,'step':'.01',
                 'min_qty':.01,'min_notional':10,'published_fee_floor_bps':0}}


def book(venue, market, t, midpoint, seq, *, bid_size=100, ask_size=100,
         generation=1, source=None):
    return {'venue':venue,'market':market,'valid':True,
            'bids':[(midpoint-.1,bid_size)],'asks':[(midpoint+.1,ask_size)],
            'received':t,'engine_time':t if source is None else source,
            'sequence':seq,'generation':generation}


def warm(model):
    for i in range(33):
        t = 1000+i
        model.on_event(PAIR,t,book('hyperliquid','BTC',t,100,i),
                       book('lighter',1,t,100,i),'hl',META)


def arm_and_confirm(model, confirm_time=1033.3):
    warm(model)
    h = book('hyperliquid','BTC',1033,100.5,33)
    o = book('lighter',1,1033,100,33)
    model.on_event(PAIR,1033,h,o,'hl',META)
    assert model.states[PAIR].arm is not None
    o = book('lighter',1,confirm_time,100,34)
    model.on_event(PAIR,confirm_time,h,o,'other',META)
    assert model.states[PAIR].active is not None


class ImpulseTests(unittest.TestCase):
    def test_prior_only_reference_opposing_confirmation_and_both_delays(self):
        model = ImpulseObserver(extra_cost_bps=0)
        arm_and_confirm(model)
        candidate = model.states[PAIR].active
        self.assertAlmostEqual(candidate['scenarios'][0]['entry_due'],1033.8)
        self.assertAlmostEqual(candidate['scenarios'][1]['entry_due'],1034.3)
        self.assertEqual(candidate['prior_basis_bps'],0)
        self.assertEqual(candidate['direction'],'other_buy')
        self.assertEqual(model.counts['armed'],1)
        self.assertEqual(model.counts['arm_terminal'],1)
        self.assertEqual(model.arm_outcomes['confirmed'],1)
        # Both books advance, but their source clocks precede the 0.5s due.
        model.on_event(PAIR,1033.6,
            book('hyperliquid','BTC',1033.6,100.5,35,source=1033.4),
            book('lighter',1,1033.6,100,35,source=1033.4),'hl',META)
        self.assertEqual(model.counts['paired_entry_quotes'],0)
        model.on_event(PAIR,1033.9,
            book('hyperliquid','BTC',1033.9,100.5,36),
            book('lighter',1,1033.9,100,36),'other',META)
        self.assertEqual(model.counts['paired_entry_quotes'],1)
        model.on_event(PAIR,1034.4,
            book('hyperliquid','BTC',1034.4,100.5,37),
            book('lighter',1,1034.4,100,37),'hl',META)
        self.assertEqual(model.counts['paired_entry_quotes'],2)
        model.on_event(PAIR,1039.5,
            book('hyperliquid','BTC',1039.5,100,38),
            book('lighter',1,1039.5,100,38),'other',META)
        model.on_event(PAIR,1040.0,
            book('hyperliquid','BTC',1040,100,39),
            book('lighter',1,1040,100,39),'hl',META)
        rows = [r for r in model.snapshot(1040)['terminal_rows'] if r['status']=='complete']
        self.assertEqual(len(rows),2)
        self.assertEqual(len({r['candidate_id'] for r in rows}),1)
        self.assertEqual({r['delay_seconds'] for r in rows},{.5,1.0})
        for row in rows:
            self.assertGreaterEqual(row['entry_hl_received'],row['entry_due'])
            self.assertGreaterEqual(row['entry_other_received'],row['entry_due'])
            self.assertGreaterEqual(row['entry_hl_source_time'],row['entry_due'])
            self.assertGreaterEqual(row['entry_other_source_time'],row['entry_due'])
            self.assertGreaterEqual(row['exit_hl_received'],row['exit_due'])
            self.assertGreaterEqual(row['exit_other_received'],row['exit_due'])
            self.assertGreaterEqual(row['exit_hl_source_time'],row['exit_due'])
            self.assertLessEqual(row['exit_time']-row['trigger_time'],10)
            self.assertAlmostEqual(row['gross_capture_usd'],
                row['entry_sell_value']-row['entry_buy_value']+
                row['exit_long_value']-row['exit_short_buyback_value'])
        self.assertEqual(model.snapshot(1040)['by_delay']['0.5']['scenario_complete'],1)
        self.assertEqual(model.snapshot(1040)['by_delay']['1.0']['scenario_complete'],1)

    def test_first_shallow_entry_censors_primary_without_retry(self):
        model = ImpulseObserver(extra_cost_bps=0)
        arm_and_confirm(model)
        model.on_event(PAIR,1033.9,
            book('hyperliquid','BTC',1033.9,100.5,35),
            book('lighter',1,1033.9,100,35,ask_size=.1),'hl',META)
        self.assertEqual(model.censored['entry_depth'],1)
        model.on_event(PAIR,1034.4,
            book('hyperliquid','BTC',1034.4,100.5,36),
            book('lighter',1,1034.4,100,36),'other',META)
        self.assertEqual(model.counts['paired_entry_quotes'],1)
        self.assertEqual(model.snapshot(1034.4)['by_delay']['0.5']['scenario_entry_depth'],1)

    def test_arm_needs_other_update_and_stop_conserves_scenarios(self):
        model = ImpulseObserver(extra_cost_bps=0)
        warm(model)
        model.on_event(PAIR,1033,
            book('hyperliquid','BTC',1033,100.5,33),
            book('lighter',1,1033,100,33),'hl',META)
        self.assertEqual(model.counts['armed'],1)
        model.on_event(PAIR,1033.4,
            book('hyperliquid','BTC',1033.4,100.5,34),
            book('lighter',1,1033,100,33),'hl',META)
        self.assertEqual(model.counts['confirmed_candidates'],0)
        model.finish(1033.5)
        self.assertEqual(model.arm_outcomes['stopped_pending'],1)
        self.assertEqual(model.counts['armed'],model.counts['arm_terminal'])

    def test_generation_invalidates_pending_and_fee_math_is_nonnegative(self):
        model = ImpulseObserver(extra_cost_bps=5)
        arm_and_confirm(model)
        model.on_event(PAIR,1033.6,
            book('hyperliquid','BTC',1033.6,100.5,35,generation=2),
            book('lighter',1,1033.6,100,35),'hl',META)
        self.assertEqual(model.censored['generation_changed'],2)
        self.assertEqual(model.snapshot(1033.6)['pending_scenarios'],0)
        with self.assertRaisesRegex(ValueError,'nonnegative'):
            bad = dict(META,other=dict(META['other'],published_fee_floor_bps=-1))
            other = book('lighter',1,1000,100,1)
            model2 = ImpulseObserver()
            model2._hurdle({'entry_value':1000,'short_entry_value':1000,
                            'long_liquidation_value':999,'short_buyback_value':1001},
                           0,__import__('paper_fixed_markout').standard_fee_bps(bad['other']))

    def test_selects_at_most_eight_existing_pairs(self):
        plan=[]
        for asset in ('BTC','ETH','NVDA','XAG'):
            for venue in ('lighter','rh_lighter'):
                p={'asset':asset,'hl':dict(META['hl'],market=asset,volume=2_000_000),
                   'other':dict(META['other'],venue=venue,volume=2_000_000)}
                plan.append(p)
        self.assertEqual(len(select_impulse_pairs(plan)),8)
        self.assertEqual(len(select_impulse_pairs(plan,max_pairs=3)),3)

    def test_entry_due_follows_confirmation_and_requires_both_receipts(self):
        model = ImpulseObserver(extra_cost_bps=0)
        arm_and_confirm(model,1033.8)
        candidate = model.states[PAIR].active
        self.assertAlmostEqual(candidate['scenarios'][0]['entry_due'],1034.3)
        self.assertAlmostEqual(candidate['scenarios'][1]['entry_due'],1034.8)
        model.on_event(PAIR,1034.1,
            book('hyperliquid','BTC',1034.1,100.5,35),
            book('lighter',1,1034.1,100,35),'hl',META)
        self.assertEqual(model.counts['paired_entry_quotes'],0)
        # Source clocks can lead local receipt; a pre-due received leg is ineligible.
        model.on_event(PAIR,1034.35,
            book('hyperliquid','BTC',1034.2,100.5,36,source=1034.4),
            book('lighter',1,1034.35,100,36),'other',META)
        self.assertEqual(model.counts['paired_entry_quotes'],0)
        model.on_event(PAIR,1034.5,
            book('hyperliquid','BTC',1034.5,100.5,37),
            book('lighter',1,1034.5,100,37),'hl',META)
        self.assertEqual(model.counts['paired_entry_quotes'],1)

    def test_impulse_requires_current_peer_window_with_half_second_span(self):
        model = ImpulseObserver(extra_cost_bps=0)
        warm(model)
        state = model.states[PAIR]
        state.side_history['other'].clear()
        state.side_history['other'].extend([(1031.0,100),(1031.7,100)])
        model.on_event(PAIR,1033,
            book('hyperliquid','BTC',1033,100.5,33),
            book('lighter',1,1032,100,32),'hl',META)
        self.assertIsNone(state.arm)
        self.assertEqual(model.gates['impulse_history_short'],1)

    def test_first_eligible_exit_below_minimum_censors(self):
        model = ImpulseObserver(extra_cost_bps=0)
        arm_and_confirm(model)
        model.on_event(PAIR,1033.9,
            book('hyperliquid','BTC',1033.9,100.5,35),
            book('lighter',1,1033.9,100,35),'hl',META)
        # The original size remains executable but its quoted exit notional
        # falls below the frozen venue minimum.
        model.states[PAIR].active['buy_min_notional'] = 2000
        model.on_event(PAIR,1039.5,
            book('hyperliquid','BTC',1039.5,100.5,36),
            book('lighter',1,1039.5,100,36),'other',META)
        self.assertEqual(model.censored['exit_minimum'],1)

    def test_retimed_peer_and_clock_regression_are_rejected(self):
        model = ImpulseObserver(extra_cost_bps=0)
        warm(model)
        state = model.states[PAIR]
        # An old peer book first accepted on a later HL event must keep its
        # own receipt time, not gain the later event's timestamp.
        state.side_history['other'].clear()
        old_other = book('lighter',1,1032.5,100,33)
        model.on_event(PAIR,1033,
            book('hyperliquid','BTC',1033,100.5,33),old_other,'hl',META)
        self.assertEqual(state.side_history['other'][-1][0],1032.5)
        self.assertIsNone(state.arm)
        previous = state.side_token['other']
        self.assertFalse(model.on_event(PAIR,1033.2,
            book('hyperliquid','BTC',1033.2,100.5,34),
            book('lighter',1,1032.8,100,34,source=1032.4),'hl',META))
        self.assertEqual(model.gates['clock_regression'],1)
        self.assertEqual(state.side_token['other'],previous)


if __name__ == '__main__':
    unittest.main()
