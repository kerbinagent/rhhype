import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ordered', ROOT/'scripts/aave_ordered_replay_v1.py')
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)


def word(n):
    return '0x' + format(n, '064x')


def address(n):
    return '0x' + format(n, '040x')


def log(asset, sender, recipient, amount, index=1, logindex=2):
    return dict(address=asset, topics=[o.TRANSFER, word(sender), word(recipient)],
                data=word(amount), removed=False, blockHash=word(100), blockNumber='0x64',
                transactionHash=word(1000+index), transactionIndex=hex(index), logIndex=hex(logindex))


class Fixture:
    def __init__(self):
        parent = dict(number='0x63', hash=word(99), parentHash=word(98), stateRoot=word(900),
                      timestamp='0x1000', gasLimit=hex(30000000), baseFeePerGas='0xa',
                      miner=address(4), mixHash=word(777), transactions=[word(999)])
        block = dict(parent, number='0x64', hash=word(100), parentHash=word(99), stateRoot=word(901),
                     timestamp='0x100c', transactions=[word(1000), word(1001)])
        self.txs = []
        for index in range(2):
            tx = dict(hash=word(1000+index), blockHash=word(100), blockNumber='0x64',
                      transactionIndex=hex(index), type='0x2' if index else '0x0',
                      to=address(3 if index else 6), input='0x12345678', gas=hex(50000),
                      nonce=hex(7+index), value='0x0', gasPrice='0xc', chainId='0x1',
                      **{'from': address(2 if index else 5)})
            if index:
                tx.update(maxFeePerGas='0x14', maxPriorityFeePerGas='0x2', accessList=[])
            self.txs.append(tx)
        self.receipts = []
        regular = [[log(address(10), 5, 6, 8, 0, 0)],
                   [log(address(11), 9, 3, 500), log(address(11), 3, 9, 500, logindex=3)]]
        for i, gas in enumerate((21000, 40000)):
            self.receipts.append(dict(transactionHash=word(1000+i), blockHash=word(100),
                blockNumber='0x64', transactionIndex=hex(i), status='0x1', gasUsed=hex(gas),
                cumulativeGasUsed=hex(gas if i == 0 else 61000), effectiveGasPrice='0xc',
                logs=regular[i], to=self.txs[i]['to'], **{'from': self.txs[i]['from']}))
        self.baseline = dict(block=block, parent=parent, event={'transaction_index': 1},
                             target_receipt=self.receipts[1])
        calls = [dict(status='0x1', gasUsed=rec['gasUsed'], returnData='0x', logs=copy.deepcopy(rec['logs']))
                 for rec in self.receipts]
        calls[1]['logs'].extend([log(o.ETH, 8, 3, 1000), log(o.ETH, 3, 2, 300), log(o.ETH, 3, 4, 200)])
        self.simulated = [dict(block, calls=calls)]
        self.requests = []

    def __call__(self, name, method, params):
        self.requests.append((name, method, copy.deepcopy(params)))
        values = dict(chain='0x1', parent=self.baseline['parent'], parent_recheck=self.baseline['parent'],
                      event_recheck=self.baseline['block'], prefix_tx=self.txs[0], target_tx=self.txs[1],
                      prefix_receipt=self.receipts[0], simulate=self.simulated)
        return copy.deepcopy(values[name])


