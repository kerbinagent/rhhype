"""Synthetic contract tests; never open old or rolling market archives."""
from decimal import Decimal as D
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import single_venue_inventory_context as context

NS = context.NS
START = 1000*NS
META = {v: {a: dict(price_tick='.01', qty_step='.01', min_qty='.01',
    min_notional='1', taker_fee_bps='1') for a in context.rolling.ASSETS}
    for v in context.VS}


def book(t, source=None, mid='100', generation='g', venue='lighter'):
    price = D(mid)
    return dict(type='book', asset='BTC', venue=venue, generation=generation,
        received_ns=START+int(D(str(t))*NS), source_ns=START+int(D(str(t if source is None else source))*NS),
        sequence=int(D(str(t))*1000)+1, valid=True, clock_valid=True,
        bids=[[float(price-D('.01')), 10]], asks=[[float(price+D('.01')), 10]])


def trade(t, cls='adding', source=None, ident=1, qty='1', buy=True, generation='g'):
    return dict(type='trade', asset='BTC', venue='lighter', generation=generation,
        received_ns=START+int(D(str(t))*NS), source_ns=START+int(D(str(t if source is None else source))*NS),
        clock_valid=True, trade_id=ident, transaction_time=ident, chronology_valid=True,
        inventory_class=cls, inventory_reason='missing_position' if cls == 'unknown' else None,
        exact_qty=D(qty), exact_price=D('100'), buy_aggressor=buy, flag='absent_unknown',
        position_field='null' if cls == 'unknown' else 'valid_numeric_string')


def send(study, *items):
    study.process_group(list(items))


def initial(study, cls='adding'):
    send(study, book(0))
    send(study, book(20))
    send(study, trade(29, cls, ident=29))
    send(study, book(30))


def terminal(study, t=600):
    send(study, dict(type='end', received_ns=START+int(D(str(t))*NS)))
    return study.result()


def raw(ident, p, qty='1', transaction=None, order='o'):
    return dict(type='trade', trade_id_str=str(ident), timestamp=1000000,
        transaction_time=1_000_000_000+ident if transaction is None else transaction,
        size=qty, price='100.00', is_maker_ask=True, bid_id_str=order,
        taker_position_size_before=p)


def enrich(raw_rows):
    row = dict(venue='lighter', generation='g', receipt_utc_ns=START+NS, payload={'trades':raw_rows})
    original = lambda row, r, market, asset, hedge: dict(
        trade_id=int(r['trade_id_str']), source_ns=START, clock_valid=True)
    adapter = context.MessageEnricher(original, META)
    return [adapter(row, r, '1', 'BTC', None) for r in raw_rows]


def feature(t, cls, c0='1', ret='0', flow='0', status='matched'):
    return dict(id=t, anchor_ns=START+t*NS, **{'class':cls}, features_usable=True,
        aggressor=1, c0_bps=D(c0), signed_return_bps=D(ret), signed_flow=D(flow),
        profile={'status':status})


