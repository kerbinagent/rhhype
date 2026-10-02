"""Focused synthetic books; no real quote or HTTP fixtures."""
import base64
import contextlib
import copy
import gzip
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import polymarket_no_basket_optimistic_books as b

DRAFT = b.metadata.strict_json(b.metadata.bounded_read(b.PLAN, 20000))
WALL = 1700000000000000000


def books(price='0.80', receipt=WALL):
  return [{'asset_id': market['no_token_id'], 'market': market['condition_id'],
      'neg_risk': True, 'tick_size': '0.01', 'min_order_size': '5',
      'timestamp': str(receipt // 1000000), 'hash': 'synthetic-hash',
      'asks': [{'price': '1.00', 'size': '1'}, {'price': price, 'size': '1'}],
      'bids': [{'price': '0.01', 'size': '1'}], 'last_trade_price': 'EXCLUDED'}
      for market in DRAFT['markets']]


class Clock:
  def __init__(self, now=0): self.now = now
  def monotonic(self): return self.now
  def sleep(self, seconds): self.now += seconds


class Response:
  status = 200
  def __init__(self, raw, length=True, partial=None):
    self.raw, self.reads, self.partial = io.BytesIO(raw), [], partial
    self.headers = {'Content-Type': 'application/json', 'Content-Encoding': 'identity', 'Date': 'synthetic-date'}
    if length: self.headers['Content-Length'] = str(len(raw))
  def getheader(self, name, default=None): return self.headers.get(name, default)
  def read1(self, count):
    self.reads.append(count)
    if self.partial is not None: raise b.http.client.IncompleteRead(self.partial, 4)
    return self.raw.read(count)


class Connection:
  def __init__(self, response): self.response, self.calls, self.closed = response, [], False
  def request(self, *args, **kwargs): self.calls.append((args, kwargs))
  def getresponse(self): return self.response
  def close(self): self.closed = True


class OptimisticBooksTests(unittest.TestCase):
  def test_exact_bounds_unordered_books_and_no_bid_economics(self):
    for price, margin, status in (
      ('0.70', '0.50', 'necessary_price_condition_only'),
      ('0.80', '0.00', 'conditional_nominal_nonpositive_recorded_set'),
      ('0.90', '-0.50', 'conditional_nominal_nonpositive_recorded_set'),
    ):
      raw = books(price)
      result = b.evaluate(list(reversed(raw)), DRAFT['markets'], WALL)
      self.assertEqual(result['optimistic_margin'], margin)
      self.assertEqual(result['status'], status)
      self.assertTrue(result['time_diagnostics']['fresh_coherent'])
      self.assertEqual([r['asset_id'] for r in result['books']], [m['no_token_id'] for m in DRAFT['markets']])
      self.assertNotIn('EXCLUDED', b.metadata.encoded(result).decode())
      self.assertNotIn('bids', b.metadata.encoded(result).decode())
      self.assertEqual(result['books'][0]['minimum_order_unit'], 'unresolved')

  def test_identity_dominates_fields_and_field_invalid_empty_crossed(self):
    for mutate in (
      lambda x: x.pop(), lambda x: x.append(copy.deepcopy(x[0])),
      lambda x: x[1].update(asset_id=x[0]['asset_id']),
      lambda x: x[0].update(market='wrong'), lambda x: x[0].update(neg_risk=1),
    ):
      raw = books()
      raw[0]['asks'][0]['price'] = 'NaN'
      mutate(raw)
      with self.assertRaises(b.Refusal): b.evaluate(raw, DRAFT['markets'], WALL)
    for value in ('-0.1', '+0.1', '1e-1', 'NaN', '0.1234567', '1' * 33, 0.5):
      with self.assertRaises(b.FieldInvalid): b.decimal_field(value)
    for key, value in (('tick_size', '0'), ('min_order_size', '0'), ('hash', ''),
             ('timestamp', '170000000000'), ('asks', None)):
      raw = books(); raw[0][key] = value
      with self.assertRaises(b.FieldInvalid): b.evaluate(raw, DRAFT['markets'], WALL)
    for level in ({'price': '0.805', 'size': '1'}, {'price': '0', 'size': '1'},
           {'price': '0.8', 'size': '0'}, {'price': '1.01', 'size': '1'}):
      raw = books(); raw[0]['asks'] = [level]
      with self.assertRaises(b.FieldInvalid): b.evaluate(raw, DRAFT['markets'], WALL)
    raw = books(); raw[0]['bids'] = [{'price': '0.80', 'size': '1'}]
    with self.assertRaisesRegex(b.FieldInvalid, 'crossed_book'): b.evaluate(raw, DRAFT['markets'], WALL)
    raw = books(); raw[0]['asks'] = []
    result = b.evaluate(raw, DRAFT['markets'], WALL)
    self.assertFalse(result['field_valid']); self.assertIsNone(result['optimistic_margin'])
    self.assertEqual(result['reason'], 'empty_ask_side')

  def test_timestamp_interpretation_exact_freshness_and_denominators(self):
    raw = books()
    raw[0]['timestamp'] = '1700000000'
    self.assertEqual(b.evaluate(raw, DRAFT['markets'], WALL)['books'][0]['timestamp']['inferred_unit'], 'seconds')
    for offset, fresh in ((250000000, True), (251000000, False), (-5000000000, True), (-5001000000, False)):
      raw = books(receipt=WALL + offset)
      self.assertEqual(b.evaluate(raw, DRAFT['markets'], WALL)['time_diagnostics']['fresh_coherent'], fresh)
    raw = books(); raw[0]['timestamp'] = str((WALL - 501000000) // 1000000)
    self.assertFalse(b.evaluate(raw, DRAFT['markets'], WALL)['time_diagnostics']['fresh_coherent'])
    slots = b.empty_slots(WALL)
    for slot in slots:
      slot.update(b.evaluate(books(), DRAFT['markets'], WALL))
    self.assertTrue(b.summarize(slots, '0' * 64)['all_scheduled_sets_fresh_nonpositive'])
    slots[7]['time_diagnostics']['fresh_coherent'] = False
    self.assertFalse(b.summarize(slots, '0' * 64)['all_scheduled_sets_fresh_nonpositive'])
    slots[7] = b.empty_slots(WALL)[7]
    summary = b.summarize(slots, '0' * 64)
    self.assertEqual(summary['counts']['scheduled'], 15)
    self.assertEqual(summary['counts']['missing'], 1)
    self.assertFalse(summary['all_scheduled_sets_fresh_nonpositive'])
    for slot in slots: slot['request_attempted'] = None
    self.assertIsNone(b.summarize(slots, '0'*64)['counts']['requests_attempted'])
    # Maximum allowed Unicode hash and decimal strings stay compact in the
    # derived summary; original bytes are retained only in raw trace.
    raw = books()
    for row in raw:
      row.update(hash='😀'*128, min_order_size='1'*32, tick_size='0'*28+'.01')
    slots = b.empty_slots(WALL)
    for slot in slots: slot.update(b.evaluate(raw, DRAFT['markets'], WALL))
    with tempfile.TemporaryDirectory() as directory:
      out = Path(directory)
      b.publish(out, 'claim.json', {'synthetic': True})
      b.publish(out, 'summary.json', b.summarize(slots, '0'*64))
      b.publish(out, 'terminal.json', {'status': 'finished'})
      b.publish(out, 'supervisor.json', {'status': 'finished'})
      self.assertLess(sum(p.stat().st_size for p in out.iterdir()), 65536)

  def test_dry_pins_and_scope_before_http(self):
    with patch.object(b.http.client, 'HTTPSConnection', side_effect=AssertionError('network')) as network:
      with contextlib.redirect_stdout(io.StringIO()):
        self.assertEqual(b.main([]), 0); self.assertEqual(b.main(['--run']), 1)
      network.assert_not_called()
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory); path = root/'plan.json'; plan = copy.deepcopy(DRAFT)
      plan.update(status='frozen_optimistic_books_probe', source_pins=[
        {'path': name, 'bytes': 1, 'sha256': b.chain.sha(b'x')} for name in (b.SOURCE, b.TEST)])
      obs = [{'id': k+1, 'observation': {'uint': '0'}} for k in range(55)]
      obs[26]['observation']['uint'] = '5'
      for k, market in enumerate(DRAFT['markets']):
        for offset, key in ((30, 'yes_token_id'), (31, 'no_token_id')):
          obs[offset+5*k]['observation']['uint'] = market[key]
      summary = {'status': 'metadata_mapping_compatible_conversion_unproven', 'observations': obs}
      def identity(file, pin, cap):
        if str(file).endswith(b.CHAIN_SUMMARY['path']): return b.metadata.encoded(summary)
        if str(file).endswith(b.CHAIN_PLAN['path']): return b'{}'
        if pin['bytes'] != 1 or pin['sha256'] != b.chain.sha(b'x'): raise b.Refusal('pin_mismatch')
        return b'x'
      def save(): path.write_bytes(b.metadata.encoded(plan)); return b.chain.sha(path.read_bytes())
      with patch.object(b, 'ROOT', root), patch.object(b, 'PLAN', path), \
        patch.object(b.chain, 'file_identity', side_effect=identity), \
        patch.object(b.chain, 'verify', return_value={'markets': DRAFT['markets']}):
        self.assertEqual(b.verify(save())['event_id'], '606422')
        baseline = copy.deepcopy(plan)
        for mutate in (lambda p: p.update(status='draft'), lambda p: p['limits'].update(slots=16),
               lambda p: p['request_body'][0].update(token_id='1'),
               lambda p: p['source_pins'].pop(), lambda p: p['source_pins'][0].update(sha256='0'*64)):
          plan.clear(); plan.update(copy.deepcopy(baseline)); mutate(plan)
          with self.assertRaises(b.Refusal): b.verify(save())
        plan.clear(); plan.update(baseline); digest = save()
        obs[26]['observation']['uint'] = '6'
        with self.assertRaises(b.Refusal): b.verify(digest)
        obs[26]['observation']['uint'] = '5'
        (root/b.OUT).mkdir(parents=True)
        with self.assertRaises(FileExistsError): b.run(digest)

  def test_transport_remaining_cap_partial_and_start_deadline(self):
    def execute(response, used=0, planned=None):
      connection = Connection(response)
      budget = {'bytes': used, 'requests': 0}; record = {'planned_monotonic': time.monotonic() if planned is None else planned}
      with patch.object(b.http.client, 'HTTPSConnection', return_value=connection):
        try: b.transport(DRAFT['request_body'], record, budget, time.monotonic()+20); code = None
        except (b.Refusal, b.FieldInvalid) as exc: code = str(exc)
      return code, record, budget, connection
    used = b.LIMITS['total_response_bytes'] - 3
    response = Response(b'123456', length=False)
    code, record, budget, connection = execute(response, used)
    self.assertEqual(code, 'incomplete_body_or_unproven_eof_boundary')
    self.assertEqual(response.reads, [3]); self.assertEqual(budget['bytes'], b.LIMITS['total_response_bytes'])
    self.assertEqual(base64.b64decode(record['body_base64']), b'123')
    self.assertEqual(connection.calls[0][0], ('POST', '/books'))
    self.assertEqual(json.loads(connection.calls[0][1]['body']), DRAFT['request_body'])
    code, record, budget, _ = execute(Response(b'', length=False, partial=b'ab'))
    self.assertEqual(code, 'incomplete_response_body'); self.assertEqual(budget['bytes'], 2)
    self.assertEqual(base64.b64decode(record['body_base64']), b'ab')
    code, _, budget, connection = execute(Response(b'[]'), planned=time.monotonic()-1)
    self.assertEqual(code, 'missed_start_lateness'); self.assertEqual(budget['requests'], 0)
    self.assertEqual(connection.calls, [])
    connection = Connection(Response(b'[]')); budget = {'bytes': 0, 'requests': 0}
    record = {'planned_monotonic': 0}
    with patch.object(b.http.client, 'HTTPSConnection', return_value=connection), \
         patch.object(b.time, 'monotonic', side_effect=[0, 0, .1, .3, .4]):
      with self.assertRaisesRegex(b.FieldInvalid, 'missed_start_lateness'):
        b.transport(DRAFT['request_body'], record, budget, 20)
    self.assertFalse(record['request_attempted']); self.assertEqual(budget['requests'], 0)
    self.assertEqual(connection.calls, []); self.assertEqual(record['actual_start_lateness_seconds'], .3)

  def test_fixed_slots_continue_fields_stop_identity_and_preserve_terminal(self):
    for failure in ('field', 'identity', 'none'):
      with tempfile.TemporaryDirectory() as directory:
        out = Path(directory); clock = Clock(); calls = []
        def transport(body, record, budget, deadline):
          k = record['slot']; calls.append(k); now = WALL + int(clock.now*1000000000)
          obj = books(receipt=now)
          if k == 2 and failure == 'field': obj[0]['tick_size'] = '0'
          if k == 2 and failure == 'identity': obj[0]['asset_id'] = 'wrong'
          raw = b.metadata.encoded(obj); budget['requests'] += 1; budget['bytes'] += len(raw)
          record.update(request_attempted=True, receipt_wall_ns=now, body_bytes=len(raw), body_sha256=b.chain.sha(raw), body_base64=base64.b64encode(raw).decode())
          return raw
        with patch.object(b, 'verify', return_value=DRAFT), patch.object(b, 'transport', side_effect=transport), \
          patch.object(b.time, 'monotonic', side_effect=clock.monotonic), patch.object(b.time, 'sleep', side_effect=clock.sleep):
          b.worker('0'*64, out, 0, WALL, 64)
        summary = json.loads((out/'summary.json').read_bytes()); terminal = json.loads((out/'terminal.json').read_bytes())
        self.assertEqual(len(summary['slots']), 15)
        self.assertEqual(len(calls), 3 if failure == 'identity' else 15)
        self.assertEqual(summary['counts']['invalid'], 0 if failure == 'none' else 1)
        self.assertEqual(summary['counts']['missing'], 12 if failure == 'identity' else 0)
        self.assertEqual(terminal['status'], 'inconclusive' if failure == 'identity' else 'fixed_sampling_finished')
        self.assertEqual(summary['all_scheduled_sets_fresh_nonpositive'], failure == 'none')
        self.assertLess((out/'summary.json').stat().st_size + (out/'terminal.json').stat().st_size, 65536)
        self.assertEqual(len(gzip.decompress((out/'trace.jsonl.gz').read_bytes()).splitlines()), len(calls))
    with tempfile.TemporaryDirectory() as directory:
      out = Path(directory); clock = Clock(0.3); slots = b.empty_slots(WALL); terminal = {}
      def stop(*_): raise b.Refusal('synthetic_transport_stop')
      with patch.object(b.time, 'monotonic', side_effect=clock.monotonic), patch.object(b.time, 'sleep', side_effect=clock.sleep), patch.object(b, 'transport', side_effect=stop):
        with self.assertRaises(b.Refusal): b.sample(DRAFT, '0'*64, out, 0, WALL, 64, slots, terminal)
      self.assertEqual(slots[0]['reason'], 'missed_start_lateness')
      self.assertEqual(slots[1]['reason'], 'synthetic_transport_stop')
      self.assertTrue(all(slot['optimistic_margin'] is None for slot in slots))

  def test_trace_resource_refusal_keeps_last_checkpoint(self):
    with tempfile.TemporaryDirectory() as directory:
      out = Path(directory); trace = b.Trace(out); trace.append({'slot': 0})
      original = (out/'trace.jsonl.gz').read_bytes()
      with patch.dict(b.LIMITS, trace_plaintext_bytes_in_memory=len(trace.plaintext)+1):
        with self.assertRaises(b.Refusal): trace.append({'slot': 1})
      self.assertEqual((out/'trace.jsonl.gz').read_bytes(), original)
      with patch.dict(b.LIMITS, trace_gzip_bytes=1):
        with self.assertRaises(b.Refusal): trace.append({'slot': 1})
      self.assertEqual((out/'trace.jsonl.gz').read_bytes(), original)
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      class DeadWorker:
        exitcode = 1
        def start(self): pass
        def join(self, timeout): pass
        def is_alive(self): return False
      class Context:
        def Process(self, **kwargs): return DeadWorker()
      with patch.object(b, 'ROOT', root), patch.object(b, 'verify', return_value=DRAFT), \
        patch.object(b.multiprocessing, 'get_context', return_value=Context()):
        result = b.run('0'*64)
      self.assertEqual(result['status'], 'worker_failed_without_terminal')
      summary = json.loads((root/b.OUT/'summary.json').read_bytes())
      self.assertIsNone(summary['counts']['requests_attempted'])
      self.assertTrue(all(slot['request_attempted'] is None for slot in summary['slots']))


if __name__ == '__main__': unittest.main()
