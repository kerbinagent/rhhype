"""Entry rejection diagnostics preserve the execution result and wallet math."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from paper_engine import EngineConfig, PaperEngine


class EntryRejectionTests(unittest.TestCase):
    def attempt(self, asks, *, limit=101, step='.01', min_qty=.01,
                min_notional=10, desired=1, source='targeted_rest'):
        engine=PaperEngine([],EngineConfig(notional=100,strategies=('standard',)),now=1000)
        position={'id':'test-entry','strategy':'standard'}
        intent={'kind':'entry','quantity':desired,'created':1000,'due':1000.1,
                'expires':1003.1,'price_limit':limit,'generation':1}
        leg={'venue':'hyperliquid','key':'hyperliquid:BTC','side':'long',
             'step':step,'min_qty':min_qty,'min_notional':min_notional,
             'fee_bps':4.5,'quantity':0,'remaining':0,'entry_value':0,
             'entry_time':None,'entry_fee':0,'fees_usd':0,'intent':intent}
        book={'venue':'hyperliquid','market':'BTC','bids':[(99,10)],'asks':asks,
              'received':1000.2,'engine_time':1000.05,'valid':True,
              'generation':1,'source':source}
        liquidity={'bids':book['bids'],'asks':book['asks']}
        before=copy.deepcopy(engine.ledgers['standard'])
        engine._fill(position,leg,intent,book,liquidity,1000.2)
        return engine,leg,liquidity,before

    def assert_rejected(self,expected,asks,**kwargs):
        engine,leg,liquidity,before=self.attempt(asks,**kwargs)
        self.assertEqual(leg['entry_result'],'rejected')
        self.assertEqual(leg['entry_rejection_reason'],expected)
        self.assertEqual(leg['quantity'],0)
        self.assertEqual(engine.ledgers['standard'],before)
        self.assertEqual(liquidity['asks'],asks)
        self.assertIsNone(leg['intent'])
        return leg

    def test_price_limit_and_missing_depth_are_distinct(self):
        leg=self.assert_rejected('price_limit',[(101,10)],limit=100)
        self.assertEqual(leg['entry_observation']['eligible_quantity'],0)
        self.assert_rejected('no_depth',[(100,0)])

    def test_lot_rounding_and_exchange_minimums_are_distinct(self):
        self.assert_rejected('lot_rounding',[(100,.005)])
        self.assert_rejected('min_notional',[(100,.1)],min_notional=20)
        self.assert_rejected('min_qty',[(100,.1)],min_qty=.2,min_notional=5)

    def test_notional_cap_is_recorded_before_zeroing_walk(self):
        leg=self.assert_rejected('notional_cap',[(101,10)],limit=102)
        self.assertEqual(leg['entry_observation']['attempted_quantity'],1)
        self.assertEqual(leg['entry_observation']['attempted_value'],101)

    def test_success_keeps_compact_book_timing_without_rejection(self):
        engine,leg,_,before=self.attempt([(100,10)])
        self.assertEqual(leg['entry_result'],'filled')
        self.assertNotIn('entry_rejection_reason',leg)
        self.assertEqual(leg['entry_observation']['book_source'],'targeted_rest')
        self.assertAlmostEqual(leg['entry_observation']['source_age_seconds'],.15)
        self.assertAlmostEqual(leg['entry_observation']['receipt_age_seconds'],0)
        self.assertAlmostEqual(leg['entry_observation']['signal_to_receipt_seconds'],.2)
        self.assertEqual(leg['entry_value'],100)
        self.assertAlmostEqual(before['wallets']['hyperliquid']-
                               engine.ledgers['standard']['wallets']['hyperliquid'],.045)


if __name__=='__main__':unittest.main()
