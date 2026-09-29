"""Runtime resource bounds and partial-close settlement intervals."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from paper_monitor import BookRing, position_funding_segments, arguments, config_from
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

    def test_default_stream_and_fully_collateralized_scenarios(self):
        args=arguments(['--no-tui'])
        config=config_from(args)
        self.assertEqual(args.transport,'stream')
        self.assertEqual(config.margin_fraction,1)
        self.assertEqual(config.notional,1000)
        self.assertEqual(config.strategies,('standard','plus','premium'))
        self.assertEqual(config.holding_seconds,300)


if __name__=='__main__':unittest.main()
