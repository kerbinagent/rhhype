"""Successor ordinary-print filtering against fully synthetic pinned archives."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import single_venue_ordinary_events as events
from scripts import single_venue_depth_capture as capture
from tests import test_core_maker_events as archive_helpers
from tests.test_passive_three_venue_events import BASE, book, flow, row, trade


SELECTED = {'rh_lighter': {'ETH': '0'}, 'lighter': {'ETH': '0'}}


def batch(offset, venue='rh_lighter', *, trades=None, liquidations=(), subscribed=False):
    result = flow(offset, venue, '0', trades=trades, subscribed=subscribed)
    result['payload']['liquidation_trades'] = list(liquidations)
    return result


def nonordinary(subtype='liquidation', **extra):
    # Nonordinary economic, identity and clock fields are deliberately absent
    # or unusable: this adapter validates only their object/market/type envelope.
    return {'type': subtype, 'market_id': 0, 'trade_id_str': None,
            'price': None, 'size': 'not-an-ordinary-quantity',
            'is_maker_ask': 'unknown', 'timestamp': 'not-an-ordinary-clock', **extra}


def fixture(directory, rows):
    # Reuse the existing compressed metadata/raw archive writer; its hardcoded
    # ETH catalog is sufficient for both venues. Patch only synthetic context.
    with patch.object(archive_helpers, 'capture', capture), \
            patch.object(archive_helpers, 'events', events):
        archive_helpers.fixture(directory, rows)
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    manifest['schema'] = 'single-venue-depth-public-capture-v1'
    manifest_path.write_text(json.dumps(manifest))
    return events.sha256(manifest_path)


class OrdinaryEventsTests(unittest.TestCase):
    def replay(self, rows, **kwargs):
        with tempfile.TemporaryDirectory() as temporary, patch.object(capture, 'SELECTED', SELECTED):
            directory = Path(temporary) / 'capture'
            digest = fixture(directory, rows)
            raw_hash = events.sha256(directory / 'frames.jsonl.gz')
            return list(events.iter_events(directory, expected_manifest_sha256=digest,
                                            expected_raw_sha256=raw_hash, **kwargs))

    def test_mixed_batches_keep_ordinary_before_after_and_later_feed_live(self):
        original = events._trade
        called = []

        def enrich(message, raw, market, asset, hedge_venue):
            called.append((message['venue'], raw['trade_id_str']))
            result = original(message, raw, market, asset, hedge_venue)
            result['ordinary_hook_marker'] = 'preserved'
            return result

        excluded = nonordinary()
        rows = [row('connection_open', 0), row('connection_open', 1, 'lighter'),
                book(100, market='0'), book(110, 'lighter', '0'),
                batch(200, trades=[trade(1, 170, 0), excluded, trade(2, 180, 0)],
                      liquidations=[excluded]),
                batch(210, 'lighter', trades=[trade(1, 170, 0), excluded, trade(2, 180, 0)],
                      liquidations=[excluded]),
                batch(300, trades=[trade(3, 280, 0)]),
                batch(310, 'lighter', trades=[trade(3, 290, 0)])]
        with patch.object(events, '_trade', enrich):
            result = self.replay(rows, hedge_venue='rh_lighter')
        prints = [event for event in result if event['type'] == 'trade']
        self.assertEqual([(event['venue'], event['trade_id']) for event in prints],
                         [('rh_lighter', 1), ('rh_lighter', 2), ('lighter', 1),
                          ('lighter', 2), ('rh_lighter', 3), ('lighter', 3)])
        self.assertEqual(len(called), 6)
        self.assertTrue(all(event['ordinary_hook_marker'] == 'preserved' for event in prints))
        self.assertTrue(all(event['market'] == '0' and event['asset'] == 'ETH' for event in prints))
        self.assertEqual({event['venue']: event['role'] for event in prints},
                         {'rh_lighter': 'hedge', 'lighter': 'maker'})
        self.assertFalse([event for event in result if event['type'] == 'invalidate'
                          and event['scope'] == 'trade' and event['reason'] != 'capture_end'])
        end = result[-1]
        for venue in SELECTED:
            self.assertEqual(end['counts'][f'excluded_trades_subtype:{venue}:liquidation'], 1)
            self.assertEqual(end['counts'][f'ignored_liquidations:{venue}'], 1)
            self.assertEqual(end['counts'][f'yield_trade:{venue}'], 3)
        self.assertEqual(end['adapter_sha256'], events.sha256(Path(events.__file__)))
        self.assertTrue(end['raw_sha_verified'] and end['manifest_sha_verified'])
        self.assertEqual(len(end['metadata_sha256']), 10)

    def test_all_known_subtypes_are_separate_raw_exclusions_not_ordinary_ids_or_clocks(self):
        known = [nonordinary(subtype) for subtype in ('liquidation', 'deleverage', 'market-settlement')]
        result = self.replay([
            row('connection_open', 0), batch(200, trades=[trade(1, 180, 0)]),
            batch(300, trades=known, liquidations=[known[0]]),
            batch(400, trades=[trade(2, 190, 0)])], max_ids=2)
        self.assertEqual([event['trade_id'] for event in result if event['type'] == 'trade'], [1, 2])
        counts = result[-1]['counts']
        for subtype in ('liquidation', 'deleverage', 'market-settlement'):
            self.assertEqual(counts[f'excluded_trades_subtype:rh_lighter:{subtype}'], 1)
        self.assertEqual(counts['ignored_liquidations:rh_lighter'], 1)
        self.assertNotIn('invalid_trade_batches:rh_lighter', counts)
        self.assertNotIn('duplicate_trade_ids:rh_lighter', counts)

    def test_unknown_identity_object_and_malformed_ordinary_fail_closed(self):
        missing_type = nonordinary(); missing_type.pop('type')
        failures = [nonordinary('unknown'), missing_type, nonordinary(type=None),
                    nonordinary(type=['liquidation']), nonordinary(market_id=99),
                    trade(4, 170, 99), dict(trade(4, 170, 0), price='0'),
                    dict(trade(4, 170, 0), size='NaN'),
                    dict(trade(4, 170, 0), is_maker_ask='true'),
                    trade(4, 210, 0), None]
        for bad in failures:
            with self.subTest(bad=bad):
                result = self.replay([
                    row('connection_open', 0), row('connection_open', 1, 'lighter'),
                    batch(200, trades=[trade(1, 170, 0), bad, trade(2, 180, 0)]),
                    batch(300, trades=[trade(3, 280, 0)]),
                    batch(310, 'lighter', trades=[trade(8, 290, 0)])])
                self.assertEqual([(event['venue'], event['trade_id']) for event in result
                                  if event['type'] == 'trade'], [('lighter', 8)])
                self.assertTrue(any(event['type'] == 'invalidate' and event['scope'] == 'trade'
                                    and event['venue'] == 'rh_lighter' and event['reason'] != 'capture_end'
                                    for event in result))
                counts = result[-1]['counts']
                self.assertEqual(counts['invalid_trade_batches:rh_lighter'], 1)
                self.assertEqual(counts['suppressed_trade_frames_after_invalidation'], 1)
                self.assertNotIn('excluded_trades_subtype:rh_lighter:liquidation', counts)

    def test_subscription_history_dedup_and_generation_reset_are_preserved(self):
        excluded = nonordinary(trade_id_str='7')
        next_open = dict(row('connection_open', 350), generation='rh_lighter:2')
        next_live = dict(batch(400, trades=[trade(7, 380, 0)]), generation='rh_lighter:2')
        next_delta = dict(book(500, market='0', nonce=2, begin=1), generation='rh_lighter:2')
        result = self.replay([
            row('connection_open', 0), book(90, market='0'),
            batch(100, trades=[trade(7, 80, 0), None, nonordinary('unknown', market_id=99)],
                  liquidations=[excluded], subscribed=True),
            batch(200, trades=[excluded, trade(7, 180, 0), trade(7, 180, 0)], liquidations=[excluded]),
            batch(300, trades=[trade(7, 280, 0)]), next_open, next_live, next_delta])
        self.assertEqual([(event['trade_id'], event['source_generation']) for event in result
                          if event['type'] == 'trade'], [(7, 'rh_lighter:1'), (7, 'rh_lighter:2')])
        counts = result[-1]['counts']
        self.assertEqual(counts['ignored_backlog_batches:rh_lighter'], 1)
        self.assertEqual(counts['duplicate_trade_ids:rh_lighter'], 2)
        self.assertEqual(counts['excluded_trades_subtype:rh_lighter:liquidation'], 1)
        self.assertEqual(counts['ignored_liquidations:rh_lighter'], 1)
        self.assertEqual(len([event for event in result if event['type'] == 'book']), 1)
        self.assertTrue(any(event.get('reason') == 'generation_change' for event in result))
        self.assertTrue(any(event.get('reason') == 'delta_without_snapshot' for event in result))


if __name__ == '__main__':
    unittest.main()
