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
    async def test_confirmation_has_a_turn_under_continuous_other_work(self):
        now=time.time();engine,key=fixture(now);stop=asyncio.Event();seen=[]
        engine.positions={};engine.books={};engine.market_meta={}
        for priority in range(5):
            k=f'hyperliquid:M{priority}'
            engine.books[k]={'valid':True,'generation':'g','received':now,'engine_time':now}
            engine.market_meta[k]={'venue':'hyperliquid','market':f'M{priority}'}
            if priority<3:
                engine.positions[str(priority)]={'legs':[{'venue':'hyperliquid','key':k,
                    'remaining':1 if priority==2 else 0,'intent':None if priority==2 else
                    {'kind':'exit' if priority==0 else 'entry','due':now-1,'expires':now+100}}]}
        engine.probes={'probe':{'due':now-1,'signal':{'buy':'hyperliquid:M3','sell':'lighter:1'},'after':{}}}
        engine.selector=SimpleNamespace(pending_confirmation_targets=lambda t:[
            {'buy':'hyperliquid:M4','sell':'lighter:1','due':now-1,'expires':now+100}])
        class Client:
            async def book(self,market):
                seen.append(market['market'])
                return {'received':time.time(),'engine_time':time.time(),
                        'levels':([(99,10)],[(100,10)])}
        def on_book(book):
            if len(seen)>=12:stop.set()
        await asyncio.wait_for(run_hl_refresh(engine,Client(),on_book,stop,
            interval=.001,min_key_interval=.0001,max_concurrent=1),2)
        self.assertEqual(seen,['M0','M1','M0','M2','M0','M3','M0','M1','M0','M2','M0','M4'])
        self.assertEqual(engine.stats['target_refresh_priority_4_successes'],1)

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

    async def test_unexpected_worker_failure_reaches_supervisor(self):
        engine,key=fixture();stop=asyncio.Event()
        class Client:
            async def book(self,market):raise AssertionError('unexpected implementation failure')
        with self.assertRaises(AssertionError):
            await asyncio.wait_for(run_hl_refresh(engine,Client(),lambda _:None,stop),1)

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


class ConfirmationRefreshTests(unittest.TestCase):
    def test_confirmations_use_spare_capacity_without_displacing_exits(self):
        engine,key=fixture();now=time.time()
        engine.selector=SimpleNamespace(pending_confirmation_targets=lambda t:[
            {'buy':key,'sell':'lighter:1','due':now-.1,'expires':now+3},
            {'buy':'hyperliquid:ETH','sell':'lighter:2','due':now-.1,'expires':now+3},
            {'buy':'hyperliquid:SOL','sell':'lighter:3','due':now+1,'expires':now+4}])
        engine.positions['1']['legs'][0]['intent']['kind']='exit'
        targets=_targets(engine,now)
        self.assertEqual(targets[key],0)
        self.assertEqual(targets['hyperliquid:ETH'],4)
        self.assertNotIn('hyperliquid:SOL',targets)
