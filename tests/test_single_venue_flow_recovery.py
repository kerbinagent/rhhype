"""Synthetic feature checks only. No old/rolling market archives are opened."""
from collections import deque
from decimal import Decimal as D
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import single_venue_flow_recovery as flow

NS = flow.NS
START = 1000 * NS
META = {v: {a: dict(price_tick='.01', qty_step='.01') for a in flow.rolling.ASSETS}
        for v in ('lighter', 'rh_lighter')}


def book(t, sequence, depth=100, venue='lighter', source=None):
    return dict(type='book', asset='BTC', venue=venue, market='1', generation=venue+'-g',
        received_ns=START+int(D(str(t))*NS), source_ns=START+int(D(str(t if source is None else source))*NS),
        sequence=sequence, valid=True, clock_valid=True,
        bids=[[99.99, 100], [99.95, 100], [99.80, 1]],
        asks=[[100.01, depth/2], [100.05, depth/2], [100.20, 1]])


def trade(t, qty, venue='lighter', source=None, side=True):
    return dict(type='trade', asset='BTC', venue=venue, market='1', generation=venue+'-g',
        received_ns=START+int(D(str(t))*NS), source_ns=START+int(D(str(t if source is None else source))*NS),
        exact_qty=D(str(qty)), exact_price=D('100.01'), buy_aggressor=side,
        observed_group=('order', '1', START+int(D(str(t))*NS)))


def send(detector, *events):
    detector.process_group(list(events))


def background(detector, venues=('lighter',)):
    send(detector, *(book(0, 1, venue=v) for v in venues))
    for second in range(1, 11):
        send(detector, *(trade(second+.1, 1, venue=v) for v in venues))
        send(detector, *(trade(second+.2, 1, venue=v) for v in venues))
    send(detector, *(book(59.9, 2, venue=v, source=59.85) for v in venues))


def initial(detector, venues=('lighter',), post_depth=40):
    background(detector, venues)
    send(detector, *(trade(60.1, 30, venue=v, source=60.05) for v in venues))
    send(detector, *(book(61.1, 3, post_depth, venue=v, source=61) for v in reversed(venues)))


