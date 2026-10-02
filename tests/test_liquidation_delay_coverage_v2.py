"""Synthetic label-only tests; no rolling capture is opened."""
import json
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import nullcontext

from scripts import liquidation_delay_coverage_v2 as obs


T = 1_790_000_000_000_000_000
SELECTED = {'lighter': {'BTC': '1'}, 'rh_lighter': {'BTC': '1'}}


def raw(trade, order, *, t=T, side=True, version=0, subtype='liquidation'):
    field = 'bid' if side else 'ask'
    return dict(type=subtype, market_id=1, trade_id=trade, trade_id_str=str(trade),
                is_maker_ask=side, timestamp=t//1_000_000,
                **{field+'_id': order, field+'_id_str': str(order), field+'_order_version': version})


def frame(t, trades=(), liquids=(), *, venue='lighter', generation='g1',
          typ='update/trade', quality='wire_ok'):
    return dict(kind='frame', venue=venue, generation=generation,
                receipt_utc_ns=t, channel='trade', market='1',
                annotation=dict(quality=quality), payload=dict(type=typ, channel='trade:1',
                    trades=list(trades), liquidation_trades=list(liquids)))


def control(t, kind, *, venue='lighter', generation='g1'):
    return dict(kind=kind, venue=venue, generation=generation, receipt_utc_ns=t)


def study(*rows, stop=T+10*obs.NS):
    s = obs.LabelStudy(SELECTED, T-obs.NS, stop, 'synthetic')
    s.process(control(T-obs.NS, 'connection_open'))
    for row in rows:
        s.process(row)
    return s.result()


