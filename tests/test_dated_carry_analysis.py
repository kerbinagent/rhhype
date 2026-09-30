import copy
from fractions import Fraction
import json
import unittest

from scripts import dated_carry_analysis as dc


T0 = 1790772000


def fixture():
    common = dict(base_currency='BTC', quote_currency='USDC', instrument_type='linear',
                  is_active=True, state='open', price_index='btc_usdc', index_id=1000004,
                  contract_size=0.1, min_trade_amount=0.1, tick_size=0.1, tick_size_steps=[])
    spot = dict(common, kind='spot', instrument_name='BTC_USDC', taker_commission=0.0005)
    future = dict(common, kind='future', instrument_name='BTC_USDC-9OCT26',
                  settlement_currency='USDC', settlement_period='week',
                  expiration_timestamp=(T0+8*86400)*1000, taker_commission=0.00035)
    config = {'t0_utc': T0, 'expiry_utc': T0+8*86400,
              'markets': {'spot': spot, 'future': future},
              'fees': {'spot_taker': '0.0005', 'future_taker': '0.00035', 'delivery_proxy': '0.00025'}}
    record = {'slot': 0, 'planned_utc': T0, 'actual_utc': T0, 'clock_drift_s': 0,
              'responses': {}}
    for role, bid, ask in [('spot', 99.9, 100), ('future', 102, 102.5)]:
        result = {'instrument_name': config['markets'][role]['instrument_name'], 'state': 'open',
                  'timestamp': (T0*1000)-500, 'bids': [[bid, 100]], 'asks': [[ask, 100]]}
        record['responses'][role] = {'status': 200, 'request_utc': T0-1,
                                     'received_utc': T0-0.25, 'clock_drift_s': 0,
                                     'raw_utf8': json.dumps({'jsonrpc': '2.0', 'result': result})}
    return config, record


