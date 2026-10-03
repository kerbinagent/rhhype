import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


m=load('receipt_v2','scripts/uniswap_fee_release_receipt_v2.py')
fixture_module=load('receipt_fixture','tests/test_uniswap_fee_release_history_v1.py')


class ReceiptTests(unittest.TestCase):
    def fixture(self):
        original,v,_,_=fixture_module.ReleaseHistoryTests().fixture()
        e=m.k.select_event(v['events']);old=dict(event=e,header=v['event_header'],
            transaction=m.k.transaction(v['transaction'],e),original=original)
        # Exercise a complete response above v1's cap while preserving real log shapes.
        receipt=copy.deepcopy(v['receipt']);receipt['syntheticPadding']='x'*140000
        values=dict(chain='0x1',receipt=receipt,recheck=copy.deepcopy(old['header']));seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return old,values,seen,rpc

    def test_fixed_transaction_charged_gas_separate_owner_ledgers(self):
        old,v,seen,rpc=self.fixture();p=m.collect(rpc,old)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        self.assertEqual(seen[1][2],[old['event']['transaction_hash']])
        self.assertEqual(seen[2][2],[hex(old['event']['block_number']),False])
        self.assertEqual(p['receipt']['gas_fee_wei'],'4200000')
        usdc=old['original']['inventory'][1]['address'];sender=old['transaction']['sender'];recipient=old['event']['recipient']
        ledger={(x[0],x[1]):x[2:] for x in p['receipt']['transfer_ledger']}
        self.assertEqual(ledger[(recipient,usdc)],['1000001','900001','100000'])
        self.assertEqual(ledger[(sender,usdc)],['900000','0','900000'])
        self.assertFalse(p['cash_closed']);self.assertFalse(p['internal_native_flows_observed'])
        self.assertTrue(p['reused_future_unit_metadata_is_annotation_only'])

    def test_receipt_failures_and_reorg_cannot_be_economic_zero(self):
        for failure in ('hash','status','logs','event','reorg'):
            old,v,seen,rpc=self.fixture()
            if failure=='hash':v['receipt']['transactionHash']='0x'+'55'*32
            elif failure=='status':v['receipt']['status']='0x0'
            elif failure=='logs':v['receipt']['logs']=v['receipt']['logs']*103
            elif failure=='event':v['receipt']['logs'][2]['removed']=True
            else:v['recheck']['stateRoot']='0x'+'55'*32
            with self.subTest(failure=failure),self.assertRaises((m.k.Refusal,m.s.o.Refusal)):m.collect(rpc,old)

    def execute(self,root,overflow=False):
        old,values,seen,rpc=self.fixture();m.collect(rpc,old);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if overflow and name=='receipt' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,m.encode(dict(status=200,headers=[['x-test','x'*1000]])))
            for i in range(0,len(raw),1024):emit(raw[i:i+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m,'inputs',return_value=old),mock.patch.object(m.resource,'setrlimit'), \
             mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,old

    def test_larger_capture_replay_and_request_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,old=self.execute(root);out=root/m.OUT
            self.assertTrue(ok,(out/'terminal.json').read_text());self.assertEqual(len(sent),3)
            self.assertGreater((out/'raw/02.body').stat().st_size,131072)
            p,body,raw=m.replay(out/'raw',old);terminal=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            self.assertEqual(len(list((out/'raw').iterdir())),12)
            path=out/'raw/02.request.json';v=m.decode(path.read_bytes());v['request']['params'][0]='0x'+'55'*32;path.write_bytes(m.encode(v))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',old)

    def test_original_failure_kept_and_new_sentinel_stops(self):
        prior=ROOT/(m.OLD+'run-v1/raw/05.body');before=m.sha(prior.read_bytes())
        self.assertEqual(prior.stat().st_size,131073);self.assertEqual(m.inputs()['event']['nonce'],1387)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,_=self.execute(root,True);out=root/m.OUT
            self.assertFalse(ok);self.assertEqual(len(sent),2)
            self.assertEqual((out/'raw/02.body').stat().st_size,196609)
            self.assertFalse((out/'projection.json').exists());self.assertFalse((out/'raw/03.body').exists())
        self.assertEqual(m.sha(prior.read_bytes()),before)


if __name__=='__main__':unittest.main()