class TimingTests(unittest.TestCase):
    def test_both_clocks_strict_lower_inclusive_upper(self):
        a = raw(1, 10)
        early_source = raw(2, 11, t=T+399_000_000)
        lower_equal = raw(3, 13, t=T+400_000_000)
        upper_equal = raw(4, 14, t=T+2_400_000_000)
        late = raw(5, 15, t=T+2_401_000_000)
        r = study(frame(T, [a], [a]), frame(T+401_000_000, [early_source]),
                  frame(T+402_000_000, [lower_equal]),
                  frame(T+2_400_000_000, [upper_equal]),
                  frame(T+2_401_000_000, [late]))
        self.assertEqual(r['episodes'][0]['qualifying_order_count'], 1)

    def test_history_earlier_and_initial_message_keys(self):
        history = raw(1, 30, t=T-10*obs.NS)
        anchor = raw(2, 40)
        same_message = raw(3, 41)
        r = study(frame(T-obs.NS, [history], typ='subscribed/trade'),
                  frame(T-500_000_000, [history], typ='subscribed/trade'),
                  frame(T, [anchor, same_message], [anchor, same_message]),
                  frame(T+600_000_000, [raw(4, 30, t=T+600_000_000),
                                           raw(5, 41, t=T+600_000_000),
                                           raw(6, 42, t=T+600_000_000),
                                           raw(7, 42, t=T+590_000_000)]))
        self.assertEqual(len(r['episodes']), 1)
        self.assertEqual(r['episodes'][0]['qualifying_order_count'], 1)
        self.assertEqual(r['episodes'][0]['qualifying_orders'][0]['first_source_ns'], T+590_000_000)
        self.assertEqual(r['counts']['duplicate_cross_or_repeat'], 3)

    def test_order_version_side_and_market(self):
        anchor = raw(1, 20, side=False)
        r = study(frame(T, [anchor]), frame(T+500_000_000,
            [raw(2, 20, t=T+500_000_000, side=False, version=1),
             raw(3, 21, t=T+500_000_000, side=True),
             raw(4, 22, t=T+500_000_000, side=False)]))
        self.assertEqual(r['episodes'][0]['qualifying_order_count'], 2)
        self.assertEqual(r['episodes'][0]['side'], False)
        # A later fill cannot rescue an order first seen with an early source.
        r = study(frame(T, [anchor]), frame(T+600_000_000,
            [raw(5, 23, t=T+399_000_000, side=False),
             raw(6, 23, t=T+500_000_000, side=False)]))
        self.assertEqual(r['episodes'][0]['qualifying_order_count'], 0)

    def test_generation_break_and_tail_censor(self):
        rows = [frame(T, [raw(1, 20)]), control(T+500_000_000, 'connection_close'),
                control(T+600_000_000, 'connection_open', generation='g2'),
                frame(T+31*obs.NS, [raw(2, 30, t=T+31*obs.NS)], generation='g2')]
        r = study(*rows, stop=T+32*obs.NS)
        self.assertEqual([x['censor_reason'] for x in r['episodes']],
                         ['connection_close', 'capture_end_before_window'])
        self.assertEqual(r['episodes'][0]['qualifying_order_count'], 0)
        s = obs.LabelStudy(SELECTED, T-obs.NS, T+10*obs.NS, 'synthetic')
        s.process(control(T-obs.NS, 'connection_open'))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            s.process(control(T, 'connection_open'))
        with self.assertRaisesRegex(ValueError, 'envelope'):
            s.process(control(T, 'unknown_kind'))
        with self.assertRaisesRegex(ValueError, 'envelope'):
            s.process(control(T, 'connection_open', venue='hyperliquid'))

    def test_conflict_and_bad_trade_censor_not_book(self):
        a = raw(1, 20)
        bad = raw(2, 21, t=T+500_000_000)
        bad['trade_id_str'] = '999'
        r = study(frame(T, [a]),
                  dict(kind='frame', venue='lighter', generation='g1',
                       receipt_utc_ns=T+200_000_000, channel='order_book'),
                  frame(T+500_000_000, [bad]))
        self.assertEqual(r['episodes'][0]['censor_reason'], 'invalid_trade_evidence')
        self.assertEqual(r['groups'][0]['counts']['invalid_trade_evidence'], 1)
        selected = {'lighter': {'BTC': '1', 'ETH': '0'}, 'rh_lighter': {'BTC': '1'}}
        s = obs.LabelStudy(selected, T-obs.NS, T+10*obs.NS, 'synthetic')
        s.process(control(T-obs.NS, 'connection_open'))
        s.process(frame(T, [a]))
        eth = frame(T+500_000_000, [bad])
        eth['market'] = '0'; eth['payload']['channel'] = 'trade:0'
        s.process(eth)
        self.assertIsNone(s.result()['episodes'][0]['censor_reason'])
        wrong_channel = frame(T+500_000_000, [raw(3, 22, t=T+500_000_000)])
        wrong_channel['channel'] = 'order_book'
        r = study(frame(T, [a]), wrong_channel,
                  frame(T+31*obs.NS, [raw(4, 23, t=T+31*obs.NS)]),
                  stop=T+40*obs.NS)
        self.assertEqual(len(r['episodes']), 1)
        self.assertEqual(r['episodes'][0]['censor_reason'], 'trade_on_wrong_capture_channel')
        self.assertEqual(r['groups'][0]['counts']['suppressed_bad_trade_frames'], 1)

    def test_valid_stale_row_keeps_identity_but_censors_and_quarantines(self):
        anchor = frame(T, [raw(1, 20)])
        stale = frame(T+800_000_000, [raw(2, 30, t=T)])
        during = frame(T+3*obs.NS, [raw(3, 31, t=T+3*obs.NS)])
        after = frame(T+31*obs.NS, [raw(4, 32, t=T+31*obs.NS)])
        later_same_key = frame(T+31*obs.NS+600_000_000,
                               [raw(5, 30, t=T+31*obs.NS+600_000_000)])
        later_new_key = frame(T+31*obs.NS+700_000_000,
                              [raw(6, 33, t=T+31*obs.NS+700_000_000)])
        r = study(anchor, stale, during, after, later_same_key, later_new_key,
                  stop=T+35*obs.NS)
        self.assertEqual(len(r['episodes']), 2)
        self.assertEqual(r['episodes'][0]['censor_reason'], 'valid_stale_trade')
        self.assertEqual(r['episodes'][1]['qualifying_order_count'], 1)
        self.assertEqual(r['groups'][0]['counts']['valid_stale_array_rows'], 1)
        self.assertEqual(r['groups'][0]['counts']['quarantined_liquidation_rows'], 2)

    def test_quarantine_inclusive_end_and_extended_by_new_stale(self):
        t = T + 30*obs.NS
        rows = [frame(T, [raw(1, 20)]),
                frame(T+600_000_000, [raw(2, 21, t=T)]),
                frame(T+2*obs.NS, [raw(3, 22, t=T+1*obs.NS)]),
                frame(T+4_400_000_000, [raw(4, 23, t=T+4_400_000_000)]),
                frame(T+4_401_000_000, [raw(5, 24, t=T+4_401_000_000)]),
                frame(t, [raw(6, 25, t=t)])]
        r = study(*rows, stop=t+3*obs.NS)
        self.assertEqual(len(r['episodes']), 2)
        self.assertEqual(r['groups'][0]['counts']['valid_stale_frames'], 2)
        self.assertEqual(r['groups'][0]['counts']['quarantined_liquidation_rows'], 3)

    def test_stale_ordinary_identity_disqualifies_later_liquidation(self):
        first = frame(T, [raw(1, 20)])
        old_ordinary = frame(T+800_000_000,
                             [raw(2, 30, t=T, subtype='trade')])
        later_anchor = frame(T+31*obs.NS, [raw(3, 40, t=T+31*obs.NS)])
        repeated = frame(T+31*obs.NS+600_000_000,
                         [raw(4, 30, t=T+31*obs.NS+600_000_000)])
        r = study(first, old_ordinary, later_anchor, repeated, stop=T+35*obs.NS)
        self.assertEqual(len(r['episodes']), 2)
        self.assertEqual(r['episodes'][0]['censor_reason'], 'valid_stale_trade')
        self.assertEqual(r['episodes'][1]['qualifying_order_count'], 0)
        self.assertEqual(r['groups'][0]['counts']['valid_stale_array_rows'], 1)

    def test_malformed_stale_identity_remains_fatal(self):
        bad = raw(2, 30, t=T)
        bad['bid_id_str'] = 'different'
        r = study(frame(T, [raw(1, 20)]), frame(T+800_000_000, [bad]),
                  frame(T+31*obs.NS, [raw(3, 40, t=T+31*obs.NS)]),
                  stop=T+35*obs.NS)
        self.assertEqual(r['episodes'][0]['censor_reason'], 'invalid_trade_evidence')
        self.assertEqual(len(r['episodes']), 1)

    def test_future_and_regressed_source_remain_fatal(self):
        future = study(frame(T, [raw(1, 20)]),
                       frame(T+500_000_000, [raw(2, 21, t=T+501_000_000)]))
        self.assertEqual(future['episodes'][0]['censor_reason'], 'invalid_trade_evidence')
        regressed = study(frame(T, [raw(1, 20)]),
                          frame(T+1_500_000_000, [raw(2, 21, t=T+1_500_000_000)]),
                          frame(T+2*obs.NS, [raw(3, 22, t=T+1*obs.NS)]))
        self.assertEqual(regressed['episodes'][0]['censor_reason'], 'invalid_trade_evidence')
        self.assertEqual(regressed['groups'][0]['counts'].get('valid_stale_frames', 0), 0)


