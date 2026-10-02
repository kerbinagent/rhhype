"""Synthetic label-only tests; no rolling capture is opened."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import liquidation_delay_observability as obs


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


class FreezeTests(unittest.TestCase):
    def test_draft_and_existing_output_refused_before_store(self):
        plan = dict(schema='liquidation-delay-observability-v1', status='draft_not_runnable',
                    parameters=obs.EXPECTED, output_caps=dict(gzip_per_batch=24576,
                    provenance_per_batch=8192, readout=8192))
        with patch.object(obs.rolling, 'read_json', return_value=plan):
            with self.assertRaisesRegex(ValueError, 'not frozen'):
                obs.run(1)
        plan.update(status='frozen',
            input_validation_plan='reports/experiment-storage/single-venue-inventory-context-ordinary-feed-fix-v1.json',
            input_validation_plan_sha256='hash', store_root='data/rolling/market-research-v1',
            pin_owner=obs.inventory.OWNER,
            output_root='reports/single-venue-research/liquidation-delay-v1',
            batches=[{'index': i, 'chunks': obs.inventory.BATCHES[i]} for i in (1, 2)])
        validation = {'source_pins': [{'path': 'x', 'sha256': 'hash'}]*45}
        with patch.object(Path, 'exists', autospec=True,
                 side_effect=lambda path: path.name == 'liquidation-delay-batch1.json.gz'), \
             patch.object(obs.rolling, 'read_json', side_effect=[plan, validation]), \
             patch.object(obs.rolling, 'digest', return_value='hash'), \
             patch.object(obs, 'sources'):
            with self.assertRaisesRegex(FileExistsError, 'immutable'):
                obs.run(1)


if __name__ == '__main__':
    unittest.main()
