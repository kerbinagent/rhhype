import unittest
from decimal import Decimal as D
from scripts.single_venue_broad_quotes import values,diagnose
from tests.test_single_venue_broad_reference import book


class QuoteTests(unittest.TestCase):
    def test_direction_and_full_depth(self):
        books={'lighter':book('BTC','lighter',1,100),
               'rh_lighter':book('BTC','rh_lighter',1,104)}
        long=values(books,'lighter',1,D(1));short=values(books,'lighter',-1,D(1))
        self.assertEqual(long['edge'],D(2)/102*10000)
        self.assertEqual(short['edge'],-D(6)/100*10000)
        self.assertEqual(long['cost'],D(2)/102*10000)
        self.assertIsNone(values(books,'lighter',1,D(2)))

    def test_first_eligible_missing_pair_is_not_retried(self):
        ns=1_000_000_000
        stream=[book('BTC','rh_lighter',3*ns,104),book('BTC','lighter',3*ns+1,100),
                book('BTC','lighter',3*ns+500_000_000,100),
                book('BTC','rh_lighter',3*ns+600_000_000,104),
                book('BTC','lighter',3*ns+600_000_001,100),
                dict(type='end',received_ns=4*ns)]
        m=dict(qty_step='0.001',min_qty='0.001',min_notional='1')
        rows=diagnose(stream,{v:{'BTC':m} for v in ('lighter','rh_lighter')},0,['BTC'])
        row=next(r for r in rows if r['venue']=='lighter' and r['direction']==1)
        self.assertEqual(row['counts']['initial_ge5'],1)
        self.assertEqual(row['counts']['delayed_missing'],1)
        self.assertEqual(row['counts'].get('delayed_full',0),0)

    def test_adjacent_second_samples_keep_both_pending(self):
        ns=1_000_000_000
        stream=[]
        for t in (3*ns+900_000_000,4*ns+10_000_000,4*ns+500_000_000):
            stream.extend([book('BTC','rh_lighter',t,104),book('BTC','lighter',t+1,100)])
        stream.append(dict(type='end',received_ns=5*ns))
        m=dict(qty_step='0.001',min_qty='0.001',min_notional='1')
        rows=diagnose(stream,{v:{'BTC':m} for v in ('lighter','rh_lighter')},0,['BTC'])
        row=next(r for r in rows if r['venue']=='lighter' and r['direction']==1)
        self.assertEqual(row['counts']['initial_ge5'],2)
        self.assertEqual(row['counts']['initial_ge5_still_ge5'],2)


if __name__=='__main__':unittest.main()
