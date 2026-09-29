"""Runtime resource bounds and partial-close settlement intervals."""
import copy
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from paper_monitor import BookRing, position_funding_segments, arguments, config_from, checkpoint_to_store
from paper_engine import PaperEngine
from paper_report import report
from paper_store import PaperStore


class RuntimeTests(unittest.TestCase):
    def test_partial_close_funding_uses_each_fill_quantity_and_time(self):
        p={'legs':[{'venue':'hyperliquid','market':'BTC','side':'long','quantity':3,
                   'remaining':1,'entry_time':3500,'exit_fills':[
                       {'quantity':1,'timestamp':3590},{'quantity':1,'timestamp':3610}]}]}
        parts=position_funding_segments(p,3620)['legs']
        self.assertEqual([x['exit_time'] for x in parts],[3590,3610,3620])
        self.assertEqual(sum(x['quantity'] for x in parts if x['entry_time']<3600<=x['exit_time']),2)
        self.assertEqual(len(position_funding_segments(p)['legs']),2)

    def test_ring_discards_by_bytes_and_time(self):
        ring=BookRing(max_bytes=5000,seconds=2,sample_interval=0)
        for n in range(1000):
            ring.add({'venue':'v','market':'m','received':float(n),'bids':[(1,1)],'asks':[(2,1)]})
            self.assertLessEqual(ring.used,5000)
            self.assertLessEqual(len(ring.rows),3)
        self.assertGreaterEqual(ring.rows[0][0],997)
        self.assertEqual(len(ring.around({'v:m'},limit=2)),2)

    def test_report_readonly_and_cash_reconciliation(self):
        with tempfile.TemporaryDirectory() as d:
            store=PaperStore(Path(d)/'paper.sqlite3',{})
            engine=PaperEngine([])
            store.checkpoint({'engine':copy.deepcopy(engine.export_state())})
            before=store.load_state()
            result=report(d)
            self.assertEqual(store.load_state(),before)
            for p in result['portfolios'].values():
                self.assertAlmostEqual(p['wallet_reconciliation_error_usd'],0)
            store.close()

    def test_older_exchange_snapshot_cannot_replace_newer_rest_book(self):
        engine=PaperEngine([])
        book={'venue':'hyperliquid','market':'BTC','received':1000,'engine_time':999.9,
              'valid':True,'generation':'session','bids':[(99,1)],'asks':[(101,1)]}
        engine.receive(book)
        engine.receive(book|{'received':1000.1,'engine_time':999.8,'bids':[(90,1)]})
        self.assertEqual(engine.books['hyperliquid:BTC']['bids'][0][0],99)
        self.assertEqual(engine.stats['out_of_order_engine_times'],1)

    def test_delayed_fill_waits_for_post_delay_source_time(self):
        from tests.test_paper_engine import engine,book
        e=engine();position=next(iter(e.positions.values()))
        e.receive(book('hyperliquid','BTC',1000.3,99.99,100)|{'engine_time':1000.1})
        self.assertEqual(position['legs'][0]['quantity'],0)
        e.receive(book('hyperliquid','BTC',1000.4,99.99,100)|{'engine_time':1000.25})
        self.assertGreater(position['legs'][0]['quantity'],0)

    def test_unposted_funding_losses_reduce_spendable_cash(self):
        from tests.test_paper_engine import engine,book,EngineTests
        e=engine();p=EngineTests().open_position(e)
        before=e.cash_available('standard','hyperliquid',1000.5)
        e.receive(book('hyperliquid','BTC',3601,99.99,100))
        e.receive(book('rh_lighter',1,3601,102,102.01))
        self.assertIsNone(e.cash_available('standard','hyperliquid',3601))
        p['open_funding']={'complete':True,'covered_until':3600,'cashflow_usd':1,
            'events':[{'venue':'hyperliquid','cashflow_usd':-2},{'venue':'rh_lighter','cashflow_usd':3}]}
        self.assertAlmostEqual(e.cash_available('standard','hyperliquid',3601),before-2)

    def test_default_stream_and_fully_collateralized_scenarios(self):
        args=arguments(['--no-tui'])
        config=config_from(args)
        self.assertEqual(args.transport,'stream')
        self.assertEqual(config.margin_fraction,1)
        self.assertEqual(config.notional,1000)
        self.assertEqual(config.strategies,('standard','plus','premium'))
        self.assertEqual(config.holding_seconds,10)
        self.assertEqual(config.take_profit_usd,.10)
        self.assertIsNone(config_from(arguments(['--no-tui','--no-take-profit'])).take_profit_usd)


class CheckpointFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_write_does_not_drop_drained_records(self):
        engine=PaperEngine([])
        engine.signals=[{'route':'newer'}]
        class FailingStore:
            def checkpoint(self,*args,**kwargs):raise RuntimeError('disk unavailable')
        async def synchronous_thread(fn,*args,**kwargs):return fn(*args,**kwargs)
        with patch('paper_monitor.asyncio.to_thread',new=synchronous_thread):
            with self.assertRaisesRegex(RuntimeError,'disk unavailable'):
                await checkpoint_to_store(engine,FailingStore(),{},[{'id':'closed-trade'}],
                    [{'route':'older'}],[('fill',{},'fill',1000)])
        self.assertEqual(engine.transitions,[{'id':'closed-trade'}])
        self.assertEqual([x['route'] for x in engine.signals],['older','newer'])
        self.assertEqual(engine.evidence[0][0],'fill')


if __name__=='__main__':unittest.main()
