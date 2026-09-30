"""Contracts for the offline optimistic static hedge-cost budget."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import analyze_passive_universe_hedge_budget as budget


def fixture(ask='100.04'):
    q, bid, ask = budget.d(2), budget.d(100), budget.d(ask)
    spread = q * (ask - bid)
    s = {'valid': True, 'budget': 1000, 'quantity': str(q), 'rh_bid': str(bid), 'rh_ask': str(ask),
         'rh_buy_notional': str(q * bid), 'rh_sell_notional': str(q * ask),
         'rh_spread_capture': str(spread), 'modeled_fill_fees': '.02',
         'hl_roundtrip_spread_impact': '-.03', 'stress_allowance': '.101',
         'after_target_stress': str(spread - budget.d('.03') - budget.d('.02') - budget.d('.1') - budget.d('.101'))}
    return {'asset': 'TEST', 'round': 0}, s


class BudgetTests(unittest.TestCase):
    def test_exact_arithmetic_minimum_stress_and_original_fees_preserved(self):
        q, s = fixture()
        r = budget.derive(q, s)
        self.assertEqual(budget.d(r['minimum_stress']), budget.d('.1'))
        self.assertEqual(budget.d(r['zero_fees_zero_hedge_spread_budget']), budget.d('-.12'))
        self.assertEqual(budget.d(r['observed_fees_retained_zero_hedge_spread_budget']), budget.d('-.14'))
        self.assertEqual(budget.d(r['optimistic_minus_original']), budget.d('.051'))
        self.assertEqual(budget.d(r['minimum_required_spread_bps']), budget.d('10'))

    def test_strict_positive_zero_and_negative(self):
        for ask, expected in [('100.2', True), ('100.1', False), ('100.04', False)]:
            q,s = fixture(ask)
            self.assertEqual(budget.derive(q,s)['positive_optimistic_budget'], expected)

    def test_original_failed_observation_never_recovered(self):
        row = budget.derive({'asset':'TEST','round':0}, {'valid':False,'budget':1000,'reason':'stale_source_or_receipt'})
        self.assertEqual(row, {'asset':'TEST','round':0,'budget':1000,'valid':False,'reason':'stale_source_or_receipt'})

    def test_rebates_positive_hedge_impact_smaller_stress_and_bad_saved_math_reject(self):
        for key, value in [('modeled_fill_fees','-.01'), ('hl_roundtrip_spread_impact','.01'),
                           ('stress_allowance','.01'), ('rh_spread_capture','9'), ('after_target_stress','9')]:
            q,s=fixture();s[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                budget.derive(q,s)

    def test_original_1000_coverage_and_median_prevent_single_peak_nomination(self):
        universe={'denominator':1,'selected':[{'asset':'TEST','min_24h_volume':'2000000'}]}
        rows=[]
        for n,ask in enumerate(['100.04','100.03','200']):
            q,s=fixture(ask);q['round']=n
            for b in budget.BUDGETS:
                score=copy.deepcopy(s);score['budget']=b
                rows.append(budget.derive(q,score))
        early=budget.summarize(rows[:8],universe)
        self.assertTrue(all(s['eligible_assets']==0 for s in early['by_size']))
        summary=budget.summarize(rows,universe)
        for size in summary['by_size']:
            self.assertEqual(size['positive_observations'],1)
            self.assertEqual(size['positive_eligible_medians'],0)
            self.assertEqual(size['eligible_assets'],1)
            self.assertEqual(budget.d(size['best_eligible_median']['median_optimistic_budget']),budget.d('-.12'))


if __name__ == '__main__':
    unittest.main()
