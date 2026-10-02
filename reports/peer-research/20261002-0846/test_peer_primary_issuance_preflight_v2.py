"""Synthetic fixtures only; no provider, market observations or tool installation."""
import copy
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('probe', ROOT/'scripts/peer_primary_issuance_preflight_v2.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def word(n):
    return '0x' + format(n, '064x')


def address(s):
    return '0x' + '0'*24 + s[2:].lower()


HEADER = dict(number='0x123', hash='0x'+'11'*32, parentHash='0x'+'22'*32,
    timestamp='0x456', stateRoot='0x'+'33'*32, transactions=['unrelated_history'])
SIM = [dict(number='0x124', parentHash=HEADER['hash'], baseFeePerGas='0x3b9aca00', calls=[
    dict(status='0x1', returnData=word(42), gasUsed='0x521a', logs=[]),
    dict(status='0x0', returnData='0x', gasUsed='0x520e', logs=[],
    error=dict(code=3, message='execution reverted'))])]


class Clock:
    now = 0.0
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class Wire:
    def __init__(self, clock, overrides):
        self.clock, self.overrides, self.requests = clock, overrides, []
    def __call__(self, request, timeout, limit):
        self.requests.append((copy.deepcopy(request), self.clock(), timeout, limit))
        values = ['0x1', HEADER, '0x', '0x', '0x', SIM, '0x6000',
            address('0x028271E30a695c0527A0C50cA30603feD004cDb0'), word(2), '0x6001',
            word(4), word(18), word(0), word(2**256-1), '0x6002',
            address('0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'),
            address('0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84'),
            word(4000000), word(5000000000), HEADER]
        n = request['id']
        value = self.overrides.get(n, values[n-1])
        return value(request, timeout, limit) if callable(value) else (200,
            p.encoded(dict(jsonrpc='2.0', id=n, result=value)))


class PreflightTests(unittest.TestCase):
    def setUp(self):
        original = json.loads((ROOT/p.PROPOSAL).read_bytes())['metadata_probe']
        keys = set(p.CAPS) | set(p.SCRATCH) | {'endpoint', 'endpoint_fallbacks', 'run_count'}
        self.plan = dict(status='frozen_metadata_probe', authorization=dict(
            coordinator_message='synthetic-only', raw_bytes=524288,
            source_cap_authority_message=p.SOURCE_CAP_AUTHORITY), runtime=p.RUNTIME.copy(),
            proposal=dict(path=p.PROPOSAL, sha256=p.PROPOSAL_SHA),
            allocation_amendment=p.AMENDMENT.copy(),
            additional_retained_source_allowance_bytes=p.SOURCE_ENVELOPE_ALLOWANCE,
            fixed_contracts=p.CONTRACTS.copy(), metadata_probe={k:original[k] for k in keys},
            later_economic_falsifier_requirements_not_authorized=dict(
            native_principal_arms_wei=[str(v) for v in p.ARMS]),
            source_pins=[dict(path=k, sha256=p.digest((ROOT/k).read_bytes())) for k in (p.SOURCE,p.TEST)])
        # Tiny immutable source fixtures isolate the authorization guard from package growth.
        self.source_bytes = {p.SOURCE:b'synthetic source fixture',p.TEST:b'synthetic test fixture'}
        self.plan['source_pins'] = [dict(path=k,sha256=p.digest(v)) for k,v in self.source_bytes.items()]
        self.plan['metadata_probe'].update(request_manifest_sha256=p.MANIFEST_SHA,
            synthetic_probe_sha256=p.SYNTHETIC_SHA,
            max_source_tests_protocol_and_remote_review_copies_bytes=294912)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.serial = 0
        self.out = Path(self.tmp.name)/'run'
        self.clock = Clock()

    def run_probe(self, overrides=None):
        self.wire = Wire(self.clock, overrides or {})
        raw = p.encoded(self.plan)
        original_reader = p.bounded_file
        def source_reader(path):
            name = str(Path(path).relative_to(ROOT))
            return self.source_bytes[name] if name in self.source_bytes else original_reader(path)
        with patch.object(p,'bounded_file',side_effect=source_reader):
            return p.run(self.plan, raw, self.out, expected_plan_sha=p.digest(raw),
            coordinator_authority='synthetic-only', endpoint=p.ENDPOINT,
            expected_source_sha=self.plan['source_pins'][0]['sha256'],
            expected_test_sha=self.plan['source_pins'][1]['sha256'],
            transport=self.wire, clock=self.clock, sleep=self.clock.sleep)

    def trace(self):
        return json.loads(gzip.decompress((self.out/'trace.json.gz').read_bytes()))

    def stop(self, overrides, status, calls):
        self.serial += 1
        self.out = Path(self.tmp.name)/str(self.serial)
        result = self.run_probe(overrides)
        self.assertEqual((result['status'],result['requests']), (status,calls))
        self.assertEqual(len(self.wire.requests), calls)
        self.assertEqual(json.loads((self.out/'terminal.json').read_bytes()), result)
        return result

    def test_authorization_has_no_side_effects(self):
        proposal = json.loads((ROOT/p.PROPOSAL).read_bytes())
        self.assertEqual(p.validate_plan(proposal)['requests_permitted'], 0)
        for mutation in (lambda: self.plan.update(status=proposal['status']),
            lambda: self.plan['authorization'].update(coordinator_message='wrong'),
            lambda: self.plan['source_pins'][0].update(sha256='0'*64)):
            saved = copy.deepcopy(self.plan)
            mutation()
            with self.assertRaises(p.ProbeError):
                self.run_probe()
            self.assertFalse(self.out.exists())
            self.assertEqual(self.wire.requests, [])
            self.plan = saved

    def test_semantics_cannot_change_calls_addresses_sizes(self):
        for mutation in (lambda q:q['metadata_probe'].update(request_manifest_sha256='0'*64),
            lambda q:q['metadata_probe'].update(endpoint='https://other.invalid'),
            lambda q:q['fixed_contracts'].update(curve_legacy_steth_eth='0x'+'00'*20),
            lambda q:q['metadata_probe'].update(synthetic_probe_sha256='0'*64),
            lambda q:q['later_economic_falsifier_requirements_not_authorized']['native_principal_arms_wei'].pop()):
            bad = copy.deepcopy(self.plan)
            mutation(bad)
            with self.assertRaises(p.ProbeError):
                p.validate_plan(bad)

    def test_package_cap_rejects_before_output_or_transport(self):
        self.plan['synthetic_padding'] = 'x'*60000
        with self.assertRaises(p.ProbeError) as caught:
            self.run_probe()
        self.assertEqual(caught.exception.category,p.RESOURCE)
        self.assertFalse(self.out.exists())
        self.assertEqual(self.wire.requests,[])

    def test_padded_responses_never_read_past_cumulative_budget(self):
        original = Wire.__call__
        body_lengths = []
        def padded(wire,request,timeout,limit):
            status,body = original(wire,request,timeout,limit)
            body = body.ljust(131072,b' ')[:limit]
            body_lengths.append(len(body))
            return status,body
        with patch.object(Wire,'__call__',padded):
            result = self.stop({},p.RESOURCE,8)
        self.assertEqual(body_lengths,[131072]*8)
        self.assertEqual(sum(body_lengths),1048576)
        self.assertEqual(result['total_response_bytes'],1048576)
        self.assertEqual([r[3] for r in self.wire.requests],[131073]*7+[131072])
        last = self.trace()[-1]
        self.assertEqual(last['body_read_limit'],131072)
        self.assertTrue(last['response_truncated'] and last['raw_hash_is_prefix'])
        self.assertIn('EOF unproven',result['error'])
        # Exhaustion also refuses admission independently of this conservative stop.
        probe = p.Probe(Path(self.tmp.name)/'exhausted',{},transport=self.wire,
                        clock=self.clock,sleep=self.clock.sleep)
        probe.total_response = 1048576
        with self.assertRaises(p.ProbeError):
            probe.rpc('eth_chainId',[])
        self.assertEqual(len(self.wire.requests),8)
        self.assertEqual(probe.trace,[])

    def test_twenty_calls_header_projection_no_economics(self):
        result = self.stop({}, 'metadata_compatible_full_route_unproven', 20)
        self.assertIsNone(result['economics'])
        self.assertFalse(result['full_route_proven'])
        self.assertEqual([r[1] for r in self.wire.requests], list(range(20)))
        methods = ['eth_chainId','eth_getBlockByNumber']+['eth_getCode']*3+[
            'eth_simulateV1','eth_getCode','eth_call','eth_call','eth_getCode']+[
                'eth_call']*4+['eth_getCode']+['eth_call']*4+['eth_getBlockByNumber']
        self.assertEqual([r[0]['method'] for r in self.wire.requests], methods)
        for request, _, _, bound in self.wire.requests:
            self.assertEqual(bound,131073)
            if request['method'] in ('eth_call','eth_getCode'):
                self.assertEqual(request['params'][1],dict(blockHash=HEADER['hash'],requireCanonical=True))
        self.assertNotIn('unrelated_history',json.dumps(self.trace()))
        self.assertEqual(result['metadata']['code_sha256'][p.CONTRACTS['lido_steth_proxy']],
            hashlib.sha256(bytes.fromhex('6000')).hexdigest())
        self.assertIn('out_and_back',result['reorg_limitation'])
        self.assertLessEqual(result['retained_raw_bytes'],262144)

    def test_synthetic_nonce_fees_and_sender_override(self):
        self.run_probe()
        payload = self.wire.requests[5][0]['params']
        self.assertEqual(payload[1],'0x123')
        context = payload[0]['blockStateCalls'][0]
        self.assertEqual(context['blockOverrides'],dict(baseFeePerGas='0x3b9aca00'))
        self.assertEqual(context['stateOverrides']['0x000000000000000000000000000000000000f103'],
            dict(balance='0xde0b6b3a7640000',nonce='0x0'))
        self.assertEqual(len(context['stateOverrides']),3)
        self.assertEqual([c['nonce'] for c in context['calls']],['0x0','0x1'])
        for c in context['calls']:
            self.assertEqual((c['input'],c['value'],c['gas']),('0x','0x0','0x186a0'))
            self.assertEqual((c['maxFeePerGas'],c['maxPriorityFeePerGas']),('0x77359400','0x3b9aca00'))
            self.assertNotIn('accessList',c)

    def test_unsupported_stops_before_metadata(self):
        def unsupported(*args):
            return 200,p.encoded(dict(jsonrpc='2.0',id=6,error=dict(code=-32601,message='unsupported')))
        result = self.stop({6:unsupported},p.CAPABILITY,6)
        self.assertNotIn('code_sha256',result['metadata'])
        self.assertEqual(self.trace()[-1]['response']['error']['code'],-32601)
        self.assertEqual(self.trace()[-1]['outcome'],'failed')

    def test_gas_revert_and_child_evidence(self):
        mutations = [lambda s:s[0]['calls'][0].update(gasUsed='0x12'),
            lambda s:s[0]['calls'][1].update(gasUsed='0x6'),lambda s:s[0]['calls'][1].pop('error'),
            lambda s:s[0].update(baseFeePerGas='0x1'),lambda s:s[0].update(number='0x123'),
            lambda s:s[0].update(parentHash='0x'+'55'*32),
            lambda s:s.append(copy.deepcopy(s[0])),lambda s:s[0]['calls'].pop(),
            lambda s:s[0]['calls'][0].update(returnData=word(41))]
        for mutate in mutations:
            bad = copy.deepcopy(SIM)
            mutate(bad)
            self.stop({6:bad},p.CAPABILITY,6)

    def test_identity_abi_and_reorg(self):
        cases = [(8,address('0x'+'77'*20),p.IDENTITY),(9,'0x02',p.IDENTITY),
            (13,word(2),p.IDENTITY),(16,'0x'+'01'*32,p.IDENTITY),
            (20,{**HEADER,'hash':'0x'+'44'*32},'canonicality_unavailable')]
        for call,value,status in cases:
            self.stop({call:value},status,call)

    def test_four_fixed_size_eligibilities(self):
        for pause,limit,expected in [(0,10**17,[True,True,False,False]),
            (1,2**256-1,[False]*4),(0,0,[False]*4)]:
            result = self.stop({13:word(pause),14:word(limit)},'issuance_eligibility_unavailable',20)
            rows = result['metadata']['native_arm_eligibility']
            self.assertEqual([r['principal_wei'] for r in rows],
                ['10000000000000000','100000000000000000','1000000000000000000','10000000000000000000'])
            self.assertEqual([r['eligible'] for r in rows],expected)

    def test_oversize_partial_and_retention_caps_preserve_receipts(self):
        raw = b'x'*131073
        self.stop({2:lambda *args:(200,raw)},p.RESOURCE,2)
        last = self.trace()[-1]
        self.assertTrue(last['response_truncated'] and last['raw_hash_is_prefix'])
        self.assertEqual(last['raw_response_sha256'],hashlib.sha256(raw).hexdigest())
        def partial(*args):
            raise p.TransportError('interrupted',b'partial',200)
        self.stop({3:partial},p.RESOURCE,3)
        self.assertEqual(self.trace()[-1]['raw_response_bytes'],7)
        code = '0x'+'00'*65500
        self.stop({7:code,10:code},p.RESOURCE,10)
        self.assertTrue(self.trace()[-1]['response_omitted_for_raw_cap'])
        self.assertLessEqual((self.out/'trace.json.gz').stat().st_size,262144)

    def test_deadline_cleanup_receipt(self):
        def slow(request,timeout,limit):
            self.clock.now += 12.001
            return 200,p.encoded(dict(jsonrpc='2.0',id=request['id'],result='0x1'))
        self.stop({1:slow},p.RESOURCE,1)
        self.clock = Clock()
        original = Wire.__call__
        def boundary(wire,request,timeout,limit):
            value = original(wire,request,timeout,limit)
            wire.clock.now += min(12,timeout)
            return value
        with patch.object(Wire,'__call__',boundary):
            result = self.stop({},p.RESOURCE,15)
        self.assertEqual(result['elapsed_seconds'],170)
        self.assertEqual(self.trace()[-1]['end_elapsed_seconds'],170)
        self.clock = Clock()
        self.clock.sleep = lambda seconds:setattr(self.clock,'now',180)
        self.stop({},p.RESOURCE,1)

    def test_nonfinite_and_unicode_errors_leave_terminal(self):
        bad = b'{"jsonrpc":"2.0","id":1,"result":"0x1","unused":{"value":1e999}}'
        self.stop({1:lambda *args:(200,bad)},p.RESOURCE,1)
        self.assertEqual(self.trace()[-1]['raw_response_sha256'],hashlib.sha256(bad).hexdigest())
        def emoji_error(request,*args):
            raw = json.dumps(dict(jsonrpc='2.0',id=request['id'],
                error=dict(code=-32000,message='\U0001f600'*30000)),ensure_ascii=False).encode()
            return 200,raw
        self.stop({2:emoji_error},p.RESOURCE,2)
        receipt = self.trace()[-1]
        self.assertTrue(receipt['rpc_error_message_truncated'])
        self.assertEqual(len(receipt['rpc_error']['message']),320)
        code = '0x'+'00'*54000
        self.stop({7:code,10:code,20:emoji_error},p.RESOURCE,20)
        self.assertTrue(self.trace()[-1]['rpc_error_message_truncated'])

    def test_redirect_proxy_and_overwrite(self):
        with patch.object(p.urllib.request,'build_opener',side_effect=RuntimeError('tripwire')) as build:
            with self.assertRaises(RuntimeError):
                p.http_transport({},12,131073)
            self.assertEqual(build.call_args.args[0].proxies,{})
            self.assertIsInstance(build.call_args.args[1],p.NoRedirect)
        with self.assertRaises(p.urllib.error.HTTPError) as caught:
            p.NoRedirect().redirect_request(p.urllib.request.Request(p.ENDPOINT),None,302,
                'redirect',{},'https://other.invalid')
        caught.exception.close()
        self.out.mkdir()
        (self.out/'existing').write_text('retain me')
        with self.assertRaises(FileExistsError):
            self.run_probe()
        self.assertEqual((self.out/'existing').read_text(),'retain me')
        self.assertEqual(self.wire.requests,[])


if __name__ == '__main__':
    unittest.main()
