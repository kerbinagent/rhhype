import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('v4fees', ROOT / 'scripts/uniswap_v4_fee_inventory_v1.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def word(n):
    return '0x' + format(n, '064x')


class V4FeeTests(unittest.TestCase):
    def fixture(self):
        assets = m.inputs()
        header = m.decode((ROOT / 'reports/uniswap-fee-collect-v1/run-v1/raw/06.body').read_bytes())['result']
        manager = '0x' + 'b' * 40
        values = dict(chain='0x1', block=header, recheck=copy.deepcopy(header), manager=word(int(manager, 16)),
                      token_jar=word(int(m.JAR, 16)), controller=word(int(m.ADAPTER, 16)),
                      releaser=word(int(m.FIREPIT, 16)), threshold=word(4000 * 10**18), nonce=word(1500), collect='0x')
        for i, address in enumerate(assets):
            values['accrued_' + str(i)] = word(i + 1)
            values['jar_' + str(i)] = '0x9' if address == m.ZERO else word(9)
        seen = []

        def rpc(name, method, params, allow_unavailable=False):
            seen.append((name, method, copy.deepcopy(params), allow_unavailable))
            return copy.deepcopy(values[name])
        return assets, values, seen, rpc

    def test_fixed_currency_hash_scope_native_and_void_collection_abi(self):
        assets, values, seen, rpc = self.fixture()
        p = m.collect(rpc, assets)
        self.assertEqual([x[0] for x in seen], [x[0] for x in m.SLOTS])
        self.assertEqual(len(seen), 50)
        calls = [x for x in seen if x[1] == 'eth_call']
        self.assertEqual(len(calls), 46)
        self.assertEqual(sum(int(x[2][0]['gas'], 16) for x in calls), 16500000)
        state = dict(blockHash=p['block']['hash'], requireCanonical=True)
        for x in seen:
            if x[1] in ('eth_call', 'eth_getBalance'):
                self.assertEqual(x[2][1], state)
        native = [x for x in seen if x[1] == 'eth_getBalance']
        self.assertEqual([x[2] for x in native], [[m.JAR, state]])
        data = calls[-1][2][0]['input']
        self.assertEqual(data[:10], m.c.keccak_hex('collect((address,uint256)[])')[:10])
        words = [data[i:i+64] for i in range(10, len(data), 64)]
        self.assertEqual(list(map(lambda x: int(x, 16), words[:2])), [32, 20])
        self.assertEqual(['0x' + w[-40:] for w in words[2::2]], assets)
        self.assertEqual(set(words[3::2]), {'0' * 64})
        self.assertTrue(p['collection_call']['available'])
        self.assertEqual([int(r[3]) for r in p['rows']], list(range(10, 30)))
        self.assertFalse(p['post_state_observed'])
        self.assertFalse(p['economics'])
        self.assertFalse(p['old_state_combined'])
        self.assertLess(len(m.encode(dict(p, plan_sha256='a'*64))), 8192)

    def test_unknown_not_zero_void_failure_suppresses_sums_and_uint_bound(self):
        assets, values, seen, rpc = self.fixture()
        values['accrued_0'] = {'rpc_unavailable': -32000}
        values['jar_1'] = '0x'
        values['accrued_2'] = word(2**256 - 1)
        values['accrued_3'] = word(0)
        p = m.collect(rpc, assets)
        self.assertEqual([x[3] for x in p['rows'][:4]], [None, None, None, '9'])
        values['collect'] = {'rpc_unavailable': 3}
        p = m.collect(rpc, assets)
        self.assertEqual([x[3] for x in p['rows']], [None] * 20)
        self.assertFalse(p['collection_call']['available'])
        values['collect'] = word(0)
        self.assertFalse(m.collect(rpc, assets)['collection_call']['available'])
        # Two valid, very wide uint256 operands can overflow the model sum.
        for i, address in enumerate(assets):
            values['accrued_' + str(i)] = word(2**256 - 1)
            values['jar_' + str(i)] = hex(2**256 - 1) if address == m.ZERO else word(2**256 - 1)
        values['collect'] = '0x'
        p = m.collect(rpc, assets)
        self.assertLess(len(m.encode(dict(p, plan_sha256='a'*64))), 8192)
        self.assertTrue(all(row[3] is None for row in p['rows']))

    def test_controller_or_recipient_mismatch_stops_before_collection(self):
        for name in ('manager', 'token_jar', 'controller', 'releaser'):
            assets, values, seen, rpc = self.fixture()
            values[name] = word(0)
            with self.subTest(name=name), self.assertRaises(m.Refusal):
                m.collect(rpc, assets)
            self.assertNotIn('collect', [x[0] for x in seen])
        assets, values, seen, rpc = self.fixture()
        values['controller'] = {'rpc_unavailable': -32000}
        with self.assertRaisesRegex(m.Refusal, 'configuration_unknown_controller'):
            m.collect(rpc, assets)
        self.assertEqual(len(seen), 8)

    def execute(self, root, failure=None):
        assets, values, seen, rpc = self.fixture()
        m.collect(rpc, assets)
        sent = []
        if failure == 'controller':
            values['controller'] = word(0)
        if failure == 'reorg':
            values['recheck']['stateRoot'] = '0x' + '88' * 32

        def fetch(request, cap, seconds, emit, observe, dispatch):
            i = len(sent)
            name, method, params, optional = seen[i]
            self.assertEqual(request, dict(jsonrpc='2.0', id=i+1, method=method, params=params))
            dispatch()
            sent.append(request)
            raw = b'x' * (cap + 1) if failure == 'overflow' and name == 'block' else m.encode(dict(jsonrpc='2.0', id=i+1, result=values[name]))
            padding = 1000 if failure == 'raw_reserve' else 512
            observe(200, m.encode(dict(status=200, headers=[['x-test-padding', 'x' * padding]])))
            for j in range(0, len(raw), 1024):
                emit(raw[j:j+1024])
            if len(raw) > cap:
                raise m.h.Refusal('response_cap_sentinel_retained')
            return 200, len(raw)
        (root / m.BASE).mkdir(parents=True)
        with mock.patch.object(m, 'ROOT', root), mock.patch.object(m, 'verify', return_value={}), \
                mock.patch.object(m, 'inputs', return_value=assets), mock.patch.object(m.resource, 'setrlimit'), \
                mock.patch.object(m.h, 'fetch', side_effect=fetch):
            ok = m.run('a' * 64)
            with self.assertRaises(FileExistsError):
                m.run('a' * 64)
        return ok, sent, assets

    def test_full_capture_reservation_replay_and_manifest_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok, sent, assets = self.execute(root)
            self.assertTrue(ok, (root / m.OUT / 'terminal.json').read_text())
            self.assertEqual(len(sent), 50)
            out = root / m.OUT
            p, body, raw = m.replay(out / 'raw', assets)
            terminal = m.decode((out / 'terminal.json').read_bytes())
            self.assertEqual((body, raw), (terminal['body_bytes'], terminal['raw_bytes']))
            self.assertEqual(len(list((out / 'raw').iterdir())), 200)
            path = out / 'raw/03.request.json'
            value = m.decode(path.read_bytes())
            value['request']['params'][1]['requireCanonical'] = False
            path.write_bytes(m.encode(value))
            with self.assertRaisesRegex(m.t.Refusal, 'request_manifest'):
                m.replay(out / 'raw', assets)

    def test_failure_sentinel_config_and_reorg_retained_without_projection(self):
        for failure, attempts in [('overflow', 2), ('controller', 8), ('reorg', 50), ('raw_reserve', 49)]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ok, sent, assets = self.execute(root, failure)
                self.assertFalse(ok)
                self.assertEqual(len(sent), attempts)
                out = root / m.OUT
                self.assertFalse((out / 'projection.json').exists())
                terminal = m.decode((out / 'terminal.json').read_bytes())
                self.assertEqual(terminal['requests_attempted'], attempts)
                if failure == 'overflow':
                    self.assertEqual((out / 'raw/02.body').stat().st_size, 32769)
                if failure == 'raw_reserve':
                    self.assertEqual(terminal['error'], 'reserve_before_dispatch')
                    self.assertFalse((out / 'raw/50.request.json').exists())


if __name__ == '__main__':
    unittest.main()
