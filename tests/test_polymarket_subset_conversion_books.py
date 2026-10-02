"""Synthetic route economics, identity, calendar, and resource gates; no HTTP."""
import base64
import contextlib
import copy
from decimal import Decimal
import gzip
import io
import json
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import polymarket_subset_conversion_books as b

PLAN = b.metadata.strict_json(b.metadata.bounded_read(b.PLAN, 22000))
WALL = 1700000000000000000


def books(no='0.80', yes='0.15', receipt=WALL):
    rows = []
    for market in PLAN['markets']:
        for key, selected, economic in (('no_token_id', 'NO', no), ('yes_token_id', 'YES', yes)):
            row = {'asset_id': market[key], 'market': market['condition_id'], 'neg_risk': True,
                   'tick_size': '0.01', 'min_order_size': '5', 'timestamp': str(receipt // 1000000),
                   'hash': 'synthetic', 'asks': [{'price': no if selected == 'NO' else '0.99', 'size': '1'}],
                   'bids': [{'price': yes if selected == 'YES' else '0.01', 'size': '1'}],
                   'last_trade_price': 'EXCLUDED'}
            rows.append(row)
    return rows


class Clock:
    def __init__(self, now=0): self.now = now
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class SubsetTests(unittest.TestCase):
    def test_masks_conversion_and_full_negative_partial_positive(self):
        self.assertEqual(PLAN['fixed_routes'], b.expected_routes())
        self.assertEqual([r['selected_indices'] for r in b.expected_routes()[1:]],
                         [[k for k in range(5) if mask & (1 << k)] for mask in range(1, 32)])
        result = b.evaluate(list(reversed(books('0.80', '0.15'))), PLAN['markets'], WALL)
        margins = [Decimal(route) for route in result['routes']]
        self.assertEqual(len(margins), 32)
        self.assertEqual(margins[0], Decimal('-0.25'))
        self.assertEqual(margins[1], Decimal('-0.20'))
        self.assertEqual(margins[3], Decimal('-0.15'))
        self.assertEqual(margins[31], Decimal('0'))
        raw = books('0.76', '0.01')
        raw[8]['asks'][0]['price'] = '0.99'
        raw[9]['bids'][0]['price'] = '0.90'
        split = [Decimal(x) for x in b.evaluate(raw, PLAN['markets'], WALL)['routes']]
        self.assertLess(split[0], 0)
        self.assertGreater(split[15], 0)
        self.assertLess(split[31], 0)
        self.assertTrue(result['time_diagnostics']['fresh_coherent'])
        self.assertNotIn('EXCLUDED', b.metadata.encoded(result).decode())
        self.assertNotIn('last_trade_price', b.metadata.encoded(result).decode())
        self.assertEqual([r['asset_id'] for r in result['books']],
                         [entry['token_id'] for entry in PLAN['request_body']])
        self.assertEqual(margins, b.route_margins([Decimal('.80')]*5, [Decimal('.15')]*5))
        # Changing the integrity-only NO bid and YES ask does not affect economics.
        raw = books('0.80', '0.15')
        for row in raw:
            if row['asset_id'] in {m['no_token_id'] for m in PLAN['markets']}:
                row['bids'][0]['price'] = '0.79'
            else:
                row['asks'][0]['price'] = '0.16'
        self.assertEqual(result['routes'], b.evaluate(raw, PLAN['markets'], WALL)['routes'])

    def test_all_signs_and_unavailable_common_family(self):
        for no, yes, positive in (('0.99', '0.01', False),
                                  ('0.70', '0.20', True), ('0.80', '0.15', False)):
            result = b.evaluate(books(no, yes), PLAN['markets'], WALL)
            self.assertEqual(Decimal(result['routes'][31]) > 0, positive)
        raw = books()
        raw[0]['asks'] = []
        result = b.evaluate(raw, PLAN['markets'], WALL)
        self.assertFalse(result['field_valid'])
        self.assertNotIn('routes', result)
        raw = books(); raw[1]['bids'] = []
        self.assertEqual(b.evaluate(raw, PLAN['markets'], WALL)['reason'], 'empty_economic_side')
        raw = books(); raw[0]['bids'] = []; raw[1]['asks'] = []
        self.assertTrue(b.evaluate(raw, PLAN['markets'], WALL)['field_valid'])

    def test_identity_fields_and_time_are_distinct(self):
        for change in (lambda x: x.pop(), lambda x: x.append(copy.deepcopy(x[0])),
                       lambda x: x[1].update(asset_id=x[0]['asset_id']),
                       lambda x: x[0].update(market='wrong'),
                       lambda x: x[0].update(neg_risk=1)):
            raw = books(); raw[0]['tick_size'] = '0'; change(raw)
            with self.assertRaises(b.Refusal): b.evaluate(raw, PLAN['markets'], WALL)
        for key, value in (('tick_size', '0'), ('min_order_size', '-1'), ('hash', ''),
                           ('timestamp', '170000000000'), ('asks', None)):
            raw = books(); raw[0][key] = value
            with self.assertRaises(b.FieldInvalid): b.evaluate(raw, PLAN['markets'], WALL)
        raw = books(); raw[0]['bids'] = [{'price': '0.80', 'size': '1'}]
        with self.assertRaisesRegex(b.FieldInvalid, 'crossed_book'):
            b.evaluate(raw, PLAN['markets'], WALL)
        for offset, fresh in ((250000000, True), (251000000, False),
                              (-5000000000, True), (-5001000000, False)):
            raw = books(receipt=WALL+offset)
            self.assertEqual(b.evaluate(raw, PLAN['markets'], WALL)['time_diagnostics']['fresh_coherent'], fresh)
        raw = books(); raw[0]['timestamp'] = str((WALL-501000000)//1000000)
        self.assertFalse(b.evaluate(raw, PLAN['markets'], WALL)['time_diagnostics']['fresh_coherent'])

    def test_denominators_signs_and_derived_peak(self):
        slots = b.empty_slots(WALL)
        for slot in slots: slot.update(b.evaluate(books('0.99', '0.01'), PLAN['markets'], WALL))
        summary = b.summarize(slots, '0'*64, True, True)
        self.assertEqual(summary['counts']['planned_route_slots'], 480)
        self.assertEqual(summary['counts']['nonpositive_route_slots'], 480)
        self.assertTrue(summary['all_scheduled_sets_fresh_nonpositive'])
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            b.publish(out, 'claim.json', {'synthetic': True})
            b.publish(out, 'summary.json', summary)
            b.publish(out, 'terminal.json', {'status': 'finished'})
            b.publish(out, 'supervisor.json', {'status': 'finished'})
            self.assertLess(sum(p.stat().st_size for p in out.iterdir()), 98304)
        slots[2]['time_diagnostics']['fresh_coherent'] = False
        self.assertFalse(b.summarize(slots, '0'*64, True, True)['all_scheduled_sets_fresh_nonpositive'])
        slots[2] = b.empty_slots(WALL)[2]
        slots[2]['request_attempted'] = None
        counts = b.summarize(slots, '0'*64, True, True)['counts']
        self.assertEqual((counts['field_valid_route_slots'], counts['unavailable_route_slots']), (448, 32))
        self.assertEqual(counts['requests_attempted_unknown_slots'], 1)
        self.assertIsNone(counts['requests_attempted'])

    def test_dry_pins_scope_and_existing_output(self):
        with patch.object(b.prior.http.client, 'HTTPSConnection', side_effect=AssertionError('HTTP')) as network:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(b.main([]), 0)
                self.assertEqual(b.main(['--run']), 1)
            network.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/'plan.json'; plan = copy.deepcopy(PLAN)
            plan.update(status='frozen_subset_conversion_books_probe', source_pins=[
                {'path': name, 'bytes': 1, 'sha256': b.chain.sha(b'x')} for name in (b.SOURCE, b.TEST)])
            obs = [{'id': k+1, 'observation': {'uint': '0'}} for k in range(55)]
            obs[26]['observation']['uint'] = '5'
            for k, market in enumerate(PLAN['markets']):
                for offset, key in ((30, 'yes_token_id'), (31, 'no_token_id')):
                    obs[offset+5*k]['observation']['uint'] = market[key]
            linked = {'status': 'metadata_mapping_compatible_conversion_unproven', 'observations': obs}
            def identity(file, pin, cap):
                if str(file).endswith(b.CHAIN_SUMMARY['path']): return b.metadata.encoded(linked)
                if str(file).endswith(b.CHAIN_PLAN['path']): return b'{}'
                if pin.get('path') in (b.PRIOR_SOURCE['path'], b.PRIOR_PLAN['path']):
                    return b'x'
                if pin['bytes'] != 1 or pin['sha256'] != b.chain.sha(b'x'):
                    raise b.Refusal('pin_mismatch')
                return b'x'
            def save():
                path.write_bytes(b.metadata.encoded(plan))
                return b.chain.sha(path.read_bytes())
            with patch.object(b, 'ROOT', root), patch.object(b, 'PLAN', path), \
                 patch.object(b.chain, 'file_identity', side_effect=identity), \
                 patch.object(b.chain, 'verify', return_value={'markets': PLAN['markets']}):
                self.assertEqual(b.verify(save())['event_id'], '606422')
                baseline = copy.deepcopy(plan)
                for mutate in (lambda p: p.update(status='draft'),
                               lambda p: p['limits'].update(slots=16),
                               lambda p: p['request_body'][1].update(token_id='1'),
                               lambda p: p['fixed_routes'][3].update(selected_indices=[1]),
                               lambda p: p['source_pins'].pop()):
                    plan.clear(); plan.update(copy.deepcopy(baseline)); mutate(plan)
                    with self.assertRaises(b.Refusal): b.verify(save())
                plan.clear(); plan.update(baseline); digest = save()
                obs[26]['observation']['uint'] = '6'
                with self.assertRaises(b.Refusal): b.verify(digest)
                obs[26]['observation']['uint'] = '5'
                (root/b.OUT).mkdir(parents=True)
                with self.assertRaises(FileExistsError): b.run(digest)

    def test_calendar_failure_preserves_unknown_and_no_early_stop(self):
        for failure in ('none', 'field', 'identity'):
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory); clock = Clock(); calls = []
                def transport(body, record, budget, deadline):
                    k = record['slot']; calls.append(k)
                    raw_books = books('0.80', '0.20', WALL+int(clock.now*1000000000))
                    if k == 2 and failure == 'field': raw_books[0]['tick_size'] = '0'
                    if k == 2 and failure == 'identity': raw_books[0]['asset_id'] = 'wrong'
                    raw = b.metadata.encoded(raw_books)
                    budget['requests'] += 1; budget['bytes'] += len(raw)
                    record.update(request_attempted=True, receipt_wall_ns=WALL+int(clock.now*1000000000),
                                  body_bytes=len(raw), body_sha256=b.chain.sha(raw),
                                  body_base64=base64.b64encode(raw).decode())
                    return raw
                with patch.object(b, 'verify', return_value=PLAN), \
                     patch.object(b.prior, 'transport', side_effect=transport), \
                     patch.object(b.time, 'monotonic', side_effect=clock.monotonic), \
                     patch.object(b.time, 'sleep', side_effect=clock.sleep):
                    b.worker('0'*64, out, 0, WALL, 64)
                summary = json.loads((out/'summary.json').read_bytes())
                terminal = json.loads((out/'terminal.json').read_bytes())
                self.assertEqual(len(calls), 3 if failure == 'identity' else 15)
                self.assertEqual(summary['counts']['planned_route_slots'], 480)
                self.assertEqual(summary['counts']['invalid_slots'], 0 if failure == 'none' else 1)
                self.assertEqual(terminal['status'], 'inconclusive' if failure == 'identity' else 'fixed_sampling_finished')
                self.assertEqual(len(gzip.decompress((out/'trace.jsonl.gz').read_bytes()).splitlines()), len(calls))
                self.assertLess(sum(p.stat().st_size for p in out.iterdir()), 98304 + b.LIMITS['trace_gzip_bytes'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            class DeadWorker:
                exitcode = 1
                def start(self): pass
                def join(self, timeout): pass
                def is_alive(self): return False
            class Context:
                def Process(self, **kwargs): return DeadWorker()
            with patch.object(b, 'ROOT', root), patch.object(b, 'verify', return_value=PLAN), \
                 patch.object(b.multiprocessing, 'get_context', return_value=Context()):
                result = b.run('0'*64)
            self.assertEqual(result['status'], 'worker_failed_without_terminal')
            summary = json.loads((root/b.OUT/'summary.json').read_bytes())
            self.assertEqual(summary['counts']['requests_attempted_unknown_slots'], 15)
            self.assertEqual(summary['counts']['unavailable_route_slots'], 480)

    def test_inherited_bounded_transport_partial_and_trace_checkpoint(self):
        class Response:
            status = 200
            def getheader(self, name, default=None):
                return {'Content-Type': 'application/json', 'Content-Encoding': 'identity'}.get(name, default)
            def read1(self, count):
                raise b.prior.http.client.IncompleteRead(b'ab', 4)
        class Connection:
            def __init__(self): self.called = False
            def request(self, *args, **kwargs): self.called = True
            def getresponse(self): return Response()
            def close(self): pass
        record = {'planned_monotonic': time.monotonic()}
        budget = {'bytes': 0, 'requests': 0}
        connection = Connection()
        with patch.object(b.prior.http.client, 'HTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(b.Refusal, 'incomplete_response_body'):
                b.prior.transport(PLAN['request_body'], record, budget, time.monotonic()+5)
        self.assertTrue(connection.called)
        self.assertEqual(budget['bytes'], 2)
        self.assertEqual(base64.b64decode(record['body_base64']), b'ab')
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory); trace = b.prior.Trace(out)
            trace.append({'slot': 0})
            before = (out/'trace.jsonl.gz').read_bytes()
            with patch.dict(b.prior.LIMITS, trace_gzip_bytes=1):
                with self.assertRaises(b.Refusal): trace.append({'slot': 1})
            self.assertEqual((out/'trace.jsonl.gz').read_bytes(), before)

    def test_post_run_pin_failure_invalidates_complete_negative_set(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            def sampled(plan, sha, destination, anchor_mono, anchor_wall, deadline, slots, terminal):
                for slot in slots:
                    slot.update(b.evaluate(books('0.99', '0.01'), PLAN['markets'], WALL))
            with patch.object(b, 'verify', side_effect=[PLAN, b.Refusal('changed_pin')]), \
                 patch.object(b, 'sample', side_effect=sampled):
                b.worker('0'*64, out, 0, WALL, 64)
            summary = json.loads((out/'summary.json').read_bytes())
            terminal = json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(summary['counts']['nonpositive_route_slots'], 480)
            self.assertFalse(summary['source_pins_verified'])
            self.assertFalse(summary['economic_conclusions_valid'])
            self.assertFalse(summary['all_scheduled_sets_fresh_nonpositive'])
            self.assertEqual(summary['maximum_conclusion'], 'no_economic_conclusion_unverified_or_incomplete')
            self.assertEqual(terminal['code'], 'post_run_pin_check_failed')

    def test_trace_failure_invalidates_only_unretained_slot_and_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory); clock = Clock(); calls = []
            original_append = b.prior.Trace.append
            def append(trace, record):
                if record['slot'] == 1:
                    raise b.Refusal('synthetic_trace_full')
                return original_append(trace, record)
            def transport(body, record, budget, deadline):
                k = record['slot']; calls.append(k)
                raw = b.metadata.encoded(books('0.99', '0.01', WALL+int(clock.now*1000000000)))
                budget['requests'] += 1; budget['bytes'] += len(raw)
                record.update(request_attempted=True, receipt_wall_ns=WALL+int(clock.now*1000000000),
                              body_sha256=b.chain.sha(raw), body_bytes=len(raw),
                              body_base64=base64.b64encode(raw).decode())
                return raw
            with patch.object(b, 'verify', return_value=PLAN), \
                 patch.object(b.prior, 'transport', side_effect=transport), \
                 patch.object(b.prior.Trace, 'append', append), \
                 patch.object(b.time, 'monotonic', side_effect=clock.monotonic), \
                 patch.object(b.time, 'sleep', side_effect=clock.sleep):
                b.worker('0'*64, out, 0, WALL, 64)
            summary = json.loads((out/'summary.json').read_bytes())
            terminal = json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(calls, [0, 1])
            self.assertEqual(summary['counts']['field_valid_route_slots'], 32)
            self.assertEqual(summary['counts']['unavailable_route_slots'], 448)
            self.assertTrue(summary['slots'][0]['field_valid'])
            self.assertFalse(summary['slots'][1]['field_valid'])
            self.assertEqual(summary['slots'][1]['reason'], 'evidence_retention_failed')
            self.assertEqual(summary['slots'][1]['routes'], [None]*32)
            self.assertNotIn('books', summary['slots'][1])
            self.assertEqual(terminal['last_request_receipt']['body_sha256'],
                             b.chain.sha(b.metadata.encoded(books('0.99','0.01',WALL+4000000000))))
            self.assertEqual(terminal['status'], 'inconclusive')
            self.assertFalse(summary['economic_conclusions_valid'])
            self.assertEqual(len(gzip.decompress((out/'trace.jsonl.gz').read_bytes()).splitlines()), 1)


if __name__ == '__main__':
    unittest.main()