class InventoryContextTests(unittest.TestCase):
    def test_exact_calendar_received_group_latest_trade_and_no_future_repair(self):
        study = context.ContextStudy(META, START, assets=['BTC'])
        send(study, book(0)); send(study, book(20))
        # Reverse observed order and same source: chronology wins, including
        # the most recent unknown classification. Every equal-time event is in.
        latest = trade(30, 'unknown', ident=4)
        send(study, latest, trade(30, 'adding', ident=3), book(30))
        row = study.rows[0]
        self.assertEqual(row['class'], 'unknown')
        self.assertEqual(row['flag'], 'absent_unknown')
        self.assertTrue(row['features_usable'])
        self.assertEqual(row['profile']['direction'], -1)
        # At60 no fresh events exist. A callback61 must not move/repair60.
        send(study, trade(61, 'reducing', ident=61), book(61))
        at60 = next(r for r in study.rows if r['anchor_ns'] == START+60*NS and r['venue']=='lighter')
        self.assertEqual(at60['anchor_failure'], 'decision_book_unusable')
        self.assertIsNone(at60['profile'])
        result = terminal(study)
        self.assertEqual(len(result['anchors']), 38)
        self.assertEqual(sum(r['counts']['scheduled'] for r in result['rows']), 38)
        self.assertEqual(row['profile']['status'], 'missing_first_eligible')
        ambiguous = context.ContextStudy(META, START, assets=['BTC'])
        send(ambiguous, book(0)); send(ambiguous, book(20))
        broken = trade(30, 'unknown', ident=2)
        broken.update(transaction_time=0, chronology_valid=False)
        send(ambiguous, trade(30, 'adding', ident=1), broken, book(30))
        self.assertEqual(ambiguous.rows[0]['anchor_failure'], 'latest_source_chronology_unknown')
        self.assertIsNone(ambiguous.rows[0]['profile'])

    def test_exact_per_fill_reverse_array_flatten_reversal_and_semantic_unknown(self):
        rows = enrich([raw(3, '-1'), raw(2, '-2'), raw(1, '-3')])
        self.assertEqual([r['inventory_class'] for r in rows], ['reducing']*3)
        self.assertEqual(rows[0]['flag'], 'absent_unknown')
        one = enrich([raw(1, '0', qty='.10')])[0]
        self.assertEqual(one['exact_qty'], D('.10'))
        self.assertEqual(one['inventory_class'], 'adding')
        self.assertEqual(enrich([raw(1, '-.50')])[0]['inventory_reason'], 'reversal')
        bad = enrich([raw(2, '-1'), raw(1, '-3')])
        self.assertEqual([r['inventory_reason'] for r in bad], ['message_order_arithmetic_failure']*2)
        self.assertEqual(enrich([raw(1, None)])[0]['inventory_class'], 'unknown')
        self.assertEqual(enrich([raw(1, '-1', qty='.001')])[0]['inventory_class'], 'unknown')
        flag = raw(1, '-1'); flag['taker_position_sign_changed'] = True
        self.assertEqual(enrich([flag])[0]['inventory_class'], 'reducing')
        # Exact signed arithmetic, not binary floating point, distinguishes
        # these values. A malformed string must never become explicit zero.
        self.assertEqual(context.inventory_class(D('-.100000000000000003'), D('.100000000000000003'))[0], 'reducing')
        self.assertEqual(enrich([raw(1, 'NaN')])[0]['inventory_class'], 'unknown')
        missing_position = enrich([raw(3, None)])[0]
        self.assertEqual(missing_position['transaction_time'], 1_000_000_003)
        self.assertTrue(missing_position['chronology_valid'])
        self.assertEqual(missing_position['position_field'], 'null')
        flag = raw(1, '-1'); flag['taker_position_sign_changed'] = 'true'
        result = enrich([flag])[0]
        self.assertEqual(result['inventory_class'], 'reducing')
        self.assertEqual(result['flag'], 'malformed_unknown')
        first = raw(1, '-1')
        original = lambda row, r, market, asset, hedge: dict(trade_id=int(r['trade_id_str']))
        adapter = context.MessageEnricher(original, META)
        for generation in ('g1', 'g2'):
            message = dict(venue='lighter', generation=generation, receipt_utc_ns=START+NS,
                           payload={'trades':[first]})
            self.assertEqual(adapter(message, first, '1', 'BTC', None)['inventory_class'], 'reducing')

    def test_matching_decision_only_tie_missing_controls_reuse_and_calipers(self):
        older = feature(30, 'adding', status='insufficient_depth')
        newer = feature(60, 'adding', status='matched')
        reducing = feature(90, 'reducing')
        chosen, reason = context.select_control([newer, older], reducing)
        self.assertIs(chosen, older); self.assertEqual(reason, 'selected')
        older['profile']['status'] = 'unresolved_at_end'
        self.assertIs(context.select_control([newer, older], reducing)[0], older)
        self.assertIs(context.select_control([older], feature(120, 'reducing'))[0], older)
        self.assertIsNone(context.select_control([older], feature(240, 'reducing'))[0])
        self.assertIsNone(context.select_control([older], feature(90, 'reducing', c0='2.01'))[0])
        self.assertIsNone(context.select_control([older], feature(90, 'reducing', ret='2.01'))[0])
        self.assertIsNone(context.select_control([older], feature(90, 'reducing', flow='.251'))[0])
        reducing['features_usable'] = False
        self.assertEqual(context.select_control([older], reducing)[1], 'reducing_features_unusable')
        # An actual study selects missing earlier profiles and reports them.
        study = context.ContextStudy(META, START, assets=['BTC']); initial(study)
        send(study, book(50)); send(study, trade(59, 'reducing', ident=59)); send(study, book(60))
        row = next(r for r in study.rows if r['anchor_ns']==START+60*NS and r['venue']=='lighter')
        self.assertEqual(row['control_id'], study.rows[0]['id'])
        send(study, book(80)); send(study, trade(89, 'reducing', ident=89)); send(study, book(90))
        result = terminal(study)
        summary = next(r for r in result['rows'] if r['venue']=='lighter')
        self.assertEqual(summary['distinct_selected_controls'], 1)
        self.assertEqual(summary['reused_control_selections'], 1)
        self.assertEqual(summary['complete_matched_pairs'], 0)
        self.assertEqual(row['control_status'], 'missing_first_eligible')

    def test_delays_actual_fees_stress_cap_first_failure_and_funding_boundary(self):
        profiles = context.InventoryProfiles(META)
        profiles.process(book(30)); row = profiles.request('BTC', 'lighter', 1, START+30*NS, 'adding')
        profiles.process(book(30.4, source=30.39))
        self.assertEqual(row['status'], 'pending_entry')
        profiles.process(book(30.5, source=30.4))
        self.assertEqual(row['status'], 'pending_exit')
        self.assertEqual(row['due_ns'], START+int(D('40.9')*NS))
        profiles.process(book(40.9, mid='100.10'))
        self.assertEqual(row['status'], 'matched')
        entry, exit_value = D(row['entry']['value']), D(row['exit']['value'])
        self.assertEqual(row['fee_cash'], (entry+exit_value)/10000)
        self.assertEqual(row['net_quote_bps'], (exit_value-entry-row['fee_cash'])/entry*10000)
        self.assertEqual(row['net_after_extra_bps']['5'], row['net_quote_bps']-5)
        self.assertNotIn('reference_bps', row)
        c0, failure = context.immediate_cost(book(30), META['lighter']['BTC'], 1)
        self.assertIsNone(failure); self.assertGreater(c0, D('3.99'))
        short_c0, _ = context.immediate_cost(book(30), META['lighter']['BTC'], -1)
        self.assertGreater(short_c0, c0)
        self.assertEqual(short_c0/c0, D('100.01')/D('99.99'))
        cap = context.InventoryProfiles(META); cap.process(book(30))
        failed = cap.request('BTC', 'lighter', 1, START+30*NS, 'adding')
        cap.process(book(30.4, mid='110'))
        self.assertEqual(failed['status'], 'entry_quote_above_cap')
        cap.process(book(30.5)); self.assertEqual(failed['status'], 'entry_quote_above_cap')
        self.assertTrue(context.funding_crosses(3600*NS-14_800_000_000))
        self.assertFalse(context.funding_crosses(3600*NS-14_800_000_001))
        at_hour = context.ContextStudy(META, 3570*NS, assets=['BTC'])
        at_hour.anchor(3590*NS)
        self.assertEqual(at_hour.rows[0]['anchor_failure'], 'funding_boundary_unknown')

    def test_prior_source_tolerance_history_unknown_profiles_and_lifecycle(self):
        study = context.ContextStudy(META, START, assets=['BTC'])
        send(study, book(0)); send(study, book(19.9, source=19.7))
        send(study, trade(29, 'reducing', ident=29)); send(study, book(30))
        self.assertEqual(study.rows[0]['feature_failure'], 'missing_or_interrupted_prior_book')
        self.assertIsNotNone(study.rows[0]['profile'])
        fresh = context.ContextStudy(META, START, assets=['BTC']); initial(fresh)
        self.assertEqual(len(fresh.earlier['BTC','lighter']), 1)
        send(fresh, dict(type='invalidate', asset='BTC', venue='lighter', received_ns=START+31*NS, reason='gap'))
        self.assertEqual(fresh.earlier['BTC','lighter'], [])
        self.assertEqual(fresh.rows[0]['profile']['status'], 'invalidated')
        send(fresh, book(50, generation='new'))
        send(fresh, trade(59, 'reducing', ident=59, generation='new'))
        send(fresh, book(60, generation='new'))
        row = next(r for r in fresh.rows if r['anchor_ns']==START+60*NS and r['venue']=='lighter')
        self.assertIsNone(row['control_id'])
        # A generation transition also resets controls and pending local quotes.
        send(fresh, book(61, generation='third'))
        self.assertEqual(row['profile']['status'], 'invalidated')
        self.assertEqual(fresh.earlier['BTC','lighter'], [])
        send(fresh, dict(type='control', received_ns=START+62*NS))
        self.assertEqual(terminal(fresh)['non_market_events'], {'control':1})

    def test_roles_pins_parameter_contract_adapter_restore_and_immutable_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            store = context.rolling.Store(Path(directory)/'store'); store.initialize('a'*64)
            plan = dict(schema='single-venue-inventory-context-v1', pin_owner=context.OWNER,
                store_root='data/rolling/market-research-v1', parameters=context.PARAMS,
                output_caps=dict(gzip_per_batch=context.MAX_OUTPUT, provenance_per_batch=context.MAX_PROVENANCE, readout_per_batch=16384),
                batches=[dict(index=1, chunks=context.BATCHES[1])],
                store_identity_sha256=context.rolling.digest(store.root/'identity.json'), capture_parent_plan_sha256='a'*64)
            for state, role, pins in [('collecting','exploratory',[context.OWNER]),
                    ('sealed_complete','reserved_validation',[context.OWNER]), ('sealed_complete','exploratory',[])]:
                with store.locked():
                    index = store.index()
                    index['chunks']['chunk-000001'] = dict(state=state, role=role, pins=pins)
                    store.write('index.json', index, context.rolling.INDEX_BYTES)
                    with self.assertRaisesRegex(ValueError, 'already pinned'):
                        context.check_inputs(store, plan, 1)
            bad = dict(plan, parameters={})
            with self.assertRaisesRegex(ValueError, 'parameters differ'):
                context.check_inputs(store, bad, 1)
            path = Path(directory)/'immutable'; context.publish(path, b'first')
            with self.assertRaises(FileExistsError):
                context.publish(path, b'second')
            self.assertEqual(path.read_bytes(), b'first')
        original = context.events.MAX_DECODED_BYTES
        with context.adapter_configuration():
            self.assertEqual(context.events.MAX_DECODED_BYTES, 1024**3)
        self.assertEqual(context.events.MAX_DECODED_BYTES, original)


if __name__ == '__main__':
    unittest.main()
