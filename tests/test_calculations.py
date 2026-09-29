"""Guard economic errors that can invert a spread or fabricate fills."""
import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from analyze_live import consume,fee_bps,levels,base_lot_step,on_lot_grid,analyze_run

class Calculations(unittest.TestCase):
    def test_walk_and_insufficient_depth(self):
        self.assertEqual(consume([(10,2),(11,3)],4),42)
        self.assertIsNone(consume([(10,2),(11,3)],5.01))
    def test_fee_growth_strings(self):
        m={'venue':'hyperliquid','kind':'perp','dex':'xyz','fee_scale':'1.0','growth_mode':'enabled'}
        self.assertAlmostEqual(fee_bps(m),.9)
        m['growth_mode']='disabled';self.assertEqual(fee_bps(m),9)
        m['fee_scale']='0.5';self.assertEqual(fee_bps(m),6.75)
        m['fee_scale']='3';self.assertEqual(fee_bps(m),27)
    def test_lighter_tiers(self):
        self.assertEqual(fee_bps({'venue':'lighter'}),0)
        self.assertEqual(fee_bps({'venue':'lighter'},True),2.8)
        self.assertEqual(fee_bps({'venue':'rh_lighter'},True),3.5)
    def test_unsorted_lighter_order_entries_are_sorted(self):
        row={'venue':'lighter','body':{'bids':[{'price':'9','remaining_base_amount':'1'},{'price':'10','remaining_base_amount':'2'}],
               'asks':[{'price':'12','remaining_base_amount':'2'},{'price':'11','remaining_base_amount':'1'}]}}
        b,a=levels(row);self.assertEqual(b[0],(10,2));self.assertEqual(a[0],(11,1))
    def test_crossed_book_rejected(self):
        with self.assertRaises(ValueError):levels({'venue':'hyperliquid','body':{'levels':[[{'px':'12','sz':'1'}],[{'px':'11','sz':'1'}]]}})
    def test_multiplier_hedge_and_both_leg_fees(self):
        tokens=100;multiplier=1.001;token_price=100.1;share_price=100
        self.assertAlmostEqual(tokens*multiplier*share_price-tokens*token_price,0)
        buy=10000;sell=10010;fees=buy*.00045+sell*.00028
        self.assertAlmostEqual((sell-buy-fees)/buy*10000,2.6972)
    def test_normalized_stock_token_lot_diagnostic(self):
        rh={'venue':'rh_lighter','market':'15','asset':'NVDA','category':'stocks','kind':'spot',
            'collateral':'USDG','sz_decimals':2,'unit_multiplier':1.001}
        hl={'venue':'hyperliquid','market':'xyz:NVDA','asset':'NVDA','category':'stocks','kind':'perp',
            'collateral':'USDC','sz_decimals':2,'dex':''}
        self.assertAlmostEqual(base_lot_step(rh),.01001)
        self.assertFalse(on_lot_grid(10,base_lot_step(rh)))
        self.assertTrue(on_lot_grid(10,base_lot_step(hl)))
        rows=[]
        for m in (rh,hl):
            if m['venue']=='rh_lighter':body={'bids':[{'price':'100.1','remaining_base_amount':'20'}],
                'asks':[{'price':'100.2','remaining_base_amount':'20'}]}
            else:body={'levels':[[{'px':'100.1','sz':'20'}],[{'px':'100.2','sz':'20'}]]}
            rows.append({'round':0,'venue':m['venue'],'market':m['market'],'body':body,
                'request_start_ms':999,'received_ms':1000})
        obs,_,_,_=analyze_run(pathlib.Path('.'),notionals=(1000,),plan_override=[rh,hl],records_override=rows)
        self.assertEqual(len(obs),2)
        self.assertTrue(all(not r['both_sizes_on_lot_grid'] for r in obs))
        self.assertTrue(all(r['full_lot_reserve_usd']>0 and r['net_after_rounding_reserve_bps']<r['net_entry_bps'] for r in obs))
if __name__=='__main__':unittest.main()