class FlowRecoveryTests(unittest.TestCase):
    def test_closed_bins_source_anchors_and_stale_intervals(self):
        detector = flow.Preflight(META, START)
        background(detector)
        send(detector, trade(60.1, 30, source=60.05))
        send(detector, book(60.9, 3, 40, source=60.85))
        self.assertEqual(detector.counts['lighter', 'BTC']['candidates_considered'], 0)
        # A book received after the due time with its source still before it
        # cannot become the confirmation anchor.
        send(detector, book(61.1, 4, 40, source=61))
        send(detector, book(63.1, 5, 90, source=62.99))
        self.assertEqual(len(detector.rows), 0)
        send(detector, book(63.2, 6, 90, source=63.1))
        self.assertEqual(detector.rows[0]['category'], 'slow_recovered')
        self.assertEqual(detector.rows[0]['continuation'], D(0))
        self.assertTrue(detector.rows[0]['observed_zero_continuation'])
        candidates = detector.counts['lighter', 'BTC']['candidates_considered']
        send(detector, trade(570.1, 30), book(570.1, 7, source=570.1))
        send(detector, book(571.1, 8, 40, source=571))
        self.assertEqual(detector.counts['lighter', 'BTC']['candidates_considered'], candidates)
        earlier = flow.Preflight(META, START)
        background(earlier)
        # The latest received book has a source newer than the burst. The
        # earlier causal book remains eligible and passes both age bounds.
        send(earlier, book(59.95, 3, source=59.94))
        send(earlier, trade(60.1, 30, source=59.9))
        send(earlier, book(61.1, 4, 40, source=61))
        self.assertEqual(earlier.waiting_confirmation[0]['pre']['sequence'], 2)
        stale_books = flow.Preflight(META, START)
        background(stale_books)
        send(stale_books, trade(60.1, 30, source=60.05))
        # Source/sequence advance, but the 300 ms old post book cannot anchor
        # or reject the initial depletion measurement.
        send(stale_books, book(61.1, 3, 90, source=60.8))
        self.assertEqual(stale_books.counts['lighter', 'BTC']['selected'], 0)
        self.assertEqual(len(stale_books.waiting_post), 1)
        send(stale_books, book(61.2, 4, 40, source=61.1))
        self.assertEqual(stale_books.counts['lighter', 'BTC']['selected'], 1)
        # This source is after the due time, but its age still exceeds 250 ms.
        send(stale_books, book(63.4, 5, 90, source=63.05))
        self.assertEqual(stale_books.rows, [])
        send(stale_books, book(63.45, 6, 90, source=63.3))
        self.assertEqual(stale_books.rows[0]['category'], 'slow_recovered')
        stale = flow.Preflight(META, START)
        initial(stale)
        send(stale, trade(62.1, 1, source=61.5))
        send(stale, book(63.1, 4, 90, source=63))
        self.assertEqual(stale.rows[0]['status'], 'unusable')
        self.assertEqual(stale.rows[0]['failure'], 'stale_trade_interval')
        self.assertEqual(stale.rows[0]['confirmation_max_trade_age_ns'], 600_000_000)
        self.assertEqual(stale.counts['lighter', 'BTC']['slow_recovered'], 0)
        stale_burst = flow.Preflight(META, START)
        background(stale_burst)
        send(stale_burst, trade(60.6, 30, source=60))
        send(stale_burst, book(61.1, 3, 40, source=61))
        self.assertEqual(stale_burst.counts['lighter', 'BTC']['reject:stale_trade_interval'], 1)

    def test_split_fills_are_exact_and_additive(self):
        original = lambda row, raw, market, asset, hedge: dict(
            source_ns=START+60*NS, buy_aggressor=True)
        raw = dict(size='0.100000000000000003', price='100.01', is_maker_ask=True,
                   bid_id_str='order1', bid_order_version=7)
        enriched = flow.enrich_trade(original, {}, raw, '1', 'BTC', None)
        self.assertEqual(enriched['exact_qty'], D('0.100000000000000003'))
        whole = flow.Preflight(META, START); split = flow.Preflight(META, START)
        background(whole); background(split)
        send(whole, trade(60.1, 30, source=60.05))
        send(split, trade(60.1, 10, source=60.05), trade(60.1, 7, source=60.05),
             trade(60.1, 13, source=60.05))
        for detector in (whole, split):
            send(detector, book(61.1, 3, 40, source=61))
            send(detector, trade(61.2, 24))
            send(detector, trade(62.2, 24))
            send(detector, book(63.1, 4, 30, source=63))
        self.assertEqual(whole.rows[0]['dominant_qty'], split.rows[0]['dominant_qty'])
        self.assertEqual(whole.rows[0]['continuation'], split.rows[0]['continuation'])
        self.assertEqual(split.rows[0]['category'], 'persistent_unrecovered')
        self.assertEqual(split.rows[0]['burst']['prints'], 3)
        self.assertEqual(split.rows[0]['burst']['observed_groups'], 1)
        old_trade = flow.events._trade
        old_limit = flow.events.MAX_DECODED_BYTES
        with flow.adapter_configuration():
            self.assertIsNot(flow.events._trade, old_trade)
            self.assertEqual(flow.events.MAX_DECODED_BYTES, 1024**3)
        self.assertIs(flow.events._trade, old_trade)
        self.assertEqual(flow.events.MAX_DECODED_BYTES, old_limit)

    def test_fixed_band_does_not_recenter_and_can_become_zero(self):
        pre = book(60, 1)
        band = flow.point(pre, META['lighter']['BTC'])['bands'][1]
        current = book(61, 2)
        current['asks'] = [[100.05, 5], [100.09, 90], [100.20, 1]]
        fixed = flow.band_depth(current, 1, band, META['lighter']['BTC'])
        recentered = flow.point(current, META['lighter']['BTC'])['depths'][1]
        self.assertEqual(fixed, D(5))
        self.assertEqual(recentered, D(95))
        current['asks'] = [[100.20, 1]]
        self.assertEqual(flow.band_depth(current, 1, band, META['lighter']['BTC']), D(0))
        current['asks'] = [[100.01, 1], [100.05, 1]]
        with self.assertRaisesRegex(ValueError, 'boundary'):
            flow.band_depth(current, 1, band, META['lighter']['BTC'])

    def test_first_post_rejection_missing_anchors_and_invalidation(self):
        rejected = flow.Preflight(META, START)
        initial(rejected, post_depth=90)
        send(rejected, book(61.2, 4, 40, source=61.1))
        self.assertEqual(rejected.counts['lighter', 'BTC']['selected'], 0)
        self.assertEqual(rejected.counts['lighter', 'BTC']['reject:insufficient_first_post_depletion'], 1)
        missing = flow.Preflight(META, START)
        background(missing); send(missing, trade(60.1, 30, source=60.05))
        send(missing, book(61.6, 3, 40, source=61.5))
        self.assertEqual(missing.counts['lighter', 'BTC']['reject:missing_post_anchor'], 1)
        invalid = flow.Preflight(META, START)
        initial(invalid)
        send(invalid, dict(type='invalidate', venue='lighter', asset='BTC',
            received_ns=START+62*NS, reason='nonce_gap'))
        self.assertEqual(invalid.rows[0]['failure'], 'nonce_gap')
        self.assertEqual(invalid.state(('lighter', 'BTC'))['flows'], {})
        ended = flow.Preflight(META, START); initial(ended)
        send(ended, dict(type='end', received_ns=START+62*NS))
        result = ended.result()
        self.assertEqual(result['rows'][0]['failure'], 'capture_end_missing_confirmation')
        self.assertEqual(len(result['counts']), 20)
        same_time_end = flow.Preflight(META, START); initial(same_time_end)
        send(same_time_end, dict(type='end', received_ns=START+int(63.1*NS)),
             book(63.1, 4, 90, source=63))
        self.assertEqual(same_time_end.result()['rows'][0]['category'], 'slow_recovered')
        no_confirm = flow.Preflight(META, START); initial(no_confirm)
        send(no_confirm, book(63.6, 4, 90, source=63.5))
        self.assertEqual(no_confirm.rows[0]['failure'], 'missing_confirmation_anchor')

    def test_shared_asset_spacing_has_deterministic_venue_ties(self):
        detector = flow.Preflight(META, START)
        initial(detector, venues=('lighter', 'rh_lighter'))
        self.assertEqual(detector.counts['lighter', 'BTC']['selected'], 1)
        self.assertEqual(detector.counts['rh_lighter', 'BTC']['selected'], 0)
        self.assertEqual(detector.counts['rh_lighter', 'BTC']['reject:same_asset_episode_repeat'], 1)

    def test_input_roles_and_pins_refused_and_publication_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            store = flow.rolling.Store(Path(directory) / 'store')
            store.initialize('a'*64)
            plan = dict(schema='single-venue-flow-recovery-v1', pin_owner=flow.OWNER,
                store_root='data/rolling/market-research-v1',
                parameters=flow.PARAMS, batches=[dict(index=1, chunks=flow.BATCHES[1])],
                store_identity_sha256=flow.rolling.digest(store.root/'identity.json'),
                capture_parent_plan_sha256='a'*64)
            for state, role, pins in [('collecting', 'exploratory', [flow.OWNER]),
                    ('sealed_complete', 'reserved_validation', [flow.OWNER]),
                    ('sealed_complete', 'exploratory', [])]:
                with store.locked():
                    index = store.index()
                    index['chunks']['chunk-000001'] = dict(state=state, role=role, pins=pins)
                    store.write('index.json', index, flow.rolling.INDEX_BYTES)
                    with self.assertRaisesRegex(ValueError, 'already pinned'):
                        flow.check_inputs(store, plan, 1)
            destination = Path(directory) / 'immutable'
            flow.publish(destination, b'first')
            with self.assertRaises(FileExistsError):
                flow.publish(destination, b'second')
            self.assertEqual(destination.read_bytes(), b'first')


if __name__ == '__main__':
    unittest.main()
