"""Tests for sampled persistence brackets and fee-scenario accounting."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_monitor import adjusted_budget, persistence


def row(ts, gross=1):
    return {'timestamp':ts,'utc':str(ts),'asset':'NVDA','route':'NVDA|hyperliquid:xyz:NVDA|rh_lighter:1',
            'buy':'hyperliquid:xyz:NVDA','sell':'rh_lighter:1','category':'RWA/xyz',
            'buy_cost_usd':1000,'sell_proceeds_usd':1000+gross,'buy_fee_bps':.9,'sell_fee_bps':0,
            'additional_cost_reserve_usd':.5}


class AuditTests(unittest.TestCase):
    def test_isolated_observation_is_not_a_known_lifetime(self):
        r=[row(0,0),row(60),row(120,0)]
        e=persistence({r[0]['route']:r})[0]
        self.assertEqual(e['positive_samples'],1)
        self.assertEqual(e['observed_first_to_last_seconds'],0)
        self.assertEqual(e['outer_bracket_seconds'],120)
        self.assertFalse(e['right_censored'])

    def test_runs_separate_and_window_edge_is_censored(self):
        r=[row(0,0),row(60),row(120),row(180,0),row(240)]
        es=persistence({r[0]['route']:r})
        self.assertEqual(len(es),2)
        self.assertEqual(es[0]['observed_first_to_last_seconds'],60)
        self.assertEqual(es[0]['outer_bracket_seconds'],180)
        self.assertTrue(es[1]['right_censored'])
        self.assertIsNone(es[1]['outer_bracket_seconds'])

    def test_premium_charges_both_open_and_close_fee_reserve(self):
        r=row(0)
        standard=adjusted_budget(r)[1]
        premium=adjusted_budget(r,'premium')[1]
        self.assertAlmostEqual(standard-premium,2*r['sell_proceeds_usd']*3.5/10000)
        r['sell']='aster:NVDAUSDT';r['sell_fee_bps']=4
        corrected=adjusted_budget(r,corrected_aster=True)[1]
        original=adjusted_budget(r)[1]
        self.assertAlmostEqual(corrected-original,2*r['sell_proceeds_usd']*(4-1.25)/10000)

if __name__=='__main__':unittest.main()
