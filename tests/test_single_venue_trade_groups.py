import unittest
from scripts.single_venue_trade_groups import collect,identity

class GroupTests(unittest.TestCase):
    def test_taker_identity_transaction_version_and_duplicate_boundaries(self):
        def trade(i,**kwargs):return dict(type='trade',market_id=120,trade_id_str=str(i),bid_id_str='b',ask_id_str='a',bid_order_version=1,ask_order_version=2,tx_hash='tx',is_maker_ask=True,price='100',size='2',**kwargs)
        a=trade(1);b=trade(2);b['price']='101'
        c=trade(3);c['is_maker_ask']=False
        d=trade(4);d['tx_hash']='next'
        e=trade(5);e['bid_order_version']=2
        f=trade(6);f.pop('tx_hash')
        row=dict(kind='frame',venue='lighter',generation='v1',receipt_utc_ns=1,payload={'type':'update/trade','trades':[a,b,a,c,d,e,f]})
        self.assertEqual(identity(row,a)[4:6],('bid','b'));self.assertEqual(identity(row,c)[4:6],('ask','a'))
        out=collect([row],[dict(venue='lighter',trade_id=i) for i in (1,2,6)])['lighter']
        self.assertEqual(out['observed_groups'],4);self.assertEqual(out['multi_price_groups'],1)
        self.assertEqual(out['counts']['unique_prints'],6);self.assertEqual(out['counts']['duplicate_prints'],1)
        self.assertEqual(out['counts']['missing_group_identity'],1);self.assertEqual(out['counts']['unmatched_shock_prints'],1)
        self.assertEqual(out['detected_shock_groups'],1);self.assertEqual(out['detected_shock_prints'],2)
        self.assertEqual(out['shock_group_details'][0]['total_observed_quantity'],'4')
        row['payload']['type']='subscribed/trade';self.assertEqual(collect([row],[])['lighter']['observed_groups'],0)

if __name__=='__main__':unittest.main()
