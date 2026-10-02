import copy
import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('transition', ROOT/'scripts/aave_state_transition_v1.py')
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
ORACLE = '0x'+'11'*20
SOURCE = '0x'+'22'*20


def words(*values):
    return '0x'+''.join(format(value % 2**256, '064x') for value in values)


def abi_string(value):
    raw = value.encode()
    return words(32, len(raw))+raw.hex().ljust((len(raw)+31)//32*64, '0')


def branch(setup, with_prefix, hf):
    context = s.o.context(setup['block'])
    context['timestamp'] = context.pop('time')
    calls = []
    if with_prefix:
        rec = setup['prefix_receipt']
        calls.append(dict(status='0x1', gasUsed=rec['gasUsed'], logs=copy.deepcopy(rec['logs']), returnData='0x'))
    calls.extend([
        dict(status='0x1', gasUsed=hex(100000), logs=[], returnData=words(12000000000, 10000000000, 0, 8000, 7500, hf)),
        dict(status='0x1', gasUsed=hex(30000), logs=[], returnData=words(1400000000 if with_prefix else 1500000000)),
    ])
    return [dict(context, calls=calls)]


class TransitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = s.inputs()

    def fixture(self):
        setup = copy.deepcopy(self.original)
        values = dict(chain='0x1', parent=setup['parent'], parent_recheck=setup['parent'], event_recheck=setup['block'],
            provider_oracle='0x'+s.word_address(ORACLE), oracle_unit=words(10**8), collateral_source='0x'+s.word_address(SOURCE),
            source_description=abi_string('LINK / USD'), source_decimals=words(8),
            source_aggregator='0x'+s.word_address(setup['answer_emitter']), source_round=words(10, 1500000000, 100, 100, 10),
            without_prefix_views=branch(setup, False, 10**18), with_prefix_views=branch(setup, True, 10**18-1))
        seen = []
        def rpc(name, method, params, allow_unavailable=False):
            seen.append((name, method, copy.deepcopy(params), allow_unavailable))
            return copy.deepcopy(values[name])
        return setup, values, seen, rpc

    def test_probe_nonce_context_and_original_prefix_preserved(self):
        original = copy.deepcopy(self.original['original_params'])
        prefix = original[0]['blockStateCalls'][0]['calls'][0]
        for flag in (False, True):
            params = s.probe_params(self.original, ORACLE, flag)
            self.assertEqual(params[1], original[1])
            self.assertEqual({k: v for k, v in params[0].items() if k != 'blockStateCalls'},
                             {k: v for k, v in original[0].items() if k != 'blockStateCalls'})
            state = params[0]['blockStateCalls'][0]
            self.assertEqual({k: v for k, v in state.items() if k != 'calls'},
                             {k: v for k, v in original[0]['blockStateCalls'][0].items() if k != 'calls'})
            calls = state['calls']
            if flag: self.assertEqual(calls[0], prefix)
            for i, call in enumerate(calls[int(flag):]):
                self.assertEqual(s.h.quantity(call['nonce']), s.h.quantity(prefix['nonce'])+int(flag)+i)
                for key in ('from', 'chainId', 'maxFeePerGas', 'maxPriorityFeePerGas'):
                    self.assertEqual(call[key], prefix[key])
                self.assertEqual(call['value'], '0x0')
                self.assertEqual(call['accessList'], [])
                self.assertEqual(call['to'], s.o.c.POOL if i == 0 else ORACLE)
        self.assertEqual(self.original['original_params'], original)

    def test_complete_fixed_manifest_and_necessary_crossing(self):
        setup, values, seen, rpc = self.fixture()
        result = s.collect(rpc, setup)
        self.assertTrue(result['necessary_eligibility_crossed'])
        self.assertTrue(result['parent_source_aggregator_matches_emitter'])
        self.assertFalse(result['parent_direct_source_matches_emitter'])
        self.assertFalse(result['selected_price_caused_health_crossing'])
        self.assertFalse(result['post_prefix_oracle_wiring_verified'])
        self.assertFalse(result['economics'])
        self.assertFalse(result['probe_sender_control_claimed'])
        self.assertEqual(result['supplied_gas_upper_bound'], 4930020)
        self.assertEqual([row[0] for row in seen], [row[0] for row in s.SLOTS])
        for name, method, params, optional in seen[2:9]:
            self.assertEqual(method, 'eth_call')
            self.assertEqual(params[1], dict(blockHash=setup['parent']['hash'], requireCanonical=True))
            self.assertEqual(params[0]['from'], setup['original_params'][0]['blockStateCalls'][0]['calls'][0]['from'])
            self.assertEqual(optional, name in s.OPTIONAL)

    def test_debt_and_exact_threshold_matter(self):
        for debt, hf in ((0, 10**18-1), (1, 10**18), (1, 10**18+1)):
            setup, values, seen, rpc = self.fixture()
            values['with_prefix_views'][0]['calls'][1]['returnData'] = words(10, debt, 0, 8000, 7500, hf)
            with self.subTest(debt=debt, hf=hf): self.assertFalse(s.collect(rpc, setup)['necessary_eligibility_crossed'])

    def test_optional_errors_null_and_bad_schema_stay_unknown(self):
        setup, values, seen, rpc = self.fixture()
        values.update(source_description=None, source_decimals=words(256),
                      source_aggregator=dict(rpc_unavailable=-32000), source_round=words(1, 2))
        result = s.collect(rpc, setup)
        self.assertTrue(all(not row['available'] for row in result['parent_source_metadata'].values()))
        self.assertIsNone(result['parent_source_aggregator_matches_emitter'])
        self.assertTrue(result['necessary_eligibility_crossed'])

    def test_abi_signed_answer_and_canonical_string(self):
        self.assertEqual(s.round_words(words(3, -123, 1, 2, 3))['answer_signed'], '-123')
        self.assertEqual(s.round_words(words(3, 2**254, 1, 2, 3))['answer_signed'], str(2**254))
        self.assertEqual(s.string_word(abi_string('LINK / USD')), 'LINK / USD')
        for raw in (abi_string('a')[:-2]+'01', words(0, 0), abi_string('a')+'00', abi_string('x'*257)):
            with self.subTest(raw=raw[:30]), self.assertRaises(s.Refusal): s.string_word(raw)
        with self.assertRaises(s.Refusal): s.round_words(words(2**80, 1, 2, 3, 1))

    def test_context_and_prefix_receipt_change_rejected(self):
        for kind in ('context', 'conflicting_alias', 'prefix_gas', 'prefix_log', 'parent', 'transactions'):
            setup, values, seen, rpc = self.fixture()
            simulation = values['with_prefix_views'][0]
            if kind == 'context': simulation['timestamp'] = '0x1'
            if kind == 'conflicting_alias': simulation['time'] = '0x1'
            if kind == 'prefix_gas': simulation['calls'][0]['gasUsed'] = hex(187113)
            if kind == 'prefix_log': simulation['calls'][0]['logs'][0]['data'] = '0x01'
            if kind == 'parent': values['parent_recheck'] = dict(values['parent'], hash='0x'+'bb'*32)
            if kind == 'transactions':
                values['event_recheck'] = copy.deepcopy(values['event_recheck'])
                values['event_recheck']['transactions'][0] = '0x'+'bb'*32
            with self.subTest(kind=kind), self.assertRaises((s.Refusal, s.o.Refusal, s.h.Refusal)):
                s.collect(rpc, setup)

    def test_probe_failure_missing_logs_bad_health_or_gas_rejected(self):
        for kind in ('failed', 'missing_logs', 'event', 'short_health', 'gas', 'price'):
            setup, values, seen, rpc = self.fixture()
            calls = values['without_prefix_views'][0]['calls']
            if kind == 'failed': calls[0].update(status='0x0', error={'message': 'reverted'})
            if kind == 'missing_logs': del calls[0]['logs']
            if kind == 'event': calls[0]['logs'] = setup['prefix_receipt']['logs'][:1]
            if kind == 'short_health': calls[0]['returnData'] = words(1)
            if kind == 'gas': calls[0]['gasUsed'] = hex(1000001)
            if kind == 'price': calls[1]['returnData'] = '0x'
            with self.subTest(kind=kind), self.assertRaises((s.Refusal, s.h.Refusal)):
                s.collect(rpc, setup)

    def test_required_oracle_source_and_unit_reject_missing_values(self):
        for name in ('provider_oracle', 'oracle_unit', 'collateral_source'):
            setup, values, seen, rpc = self.fixture()
            values[name] = words(0)
            with self.subTest(name=name), self.assertRaisesRegex(s.Refusal, 'empty_oracle_source_or_unit'):
                s.collect(rpc, setup)
            self.assertLess(len(seen), 10)

    def execute(self, root, failure=None):
        setup, values, seen, rpc = self.fixture()
        s.collect(rpc, setup)
        sent = []
        def fetch(request, cap, seconds, emit, observe, dispatch):
            index = len(sent)
            name, method, params, optional = seen[index]
            self.assertEqual(request, dict(jsonrpc='2.0', id=index+1, method=method, params=params))
            dispatch()
            sent.append(request)
            status = 403 if failure == 'http' and index == 2 else 200
            observe(status, s.encode(dict(status=status, headers=[])))
            if failure in ('rpc', 'optional_rpc') and index == (5 if failure == 'optional_rpc' else 2):
                raw = s.encode(dict(jsonrpc='2.0', id=index+1, error=dict(code=-32000, message='unavailable')))
            elif failure == 'sentinel' and index == 0: raw = b'x'*(cap+1)
            elif status == 403: raw = b'bounded HTTP refusal'
            else: raw = s.encode(dict(jsonrpc='2.0', id=index+1, result=values[name]))
            for at in range(0, len(raw), 97): emit(raw[at:at+97])
            if len(raw) > cap: raise s.h.Refusal('response_cap_sentinel_retained')
            return status, len(raw)
        (root/s.BASE).mkdir(parents=True)
        with mock.patch.object(s, 'ROOT', root), mock.patch.object(s, 'verify', return_value={'pins': []}), \
             mock.patch.object(s, 'inputs', return_value=setup), mock.patch.object(s.resource, 'setrlimit'), \
             mock.patch.object(s.h, 'fetch', side_effect=fetch):
            ok = s.run('a'*64)
            with self.assertRaises(FileExistsError): s.run('a'*64)
        return ok, sent, setup

    def test_capture_exact_replay_and_exclusive_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok, sent, setup = self.execute(root)
            self.assertTrue(ok)
            self.assertEqual(len(sent), 13)
            out = root/s.OUT
            result, body, raw = s.replay(out/'raw', setup)
            terminal = s.decode((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['retained_body_bytes'], body)
            self.assertEqual(terminal['raw_bytes'], raw)
            self.assertTrue(result['necessary_eligibility_crossed'])
            self.assertEqual(len(list((out/'raw').iterdir())), 52)
            request_path = out/'raw/01.request.json'
            original_request = request_path.read_bytes()
            changed = s.decode(original_request)
            changed['allow_unavailable'] = True
            request_path.write_bytes(s.encode(changed))
            with self.assertRaisesRegex(s.t.Refusal, 'request_manifest'): s.replay(out/'raw', setup)
            request_path.write_bytes(original_request)
            (out/'raw/01.body').write_bytes(b'{}')
            with self.assertRaisesRegex(s.t.Refusal, 'incomplete_rpc'): s.replay(out/'raw', setup)

    def test_optional_rpc_error_allows_complete_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok, sent, setup = self.execute(root, 'optional_rpc')
            self.assertTrue(ok)
            result, _, _ = s.replay(root/s.OUT/'raw', setup)
            self.assertEqual(result['parent_source_metadata']['source_description'], dict(available=False, reason='rpc_error', code=-32000))

    def test_transport_failures_preserve_evidence_and_stop(self):
        for failure in ('http', 'rpc', 'sentinel'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ok, sent, setup = self.execute(root, failure)
                self.assertFalse(ok)
                out = root/s.OUT
                self.assertEqual(len(sent), 1 if failure == 'sentinel' else 3)
                self.assertEqual(s.decode((out/'terminal.json').read_bytes())['status'], 'unavailable')
                self.assertFalse((out/'projection.json').exists())
                if failure == 'sentinel': self.assertEqual((out/'raw/01.body').stat().st_size, 4097)
                with self.assertRaisesRegex(s.t.Refusal, 'raw_file_manifest'): s.replay(out/'raw', setup)

    def test_reservation_prevents_dispatch(self):
        for key in ('raw_bytes', 'body_bytes'):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                caps = dict(s.CAPS, **{key: 100})
                capture = s.t.Capture(Path(tmp)/'raw', s.SLOTS, caps, s.o.c, time.monotonic(), s.reason)
                with mock.patch.object(s.h, 'fetch') as fetch, self.assertRaisesRegex(s.t.Refusal, 'reserve_before_dispatch'):
                    capture.rpc('chain', 'eth_chainId', [])
                fetch.assert_not_called()
                self.assertEqual(capture.attempts, 0)
                self.assertEqual(list(capture.path.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