class OrderedTests(unittest.TestCase):
    def test_retained_baseline_selects_exact_first_event(self):
        baseline = o.load_baseline()
        self.assertEqual(baseline['event']['transaction_hash'], o.SPEC['target'])
        self.assertEqual(baseline['block']['transactions'][:2], [o.SPEC['prefix'], o.SPEC['target']])
        self.assertEqual(baseline['event']['transaction_index'], 1)

    def test_original_calls_order_block_context_and_fee_accounting(self):
        f = Fixture()
        result = o.collect(f, f.baseline)
        self.assertEqual([r[0] for r in f.requests], [s[0] for s in o.SLOTS])
        name, method, params = f.requests[5]
        self.assertEqual(method, 'eth_simulateV1')
        self.assertEqual(params[1], '0x63')
        payload = params[0]
        self.assertIs(payload['validation'], True)
        self.assertIs(payload['traceTransfers'], True)
        self.assertIs(payload['returnFullTransactions'], False)
        block = payload['blockStateCalls'][0]
        self.assertEqual(set(block), {'blockOverrides', 'calls'})
        self.assertEqual(block['blockOverrides']['time'], '0x100c')
        before, target = block['calls']
        self.assertEqual(before['nonce'], '0x7')
        self.assertEqual(before['gasPrice'], '0xc')
        self.assertNotIn('accessList', before)
        self.assertEqual(target['nonce'], '0x8')
        self.assertEqual(target['maxPriorityFeePerGas'], '0x2')
        self.assertEqual(target['accessList'], [])
        self.assertNotIn('gasPrice', target)
        flow = result['target_flows']
        self.assertEqual(flow['conditional_group_event_net_raw'][o.ETH], '800')
        self.assertEqual(flow['conditional_group_event_net_raw'][address(11)], '0')
        self.assertEqual(flow['target_transaction_gas_fee_wei'], '480000')
        self.assertEqual(flow['conditional_group_native_after_target_gas_wei'], '-479200')
        self.assertFalse(flow['realized_profit'])
        self.assertFalse(result['whole_block_state_root_reproduced'])

    def test_type_one_access_list_preserved_and_unknown_types_rejected(self):
        f = Fixture()
        tx = dict(f.txs[0], type='0x1', accessList=[dict(address=address(11), storageKeys=[word(7)])])
        args = o.call_args(tx, f.baseline['block'], 0)
        self.assertEqual(args['accessList'], tx['accessList'])
        for typ in (3, 4, 5):
            with self.subTest(typ=typ), self.assertRaisesRegex(o.Refusal, 'unsupported_transaction_type'):
                o.call_args(dict(tx, type=hex(typ)), f.baseline['block'], 0)
        with self.assertRaises(o.h.Refusal):
            o.call_args(dict(tx, to=None), f.baseline['block'], 0)

    def test_identity_nonce_calldata_and_gas_bounds(self):
        f = Fixture()
        for key, value in [('hash', word(9)), ('blockHash', word(9)), ('transactionIndex', '0x0'),
                           ('nonce', hex(2**64)), ('gas', hex(6000001)),
                           ('input', '0x'+'aa'*16385), ('chainId', '0x2')]:
            with self.subTest(key=key), self.assertRaises((o.Refusal, o.h.Refusal)):
                o.call_args(dict(f.txs[1], **{key: value}), f.baseline['block'], 1)

    def test_divergence_never_yields_accounting(self):
        for change in ('gas', 'logs', 'context', 'missing_native', 'failed_call'):
            f = Fixture()
            if change == 'gas': f.simulated[0]['calls'][1]['gasUsed'] = hex(40001)
            if change == 'logs': f.simulated[0]['calls'][1]['logs'][0]['data'] = word(501)
            if change == 'context': f.simulated[0]['baseFeePerGas'] = '0xb'
            if change == 'missing_native': f.simulated[0]['calls'][1]['logs'] = f.receipts[1]['logs']
            if change == 'failed_call': f.simulated[0]['calls'][0]['status'] = '0x0'
            with self.subTest(change=change), self.assertRaises(o.Refusal):
                o.collect(f, f.baseline)
            self.assertEqual(len(f.requests), 6)

    def test_receipt_prefix_and_effective_price_checks_before_simulate(self):
        for field, value in [('cumulativeGasUsed', hex(61001)), ('effectiveGasPrice', '0xd'),
                             ('from', address(99)), ('transactionIndex', '0x0')]:
            f = Fixture()
            f.receipts[1][field] = value
            with self.subTest(field=field), self.assertRaises(o.Refusal):
                o.collect(f, f.baseline)
            self.assertEqual(len(f.requests), 5)

    def test_simulated_header_aliases_and_noncanonical_native_address(self):
        f = Fixture()
        sim = f.simulated[0]
        sim['feeRecipient'] = sim.pop('miner')
        sim['prevRandao'] = sim.pop('mixHash')
        self.assertEqual(o.collect(f, f.baseline)['status'], 'ordered_receipts_matched')
        f = Fixture()
        f.simulated[0]['calls'][1]['logs'][-1]['topics'][1] = word(2**160)
        with self.assertRaisesRegex(o.c.Refusal, 'noncanonical_address_word'):
            o.collect(f, f.baseline)

    def test_group_deduplicates_sender_equal_to_recipient(self):
        rows = [o.log_content(log(o.ETH, 8, 3, 1000))]
        result = o.flow_accounting(rows, {'from': address(3), 'to': address(3)}, 100)
        self.assertEqual(result['conditional_group_native_after_target_gas_wei'], '900')
        self.assertEqual(len(result['selected_addresses']), 1)

    def test_raw_replay_manifest_and_truncation(self):
        fixture = Fixture()
        with tempfile.TemporaryDirectory() as tmp:
            frames = o.Frames(Path(tmp))
            n = 0
            def rpc(name, method, params):
                nonlocal n
                n += 1
                value = fixture(name, method, params)
                raw = o.encode(dict(jsonrpc='2.0', id=n, result=value))
                frames.append(b'B', o.encode(dict(name=name, request=dict(jsonrpc='2.0', id=n, method=method, params=params))))
                frames.append(b'H', o.encode(dict(status=200, headers=[])))
                for at in range(0, len(raw), 4096): frames.append(b'D', raw[at:at+4096])
                frames.append(b'E', o.encode(dict(error=None, http_status=200, dispatch_attempted=True,
                    response_bytes=len(raw), response_sha256=o.sha(raw))))
                return value
            expected = o.collect(rpc, fixture.baseline)
            frames.close()
            result, pin, total = o.replay(frames.path, fixture.baseline)
            self.assertEqual(result, expected)
            self.assertGreater(total, 0)
            raw = frames.path.read_bytes()
            frames.path.write_bytes(raw.replace(b'prefix_tx', b'target_tx', 1))
            with self.assertRaisesRegex(o.Refusal, 'request_manifest'):
                o.replay(frames.path, fixture.baseline)
            frames.path.write_bytes(raw[:-1])
            with self.assertRaises(o.Refusal): o.replay(frames.path, fixture.baseline)

    def _run(self, root, failure=None):
        fixture, queue = Fixture(), []
        def prepare(name, method, params):
            value = fixture(name, method, params)
            queue.append((method, params, value))
            return value
        o.collect(prepare, fixture.baseline)
        requests = []
        def fetch(request, cap, seconds, emit, observe, dispatch):
            index = len(requests)
            requests.append(request)
            method, params, value = queue[index]
            self.assertEqual(request, dict(jsonrpc='2.0', id=index+1, method=method, params=params))
            dispatch()
            code = 403 if failure == 'http' and index == 5 else 200
            observe(code, o.encode(dict(status=code, headers=[])))
            if code == 403: raw = b'bounded HTTP rejection'
            elif failure == 'rpc' and index == 5:
                raw = o.encode(dict(jsonrpc='2.0', id=6, error=dict(code=-32601, message='not available')))
            else: raw = o.encode(dict(jsonrpc='2.0', id=index+1, result=value))
            if failure == 'sentinel' and index == 0:
                raw = b'x' * (cap+1)
            for at in range(0, len(raw), 97): emit(raw[at:at+97])
            if len(raw) > cap: raise o.h.Refusal('response_cap_sentinel_retained')
            return code, len(raw)
        (root/'reports/aave-ordered-replay-v1').mkdir(parents=True)
        with mock.patch.object(o, 'ROOT', root), mock.patch.object(o, 'verify', return_value={'pins': []}), \
             mock.patch.object(o, 'load_baseline', return_value=fixture.baseline), \
             mock.patch.object(o.resource, 'setrlimit'), mock.patch.object(o.h, 'fetch', side_effect=fetch):
            result = o.run('a'*64)
            with self.assertRaises(FileExistsError): o.run('a'*64)
        return result, requests

    def test_run_and_claim_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok, requests = self._run(root)
            self.assertTrue(ok)
            self.assertEqual(len(requests), 8)
            terminal = o.decode((root/o.OUT/'terminal.json').read_bytes())
            self.assertEqual(terminal['status'], 'ordered_receipts_matched')

    def test_http_and_rpc_failures_preserve_evidence_without_retry(self):
        for failure in ('http', 'rpc', 'sentinel'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ok, requests = self._run(root, failure)
                self.assertFalse(ok)
                self.assertEqual(len(requests), 1 if failure == 'sentinel' else 6)
                out = root/o.OUT
                self.assertFalse((out/'projection.json').exists())
                terminal = o.decode((out/'terminal.json').read_bytes())
                self.assertEqual(terminal['status'], 'unavailable')
                raw = (out/'responses.frames').read_bytes()
                self.assertIn(b'x'*4096 if failure == 'sentinel' else
                              (b'bounded HTTP rejection' if failure == 'http' else b'not available'), raw)
                self.assertLess(len(raw), o.CAPS['raw_bytes'])


if __name__ == '__main__':
    unittest.main()