class DatedCarryAnalysisTests(unittest.TestCase):
    def test_selection_is_expiry_only_and_excludes_perpetual(self):
        c, _ = fixture()
        f = c['markets']['future']
        later = dict(f, instrument_name='BTC_USDC-30OCT26', expiration_timestamp=(T0+29*86400)*1000)
        perp = dict(f, instrument_name='BTC_USDC-PERPETUAL', settlement_period='perpetual')
        early = dict(f, instrument_name='BTC_USDC-2OCT26', expiration_timestamp=(T0+2*86400)*1000)
        got = dc.select_markets({'result': [later, perp, early, f]}, {'result': [c['markets']['spot']]}, T0)
        self.assertEqual(got['future']['instrument_name'], f['instrument_name'])
        with self.assertRaisesRegex(dc.InvalidQuote, 'no_eligible'):
            dc.select_markets({'result': [perp, early]}, {'result': [c['markets']['spot']]}, T0)

    def test_exact_cashflow_and_full_maturity_capital(self):
        c, record = fixture()
        row = dc.evaluate_record(record, c)[-1]
        self.assertEqual(row['status'], 'conditional_quote_valid')
        self.assertEqual(row['quantity'], '49/5')
        entry = Fraction(980)*Fraction(5,10000)+Fraction('999.6')*Fraction('0.00035')
        fees = entry+Fraction(980)*Fraction(5,10000)+Fraction('999.6')*Fraction('0.00025')
        capital = (2000+entry)*Fraction(5,100)*(8*86400+3600)/(365*86400)
        expected = Fraction('19.6')-fees-capital-Fraction('999.6')/2000
        self.assertEqual(row['conditional_proxy_exact'], dc.fraction_text(expected))
        self.assertIsNone(row['closed_net_usd'])
        self.assertIsNone(row['all_in_headroom_usd'])
        self.assertEqual(row['remaining_capital_seconds'], 8*86400+3600)

    def test_depth_budget_overrun_rejected_without_resizing(self):
        c, record = fixture()
        data = json.loads(record['responses']['spot']['raw_utf8'])
        data['result']['asks'] = [[100, 1], [200, 99]]
        record['responses']['spot']['raw_utf8'] = json.dumps(data)
        self.assertEqual(dc.evaluate_record(record, c)[-1]['status'], 'walked_entry_budget_exceeded')

    def test_late_receipt_does_not_replace_decision(self):
        c, record = fixture()
        record['responses']['spot']['received_utc'] = T0+0.01
        rows = dc.evaluate_record(record, c)
        self.assertTrue(all('receipt_after' in r['status'] for r in rows))

    def test_future_clock_skew_and_dispatch_failures(self):
        for field in ('future', 'skew', 'dispatch', 'mapping'):
            with self.subTest(field=field):
                c, record = fixture()
                if field in ('future', 'skew'):
                    data = json.loads(record['responses']['spot']['raw_utf8'])
                    data['result']['timestamp'] = T0*1000+1 if field == 'future' else T0*1000-1000
                    record['responses']['spot']['raw_utf8'] = json.dumps(data)
                elif field == 'dispatch':
                    record['actual_utc'] = T0+0.3
                else:
                    record['clock_drift_s'] = 0.3
                self.assertTrue(all(r['status'] != 'conditional_quote_valid' for r in dc.evaluate_record(record,c)))

    def test_duplicate_levels_and_nan_rejected(self):
        c, record = fixture()
        data = json.loads(record['responses']['future']['raw_utf8'])
        data['result']['bids'] = [[102, 1], [102, 2]]
        record['responses']['future']['raw_utf8'] = json.dumps(data)
        self.assertEqual(dc.evaluate_record(record,c)[0]['status'], 'depth_order_or_duplicate')
        for bad in ('NaN', 'Infinity', '1e100000', True):
            with self.assertRaises(dc.InvalidQuote):
                dc.number(bad)

    def test_common_lot_uses_quantity_increment(self):
        self.assertEqual(dc.common_lot('0.00000001', '0.0001'), Fraction(1,10000))
        self.assertEqual(dc.common_lot('0.02','0.03'), Fraction(3,50))

    def test_rpc_shape_failure_preserves_four_nulls(self):
        c, record = fixture()
        record['responses']['spot']['raw_utf8'] = '[]'
        rows = dc.evaluate_record(record, c)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r['status'] == 'spot_rpc_error' for r in rows))

    def test_full_denominator_and_unknown_gate(self):
        rows = [r for slot in range(dc.SLOTS) for r in dc.invalid_rows(slot, 'not_collected')]
        summary = dc.summarize(rows)
        self.assertEqual(summary['scheduled_rows'], 3456)
        self.assertEqual(len(summary['primary_decisions']), 6)
        self.assertEqual(summary['all_cost_feasibility_gate'], 'unresolved')
        self.assertEqual(summary['groups']['1000']['valid'], 0)
        with self.assertRaises(ValueError):
            dc.summarize(rows[:-1]+rows[:1])

    def test_valid_summary_preserves_large_generated_rationals(self):
        c, record = fixture()
        valid = dc.evaluate_record(record, c)
        self.assertTrue(all(r['status'] == 'conditional_quote_valid' for r in valid))
        rows = valid + [r for slot in range(1, dc.SLOTS) for r in dc.invalid_rows(slot, 'not_collected')]
        summary = dc.summarize(rows)
        self.assertEqual(summary['groups']['1000']['valid'], 1)
        self.assertEqual(summary['conditional_prerequisite']['positive_decisions'], 1)
        self.assertEqual(dc.generated_fraction('12345678901234567890123/1234567890123456789012'),
                         Fraction(12345678901234567890123,1234567890123456789012))

    def test_configured_fees_expiry_and_price_band_are_enforced(self):
        for key in ('fee', 'expiry', 'band'):
            c, record = fixture()
            if key == 'fee':
                c['fees']['spot_taker'] = '0'
                reason = 'configured_public_entry_fee_mismatch'
            elif key == 'expiry':
                c['expiry_utc'] -= 86400
                reason = 'configured_expiry_mismatch'
            else:
                payload = json.loads(record['responses']['spot']['raw_utf8'])
                payload['result']['max_price'] = 99.9
                record['responses']['spot']['raw_utf8'] = json.dumps(payload)
                reason = 'known_entry_price_band'
            self.assertTrue(all(r['status'] == reason for r in dc.evaluate_record(record, c)))

    def test_collector_deadline_and_start_drift_are_enforced(self):
        c, record = fixture()
        record['responses']['spot']['deadline_admitted'] = False
        self.assertEqual(dc.evaluate_record(record, c)[0]['status'], 'spot_deadline_not_admitted')
        record['responses']['spot']['deadline_admitted'] = True
        record['responses']['spot']['start_clock_drift_s'] = 0.3
        self.assertEqual(dc.evaluate_record(record, c)[0]['status'], 'spot_request_clock_drift')

    def test_malformed_metadata_is_a_classified_preflight_failure(self):
        c, _ = fixture()
        for response in (None, [], {'result':[{'instrument_name':[]}]}):
            with self.assertRaises(dc.InvalidQuote):
                dc.select_markets(response, {'result':[c['markets']['spot']]}, T0)


if __name__ == '__main__':
    unittest.main()