class FreezeTests(unittest.TestCase):
    def test_draft_refused_before_raw_or_store(self):
        draft = dict(schema='liquidation-delay-coverage-v2', status='offline_implementation_only')
        with patch.object(obs.rolling, 'digest', return_value='a'*64), \
             patch.object(obs.rolling, 'read_json', return_value=draft), \
             patch.object(obs.rolling, 'Store', side_effect=AssertionError('store opened')):
            with self.assertRaisesRegex(ValueError, 'not frozen'):
                obs.frozen('a'*64)

    def test_calendar_and_unavailable_projection(self):
        self.assertEqual(obs.BATCHES[4], ['chunk-000031', 'chunk-000032', 'chunk-000033'])
        self.assertEqual(obs.BATCHES[5], ['chunk-000037', 'chunk-000038', 'chunk-000039'])
        projection = obs.rolling.read_json(obs.PROJECTION, 65536)
        self.assertEqual(len(projection['inputs']), 18)
        self.assertEqual([x['chunk'] for x in projection['inputs'] if not x['available']],
                         ['chunk-000033', 'chunk-000039'])

    def test_missing_run_hash_does_not_enter_supervisor(self):
        with patch.object(obs, 'supervise', side_effect=AssertionError('run entered')):
            with patch('sys.argv', ['coverage', '--run']):
                with self.assertRaisesRegex(ValueError, 'exact --plan-sha'):
                    obs.main()

    def test_unavailable_chunk_is_unknown_in_all_twenty_cells(self):
        rows = [dict(chunk=n, available=n != 'chunk-000033',
                     state='sealed_complete' if n != 'chunk-000033' else 'sealed_failed',
                     seal_sha256='x', failure='failed') for n in obs.BATCHES[4]]
        class FakeStore:
            def locked(self):
                return nullcontext()
        def fake_stream(row):
            return dict(chunk=row['chunk'], available=True, episodes=[], groups=[
                dict(asset=a, venue=v, counts={'complete_episodes': 1})
                for a in obs.rolling.ASSETS for v in ('lighter', 'rh_lighter')])
        plan = dict(source_pins=[], input_identity_projection={'sha256': 'p'})
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(obs, 'OUT', Path(directory)), \
             patch.object(obs.rolling, 'Store', return_value=FakeStore()), \
             patch.object(obs, 'check_inputs', return_value=rows), \
             patch.object(obs, 'stream', side_effect=fake_stream) as streamed, \
             patch.object(obs, 'frozen', return_value=(plan, {})), \
             patch.object(obs.rolling, 'digest', return_value='h'):
            result = obs.run_batch(4, 'h', plan, {})
            report = json.loads(gzip.decompress(
                (Path(directory)/'liquidation-coverage-batch4.json.gz').read_bytes()))
            self.assertEqual(result['unavailable_chunks'], 1)
            self.assertEqual(result['state'], 'partial')
            self.assertEqual(streamed.call_count, 2)
            self.assertEqual(report['chunks'][2]['chunk'], 'chunk-000033')
            self.assertFalse(report['chunks'][2]['available'])
            self.assertEqual(len(report['groups']), 20)
            self.assertTrue(all(x['unavailable_chunks'] == 1 and
                                x['counts']['complete_episodes'] == 2 for x in report['groups']))

    def test_supervisor_preserves_all_six_after_failure_and_refuses_rerun(self):
        def batch_result(i, *_args):
            if i == 2:
                raise ValueError('synthetic failure')
            return dict(batch=i, state='complete')
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(obs, 'OUT', Path(directory)), \
             patch.object(obs, 'frozen', return_value=({}, {})), \
             patch.object(obs, 'run_batch', side_effect=batch_result), \
             patch.object(obs.signal, 'setitimer'):
            receipt = obs.supervise('h')
            self.assertEqual([x['batch'] for x in receipt['batches']], list(range(1, 7)))
            self.assertEqual(receipt['batches'][1]['state'], 'failed')
            self.assertEqual(len(receipt['batches'][1]['groups']), 20)
            self.assertTrue(all(x['counts'] is None for x in receipt['batches'][1]['groups']))
            self.assertEqual(receipt['batches'][5]['state'], 'complete')
            self.assertTrue((Path(directory)/'run-receipt.json').exists())
            with self.assertRaisesRegex(FileExistsError, 'existing batch output'):
                obs.supervise('h')


if __name__ == '__main__':
    unittest.main()
