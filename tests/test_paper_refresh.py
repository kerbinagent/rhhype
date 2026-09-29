import asyncio
from collections import Counter
from types import SimpleNamespace
import time
import unittest

from scripts.paper_refresh import _targets, _prune_history, run_hl_refresh


def fixture(now=None):
    now = now or time.time()
    market = {'venue': 'hyperliquid', 'market': 'BTC'}
    key = 'hyperliquid:BTC'
    book = {'venue': 'hyperliquid', 'market': 'BTC', 'valid': True,
            'generation': 'stream-a', 'received': now, 'engine_time': now,
            'bids': [(99.0, 10.0)], 'asks': [(100.0, 10.0)]}
    leg = {'venue': 'hyperliquid', 'market': 'BTC', 'key': key,
           'remaining': 0, 'intent': {'kind': 'entry', 'due': now-.1,
                                     'expires': now+3}}
    engine = SimpleNamespace(books={key: book},
                             positions={'1': {'legs': [leg]}}, probes={},
                             market_meta={key: market}, stats=Counter())
    return engine, key


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_intent_refreshes_using_stream_generation(self):
        engine, key = fixture()
        stop = asyncio.Event()
        published = []

        class Client:
            async def book(self, market):
                self_market = market['market']
                assert self_market == 'BTC'
                return {'received': time.time(), 'engine_time': time.time(),
                        'levels': ([(99.0, 10.0)], [(100.0, 10.0)])}

        def on_book(book):
            published.append(book)
            stop.set()

        await asyncio.wait_for(run_hl_refresh(engine, Client(), on_book, stop), 1)
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]['generation'], 'stream-a')
        self.assertEqual(published[0]['source'], 'targeted_rest')
        self.assertEqual(engine.stats['target_refresh_successes'], 1)

    async def test_reconnect_during_request_discards_result(self):
        engine, key = fixture()
        stop = asyncio.Event()
        begun, release = asyncio.Event(), asyncio.Event()
        published = []

        class Client:
            async def book(self, market):
                begun.set()
                await release.wait()
                stop.set()
                return {'received': time.time(), 'engine_time': time.time(),
                        'levels': ([(99.0, 10.0)], [(100.0, 10.0)])}

        task = asyncio.create_task(run_hl_refresh(engine, Client(), published.append, stop))
        await asyncio.wait_for(begun.wait(), 1)
        engine.books[key] = engine.books[key] | {'generation': 'stream-b'}
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertEqual(published, [])
        self.assertEqual(engine.stats['target_refresh_skipped_generation'], 1)

    async def test_rest_failure_leaves_stream_book_valid(self):
        engine, key = fixture()
        stop = asyncio.Event()

        class Client:
            async def book(self, market):
                stop.set()
                raise RuntimeError('HTTP 429')

        published = []
        await asyncio.wait_for(run_hl_refresh(engine, Client(), published.append, stop), 1)
        self.assertEqual(engine.stats['target_refresh_errors'], 1)
        self.assertTrue(engine.books[key]['valid'])
        self.assertEqual(published, [])

    def test_priorities_and_held_market_after_discovery(self):
        engine, key = fixture()
        now = time.time()
        self.assertEqual(_targets(engine, now)[key], 1)
        engine.positions['1']['legs'][0]['intent']['kind'] = 'exit'
        self.assertEqual(_targets(engine, now)[key], 0)
        engine.positions['1']['legs'][0]['intent'] = None
        engine.positions['1']['legs'][0]['remaining'] = 1
        self.assertEqual(_targets(engine, now)[key], 2)
        engine.probes['p'] = {'due': now-.1,
                              'signal': {'buy': key, 'sell': 'lighter:1'}, 'after': {}}
        self.assertEqual(_targets(engine, now)[key], 2)

    def test_scheduler_history_is_bounded_across_universe_changes(self):
        now = time.time()
        history = {f'market:{i}': now-i*.01 for i in range(2000)}
        retained = _prune_history(history, {'market:1500'}, now)
        self.assertLessEqual(len(retained), 1024)
        self.assertIn('market:1500', retained)


if __name__ == '__main__':
    unittest.main()
