"""Offline adversarial contracts for the public quote universe screen."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import passive_universe_screen as screen


def fixture():
    market = {'asset': 'NVDA', 'rh_market': '15', 'hl_market': 'xyz:NVDA',
              'rh_price_tick': '.01', 'rh_size_step': '.001', 'hl_size_step': '.01',
              'hl_size_decimals': 2, 'common_step': '.01', 'rh_min_qty': '.01',
              'rh_min_notional': '10', 'rh_max_quote': '1000000',
              'rh_maker_fee_bps': '1', 'hl_taker_fee_bps': '.9', 'min_24h_volume': '2000000'}
    row = {'asset': 'NVDA', 'round': 0, 'hl_started_ns': 2_000_000_000,
           'hl_received_ns': 2_100_000_000,
           'rh_ticker': {'source_ns': 1_900_000_000, 'received_ns': 1_950_000_000,
                         'payload': {'ticker': {'s': 'NVDA', 'b': {'price': '100', 'size': '1'},
                                               'a': {'price': '101', 'size': '1'}}}},
           'hl_book': {'coin': 'xyz:NVDA', 'time': 2050,
                       'levels': [[{'px': '100', 'sz': '5'}, {'px': '99', 'sz': '100'}],
                                  [{'px': '101', 'sz': '100'}]]}}
    return row, market


class ScreenTests(unittest.TestCase):
    def test_quantity_depth_own_notionals_and_separate_allowances(self):
        row, market = fixture()
        result = screen.score(row, market, 1000)
        self.assertTrue(result['valid'], result)
        self.assertEqual(result['quantity'], '9.90')
        # 5*100 + 4.9*99 = 985.1; ask = 9.9*101 = 999.9.
        self.assertEqual(screen.dec(result['hl_sell_notional']), screen.dec('985.1'))
        fees = screen.dec('1989.9') * screen.dec('.0001') + screen.dec('1985') * screen.dec('.00009')
        self.assertEqual(screen.dec(result['modeled_fill_fees']), fees)
        self.assertEqual(screen.dec(result['after_target_stress']), screen.dec(result['fee_only_margin']) - screen.dec('.1') - screen.dec('.495'))
        # Displayed RH quantity < cycle quantity stays descriptive, not a fill claim.
        self.assertLess(screen.dec(result['rh_bid_size']), screen.dec(result['quantity']))

    def test_future_stale_missing_crossed_offgrid_depth_rejected(self):
        base, market = fixture()
        changes = [
            (lambda r: r['rh_ticker'].update(received_ns=2_010_000_000), 'future_ticker_selection'),
            (lambda r: r['rh_ticker'].update(source_ns=1), 'stale_source_or_receipt'),
            (lambda r: r['rh_ticker'].update(source_ns=2_000_000_000), 'source_ahead_of_receipt'),
            (lambda r: r.update(rh_ticker=None), 'missing_rh_ticker'),
            (lambda r: r['rh_ticker']['payload']['ticker']['b'].update(price='102'), 'crossed_rh'),
            (lambda r: r['hl_book']['levels'][1][0].update(sz='.01'), 'insufficient_hl_depth'),
            (lambda r: r['hl_book']['levels'][1][0].update(px='101.12345'), 'hl_quote_off_grid'),
            (lambda r: r['hl_book'].update(time=2200), 'source_ahead_of_receipt'),
        ]
        for mutation, reason in changes:
            row = copy.deepcopy(base)
            mutation(row)
            with self.subTest(reason=reason):
                self.assertEqual(screen.score(row, market, 1000).get('reason'), reason)

    def test_no_upsize_and_both_venues_minimums(self):
        row, market = fixture()
        market['common_step'] = '10'
        self.assertEqual(screen.score(row, market, 100).get('reason'), 'quantity_below_minimum')
        row, market = fixture()
        market['rh_min_qty'] = '20'
        self.assertEqual(screen.score(row, market, 1000).get('reason'), 'quantity_below_minimum')

    def test_ranking_requires_three_valid_rounds_and_median(self):
        row, market = fixture()
        scored = screen.score(row, market, 1000)
        rows = [{'asset': 'NVDA', 'scores': [scored]} for _ in range(2)]
        self.assertEqual(screen.summarize(rows, [market])['ranking'], [])
        rows.append({'asset': 'NVDA', 'scores': [dict(scored, after_target_stress='1000000')]})
        ranking = screen.summarize(rows, [market])['ranking']
        self.assertEqual(ranking[0]['median_after_target_stress'], scored['after_target_stress'])

    def test_snapshot_old_updates_and_duplicate_flow_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = screen.Feed([fixture()[1]], screen.Store(tmp))
            trade = {'type': 'trade', 'market_id': 15, 'trade_id': 7, 'is_maker_ask': False,
                     'timestamp': 2000, 'price': '100', 'size': '2'}
            feed.process({'type': 'subscribed/trade', 'channel': 'trade:15', 'trades': [trade]}, 2_001_000_000)
            feed.process({'type': 'update/trade', 'channel': 'trade:15', 'trades': [trade]}, 2_010_000_000)
            self.assertFalse(feed.ids)
            trade['timestamp'] = 2005
            update = {'type': 'update/trade', 'channel': 'trade:15', 'trades': [trade]}
            feed.process(update, 2_010_000_000)
            feed.process(update, 2_011_000_000)
            self.assertEqual(feed.flow[(-1, 'NVDA')]['sell_count'], 1)
            self.assertEqual(feed.flow[(-1, 'NVDA')]['sell_notional'], 200)
            self.assertEqual(feed.counters['duplicate_trades'], 1)

    def test_metadata_gate_volume_multiplier_and_fee(self):
        # Existing frozen pilot metadata is offline test input only, never screen input.
        base = screen.ROOT / 'reports/rh-passive-exit-v1/metadata'
        rh = json.loads((base / 'rh_order_book_details.json').read_bytes())
        native = json.loads((base / 'hl_meta_native.json').read_bytes())
        xyz = json.loads((base / 'hl_meta_xyz.json').read_bytes())
        nctx = [{'dayNtlVlm': '2000000', 'oraclePx': '1'} for _ in native['universe']]
        xctx = [{'dayNtlVlm': '2000000', 'oraclePx': '228'} for _ in xyz['universe']]
        response = {'rh_order_book_details': rh, 'hl_meta_native': [native, nctx], 'hl_meta_xyz': [xyz, xctx]}
        plan = {'pairs': [{'asset': a, 'other': {'venue': 'rh_lighter', 'market': m},
                           'hl': {'venue': 'hyperliquid', 'market': h}}
                          for a, m, h in [('NVDA', 15, 'xyz:NVDA'), ('SPCX', 18, 'xyz:SPCX')]]}
        selected = screen.select(plan, response)
        self.assertEqual([x['asset'] for x in selected['selected']], ['NVDA'])
        self.assertEqual(selected['selected'][0]['hl_taker_fee_bps'], '0.900')
        self.assertEqual(selected['denominator'], 2)
        r = next(r for r in rh['order_book_details'] if r['symbol'] == 'NVDA')
        r['daily_quote_token_volume'] = '999999'
        self.assertFalse(screen.select(plan, response)['selected'])
        r['daily_quote_token_volume'] = '2000000'
        r['multiplier'] = '2'
        self.assertFalse(screen.select(plan, response)['selected'])

    def test_cap_never_writes_partial_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = screen.Store(tmp)
            store.used = screen.RAW_CAP - 2
            with self.assertRaises(screen.CapReached):
                store.write('quotes.jsonl', {'key': 'value'}, raw=True, append=True)
            self.assertFalse((Path(tmp) / 'quotes.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
