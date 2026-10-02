"""Focused synthetic strict-print, native-cash, unknown-state and stage contracts."""
import copy, gzip, json, tempfile, unittest
from contextlib import nullcontext
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from scripts import single_venue_passive_through as p

NS = p.NS
DECISION = 30 * NS
PROXY = DECISION + 400000000
CLOSE = DECISION + 10400000000


def metadata(assets=('BTC',)):
    return {v: {a: dict(price_tick='0.01', qty_step='0.001', min_qty='0.001',
        min_notional='1', max_qty=None, max_quote='1000000',
        maker_fee_bps='1', taker_fee_bps='2') for a in assets} for v in p.PARAMS['venues']}


def book(t, bid='100', ask='100.01', qty='1000', source=None, snapshot=False, generation='g'):
    return dict(type='book', asset='BTC', venue='lighter', received_ns=t,
        source_ns=t if source is None else source, generation=generation,
        valid=True, clock_valid=True, bids=[[bid, qty]], asks=[[ask, qty]], book_snapshot=snapshot)


def trade(t, *, ident=1, price='99.99', qty='200', buy=False, source=None, generation='g'):
    return dict(type='trade', asset='BTC', venue='lighter', received_ns=t,
        source_ns=t if source is None else source, generation=generation,
        clock_valid=True, trade_id=ident, price=price, qty=qty,
        buy_aggressor=buy, exact_native_print=True)


def invalid(t, scope='book'):
    return dict(type='invalidate', asset='BTC', venue='lighter', received_ns=t,
        generation='g', scope=scope, reason='synthetic')


def begin(m=None):
    s = p.Study(metadata() if m is None else m, 0, 'synthetic', assets=('BTC',))
    s.process_group([book(DECISION)])
    return s


def profile(s, target='100', direction=1):
    return next(x for x in s.rows[0]['profiles'] if x['target'] == target and x['direction'] == direction)


def continue_books(s, until, *, endpoint=None):
    last = s.books['BTC', 'lighter']['received_ns']
    t = last + 500000000
    while t < until:
        s.process_group([book(t)])
        t += 500000000
    s.process_group([book(until, bid='102', ask='102.01') if endpoint is None else endpoint])


def chunks(names, *, positive=True):
    result = []
    for name in names:
        rows = []
        for asset in p.PARAMS['assets']:
            for venue in p.PARAMS['venues']:
                for slot in range(28):
                    profiles = []
                    for target in p.PARAMS['notionals']:
                        for direction in p.PARAMS['directions']:
                            witness = asset == 'BTC' and venue == 'lighter' and target == '100' and direction == 1 and slot < 3
                            profiles.append(dict(target=target, direction=direction,
                                status='complete_conditional_value' if witness else 'no_full_witness_unknown',
                                witness={'trade_id': slot + 1, 'generation': 'g'} if witness else None,
                                net_cash=('1' if positive else '-1') if witness else None,
                                gross_cash='3', fee_cash='1', capital_cash='1',
                                smaller_through_count=0, maximum_base_quantity_unknown=True,
                                maximum_quote_unknown=False))
                    rows.append(dict(chunk=name, asset=asset, venue=venue, slot=slot, profiles=profiles))
        result.append(dict(chunk=name, scheduled_anchors=560, scheduled_profiles=3360, anchors=rows))
    return result


