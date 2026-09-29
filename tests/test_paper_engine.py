import sys
from pathlib import Path
import copy
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from paper_engine import PaperEngine, EngineConfig


def pair():
    a={'venue':'hyperliquid','market':'BTC','asset':'BTC','fee_bps':4.5,'step':'.01','min_qty':.01,'min_notional':10,'collateral':'USDC'}
    b=dict(a,venue='rh_lighter',market=1,fee_bps=0)
    return {'asset':'BTC','hl':a,'other':b,'metadata_timestamp':1000}


def book(venue,market,ts,bid,ask,size=100,generation=1):
    return {'venue':venue,'market':market,'bids':[(bid,size)],'asks':[(ask,size)],'received':ts,
            'engine_time':ts,'valid':True,'generation':generation,'sequence':str(ts)}


def engine(**kwargs):
    cfg=EngineConfig(holding_seconds=5,strategies=('standard',),capital_rate=0,**kwargs)
    e=PaperEngine([pair()],cfg,now=1000)
    e.receive(book('hyperliquid','BTC',1000,99.99,100))
    e.receive(book('rh_lighter',1,1000,102,102.01))
    e.tick(1000)
    return e


def pending_xag(*, scoped=True):
    funding={'complete':False,'cashflow_usd':None,'estimated':True,
             'events':[{'venue':'hyperliquid','cashflow_usd':-0.2}],
             'missing':[{'venue':'aster','reason':'settlement_sequence_uncertain_15s'}]}
    if scoped:
        funding['venue_results']={
            'hyperliquid':{'complete':True,'cashflow_usd':-0.2,'covered_until':3605,
                           'events':[{'venue':'hyperliquid','cashflow_usd':-0.2}],
                           'missing':[]},
            'aster':{'complete':False,'cashflow_usd':None,'covered_until':None,
                     'events':[],'missing':[{'reason':'settlement_sequence_uncertain_15s'}]}}
    return {'id':'pending-xag','pair_id':'XAG|hyperliquid:xyz:SILVER|aster:XAGUSDT',
            'asset':'XAG','strategy':'standard','status':'AWAITING_FUNDING',
            'created_at':3590,'closed_at':3605,'reserved':{'hyperliquid':1000.68,'aster':1000.75},
            'funding':funding,'legs':[
                {'venue':'hyperliquid','market':'xyz:SILVER','key':'hyperliquid:xyz:SILVER',
                 'side':'long','quantity':2,'remaining':0,'entry_time':3590,'exit_time':3605},
                {'venue':'aster','market':'XAGUSDT','key':'aster:XAGUSDT',
                 'side':'short','quantity':2,'remaining':0,'entry_time':3590,'exit_time':3605}]}


