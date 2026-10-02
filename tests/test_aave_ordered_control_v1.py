import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('control', ROOT/'scripts/aave_ordered_control_v1.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def revert(message):
    raw = message.encode()
    return '0x08c379a0' + format(32, '064x') + format(len(raw), '064x') + raw.hex().ljust((len(raw)+31)//32*64, '0')


def simulation(setup, successful=False):
    values = c.o.context(setup['block'])
    values['timestamp'] = values.pop('time')
    if successful:
        rec = setup['target_receipt']
        call = dict(status='0x1', gasUsed=rec['gasUsed'], logs=copy.deepcopy(rec['logs']), returnData='0x')
    else:
        call = dict(status='0x0', gasUsed=hex(100000), returnData=revert('45'), logs=[],
                    error=dict(message='execution reverted: 45'))
    return [dict(values, calls=[call])]


class ControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = c.inputs()

    def fixture(self, successful=False):
        setup = copy.deepcopy(self.original)
        results = dict(chain='0x1', parent=setup['parent'], parent_recheck=setup['parent'],
                       event_recheck=setup['block'], without_prefix=simulation(setup, successful))
        calls = []
        def rpc(name, method, params):
            calls.append((name, method, copy.deepcopy(params)))
            return copy.deepcopy(results[name])
        return setup, results, calls, rpc

    def test_only_prefix_is_removed_from_original_payload(self):
        setup = self.original
        expected = copy.deepcopy(setup['original_params'])
        target = expected[0]['blockStateCalls'][0]['calls'].pop(0)
        self.assertNotEqual(target['from'], expected[0]['blockStateCalls'][0]['calls'][0]['from'])
        self.assertEqual(setup['params'], expected)
        self.assertIs(setup['params'][0]['validation'], True)
        self.assertIs(setup['params'][0]['traceTransfers'], True)
        self.assertEqual(len(setup['manifest']), 5)

    def test_revert_is_an_observed_control_outcome(self):
        setup, values, calls, rpc = self.fixture()
        result = c.collect(rpc, setup)
        self.assertEqual(result['outcome'], 'reverted_without_prefix')
        self.assertEqual(result['abi_error_string'], '45')
        self.assertFalse(result['same_receipt_matched'])
        self.assertTrue(result['hypothetical_gas_not_spent'])
        self.assertFalse(result['oracle_causality_established'])
        self.assertEqual([r[0] for r in calls], [r[0] for r in c.SLOTS])

    def test_success_and_changed_effects_distinguished(self):
        setup, values, calls, rpc = self.fixture(True)
        self.assertEqual(c.collect(rpc, setup)['outcome'], 'same_receipt_reproduced_without_prefix')
        values['without_prefix'][0]['calls'][0]['gasUsed'] = hex(790305)
        self.assertEqual(c.collect(rpc, setup)['outcome'], 'succeeded_with_different_effects')

    def test_context_change_and_logs_on_revert_rejected(self):
        for kind in ('context', 'logs', 'recheck'):
            setup, values, calls, rpc = self.fixture()
            if kind == 'context': values['without_prefix'][0]['baseFeePerGas'] = '0x1'
            if kind == 'logs': values['without_prefix'][0]['calls'][0]['logs'] = setup['target_receipt']['logs'][:1]
            if kind == 'recheck':
                values['parent_recheck'] = dict(values['parent_recheck'], hash='0x'+'aa'*32)
            with self.subTest(kind=kind), self.assertRaises((c.Refusal, c.o.Refusal)):
                c.collect(rpc, setup)

    def test_revert_abi_padding_offset_and_empty_unknown(self):
        self.assertEqual(c.error_string(revert('45')), '45')
        self.assertIsNone(c.error_string('0x'))
        self.assertIsNone(c.error_string('0x12345678'))
        for value in [revert('45')[:-2]+'01', '0x08c379a0'+'00'*64, revert('45')+'00']:
            with self.assertRaises(c.Refusal): c.error_string(value)

    def test_success_requires_logs_and_synthetic_events_are_validated(self):
        setup, values, calls, rpc = self.fixture(True)
        del values['without_prefix'][0]['calls'][0]['logs']
        with self.assertRaisesRegex(c.Refusal, 'simulation_logs'): c.collect(rpc, setup)
        setup, values, calls, rpc = self.fixture(True)
        values['without_prefix'][0]['calls'][0]['logs'].append(dict(address=c.o.ETH, topics=[], data='0x'))
        with self.assertRaisesRegex(c.o.Refusal, 'transfer_shape'): c.collect(rpc, setup)
        # Execution API failure schema permits logs to be omitted.
        setup, values, calls, rpc = self.fixture()
        del values['without_prefix'][0]['calls'][0]['logs']
        self.assertEqual(c.collect(rpc, setup)['outcome'], 'reverted_without_prefix')

    def test_failed_call_requires_structured_error(self):
        for value in (None, {}, 'reverted', {'code': True}):
            setup, values, calls, rpc = self.fixture()
            values['without_prefix'][0]['calls'][0]['error'] = value
            with self.subTest(value=value), self.assertRaisesRegex(c.Refusal, 'failed_call_error_schema'):
                c.collect(rpc, setup)
        del values['without_prefix'][0]['calls'][0]['error']
        with self.assertRaisesRegex(c.Refusal, 'failed_call_error_schema'): c.collect(rpc, setup)

    def execute(self, root, failure=None):
        setup, values, calls, rpc = self.fixture()
        dispatched = []
        def fetch(request, cap, seconds, emit, observe, dispatch):
            i = len(dispatched)
            name, method, params = setup['manifest'][i]
            self.assertEqual(request, dict(jsonrpc='2.0', id=i+1, method=method, params=params))
            dispatch()
            dispatched.append(request)
            status = 403 if failure == 'http' and i == 2 else 200
            observe(status, c.encode(dict(status=status, headers=[])))
            if failure == 'rpc' and i == 2:
                raw = c.encode(dict(jsonrpc='2.0', id=3, error=dict(code=-32601, message='unavailable')))
            elif failure == 'sentinel' and i == 0:
                raw = b'x'*(cap+1)
            elif status == 403: raw = b'bounded HTTP rejection'
            else: raw = c.encode(dict(jsonrpc='2.0', id=i+1, result=values[name]))
            for at in range(0, len(raw), 91): emit(raw[at:at+91])
            if len(raw) > cap: raise c.h.Refusal('response_cap_sentinel_retained')
            return status, len(raw)
        (root/c.BASE).mkdir(parents=True)
        with mock.patch.object(c, 'ROOT', root), mock.patch.object(c, 'verify', return_value={'pins': []}), \
             mock.patch.object(c, 'inputs', return_value=setup), mock.patch.object(c.resource, 'setrlimit'), \
             mock.patch.object(c.h, 'fetch', side_effect=fetch):
            ok = c.run('a'*64)
            with self.assertRaises(FileExistsError): c.run('a'*64)
        return ok, dispatched, setup

    def test_bounded_capture_replay_and_exclusive_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok, requests, setup = self.execute(root)
            self.assertTrue(ok)
            self.assertEqual(len(requests), 5)
            out = root/c.OUT
            result, body, raw = c.replay(out/'raw', setup)
            self.assertEqual(result['outcome'], 'reverted_without_prefix')
            terminal = c.decode((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['retained_body_bytes'], body)
            self.assertEqual(terminal['raw_bytes'], raw)
            (out/'raw/01.body').write_bytes(b'{}')
            with self.assertRaisesRegex(c.Refusal, 'incomplete_rpc'): c.replay(out/'raw', setup)

    def test_failures_preserve_raw_and_do_not_become_control_reverts(self):
        for failure in ('http', 'rpc', 'sentinel'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ok, requests, setup = self.execute(root, failure)
                self.assertFalse(ok)
                out = root/c.OUT
                self.assertEqual(len(requests), 1 if failure == 'sentinel' else 3)
                self.assertEqual(c.decode((out/'terminal.json').read_bytes())['status'], 'unavailable')
                self.assertFalse((out/'projection.json').exists())
                if failure == 'sentinel': self.assertEqual((out/'raw/01.body').stat().st_size, 4097)
                with self.assertRaisesRegex(c.Refusal, 'raw_file_manifest'): c.replay(out/'raw', setup)


if __name__ == '__main__':
    unittest.main()
