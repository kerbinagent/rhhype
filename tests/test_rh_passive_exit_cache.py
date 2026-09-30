"""Event-scoped full-depth parse sharing preserves read-only book semantics."""
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
import unittest

from scripts import rh_maker_model, rh_maker_sell_model
from scripts.rh_maker_config import policy_metadata
from scripts.rh_maker_engine import Book
from scripts.rh_maker_sell_model import RhMakerSellModel
from scripts.rh_passive_exit_engine import PassiveExitBranch, POLICY_HOLDS
from scripts.rh_passive_exit_cache import cached_event_parses
from scripts.rh_maker_engine import Config


NS = 1_000_000_000
START = 1_790_640_000 * NS
METADATA = Path(__file__).resolve().parents[1] / 'reports/rh-small-maker-v1/metadata'


def book(venue='rh_lighter', *, received=START, asks=None):
    return {'type': 'book', 'venue': venue, 'asset': 'BTC',
            'generation': f'{venue}:one', 'received_ns': received,
            'source_ns': received, 'valid': True, 'clock_valid': True,
            'bids': [[100, 15], [99, 10]],
            'asks': asks if asks is not None else [[101, 15], [102, 10]]}


class CachedEventParseTests(unittest.TestCase):
    def test_engine_book_is_immutable_and_economically_identical(self):
        event = book()
        baseline = Book.parse(event)
        descriptor = Book.__dict__['parse']
        with cached_event_parses() as (stats, next_event):
            next_event()
            first, second = Book.parse(event), Book.parse(event)
            self.assertIs(first, second)
            self.assertEqual(first.walk('buy', Decimal('16')),
                             baseline.walk('buy', Decimal('16')))
            self.assertEqual(first.mid(), baseline.mid())
            self.assertEqual(first.bids, tuple(baseline.bids))
            with self.assertRaises(FrozenInstanceError):
                first.asks = ()
            with self.assertRaises(TypeError):
                first.asks[0] = (Decimal(1), Decimal(1))
            self.assertEqual((stats['book_calls'], stats['book_hits'],
                              stats['book_misses']), (2, 1, 1))
        self.assertIs(Book.__dict__['parse'], descriptor)

    def test_model_alias_shared_across_tiers_and_reset_for_reused_event(self):
        event = book()
        baseline = rh_maker_model._parse_book(event)
        model_parser = rh_maker_model._parse_book
        sell_alias = rh_maker_sell_model._parse_book
        with cached_event_parses() as (stats, next_event):
            next_event()
            first = rh_maker_model._parse_book(event)
            second = rh_maker_sell_model._parse_book(event)
            self.assertIs(first, second)
            self.assertEqual({**first, 'bids': list(first['bids']),
                              'asks': list(first['asks'])}, baseline)
            with self.assertRaises(TypeError):
                first['bids'] = ()
            with self.assertRaises(TypeError):
                first['bids'][0] = (1.0, 1.0)
            event['asks'] = [[103, 15], [104, 10]]
            next_event()
            changed = rh_maker_model._parse_book(event)
            self.assertIsNot(changed, first)
            self.assertEqual(changed['asks'][0][0], 103.0)
            self.assertEqual((stats['model_calls'], stats['model_hits'],
                              stats['model_misses']), (3, 1, 2))
        self.assertIs(rh_maker_model._parse_book, model_parser)
        self.assertIs(rh_maker_sell_model._parse_book, sell_alias)

    def test_invalid_input_preserves_per_consumer_validation(self):
        event = book(asks=[[99, 15], [102, 10]])
        with cached_event_parses() as (stats, next_event):
            next_event()
            for _ in range(2):
                with self.assertRaises(ValueError):
                    Book.parse(event)
                with self.assertRaises(ValueError):
                    rh_maker_model._parse_book(event)
            self.assertEqual(stats['book_misses'], 0)
            self.assertEqual(stats['model_misses'], 0)

    def test_two_sell_models_keep_independent_state_with_shared_book(self):
        events = [book(), book('hyperliquid', received=START + NS),
                  book(received=START + 2 * NS, asks=[[101.5, 15], [102, 10]])]
        base = {tier: RhMakerSellModel(policy_metadata(METADATA, tier), START)
                for tier in ('standard', 'premium')}
        cached = {tier: RhMakerSellModel(policy_metadata(METADATA, tier), START)
                  for tier in ('standard', 'premium')}
        for event in events:
            for model in base.values():
                model.consume(event)
        with cached_event_parses() as (stats, next_event):
            for event in events:
                next_event()
                for model in cached.values():
                    model.consume(event)
            self.assertEqual(stats['model_misses'], len(events))
            self.assertEqual(stats['model_hits'], len(events))
            for tier in base:
                self.assertEqual(cached[tier].snapshot(), base[tier].snapshot())
            self.assertIs(cached['standard'].books[('rh_lighter', 'BTC')],
                          cached['premium'].books[('rh_lighter', 'BTC')])
            self.assertIsNot(cached['standard'].books, cached['premium'].books)

    def test_passive_branch_processing_matches_uncached(self):
        events = [book(), book('hyperliquid', received=START + NS),
                  book(received=START + 2 * NS, asks=[[101.5, 15], [102, 10]])]
        metadata = policy_metadata(METADATA, 'standard')['BTC']
        baseline, cached = [], []
        for exit_policy, hold in POLICY_HOLDS.items():
            config = Config('BTC', Decimal(1000), 'fixed_best',
                            tier='standard', hold_ns=hold)
            baseline.append(PassiveExitBranch(config, metadata,
                                              exit_policy=exit_policy))
            cached.append(PassiveExitBranch(config, metadata,
                                            exit_policy=exit_policy))
        for event in events:
            for branch in baseline:
                branch.process(event)
        with cached_event_parses() as (stats, next_event):
            for event in events:
                next_event()
                for branch in cached:
                    branch.process(event)
            self.assertEqual(stats['book_misses'], len(events))
            self.assertEqual(stats['book_hits'], len(events) * (len(cached) - 1))
            for original, shared in zip(baseline, cached):
                self.assertEqual(shared.summary(), original.summary())


if __name__ == '__main__':
    unittest.main()
