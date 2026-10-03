import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_history',ROOT/'scripts/uniswap_fee_release_history_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def word(n):return '0x'+format(n,'064x')


class ReleaseHistoryTests(unittest.TestCase):
    def fixture(self):
        original=m.inputs();anchor=m.decode((ROOT/'reports/uniswap-fee-collect-v1/run-v1/raw/06.body').read_bytes())['result']
        header=copy.deepcopy(anchor);header.update(number=hex(m.ANCHOR-10),hash='0x'+'11'*32,timestamp=hex(int(anchor['timestamp'],16)-120))
        sender='0x'+'22'*20;recipient='0x'+'33'*20;txhash='0x'+'44'*32
        uni=original['inventory'][5]['address'];usdc=original['inventory'][1]['address']
        def log(index,address,topics,data):
            return dict(address=address,topics=topics,data=data,blockNumber=header['number'],blockHash=header['hash'],
                        transactionHash=txhash,transactionIndex='0x2',logIndex=hex(index),removed=False)
        data=word(32)+word(2)[2:]+word(int(uni,16))[2:]+word(int(usdc,16))[2:]
        release=log(6,m.FIREPIT,[m.RELEASED,word(m.NONCE),word(int(recipient,16))],data)
        def transfer(index,token,a,b,n):return log(index,token,[m.TRANSFER,word(int(a,16)),word(int(b,16))],word(n))
        logs=[transfer(4,uni,sender,'0x'+'0'*36+'dead',4000*10**18),transfer(5,usdc,m.JAR,recipient,1000000),release,
              transfer(7,usdc,recipient,sender,900000),transfer(8,usdc,recipient,recipient,1)]
        tx=dict(hash=txhash,blockHash=header['hash'],blockNumber=header['number'],transactionIndex='0x2',
                **{'from':sender,'to':recipient},value='0x0',gas=hex(200000),type='0x2',input='0x12345678')
        receipt=dict(transactionHash=txhash,blockHash=header['hash'],blockNumber=header['number'],transactionIndex='0x2',
                     **{'from':sender,'to':recipient},status='0x1',gasUsed=hex(100000),effectiveGasPrice=hex(42),logs=logs)
        values=dict(chain='0x1',events=[copy.deepcopy(release)],event_header=header,transaction=tx,receipt=receipt,recheck=anchor)
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return original,values,seen,rpc

    def test_exact_event_receipt_and_separate_address_ledgers(self):
        original,v,seen,rpc=self.fixture();p=m.collect(rpc,original)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS]);self.assertEqual(len(seen),6)
        f=seen[1][2][0];self.assertEqual(f,dict(address=m.FIREPIT,fromBlock=hex(m.ANCHOR-4095),toBlock=hex(m.ANCHOR),topics=[m.RELEASED,word(m.NONCE)]))
        self.assertEqual(p['selected_event']['nonce'],1387)
        self.assertEqual(p['receipt']['gas_fee_wei'],'4200000')
        self.assertEqual(p['receipt']['erc20_shaped_transfer_logs'],4)
        self.assertEqual(p['receipt']['other_logs'],1)
        usdc=original['inventory'][1]['address'];sender=v['transaction']['from'];recipient=v['transaction']['to']
        ledger={(row[0],row[1]):row[2:] for row in p['receipt']['transfer_ledger']}
        self.assertEqual(ledger[(recipient,usdc)],['1000001','900001','100000'])
        self.assertEqual(ledger[(sender,usdc)],['900000','0','900000'])
        self.assertEqual(len(p['receipt']['jar_transfers']),1)
        self.assertFalse(p['receipt']['ledger_covers_balance_changes']);self.assertFalse(p['cash_closed'])
        self.assertLess(len(m.encode(dict(p,plan_sha256='a'*64))),16384)

    def test_empty_ambiguous_removed_noncanonical_and_outside_event(self):
        original,v,seen,rpc=self.fixture();e=v['events'][0]
        for value in ([],[e,e],{'rpc_unavailable':-32602},None):
            with self.subTest(value=value),self.assertRaises(m.Refusal):m.select_event(value)
        mutations=[('removed',True),('blockNumber',hex(m.ANCHOR-4096)),('data',word(64)+e['data'][66:]),
                   ('topics',[m.RELEASED,word(m.NONCE+1),e['topics'][2]])]
        for key,value in mutations:
            bad=copy.deepcopy(e);bad[key]=value
            with self.subTest(key=key),self.assertRaises(m.Refusal):m.event(bad)
        bad=copy.deepcopy(e);bad['data']=e['data']+'00'
        with self.assertRaises(m.Refusal):m.event(bad)
        # Source permits zero assets, repeated assets and the native-currency address.
        empty=copy.deepcopy(e);empty['data']=word(32)+word(0)[2:];self.assertEqual(m.event(empty)['assets'],[])
        repeated=copy.deepcopy(e);repeated['data']=word(32)+word(2)[2:]+word(0)[2:]*2
        self.assertEqual(m.event(repeated)['assets'],['0x'+'0'*40]*2)

    def test_receipt_mismatch_order_status_and_anchor_fail(self):
        for kind in ('hash','event','order','status','gas','anchor'):
            original,v,seen,rpc=self.fixture()
            if kind=='hash':v['transaction']['hash']='0x'+'55'*32
            elif kind=='event':v['receipt']['logs'][2]['data']=word(32)+word(0)[2:]
            elif kind=='order':v['receipt']['logs'].reverse()
            elif kind=='status':v['receipt']['status']='0x0'
            elif kind=='gas':v['receipt']['gasUsed']=hex(200001)
            else:v['recheck']['stateRoot']='0x'+'55'*32
            with self.subTest(kind=kind),self.assertRaises(m.Refusal):m.collect(rpc,original)

    def execute(self,root,failure=None):
        original,values,seen,rpc=self.fixture();m.collect(rpc,original);sent=[]
        if failure=='empty':values['events']=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if failure=='overflow' and name=='events' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,m.encode(dict(status=200,headers=[['x-test-padding','x'*1000]])))
            for k in range(0,len(raw),1024):emit(raw[k:k+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m,'inputs',return_value=original),mock.patch.object(m.resource,'setrlimit'), \
             mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,original

    def test_complete_capture_real_header_replay_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,original=self.execute(root);self.assertTrue(ok);self.assertEqual(len(sent),6)
            out=root/m.OUT;p,body,raw=m.replay(out/'raw',original)
            term=m.decode((out/'terminal.json').read_bytes());self.assertEqual((body,raw),(term['body_bytes'],term['raw_bytes']))
            self.assertEqual(len(list((out/'raw').iterdir())),24)
            path=out/'raw/02.request.json';x=m.decode(path.read_bytes());x['request']['params'][0]['toBlock']=hex(m.ANCHOR+1);path.write_bytes(m.encode(x))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',original)

    def test_empty_and_overflow_stop_without_receipt_or_retry(self):
        for failure in ('empty','overflow'):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent,_=self.execute(root,failure);self.assertFalse(ok);self.assertEqual(len(sent),2)
                out=root/m.OUT;self.assertFalse((out/'projection.json').exists());term=m.decode((out/'terminal.json').read_bytes())
                self.assertEqual(term['requests_attempted'],2)
                if failure=='overflow':self.assertEqual((out/'raw/02.body').stat().st_size,8193)
                else:self.assertEqual(term['error'],'no_matching_last_nonce_event')


if __name__=='__main__':unittest.main()