class EngineTests(unittest.TestCase):
    def test_venue_scoped_funding_releases_known_flat_margin_only(self):
        cfg=EngineConfig(strategies=('standard',),max_positions=1,max_matched_notional=1000)
        e=PaperEngine([],cfg,now=3605);e.update_pairs([pair()])
        p=pending_xag();e.positions[p['id']]=p
        self.assertAlmostEqual(e.cash_available('standard','hyperliquid',3610),4999.8)
        self.assertIsNone(e.cash_available('standard','aster',3610))
        self.assertEqual(e._reserved('standard','hyperliquid'),0)
        self.assertEqual(e._reserved('standard','aster'),1000.75)
        row=e.snapshot(3610)['strategies']['standard']
        self.assertAlmostEqual(row['reserved_usd'],1000.75)
        self.assertAlmostEqual(row['original_reserved_usd'],2001.43)
        self.assertEqual(row['closed_trades'],0)
        self.assertEqual(row['incomplete_trades'],1)
        self.assertEqual(e.ledgers['standard']['wallets']['hyperliquid'],5000)  # debit reserved, not booked
        # Flat pending trades do not consume active exposure slots, while the
        # pair itself stays present and blocks an exact duplicate.
        hl=book('hyperliquid','BTC',3610,99.99,100)
        rh=book('rh_lighter',1,3610,102,102.01)
        e.books={'hyperliquid:BTC':hl,'rh_lighter:1':rh}
        signal=e._signal(pair(),pair()['hl'],pair()['other'],hl,rh,'standard',3610)
        e._maybe_enter(pair(),p['pair_id'],signal,'standard',3610)
        self.assertEqual(len(e.positions),1)
        e._maybe_enter(pair(),e.pair_id(pair()),signal,'standard',3610)
        self.assertEqual(len(e.positions),2)
        self.assertEqual(e.ledgers['standard']['entry_attempts'],1)
        restored=PaperEngine([pair()],cfg,state=e.export_state(),now=3611)
        self.assertAlmostEqual(restored.cash_available('standard','hyperliquid',3611),
                               e.cash_available('standard','hyperliquid',3611))
        self.assertIsNone(restored.cash_available('standard','aster',3611))
        self.assertEqual(restored.ledgers['standard']['closed_trades'],0)

    def test_legacy_incomplete_funding_cannot_release_either_venue(self):
        cfg=EngineConfig(strategies=('standard',))
        e=PaperEngine([],cfg,now=3605);e.update_pairs([pair()])
        p=pending_xag(scoped=False);e.positions[p['id']]=p
        self.assertIsNone(e.cash_available('standard','hyperliquid',3610))
        self.assertIsNone(e.cash_available('standard','aster',3610))
        self.assertEqual(e._reserved('standard','hyperliquid'),1000.68)
        self.assertEqual(e._reserved('standard','aster'),1000.75)

    def test_scoped_funding_requires_coverage_and_never_spends_pending_credit(self):
        cfg=EngineConfig(strategies=('standard',))
        e=PaperEngine([],cfg,now=3605);e.update_pairs([pair()])
        p=pending_xag();e.positions[p['id']]=p
        hl=p['funding']['venue_results']['hyperliquid']
        hl['cashflow_usd']=1.0;hl['events'][0]['cashflow_usd']=1.0
        self.assertEqual(e.cash_available('standard','hyperliquid',3610),5000)
        self.assertEqual(e.ledgers['standard']['wallets']['hyperliquid'],5000)
        hl['covered_until']=3604
        self.assertIsNone(e.cash_available('standard','hyperliquid',3610))
        self.assertEqual(e._reserved('standard','hyperliquid'),1000.68)
        del hl['covered_until']
        self.assertIsNone(e.cash_available('standard','hyperliquid',3610))

    def test_no_fill_from_trigger_book_and_different_venue_delays(self):
        e=engine();p=next(iter(e.positions.values()))
        self.assertEqual(p['status'],'ENTRY_PENDING')
        self.assertEqual(e.snapshot(1000)['strategies']['standard']['pending_entries'],1)
        self.assertEqual(e.snapshot(1000)['strategies']['standard']['open_positions'],0)
        e.receive(book('hyperliquid','BTC',1000.1,99.99,100))
        self.assertEqual(p['legs'][0]['quantity'],0)
        e.receive(book('hyperliquid','BTC',1000.2,99.99,100))
        self.assertGreater(p['legs'][0]['quantity'],0)
        e.receive(book('rh_lighter',1,1000.3,102,102.01))
        self.assertEqual(p['legs'][1]['quantity'],0)
        e.receive(book('rh_lighter',1,1000.5,102,102.01))
        self.assertEqual(p['status'],'OPEN')
        self.assertEqual(p['legs'][0]['quantity'],p['legs'][1]['quantity'])

    def open_position(self,e):
        e.receive(book('hyperliquid','BTC',1000.2,99.99,100))
        e.receive(book('rh_lighter',1,1000.5,102,102.01))
        return next(iter(e.positions.values()))

    def test_exit_accounts_actual_gap_four_fees_and_reserves(self):
        e=engine();p=self.open_position(e)
        e.tick(1005.6)
        e.receive(book('hyperliquid','BTC',1005.8,99.99,100))
        e.receive(book('rh_lighter',1,1006.1,102,102.01))
        self.assertEqual(p['status'],'AWAITING_FUNDING')
        self.assertLess(p['price_net_before_funding'],0) # persistent premium is not income
        self.assertEqual(e.snapshot(1006.1)['strategies']['standard']['closed_trades'],0)
        e.settle_funding(p['id'],{'complete':False,'cashflow_usd':None,'missing':['rate']},1006.2)
        self.assertIn(p['id'],e.positions)
        e.settle_funding(p['id'],{'complete':True,'cashflow_usd':0,'estimated':False,'events':[]},1006.3)
        ledger=e.ledgers['standard']
        self.assertEqual(ledger['closed_trades'],1)
        self.assertEqual(ledger['closed_losses_exact'],1)
        self.assertAlmostEqual(ledger['closed_loss_sum_exact'],ledger['closed_pnl_exact'])
        self.assertAlmostEqual(sum(ledger['wallets'].values())-ledger['initial_capital'],ledger['closed_pnl_exact'])
        self.assertEqual(len(e.positions),0)

    def test_partial_hedge_failure_keeps_exposure_until_flattened(self):
        e=engine();p=next(iter(e.positions.values()))
        e.receive(book('hyperliquid','BTC',1000.2,99.99,100,size=1))
        e.receive(book('rh_lighter',1,1000.5,102,102.01))
        self.assertEqual(p['status'],'EXITING')
        self.assertGreater(p['legs'][1]['remaining'],p['legs'][0]['remaining'])
        self.assertEqual(e.stats['hedge_failures'],1)
        e.receive(book('hyperliquid','BTC',1000.8,99.99,100))
        e.receive(book('rh_lighter',1,1001.0,102,102.01))
        self.assertEqual(p['status'],'AWAITING_FUNDING')

    def test_disconnect_or_generation_change_cannot_fill(self):
        e=engine();p=next(iter(e.positions.values()))
        e.receive(book('hyperliquid','BTC',1000.3,99.99,100,generation=2))
        self.assertEqual(p['legs'][0]['quantity'],0)
        self.assertEqual(len(e.positions),0)
        e.tick(1004)
        self.assertEqual(len(e.positions),0)
        self.assertEqual(e.ledgers['standard']['aborted_trades'],1)

    def test_generation_change_flattens_hedge_immediately_and_reissues_exit(self):
        e=engine();p=next(iter(e.positions.values()))
        e.receive(book('hyperliquid','BTC',1000.2,99.99,100))
        self.assertGreater(p['legs'][0]['remaining'],0)
        e.receive(book('rh_lighter',1,1000.3,102,102.01,generation=2))
        self.assertEqual(p['status'],'EXITING')
        self.assertEqual(p['legs'][1]['entry_result'],'generation_changed')
        self.assertEqual(p['legs'][0]['intent']['kind'],'exit')
        e.receive(book('hyperliquid','BTC',1000.4,99.99,100,generation=2))
        self.assertEqual(p['legs'][0]['intent']['generation'],2)
        self.assertLess(p['legs'][0]['intent']['due'],1001)

    def test_stale_exposure_blocks_new_capital_on_same_venue(self):
        e=engine();self.open_position(e)
        e.receive({'venue':'rh_lighter','market':1,'received':1000.7,'valid':False,
                   'bids':[],'asks':[],'generation':1})
        self.assertIsNone(e.cash_available('standard','rh_lighter',1000.7))
        self.assertIsNotNone(e.cash_available('standard','hyperliquid',1000.7))
        other=copy.deepcopy(pair())
        other['asset']='ETH';other['hl']['market']='ETH';other['other']['market']=2
        other['metadata_timestamp']=1000.7
        e.update_pairs([pair(),other])
        e.receive(book('hyperliquid','ETH',1000.7,99.99,100))
        e.receive(book('rh_lighter',2,1000.7,102,102.01))
        e.tick(1000.7)
        self.assertEqual(len(e.positions),1)
        self.assertGreaterEqual(e.stats['capital_rejections'],1)

    def test_fill_evidence_uses_available_book_and_updated_exit_fee(self):
        e=engine();p=self.open_position(e)
        changed=pair();changed['hl']['fee_bps']=20
        e.update_pairs([changed])
        e.tick(1005.6)
        e.receive(book('hyperliquid','BTC',1005.8,99.99,100))
        self.assertEqual(p['legs'][0]['exit_fills'][0]['fee_bps'],20)
        fill=[x for x in e.evidence if x[2]=='fill' and x[1]['intent']['kind']=='exit' and x[1]['leg']=='hyperliquid:BTC'][-1]
        self.assertEqual(fill[1]['available_side_before_fill'],[(99.99,100)])
        self.assertEqual(fill[1]['fill_fee_bps'],20)

    def test_closed_winning_sum_and_counts(self):
        e=engine();p=self.open_position(e);e.tick(1005.6)
        e.receive(book('hyperliquid','BTC',1005.8,99.99,100))
        e.receive(book('rh_lighter',1,1006.1,102,102.01))
        e.settle_funding(p['id'],{'complete':True,'cashflow_usd':100,'estimated':False,'events':[]},1006.2)
        row=e.snapshot(1006.2)['strategies']['standard']
        self.assertEqual(row['closed_wins'],1)
        self.assertEqual(row['closed_losses'],0)
        self.assertAlmostEqual(row['closed_winning_sum_usd'],row['closed_pnl_exact'])

    def test_portfolio_limit_and_one_position_per_pair(self):
        e=engine(max_positions=1)
        for ts in (1000.1,1000.2,1000.3):
            e.receive(book('rh_lighter',1,ts,102,102.01));e.tick(ts)
        self.assertEqual(len(e.positions),1)
        self.assertEqual(e.ledgers['standard']['entry_attempts'],1)

    def test_funding_estimates_separate_and_restart_does_not_recredit(self):
        e=engine();p=self.open_position(e);e.tick(1005.6)
        e.receive(book('hyperliquid','BTC',1005.8,99.99,100))
        e.receive(book('rh_lighter',1,1006.1,102,102.01))
        restored=PaperEngine([pair()],e.config,state=e.export_state(),now=1006.2)
        result={'complete':True,'cashflow_usd':1.2,'estimated':True,'events':[{'venue':'hyperliquid','cashflow_usd':1.2}]}
        restored.settle_funding(p['id'],result,1007);restored.settle_funding(p['id'],result,1008)
        ledger=restored.ledgers['standard']
        self.assertEqual(ledger['funding_usd'],1.2)
        self.assertEqual(ledger['estimated_trades'],1)
        self.assertEqual(ledger['closed_trades'],0)
        self.assertAlmostEqual(sum(ledger['wallets'].values())-ledger['initial_capital'],ledger['closed_pnl_estimated'])

    def test_stale_books_never_generate_signal(self):
        e=PaperEngine([pair()],EngineConfig(),now=1000)
        e.receive(book('hyperliquid','BTC',990,99.99,100))
        e.receive(book('rh_lighter',1,1000,102,102.01));e.tick(1000)
        self.assertEqual(e.positions,{})

    def test_latency_probes_use_new_books_after_delay(self):
        e=engine();e.receive(book('hyperliquid','BTC',1000.6,99.99,100))
        e.receive(book('rh_lighter',1,1000.65,102,102.01))
        self.assertEqual(e.probe_stats['300']['observed'],1)
        self.assertEqual(e.probe_stats['300']['survived'],1)
        self.assertGreaterEqual(e.probe_stats['300']['actual_delay_ms_sum'],650-1e-6)


if __name__=='__main__':unittest.main()
