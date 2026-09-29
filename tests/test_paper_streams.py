import asyncio
import unittest

from scripts.paper_streams import StreamManager


def market(venue, ident):
    return {"venue": venue, "market": ident, "asset": "BTC", "step": "0.001"}


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.books, self.status = [], []
        self.manager = StreamManager(None, [market("hyperliquid", "BTC"),
                                            market("lighter", 1), market("rh_lighter", 1),
                                            market("aster", "BTCUSDT")],
                                     self.books.append, lambda v, s: self.status.append((v, s)),
                                     max_levels=1)

    def lighter(self, kind, nonce, begin=None, bid="100", ask="101", venue="lighter"):
        body = {"nonce": nonce, "last_updated_at": 1_700_000_000_000_000,
                "bids": [{"price": bid, "size": "2"}],
                "asks": [{"price": ask, "size": "3"}]}
        if begin is not None:
            body["begin_nonce"] = begin
        return {"type": kind + "/order_book", "channel": "order_book:1", "order_book": body}

    def test_hyperliquid_snapshots_and_crossed_invalidation(self):
        self.manager.process_message("hyperliquid", {"channel": "l2Book", "data": {
            "coin": "BTC", "time": 1_700_000_000_000,
            "levels": [[{"px": "100", "sz": "2"}, {"px": "99", "sz": "1"}],
                       [{"px": "101", "sz": "3"}]]}}, "hl:0:1")
        self.assertTrue(self.books[-1]["valid"])
        self.assertEqual(self.books[-1]["bids"], [(100.0, 2.0)])
        self.assertEqual(self.books[-1]["engine_time"], 1_700_000_000.0)
        self.manager.process_message("hyperliquid", {"channel": "l2Book", "data": {
            "coin": "BTC", "time": 1_700_000_000_001,
            "levels": [[{"px": "102", "sz": "1"}], [{"px": "101", "sz": "1"}]]}}, "hl:0:1")
        self.assertFalse(self.books[-1]["valid"])
        self.assertEqual(self.books[-1]["reason"], "empty_or_crossed")

    def test_lighter_nonce_and_full_retained_depth(self):
        self.manager.process_message("lighter", self.lighter("subscribed", 10), "lc:0:1")
        self.assertTrue(self.books[-1]["valid"])
        self.manager.process_message("lighter", self.lighter("update", 11, 10,
                                                              bid="99", ask="101"), "lc:0:1")
        self.assertEqual(self.books[-1]["bids"], [(100.0, 2.0)])
        self.assertEqual(len(self.manager.states[("lighter", "1")]["bids"]), 2)
        self.manager.process_message("lighter", self.lighter("update", 13, 11,
                                                              bid="100", ask="101"), "lc:0:1")
        self.assertTrue(self.books[-1]["valid"])
        self.manager.process_message("lighter", self.lighter("update", 15, 12), "lc:0:1")
        self.assertFalse(self.books[-1]["valid"])
        self.assertIn(("lighter", "1"), self.manager.resubscribe)
        self.assertNotIn(("lighter", "1"), self.manager.states)
        self.manager.process_message("lighter", self.lighter("update", 16, 15), "lc:0:1")
        self.assertFalse(self.books[-1]["valid"])
        self.manager.process_message("lighter", self.lighter("subscribed", 20), "lc:0:1")
        self.assertTrue(self.books[-1]["valid"])

    def test_separate_lighter_domains_and_unknown_time(self):
        m = self.lighter("subscribed", 1, venue="rh_lighter")
        del m["order_book"]["last_updated_at"]
        self.manager.process_message("rh_lighter", m, "rh:0:1")
        self.assertTrue(self.books[-1]["valid"])
        self.assertIsNone(self.books[-1]["engine_time"])
        self.assertNotIn(("lighter", "1"), self.manager.states)

    def test_aster_sequence_gap_and_delete(self):
        key = ("aster", "BTCUSDT")
        self.manager.states[key] = {"generation": "as:0:1", "sequence": 100,
                                    "buffer": None, "bids": {100.0: 2.0, 99.0: 3.0},
                                    "asks": {101.0: 4.0}}
        self.manager.process_aster_delta({"s": "BTCUSDT", "U": 101, "u": 102,
                                          "pu": 100, "E": 1_700_000_000_000,
                                          "b": [["100", "0"]], "a": []}, "as:0:1")
        self.assertEqual(self.books[-1]["bids"], [(99.0, 3.0)])
        self.assertEqual(self.books[-1]["sequence"], 102)
        self.manager.process_aster_delta({"s": "BTCUSDT", "U": 104, "u": 104,
                                          "pu": 103, "b": [], "a": []}, "as:0:1")
        self.assertFalse(self.books[-1]["valid"])
        self.assertEqual(self.books[-1]["reason"], "sequence_gap")

    def test_aster_bridge_allows_old_pu_then_requires_exact_link(self):
        key = ("aster", "BTCUSDT")
        self.manager.states[key] = {"generation": "as:0:1", "sequence": 100,
                                    "buffer": None, "await_bridge": True,
                                    "bids": {100.0: 2.0}, "asks": {101.0: 4.0}}
        self.manager.process_aster_delta({"s": "BTCUSDT", "U": 101, "u": 102,
                                          "pu": 98, "b": [["100", "3"]],
                                          "a": []}, "as:0:1")
        self.assertTrue(self.books[-1]["valid"])
        self.assertEqual(self.books[-1]["sequence"], 102)
        self.assertFalse(self.manager.states[key]["await_bridge"])
        self.manager.process_aster_delta({"s": "BTCUSDT", "U": 103, "u": 104,
                                          "pu": 102, "b": [], "a": []}, "as:0:1")
        self.assertTrue(self.books[-1]["valid"])

    def test_reference_events_have_source_timestamp(self):
        self.manager.process_message("hyperliquid", {"channel": "activeAssetCtx",
            "data": {"coin": "BTC", "ctx": {"oraclePx": "100", "funding": "0.001"}}}, "hl:0:1")
        self.assertEqual(self.status[-1][1]["references"][0]["oracle_price"], 100)
        self.assertEqual(self.status[-1][1]["references"][0]["timestamp_source"], "received")
        self.manager.process_message("lighter", {"type": "update/market_stats",
            "market_stats": {"market_id": 1, "mark_price": "101", "index_price": "100"},
            "timestamp": 1_700_000_000_000}, "lc:0:1")
        self.assertEqual(self.status[-1][1]["references"][0]["reference_kind"], "mark")
        self.assertEqual(self.status[-1][1]["references"][0]["timestamp_source"], "server")

    def test_new_manager_has_distinct_generation_namespace(self):
        rebuilt = StreamManager(None, [market("lighter", 1)],
                                self.books.append, lambda v, s: None)
        self.assertNotEqual(self.manager.instance_id, rebuilt.instance_id)
        old = f"{self.manager.instance_id}:lighter:0:1"
        new = f"{rebuilt.instance_id}:lighter:0:1"
        self.assertNotEqual(old, new)

    def _hl_bbo_manager(self):
        return StreamManager(None, [market('hyperliquid', 'BTC')],
                             self.books.append,
                             lambda v, s: self.status.append((v, s)),
                             max_levels=100, prefer_bbo=True)

    def test_bbo_is_opt_in_and_never_borrows_l2_depth(self):
        frame = {'channel': 'bbo', 'data': {'coin': 'BTC', 'time': 1001,
                 'bbo': [{'px': '100', 'sz': '2'}, {'px': '101', 'sz': '3'}]}}
        self.manager.process_message('hyperliquid', frame, 'g1')
        self.assertEqual(self.books, [])
        m = self._hl_bbo_manager()
        l2 = {'channel': 'l2Book', 'data': {'coin': 'BTC', 'time': 1000,
              'levels': [[{'px': '100', 'sz': '2'}, {'px': '99', 'sz': '4'}],
                         [{'px': '101', 'sz': '3'}, {'px': '102', 'sz': '5'}]]}}
        m.process_message('hyperliquid', l2, 'g1')
        self.assertEqual(len(self.books[-1]['bids']), 2)
        m.process_message('hyperliquid', frame, 'g1')
        self.assertEqual(self.books[-1]['source'], 'bbo')
        self.assertEqual(self.books[-1]['bids'], [(100.0, 2.0)])
        self.assertEqual(self.books[-1]['asks'], [(101.0, 3.0)])
        self.assertEqual(self.books[-1]['sequence'], 1001)
        before = len(self.books)
        m.process_message('hyperliquid', l2, 'g1')
        self.assertEqual(len(self.books), before)
        self.assertEqual(m.counters['hyperliquid']['older_book_drops'], 1)

    def test_equal_time_l2_adds_depth_only_when_top_matches_bbo(self):
        m = self._hl_bbo_manager()
        bbo = {'channel': 'bbo', 'data': {'coin': 'BTC', 'time': 2000,
               'bbo': [{'px': '100', 'sz': '2', 'n': 4},
                       {'px': '101', 'sz': '3', 'n': 5}]}}
        m.process_message('hyperliquid', bbo, 'g1')
        mismatch = {'channel': 'l2Book', 'data': {'coin': 'BTC', 'time': 2000,
                    'levels': [[{'px': '100', 'sz': '9', 'n': 4},
                                {'px': '99', 'sz': '4', 'n': 1}],
                               [{'px': '101', 'sz': '3', 'n': 5}]]}}
        m.process_message('hyperliquid', mismatch, 'g1')
        self.assertEqual(self.books[-1]['source'], 'bbo')
        same_size_wrong_count = {'channel': 'l2Book', 'data': {'coin': 'BTC', 'time': 2000,
            'levels': [[{'px': '100', 'sz': '2', 'n': 999}],
                       [{'px': '101', 'sz': '3', 'n': 5}]]}}
        before = len(self.books)
        m.process_message('hyperliquid', same_size_wrong_count, 'g1')
        self.assertEqual(len(self.books), before)
        match = {'channel': 'l2Book', 'data': {'coin': 'BTC', 'time': 2000,
                 'levels': [[{'px': '100', 'sz': '2', 'n': 4},
                             {'px': '99', 'sz': '4', 'n': 1}],
                            [{'px': '101', 'sz': '3', 'n': 5},
                             {'px': '102', 'sz': '5', 'n': 1}]]}}
        m.process_message('hyperliquid', match, 'g1')
        self.assertEqual(self.books[-1]['source'], 'l2book')
        self.assertEqual(self.books[-1]['bids'], [(100.0, 2.0), (99.0, 4.0)])

    def test_null_and_malformed_bbo_invalidate_then_recover(self):
        m = self._hl_bbo_manager()
        valid = {'channel': 'bbo', 'data': {'coin': 'BTC', 'time': 3000,
                 'bbo': [{'px': '100', 'sz': '2'}, {'px': '101', 'sz': '3'}]}}
        m.process_message('hyperliquid', valid, 'g1')
        null = {'channel': 'bbo', 'data': {'coin': 'BTC', 'time': 3000,
                'bbo': [None, {'px': '101', 'sz': '3'}]}}
        m.process_message('hyperliquid', null, 'g1')
        self.assertFalse(self.books[-1]['valid'])
        self.assertEqual(self.books[-1]['reason'], 'bbo_missing_side')
        old_l2 = {'channel': 'l2Book', 'data': {'coin': 'BTC', 'time': 3000,
                  'levels': [[{'px': '100', 'sz': '2'}], [{'px': '101', 'sz': '3'}]]}}
        count = len(self.books)
        m.process_message('hyperliquid', old_l2, 'g1')
        self.assertEqual(len(self.books), count)
        malformed = {'channel': 'bbo', 'data': {'coin': 'BTC', 'time': 3002,
                     'bbo': [{'px': '100', 'sz': 'NaN'}, {'px': '101', 'sz': '3'}]}}
        m.process_message('hyperliquid', malformed, 'g1')
        self.assertFalse(self.books[-1]['valid'])
        m.process_message('hyperliquid', valid | {'data': valid['data'] | {'time': float('inf')}}, 'g1')
        self.assertFalse(self.books[-1]['valid'])
        new_l2 = old_l2 | {'data': old_l2['data'] | {'time': 3003}}
        count = len(self.books)
        m.process_message('hyperliquid', new_l2, 'g1')
        self.assertEqual(len(self.books), count)
        m.process_message('hyperliquid', valid | {'data': valid['data'] | {'time': 3004}}, 'g1')
        self.assertTrue(self.books[-1]['valid'])
        self.assertEqual(self.books[-1]['source'], 'bbo')
        m.process_message('hyperliquid', new_l2 | {'data': new_l2['data'] | {'time': 3005}}, 'g2')
        self.assertTrue(self.books[-1]['valid'])
        self.assertEqual(self.books[-1]['generation'], 'g2')

    def test_aster_buffer_overflow_fails_closed(self):
        key = ("aster", "BTCUSDT")
        from scripts.paper_streams import BUFFER_LIMIT
        from collections import deque
        self.manager.states[key] = {"generation": "as:0:1",
                                    "buffer": deque([{}] * BUFFER_LIMIT, maxlen=BUFFER_LIMIT)}
        self.manager.process_aster_delta({"s": "BTCUSDT"}, "as:0:1")
        self.assertEqual(self.books[-1]["reason"], "bootstrap_overflow")