class PassiveThroughTest(unittest.TestCase):
    def test_exact_hook_restores_all_scoped_globals_after_error(self):
        original = (p.ordinary._trade, p.ordinary._common, p.ordinary.MAX_DECODED_BYTES,
                    p.inventory.capture.HARD_BYTES)
        row = dict(venue='lighter', generation='g', receipt_utc_ns=1790944200000000000,
            channel='order_book', payload={'type': 'subscribed/order_book'})
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with p.adapter_configuration():
                self.assertTrue(p.ordinary._common(row)['book_snapshot'])
                raw = dict(type='trade', market_id=1, is_maker_ask=False, trade_id=1,
                    price='100.000000000000000001', size='0.123456789123456789', timestamp=1790944200000)
                e = p.ordinary._trade(dict(row, channel='trade', payload={}), raw, '1', 'BTC', None)
                self.assertEqual(e['price'], raw['price'])
                self.assertEqual(e['qty'], raw['size'])
                self.assertTrue(e['exact_native_print'])
                raise RuntimeError('fixture')
        self.assertEqual(original, (p.ordinary._trade, p.ordinary._common,
            p.ordinary.MAX_DECODED_BYTES, p.inventory.capture.HARD_BYTES))

    def test_one_unique_strict_full_native_print_and_clock_rules(self):
        s = begin()
        s.process_group([book(PROXY), trade(PROXY, qty='200')])
        self.assertIsNone(profile(s)['witness'])
        t = PROXY + 100000000
        events = [trade(t, ident=2, price='100'), trade(t, ident=3, qty='.001'),
            trade(t, ident=4, price='99.990000000000000001'),
            trade(t, ident=5, source=PROXY), trade(t, ident=6, generation='other')]
        s.process_group(events)
        self.assertIsNone(profile(s)['witness'])
        self.assertEqual(profile(s)['smaller_through_count'], 1)
        s.process_group([trade(t + 1, ident=3, qty='200')])
        self.assertIsNone(profile(s)['witness'])
        full = trade(t + 2, ident=7, qty=profile(s, '10000')['quantity'])
        s.process_group([full])
        for target in p.PARAMS['notionals']:
            self.assertEqual(profile(s, target)['witness']['trade_id'], 7)
            self.assertEqual(profile(s, target)['conditional_full_quantity'], profile(s, target)['quantity'])
        self.assertIsNone(profile(s, direction=-1)['witness'])
        s.process_group([trade(t + 3, ident=8, qty='999')])
        self.assertEqual(profile(s)['witness']['trade_id'], 7)
        s = begin()
        s.process_group([book(PROXY)])
        s.process_group([book(PROXY + 500000000)])
        s.process_group([trade(PROXY + 600000001, source=PROXY + 100000000)])
        self.assertIsNone(profile(s)['witness'])
        continue_books(s, DECISION + 10 * NS, endpoint=book(DECISION + 10 * NS))
        s.process_group([trade(DECISION + 10 * NS, ident=99)])
        self.assertEqual(profile(s)['status'], 'no_full_witness_unknown')
        self.assertIsNone(profile(s)['net_cash'])

    def test_three_sizes_exact_native_close_fees_and_earliest_capital(self):
        s = begin()
        s.process_group([book(PROXY)])
        s.process_group([trade(PROXY + 100000000)])
        continue_books(s, CLOSE)
        for target in p.PARAMS['notionals']:
            x = profile(s, target)
            self.assertEqual(x['status'], 'complete_conditional_value')
            E, X = D(x['entry_value']), D(x['exit_value'])
            capital = D(target) * D('.05') * D(10) / 31536000
            fees = E / 10000 + X * 2 / 10000
            self.assertEqual(D(x['fee_cash']), fees)
            self.assertEqual(D(x['capital_cash']), capital)
            self.assertEqual(D(x['net_cash']), X - E - fees - capital)
            self.assertEqual(D(x['stressed_cash']['5']), D(x['net_cash']) - E * 5 / 10000)
            self.assertGreater(X, D(target))  # Exit proceeds have no target cap.
            self.assertEqual(x['exit_observation']['received_ns'], CLOSE)
            self.assertTrue(x['maximum_base_quantity_unknown'])
        self.assertEqual(s.rows[0]['eligibility_ns'], PROXY)
        self.assertIsNone(profile(s, direction=-1)['net_cash'])
        sell = begin()
        sell.process_group([book(PROXY)])
        sell.process_group([trade(PROXY + 1, buy=True, price='100.02')])
        continue_books(sell, CLOSE, endpoint=book(CLOSE, bid='98', ask='98.01'))
        x = profile(sell, direction=-1)
        self.assertEqual(D(x['gross_cash']), D(x['entry_value']) - D(x['exit_value']))

    def test_first_eligible_cross_stale_missing_and_depth_failures_are_final(self):
        s = begin()
        s.process_group([book(PROXY, bid='99', ask='99.01')])
        s.process_group([book(PROXY + 1), trade(PROXY + 1)])
        self.assertEqual(profile(s)['status'], 'placement_crossed_proxy_unknown')
        self.assertIsNone(profile(s)['net_cash'])
        s = begin()
        s.process_group([book(PROXY + 300000000, source=PROXY)])
        s.process_group([book(PROXY + 300000001)])
        self.assertEqual(profile(s)['status'], 'book_path_stale_clock')
        s = begin()
        s.process_group([dict(type='synthetic_clock', received_ns=PROXY + 2000000001)])
        self.assertEqual(profile(s)['status'], 'placement_first_eligible_missing')
        s.process_group([book(PROXY + 2000000002)])
        self.assertEqual(profile(s)['status'], 'placement_first_eligible_missing')
        for endpoint, status in ((book(CLOSE, qty='.001'), 'insufficient_depth'),
                                 (book(CLOSE, source=CLOSE - 300000000), 'book_path_stale_clock')):
            s = begin()
            s.process_group([book(PROXY)])
            s.process_group([trade(PROXY + 1)])
            continue_books(s, CLOSE, endpoint=endpoint)
            s.process_group([book(CLOSE + 1)])
            self.assertEqual(profile(s)['status'], status)
            self.assertIsNotNone(profile(s)['witness'])
            self.assertIsNone(profile(s)['net_cash'])
        s = begin()
        s.process_group([book(PROXY)])
        s.process_group([trade(PROXY + 1)])
        bad = book(CLOSE)
        bad['bids'].append(['99.999', '1'])
        continue_books(s, CLOSE, endpoint=bad)
        self.assertEqual(profile(s)['status'], 'endpoint_native_book_failure')
        s = begin()
        s.process_group([book(PROXY)])
        s.process_group([trade(PROXY + 1)])
        continue_books(s, CLOSE, endpoint=book(CLOSE, source=CLOSE - 1))
        self.assertEqual(profile(s)['status'], 'pending_close')
        s.process_group([book(CLOSE + 2000000001, source=CLOSE - 1)])
        self.assertEqual(profile(s)['status'], 'close_first_eligible_missing')
        self.assertIsNotNone(profile(s)['witness'])

    def test_invalidation_priority_snapshot_gap_and_unknown_nonwitness(self):
        t = PROXY + 1
        for events in ([trade(t), invalid(t)], [invalid(t), trade(t)],
                       [trade(t), invalid(t, 'trade')]):
            s = begin()
            s.process_group([book(PROXY)])
            s.process_group(events)
            self.assertIsNone(profile(s)['witness'])
            self.assertIsNone(profile(s)['net_cash'])
        s = begin()
        s.process_group([book(PROXY)])
        s.process_group([trade(t)])
        s.process_group([invalid(t + 1, 'trade')])
        self.assertEqual(profile(s)['status'], 'pending_close')
        continue_books(s, CLOSE)
        self.assertEqual(profile(s)['status'], 'complete_conditional_value')
        for event, reason in ((book(PROXY + 2, snapshot=True), 'book_path_snapshot_reset'),
                              (book(PROXY + 500000001), 'book_path_interbook_gap')):
            s = begin()
            s.process_group([book(PROXY)])
            s.process_group([trade(t)])
            s.process_group([event])
            self.assertEqual(profile(s)['status'], reason)
            self.assertIsNotNone(profile(s)['witness'])
        s = begin()
        s.process_group([book(PROXY)])
        s.process_group([trade(t, qty='.001')])
        continue_books(s, DECISION + 10 * NS, endpoint=book(DECISION + 10 * NS))
        self.assertEqual(profile(s)['status'], 'smaller_through_only_unknown')
        self.assertIsNone(profile(s)['net_cash'])
        s = begin()
        s.process_group([book(PROXY)])
        s.process_group([trade(t)])
        continue_books(s, CLOSE - 1, endpoint=book(CLOSE - 1))
        s.process_group([book(CLOSE), invalid(CLOSE)])
        self.assertEqual(profile(s)['status'], 'book_path_unresolved')
        self.assertIsNotNone(profile(s)['witness'])
        self.assertIsNone(profile(s)['net_cash'])

    def test_native_bounds_funding_all_calendars_and_witness_failure_gate(self):
        for field, value, reason in (('max_qty', '.5', 'maximum_quantity_reject'),
                                    ('maker_fee_bps', '-1', 'decision_native_or_fee_metadata_failure')):
            m = metadata()
            m['lighter']['BTC'][field] = value
            self.assertEqual(profile(begin(m))['status'], reason)
        m = metadata()
        m['lighter']['BTC']['max_quote'] = '2000'
        self.assertEqual(profile(begin(m), '10000')['status'], 'maximum_quote_reject')
        self.assertTrue(p.funding_crosses(3600 * NS - p.PARAMS['maximum_profile_span_ns']))
        self.assertFalse(p.funding_crosses(3600 * NS - p.PARAMS['maximum_profile_span_ns'] - 1))
        s = p.Study(metadata(p.PARAMS['assets']), 0, 'synthetic')
        s.process_group([dict(type='end', received_ns=600 * NS)])
        r = s.result()
        self.assertEqual((r['scheduled_anchors'], r['scheduled_profiles']), (560, 3360))
        self.assertTrue(all(x['net_cash'] is None for row in r['anchors'] for x in row['profiles']))
        first = chunks(p.FIRST)
        summary = p.summarize(first, stage='first')
        self.assertEqual(len(summary['arms']), 120)
        self.assertTrue(summary['second_stage_open'])
        arm = summary['arms'][0]
        self.assertEqual(arm['chunks'][0]['scheduled'], 28)
        self.assertEqual(arm['chunks'][0]['distinct_witness_count'], 3)
        first[0]['anchors'][1]['profiles'][0]['witness'] = {'trade_id': 1, 'generation': 'g2'}
        identity_summary = p.summarize(first, stage='first')
        self.assertTrue(identity_summary['second_stage_open'])
        identities = identity_summary['arms'][0]['chunks'][0]['distinct_witness_ids']
        self.assertEqual(identities, [dict(generation='g', trade_id=1),
                                     dict(generation='g', trade_id=3),
                                     dict(generation='g2', trade_id=1)])
        broken = first[0]['anchors'][0]['profiles'][0]
        broken.update(status='book_path_unresolved', net_cash=None)
        summary = p.summarize(first, stage='first')
        self.assertFalse(summary['second_stage_open'])
        self.assertEqual(summary['arms'][0]['chunks'][0]['full_witnesses'], 3)
        self.assertEqual(summary['arms'][0]['chunks'][0]['full_witness_close_failures'], 1)
        self.assertIsNone(summary['all_calendar_strategy_cash'])
        final = chunks(p.FIRST + p.SECOND)
        final[-1]['anchors'][0]['profiles'][0]['net_cash'] = '-99'
        self.assertFalse(p.summarize(final, stage='final')['arms'][0]['all_six_gate'])
        with self.assertRaisesRegex(ValueError, 'chunk_identity'):
            p.summarize(chunks(p.SECOND), stage='first')
        with patch.dict(p.PARAMS, max_same_receipt_events=1):
            with self.assertRaisesRegex(ValueError, 'group_cap'):
                begin().process_group([book(PROXY), trade(PROXY)])
        with patch.dict(p.PARAMS, max_profiles_per_chunk=1):
            with self.assertRaisesRegex(ValueError, 'profile_count_cap'):
                begin()

    def test_pipeline_summary_barrier_no_second_decode_on_failure_and_bounded_refusal(self):
        for positive in (False, True):
            fixture = chunks(p.FIRST + p.SECOND, positive=positive)
            records = {str(b): dict(inputs=[dict(chunk=name) for name in names])
                       for b, names in ((1, p.FIRST), (2, p.SECOND))}
            store = type('Store', (), {'locked': lambda self: nullcontext()})()
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                protocol = root / 'plan.json'
                protocol.write_text('{}')
                plan = dict(output_root='out', store_root='store', source_pins=[],
                    frozen_input_identities=dict(snapshot=records))
                calls = []
                def stream(record):
                    calls.append(record['chunk'])
                    if record['chunk'] in p.SECOND:
                        out = root / 'out'
                        seal = json.loads((out / 'first-stage-sha.json').read_bytes())
                        self.assertTrue(seal['second_stage_open'])
                        self.assertEqual(seal['first_stage_summary_sha256'], p.q.digest(out / 'first-stage-summary.json.gz'))
                    return copy.deepcopy(next(c for c in fixture if c['chunk'] == record['chunk']))
                with (patch.object(p, 'ROOT', root), patch.object(p, 'PLAN', protocol),
                        patch.object(p, 'verify', return_value=(plan, {})),
                        patch.object(p.rolling, 'Store', return_value=store),
                        patch.object(p.inventory, 'check_inputs', side_effect=lambda s, v, b: records[str(b)]),
                        patch.object(p, 'stream_chunk', side_effect=stream)):
                    p.run()
                    self.assertEqual(calls, list(p.FIRST + p.SECOND if positive else p.FIRST))
                    out = root / 'out'
                    final = json.loads(gzip.decompress((out / 'summary.json.gz').read_bytes()))
                    self.assertEqual(len(final['arms']), 120)
                    self.assertEqual(final['second_stage_open'], positive)
                    if not positive:
                        self.assertEqual(final['second_stage_status'], 'second_stage_not_opened')
                    self.assertTrue(json.loads((out / 'terminal.json').read_bytes())['success'])
                    self.assertLessEqual(sum((out / name).stat().st_size for name in ('first-stage-summary.json.gz', 'summary.json.gz')), p.CAPS['summary_gzip'])
                    with self.assertRaises(FileExistsError):
                        p.run()
                path = root / 'bounded'
                with self.assertRaisesRegex(ValueError, 'output_byte_cap'):
                    p.publish(path, {'x': 'too large'}, 1)
                with self.assertRaisesRegex(ValueError, 'decoded_output_byte_cap'):
                    p.publish(path, {'x': 'z' * 100}, 1000, compressed=True, decoded_cap=10)
                self.assertFalse(path.exists())
                plan['frozen_input_identities']['snapshot'] = {}
                plan['output_root'] = 'changed-input'
                with (patch.object(p, 'ROOT', root), patch.object(p, 'PLAN', protocol),
                        patch.object(p, 'verify', return_value=(plan, {})),
                        patch.object(p.rolling, 'Store', return_value=store),
                        patch.object(p.inventory, 'check_inputs', side_effect=lambda s, v, b: records[str(b)]),
                        patch.object(p, 'stream_chunk') as reader):
                    with self.assertRaisesRegex(ValueError, 'frozen_input_identities'):
                        p.run()
                    reader.assert_not_called()

    def test_verify_refuses_draft_missing_duplicate_changed_sources_and_parent(self):
        plan = dict(status='frozen', schema='single-venue-passive-through-v1',
            parameters=p.PARAMS, output_caps=p.CAPS, first_stage_chunks=list(p.FIRST),
            conditional_second_stage_chunks=list(p.SECOND),
            output_root='reports/single-venue-research/passive-through-v1',
            store_root='data/rolling/market-research-v1', pin_owner='inventory_context_v1',
            reserved_bytes=4194304, runtime_requirements={'python': '3.13.9', 'decimal_precision': 28},
            source_pins=[], helper_source='scripts/single_venue_queue_ofi.py', helper_source_sha256=p.HELPER_SHA,
            previous='reports/experiment-storage/single-venue-queue-ofi-publication-fix-v1.json', previous_sha256=p.PREVIOUS_SHA,
            input_validation_plan='reports/experiment-storage/single-venue-inventory-context-ordinary-feed-fix-v1.json',
            input_validation_plan_sha256=p.q.VALIDATION_SHA,
            frozen_input_identities=dict(provenance_path=p.INPUT_PROVENANCE,
                provenance_sha256=p.INPUT_PROVENANCE_SHA, snapshot={'1': {}, '2': {}}))
        with patch.object(p.rolling, 'read_json', return_value=plan), patch.object(p.q, 'verify') as parent:
            with self.assertRaisesRegex(ValueError, 'unique_own_test_helper'):
                p.verify()
            plan['source_pins'] = [dict(path=x, sha256='x') for x in
                ('scripts/single_venue_passive_through.py', 'tests/test_single_venue_passive_through.py', 'scripts/single_venue_queue_ofi.py')]
            plan['source_pins'].append(plan['source_pins'][0])
            with self.assertRaisesRegex(ValueError, 'unique_own_test_helper'):
                p.verify()
            plan['source_pins'].pop()
            with patch.object(p.q, 'source_pins', side_effect=ValueError('changed_direct_pin')):
                with self.assertRaisesRegex(ValueError, 'changed_direct_pin'):
                    p.verify()
            with patch.object(p.q, 'source_pins'), patch.object(p.q, 'digest', return_value=p.HELPER_SHA):
                with self.assertRaisesRegex(ValueError, 'previous_plan_changed'):
                    p.verify()
            parent.assert_not_called()
            plan['status'] = 'draft_not_runnable'
            with self.assertRaisesRegex(ValueError, 'not_frozen'):
                p.verify()


if __name__ == '__main__':
    unittest.main()
