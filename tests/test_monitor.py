"""Economic, retention, persistence and async pacing tests for the monitor."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from monitor import Gate, Store, arguments, common_step, evaluate, parse_book, aster_fee


def sample_row(route='BTC|hl|rh', score=1.0, timestamp=None, notional=1000):
    return {'route': route, 'timestamp': time.time() if timestamp is None else timestamp,
            'target_notional_usd': notional, 'net_entry_usd': score + 1,
            'budgeted_edge_usd': score, 'budgeted_edge_bps': score * 10}


class MonitorTests(unittest.TestCase):
    def test_equal_quantity_and_fee_budget(self):
        args = arguments(['--no-tui', '--notionals', '1000', '--extra-cost-bps', '5'])
        now = time.time()
        h = {'venue': 'hyperliquid', 'market': 'BTC', 'fee_bps': 4.5, 'step': '0.01',
             'min_qty': 0, 'min_notional': 10, 'collateral': 'USDC'}
        o = dict(h, venue='rh_lighter', market=1, fee_bps=0, step='0.03', collateral='USDG')
        pair = {'asset': 'BTC', 'category': 'crypto', 'hl': h, 'other': o, 'metadata_utc': 'test'}
        hl = {'levels': ([(99, 100)], [(100, 100)]), 'received': now, 'engine_time': now}
        rh = {'levels': ([(102, 100)], [(103, 100)]), 'received': now, 'engine_time': None}
        row = evaluate(pair, hl, rh, args, now)[0]
        q = Decimal(row['base_quantity'])
        self.assertLessEqual(row['buy_cost_usd'], 1000)
        self.assertEqual(q % Decimal('0.01'), 0)
        self.assertEqual(q % Decimal('0.03'), 0)
        self.assertAlmostEqual(row['net_entry_usd'], float(q) * 2 - float(q) * 100 * .00045)
        self.assertAlmostEqual(row['budgeted_edge_usd'], row['net_entry_usd'] - row['entry_fees_usd'] - row['buy_cost_usd'] * .0005)
        self.assertFalse(row['other_engine_freshness_known'])
        hl['engine_time'] = now - 8
        with self.assertRaisesRegex(ValueError, 'engine_stale'):
            evaluate(pair, hl, rh, args, now)
        hl['engine_time'] = now
        rh['levels'] = ([(102, .0001)], [(103, .0001)])
        self.assertEqual(evaluate(pair, hl, rh, args, now), [])

    def test_book_rejects_nan_and_crossed(self):
        with self.assertRaises(ValueError):
            parse_book('aster', {'bids': [['nan', '2']], 'asks': [['10', '2']]})
        with self.assertRaises(ValueError):
            parse_book('aster', {'bids': [['11', '2']], 'asks': [['10', '2']]})
        self.assertEqual(common_step('0.002', '0.003'), Decimal('.006'))

    def test_bounded_window_top10_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.sqlite3'
            s = Store(path, {'model': 1}, 60, 10, 'usd')
            for i in range(15):
                s.add([sample_row(str(i), i + 1)])
            snap = s.snapshot(time.time())
            self.assertEqual(snap['retained_observations'], 10)
            self.assertEqual(len(snap['all_time_top10']), 10)
            self.assertEqual(snap['all_time_top10'][0]['budgeted_edge_usd'], 15)
            self.assertEqual(snap['totals']['cap_evictions'], 5)
            s.add([sample_row('14', 20, notional=10000)])
            self.assertEqual(len(s.snapshot(time.time())['all_time_top10']), 10)
            s.close()
            s = Store(path, {'model': 1}, 60, 10, 'usd')
            self.assertEqual(s.snapshot(time.time())['all_time_top10'][0]['budgeted_edge_usd'], 20)
            future = s.snapshot(time.time() + 61)
            self.assertEqual(future['retained_observations'], 0)
            self.assertEqual(future['window_top10'], [])
            self.assertEqual(len(future['all_time_top10']), 10)
            s.close()
            with self.assertRaisesRegex(ValueError, 'different ranking'):
                Store(path, {'model': 2}, 60, 10, 'usd')

    def test_paper_tally_counts_episodes_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'test.sqlite3'
            s = Store(path, {}, 60, 100, 'usd', episode_gap=600)
            s.add([sample_row(score=2), sample_row(score=3)])
            self.assertEqual(s.totals['paper_1000_episodes'], 1)
            self.assertEqual(s.totals['paper_1000_budgeted_sum_usd'], 2)
            s.close()
            s = Store(path, {}, 60, 100, 'usd', episode_gap=600)
            s.add([sample_row(score=4)])
            self.assertEqual(s.totals['paper_1000_episodes'], 1)
            s.add([sample_row(score=-1), sample_row(score=5)])
            self.assertEqual(s.totals['paper_1000_episodes'], 2)
            self.assertEqual(s.totals['paper_1000_budgeted_sum_usd'], 7)
            self.assertEqual(s.totals['paper_1000_net_entry_sum_usd'], 9)
            self.assertEqual(s.totals['paper_1000_positive_samples'], 4)
            s.db.execute('UPDATE signals SET last_ts=?', (time.time() - 601,))
            s.add([sample_row(score=6)])
            self.assertEqual(s.totals['paper_1000_episodes'], 3)
            s.close()

    def test_aster_asset_fee_classes(self):
        self.assertEqual(aster_fee('BTCUSDT', False)[0], 4)
        self.assertEqual(aster_fee('NVDAUSDT', True)[0], 1.25)
        self.assertEqual(aster_fee('B3USDT', False)[0], 10)
        self.assertEqual(aster_fee('SKHYNIXUSDT', True)[0], 10)

    def test_invalid_args_and_always_1000_tally(self):
        args = arguments(['--no-tui', '--notionals', '10000'])
        self.assertEqual(args.notionals, [1000, 10000])


class PacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_requests_are_paced(self):
        gate = Gate(6000)  # 10 ms intervals for test speed.
        times = []
        async def request():
            await gate.acquire()
            times.append(time.monotonic())
        await asyncio.gather(*(request() for _ in range(4)))
        self.assertTrue(all(b - a >= .009 for a, b in zip(times, times[1:])))


if __name__ == '__main__':
    unittest.main()