if __name__ == "__main__":
    unittest.main()


class KeepaliveTests(unittest.IsolatedAsyncioTestCase):
    async def test_busy_inbound_feed_still_sends_regular_outbound_keepalives(self):
        import time
        from types import SimpleNamespace
        from unittest.mock import patch
        import aiohttp
        stop=asyncio.Event()
        class BusySocket:
            close_code=None
            def __init__(self):self.last_sent=time.monotonic();self.pings=[];self.expired=False
            async def send_json(self,message):
                self.last_sent=time.monotonic()
                if message.get('type')=='ping':self.pings.append(self.last_sent)
            async def receive(self,timeout):
                await asyncio.sleep(.001)
                if time.monotonic()-self.last_sent>.08:
                    self.expired=True;stop.set()
                    return SimpleNamespace(type=aiohttp.WSMsgType.CLOSE,data=1000,extra='keepalive expired')
                return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,data='{"type":"update/market_stats","market_stats":{}}')
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        ws=BusySocket()
        class Session:
            def ws_connect(self,*args,**kwargs):return ws
        manager=StreamManager(Session(),[market('lighter',1)],lambda _:None,lambda *_:None)
        async def finish():await asyncio.sleep(.20);stop.set()
        with patch('scripts.paper_streams.LIGHTER_KEEPALIVE_SECONDS',.02):
            await asyncio.gather(manager._connection('lighter',[market('lighter',1)],stop,0),finish())
        self.assertFalse(ws.expired)
        self.assertGreaterEqual(len(ws.pings),4)
        self.assertGreater(manager.counters['lighter']['messages'],20)
        self.assertEqual(manager.counters['lighter']['keepalives'],len(ws.pings))


class AsterPriorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_held_market_bootstrap_starts_before_new_market_delta(self):
        import aiohttp
        from types import SimpleNamespace

        stop = asyncio.Event()
        normal = market('aster', 'NORMALUSDT')
        held = market('aster', 'HELDUSDT') | {'risk_priority': True}
        started = []

        class Socket:
            close_code = 1000
            count = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def receive(self, timeout):
                self.count += 1
                if self.count == 1:
                    return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,
                                           data='{"data":{"e":"depthUpdate","s":"NORMALUSDT"}}')
                stop.set()
                return SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=1000, extra='')

        class Session:
            def ws_connect(self, *args, **kwargs):
                return Socket()

        manager = StreamManager(Session(), [normal, held], lambda _: None, lambda *_: None)
        manager._aster_task = lambda key, generation: started.append(key)
        await manager._connection('aster', [normal, held], stop, 0)
        self.assertEqual(started, [('aster', 'HELDUSDT'), ('aster', 'NORMALUSDT')])


class BboSubscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_opt_in_subscribes_bbo_with_l2_and_context(self):
        import aiohttp
        from types import SimpleNamespace
        stop = asyncio.Event()
        sent = []

        class Socket:
            close_code = 1000

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def send_json(self, message):
                sent.append(message)

            async def receive(self, timeout):
                stop.set()
                return SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=1000, extra='')

        class Session:
            def ws_connect(self, *args, **kwargs):
                return Socket()

        manager = StreamManager(Session(), [market('hyperliquid', 'BTC')],
                                lambda _: None, lambda *_: None, prefer_bbo=True)
        await manager._connection('hyperliquid', [market('hyperliquid', 'BTC')], stop, 0)
        self.assertEqual([x['subscription']['type'] for x in sent],
                         ['l2Book', 'bbo', 'activeAssetCtx'])
        self.assertEqual(manager.counters['hyperliquid']['subscriptions'], 3)
