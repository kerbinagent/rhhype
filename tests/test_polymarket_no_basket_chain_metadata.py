"""Focused offline fixtures for the fixed 55-call metadata manifest."""
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

from scripts import polymarket_no_basket_chain_metadata as c


DRAFT = c.metadata.strict_json(c.metadata.bounded_read(c.PLAN, 32768))
SYNTHETIC_HEADER = {'number': '0x123', 'timestamp': '0x456', 'hash': '0x' + 'ab' * 32,
                    'parentHash': '0x' + 'cd' * 32, 'stateRoot': '0x' + 'ef' * 32,
                    'transactions': ['EXCLUDED-TRANSACTION-HISTORY']}


def word(number):
    return '0x' + int(number).to_bytes(32, 'big').hex()


def synthetic_result(row, addresses):
    if row['method'] == 'eth_chainId':
        return '0x89'
    if row['method'] == 'eth_getBlockByNumber':
        return dict(SYNTHETIC_HEADER)
    if row['method'] == 'eth_getCode':
        return '0x6000'
    key, wanted = next(iter(row['expect'].items()))
    if key == 'address_equals':
        return word(int(addresses[wanted], 16))
    if key == 'capture_nonzero_address':
        return word(int('11' * 20 if wanted == 'usdce' else '22' * 20, 16))
    if key == 'nonzero_address':
        return word(123)
    if key == 'bytes32_equals':
        return wanted
    if key == 'bool_equals':
        return word(int(wanted))
    if key == 'uint_range':
        return word(7)
    return word(wanted)


class Response:
    def __init__(self, body, length=True, status=200, break_after=None):
        self.body = io.BytesIO(body)
        self.status = status
        self.break_after = break_after
        self.headers = {'Content-Type': 'application/json', 'Content-Encoding': 'identity'}
        if length:
            self.headers['Content-Length'] = str(len(body))
        self.read_counts = []

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, count):
        self.read_counts.append(count)
        if self.break_after is not None:
            remaining = self.break_after - self.body.tell()
            if remaining <= 0:
                raise OSError('EXCLUDED-response-text')
            count = min(count, remaining)
        return self.body.read(count)


