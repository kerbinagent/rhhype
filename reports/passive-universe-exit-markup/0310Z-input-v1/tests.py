"""Exact fee-dependent grid repricing and unchanged-denominator contracts."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import analyze_passive_universe_exit_markup as markup


def fixture(q='2',bid='100',ask='100.04',sell='199',buy='201',rh_bps='10',hl_bps='1',tick='.01'):
    q,b,a,S,B=map(markup.f,(q,bid,ask,sell,buy));r,h=markup.f(rh_bps)/10000,markup.f(hl_bps)/10000
    fee=(q*b+q*a)*r+(S+B)*h;stress=max(q*b,S)*markup.STRESS
    score={'valid':True,'budget':1000,'quantity':markup.decimal(q),'rh_bid':markup.decimal(b),
           'rh_ask':markup.decimal(a),'hl_sell_notional':markup.decimal(S),'hl_buy_notional':markup.decimal(B),
           'modeled_fill_fees':markup.decimal(fee),'stress_allowance':markup.decimal(stress),
           'after_target_stress':markup.decimal(q*(a-b)+S-B-fee-markup.TARGET-stress)}
    market={'rh_price_tick':tick,'rh_maker_fee_bps':rh_bps,'hl_taker_fee_bps':hl_bps,
            'rh_max_quote':'1000000','rh_min_notional':'10'}
    return {'asset':'TEST','round':0},score,market


class MarkupTests(unittest.TestCase):
    def test_exit_fee_dependency_and_minimal_exact_grid_ceiling(self):
        quote,score,market=fixture();row=markup.derive(quote,score,market)
        self.assertTrue(row['pricing_supported'],row)
        self.assertEqual(row['required_exit_price'],'101.33')
        self.assertEqual(row['markup_ticks'],129)
        self.assertEqual(markup.f(row['repriced_rh_exit_fee']),markup.f('.20266'))
        self.assertEqual(markup.f(row['rounded_exit_margin_after_target_stress']),markup.f('.01734'))
        self.assertEqual(markup.f(row['previous_tick_margin_after_target_stress']),markup.f('-.00264'))

    def test_exact_grid_equality_and_sub_decimal_precision_ceil(self):
        quote,score,market=fixture(q='1',ask='100.01',sell='100',buy='100',rh_bps='0',hl_bps='0')
        row=markup.derive(quote,score,market)
        self.assertEqual(row['required_exit_price'],'100.15')
        self.assertEqual(markup.f(row['rounded_exit_margin_after_target_stress']),0)
        quote,score,market=fixture(q='1',ask='100.01',sell='100',buy='100.000000000000000000000000001',rh_bps='0',hl_bps='0')
        row=markup.derive(quote,score,market)
        self.assertTrue(row['pricing_supported'],row)
        self.assertEqual(row['required_exit_price'],'100.16')

    def test_existing_ask_that_clears_hurdle_has_zero_markup(self):
        quote,score,market=fixture(ask='102');row=markup.derive(quote,score,market)
        self.assertTrue(row['pricing_supported'],row)
        self.assertEqual(row['required_exit_price'],'102')
        self.assertEqual(row['markup_ticks'],0)

    def test_missing_metadata_and_bad_original_fees_are_explicit_limitations(self):
        quote,score,market=fixture();market.pop('rh_price_tick')
        row=markup.derive(quote,score,market)
        self.assertTrue(row['original_valid']);self.assertFalse(row['pricing_supported'])
        self.assertIn('rh_price_tick',row['pricing_limitation'])
        quote,score,market=fixture();score['modeled_fill_fees']='999'
        self.assertIn('not_exactly_supported',markup.derive(quote,score,market)['pricing_limitation'])
        quote,score,market=fixture();market['rh_max_quote']='200'
        self.assertEqual(markup.derive(quote,score,market)['pricing_limitation'],'required_exit_notional_violates_frozen_bound')

    def test_original_failure_and_coverage_remain_visible_without_nominations(self):
        universe={'selected':[{'asset':'TEST'}]};rows=[]
        for n in range(5):
            for size in markup.SIZES:
                quote,score,market=fixture();quote['round']=n;score['budget']=size
                if n>=3:score={'valid':False,'budget':size,'reason':'stale_source_or_receipt'}
                rows.append(markup.derive(quote,score,market))
        summary=markup.summarize(rows,universe)
        self.assertEqual(summary['total_observations'],20)
        self.assertEqual(summary['original_valid_observations'],12)
        self.assertEqual(summary['original_exclusion_reasons'],{'stale_source_or_receipt':8})
        self.assertEqual(summary['eligible_assets_original_1000'],1)
        self.assertEqual(summary['candidate_nominations'],[])
        self.assertTrue(all(r['supported_rounds']==3 for r in summary['asset_size_distances']))


if __name__=='__main__':unittest.main()