class Connection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ChainMetadataTests(unittest.TestCase):
    def test_actual_manifest_all_abi_calls_and_frozen_block(self):
        self.assertEqual(c.sha(c.canonical(DRAFT['manifest'])), c.MANIFEST_SHA)
        self.assertEqual(len(DRAFT['manifest']), 55)
        addresses = {k: v.lower() for k, v in c.CONTRACTS.items()}
        header = None
        for row in DRAFT['manifest']:
            request = c.request_for(row, addresses, header)
            self.assertEqual(request['id'], row['id'])
            if row['id'] not in (1, 2, 55):
                self.assertEqual(request['params'][-1], {'blockHash': header['hash'], 'requireCanonical': True})
            if row['method'] == 'eth_call':
                data = request['params'][0]['data']
                self.assertEqual((len(data) - 10) // 64, len(row['args']))
                self.assertEqual(request['params'][0]['to'], addresses[row['target']])
            result = synthetic_result(row, addresses)
            observed = c.accept(row, {'jsonrpc': '2.0', 'id': row['id'], 'result': result}, addresses, header)
            if row['id'] == 2:
                header = observed
                self.assertNotIn('transactions', header)
            if row['id'] == 55:
                self.assertEqual(request['params'], ['0x123', False])
        self.assertEqual(c.calldata('getConditionId(bytes32)', [c.MARKET], addresses)[:10], '0x04329c03')
        self.assertEqual(c.calldata('decimals()', [], addresses), '0x313ce567')
        condition_call = c.calldata('getPositionId(bytes32,bool)', [c.MARKET, True], addresses)
        self.assertEqual(condition_call[-64:], word(1)[2:])
        for args in ([c.MARKET, 1], [c.MARKET], [c.MARKET, False, False]):
            with self.assertRaises(c.Refusal):
                c.calldata('getPositionId(bytes32,bool)', args, addresses)

    def test_abi_count_token_address_bool_and_header_mismatches(self):
        addresses = {k: v.lower() for k, v in c.CONTRACTS.items()}
        for rpc_id, bad in ((27, word(6)), (31, word(1)), (4, word(9)),
                            (23, word(2)), (3, '0x'), (18, '0x06')):
            row = DRAFT['manifest'][rpc_id - 1]
            with self.assertRaises(c.Refusal):
                c.accept(row, {'jsonrpc': '2.0', 'id': rpc_id, 'result': bad}, addresses, None)
        row = DRAFT['manifest'][0]
        for envelope in ({'jsonrpc': '2.0', 'id': True, 'result': '0x89'},
                         {'jsonrpc': '2.0', 'id': 1, 'error': {'message': 'EXCLUDED'}},
                         {'jsonrpc': '2.0', 'id': 1, 'result': '0x1'},
                         {'jsonrpc': '2.0', 'id': 1, 'result': '0x089'}):
            with self.assertRaises(c.Refusal):
                c.accept(row, envelope, addresses, None)
        with self.assertRaises(c.Refusal):
            c.address_word('0x01' + '00' * 31)
        changed = dict(SYNTHETIC_HEADER, hash='0x' + '12' * 32)
        with self.assertRaises(c.Refusal):
            c.accept(DRAFT['manifest'][-1], {'jsonrpc': '2.0', 'id': 55, 'result': changed},
                     addresses, c.header_projection(SYNTHETIC_HEADER))

    def fixture(self, root):
        plan = copy.deepcopy(DRAFT)
        plan['status'] = 'frozen_chain_metadata_probe'
        plan['source_pins'] = []
        for name in (c.SOURCE, c.TEST):
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'synthetic source identity')
            plan['source_pins'].append({'path': name, 'bytes': file.stat().st_size,
                                        'sha256': c.sha(file.read_bytes())})
        for name in (c.PARENT, c.PROJECTION['path']):
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes((c.ROOT / name).read_bytes())
        path = root / 'plan.json'
        def save():
            path.write_bytes(c.metadata.encoded(plan))
            return c.sha(path.read_bytes())
        return plan, path, save

    def test_dry_frozen_pins_manifest_projection_and_scope_refusal(self):
        with patch.object(c.http.client, 'HTTPSConnection', side_effect=AssertionError('network')) as network:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(c.main([]), 0)
                self.assertEqual(c.main(['--run']), 1)
            self.assertIn('dry_no_http', output.getvalue())
            network.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan, path, save = self.fixture(root)
            original_identity = c.file_identity
            def identity(file, pin, cap):
                if str(file).endswith('scripts/polymarket_no_basket_calendar_review.py'):
                    return b'synthetic already pinned helper'
                return original_identity(file, pin, cap)
            with patch.object(c, 'ROOT', root), patch.object(c, 'PLAN', path), \
                 patch.object(c, 'file_identity', side_effect=identity), \
                 patch.object(c.metadata, 'verify', return_value={}) as old_verify:
                self.assertEqual(c.verify(save())['status'], 'frozen_chain_metadata_probe')
                old_verify.assert_called_with(c.ORIGINAL_SHA)
                baseline = copy.deepcopy(plan)
                for mutation in (
                    lambda p: p.update(status='draft'),
                    lambda p: p.update(endpoint='https://example.invalid'),
                    lambda p: p['limits'].update(rpc_requests=56),
                    lambda p: p['manifest'][26]['expect'].update(uint_equals=6),
                    lambda p: p['contracts'].update(wrapper='0x' + '11' * 20),
                    lambda p: p['source_pins'].pop(),
                    lambda p: p['source_pins'][0].update(sha256='0' * 64),
                    lambda p: p['markets'][0].update(no_token_id='1'),
                    lambda p: p['input_projection'].update(sha256='0' * 64),
                ):
                    plan.clear()
                    plan.update(copy.deepcopy(baseline))
                    mutation(plan)
                    with self.assertRaises(c.Refusal):
                        c.verify(save())
                plan.clear()
                plan.update(baseline)
                digest = save()
                (root / c.OUT).mkdir(parents=True)
                with patch.object(c.http.client, 'HTTPSConnection') as network:
                    with self.assertRaises(FileExistsError):
                        c.run(digest)
                    network.assert_not_called()
                (root / c.PROJECTION['path']).write_bytes(b'corrupted metadata')
                with self.assertRaises(c.Refusal):
                    c.verify(digest)

    def execute_transport(self, response, already_read=0, method='eth_call'):
        connection = Connection(response)
        record = {'body_complete': False}
        budget = {'bytes': already_read, 'requests': 0}
        payload = {'jsonrpc': '2.0', 'id': 3, 'method': method, 'params': []}
        with patch.object(c.http.client, 'HTTPSConnection', return_value=connection) as factory:
            try:
                result = c.transport(payload, record, budget, time.monotonic() + 30)
                code = None
            except Exception as exc:
                result = None
                code = str(exc) if isinstance(exc, c.Refusal) else type(exc).__name__
        if budget['requests']:
            self.assertEqual(connection.requests[0][0], ('POST', '/'))
            self.assertEqual(factory.call_args.args, (c.HOST,))
            self.assertTrue(connection.closed)
        return code, result, record, budget, response

    def test_transport_cumulative_boundary_without_length_and_no_overread(self):
        already = c.LIMITS['total_response_bytes'] - 3
        code, _, record, budget, response = self.execute_transport(Response(b'123456', length=False), already)
        self.assertEqual(code, 'response_cap_without_proven_eof')
        self.assertEqual(budget['bytes'], c.LIMITS['total_response_bytes'])
        self.assertEqual(response.read_counts, [3])
        self.assertEqual(base64.b64decode(record['body_base64']), b'123')
        self.assertFalse(record['body_complete'])
        code, body, record, budget, response = self.execute_transport(Response(b'123'), already)
        self.assertIsNone(code)
        self.assertEqual(body, b'123')
        self.assertTrue(record['body_complete'])
        code, _, record, budget, response = self.execute_transport(Response(b'1234'), already)
        self.assertEqual(code, 'declared_response_exceeds_remaining_cap')
        self.assertEqual(response.read_counts, [])
        self.assertEqual(budget['bytes'], already)
        code, _, record, budget, response = self.execute_transport(Response(b''), c.LIMITS['total_response_bytes'])
        self.assertEqual(code, 'cumulative_response_cap_before_request')
        self.assertEqual(budget['requests'], 0)

    def test_transport_partial_error_and_header_body_omission(self):
        code, _, record, budget, _ = self.execute_transport(Response(b'EXCLUDED-secret', break_after=4))
        self.assertEqual(code, 'OSError')
        self.assertEqual(budget['bytes'], 4)
        self.assertEqual(base64.b64decode(record['body_base64']), b'EXCL')
        self.assertEqual(record['body_sha256'], c.sha(b'EXCL'))
        response = Response(b'')
        response.headers.pop('Content-Length')
        response.read1 = lambda _: (_ for _ in ()).throw(c.http.client.IncompleteRead(b'abc', 5))
        code, _, record, budget, _ = self.execute_transport(response)
        self.assertEqual(code, 'incomplete_response_body')
        self.assertEqual(budget['bytes'], 3)
        self.assertEqual(base64.b64decode(record['body_base64']), b'abc')
        code, _, record, _, _ = self.execute_transport(Response(b'EXCLUDED-block-body'), method='eth_getBlockByNumber')
        self.assertIsNone(code)
        self.assertNotIn('body_base64', record)
        self.assertNotIn('EXCLUDED', c.metadata.encoded(record).decode())
        for status in (302, 500):
            self.assertEqual(self.execute_transport(Response(b'{}', status=status))[0], 'http_status_not_200')

    def test_trace_caps_preserve_previous_checkpoint_and_derived_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            trace = c.Trace(out)
            trace.append({'id': 1, 'synthetic': 'small'})
            before = (out / 'trace.jsonl.gz').read_bytes()
            with patch.dict(c.LIMITS, retained_trace_plaintext_bytes=len(trace.plaintext) + 1):
                with self.assertRaises(c.Refusal):
                    trace.append({'id': 2, 'synthetic': 'oversized'})
            self.assertEqual((out / 'trace.jsonl.gz').read_bytes(), before)
            self.assertFalse((out / 'trace.pending.gz').exists())
            with patch.dict(c.LIMITS, retained_trace_gzip_bytes=1):
                with self.assertRaises(c.Refusal):
                    trace.append({'id': 2})
            self.assertEqual((out / 'trace.jsonl.gz').read_bytes(), before)
            c.publish(out, 'terminal.json', {'status': 'inconclusive'})
            terminal = (out / 'terminal.json').read_bytes()
            with patch.dict(c.LIMITS, derived_receipts_bytes=len(terminal) + 1):
                with self.assertRaises(c.Refusal):
                    c.publish(out, 'summary.json', {'status': 'too_large'})
            self.assertEqual((out / 'terminal.json').read_bytes(), terminal)

    def collector_transport(self, fail_id=None):
        # Separate synthetic server bindings; the collector learns only the two
        # approved dependency addresses through the frozen wrapper getters.
        server = {k: v.lower() for k, v in c.CONTRACTS.items()}
        server.update(usdce='0x' + '11' * 20, wrapped_collateral='0x' + '22' * 20)
        calls = []
        def request(payload, record, budget, deadline):
            calls.append(payload['id'])
            row = DRAFT['manifest'][payload['id'] - 1]
            result = synthetic_result(row, server)
            if payload['id'] == fail_id:
                result = word(99)
            body = c.canonical({'jsonrpc': '2.0', 'id': payload['id'], 'result': result})
            budget['requests'] += 1
            budget['bytes'] += len(body)
            record.update(request_attempted=True, body_complete=True, body_bytes=len(body),
                          body_sha256=c.sha(body), http_status=200)
            if row['method'] != 'eth_getBlockByNumber':
                record['body_base64'] = base64.b64encode(body).decode('ascii')
            return body
        return calls, request

    def test_complete_fixed_pipeline_and_count_token_stop_terminal_supervisor(self):
        for fail_id in (None, 27, 31):
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                calls, request = self.collector_transport(fail_id)
                with patch.object(c, 'verify', return_value=DRAFT), patch.object(c, 'transport', side_effect=request), \
                     patch.object(c.time, 'sleep', return_value=None):
                    c.worker('0' * 64, out)
                terminal = json.loads((out / 'terminal.json').read_bytes())
                rows = [json.loads(line) for line in gzip.decompress((out / 'trace.jsonl.gz').read_bytes()).splitlines()]
                self.assertEqual(len(calls), fail_id or 55)
                self.assertEqual(len(rows), fail_id or 55)
                self.assertNotIn('EXCLUDED', gzip.decompress((out / 'trace.jsonl.gz').read_bytes()).decode())
                if fail_id:
                    self.assertEqual(terminal['status'], 'inconclusive')
                    self.assertEqual(terminal['passed_rpc_count'], fail_id - 1)
                    self.assertEqual(rows[-1]['code'], 'uint_count_or_token_mismatch')
                    self.assertFalse((out / 'summary.json').exists())
                else:
                    self.assertEqual(terminal['status'], 'metadata_mapping_compatible_conversion_unproven')
                    summary = json.loads((out / 'summary.json').read_bytes())
                    self.assertEqual(len(summary['observations']), 55)
                    self.assertEqual(summary['compiled_source_equivalence'], 'unverified')
                class Finished:
                    exitcode = 0
                    def start(self): pass
                    def join(self, seconds): pass
                    def is_alive(self): return False
                c.supervise(Finished(), time.monotonic() + 1, out, '0' * 64)
                supervisor = json.loads((out / 'supervisor.json').read_bytes())
                self.assertTrue(supervisor['terminal_exists'])
                self.assertEqual(supervisor['status'], 'worker_finished')


if __name__ == '__main__':
    unittest.main()
