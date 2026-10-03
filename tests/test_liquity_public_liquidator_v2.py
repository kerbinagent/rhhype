import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('liquidator',ROOT/'scripts/liquity_public_liquidator_v2.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def word(n):return '0x'+format(n,'064x')


class LiquidatorTests(unittest.TestCase):
    def fixture(self):
        original=m.inputs();anchor=m.decode((ROOT/'reports/uniswap-fee-collect-v1/run-v1/raw/06.body').read_bytes())['result']
        header=copy.deepcopy(anchor);header.update(number=hex(m.ANCHOR-10),hash='0x'+'11'*32,timestamp=hex(int(anchor['timestamp'],16)-120))
        sender='0x'+'22'*20;branch=m.BRANCHES[0];txhash='0x'+'44'*32;reserve=37500000000000000;coll=10000000000000000
        def log(index,address,topics,data):
            return dict(address=address,topics=topics,data=data,blockNumber=header['number'],blockHash=header['hash'],
                        transactionHash=txhash,transactionIndex='0x2',logIndex=hex(index),removed=False)
        values=[10**21,0,reserve,coll,10**18,0,10**17,1,2,2000*10**18]
        event=log(6,branch[1],[m.LIQUIDATION],'0x'+''.join(format(x,'064x') for x in values))
        def transfer(index,token,a,b,n):return log(index,token,[m.TRANSFER,word(int(a,16)),word(int(b,16))],word(n))
        logs=[event,transfer(7,m.WETH,branch[2],sender,reserve),transfer(8,m.WETH,branch[3],sender,coll),
              transfer(9,m.WETH,sender,sender,1)]
        tx=dict(hash=txhash,blockHash=header['hash'],blockNumber=header['number'],transactionIndex='0x2',
                **{'from':sender,'to':branch[1]},value='0x0',gas=hex(200000),type='0x2',
                input=m.BATCH_SELECTOR+word(32)[2:]+word(2)[2:]+word(123)[2:]+word(456)[2:])
        receipt=dict(transactionHash=txhash,blockHash=header['hash'],blockNumber=header['number'],transactionIndex='0x2',
                     **{'from':sender,'to':branch[1]},status='0x1',gasUsed=hex(100000),effectiveGasPrice=hex(42),logs=logs)
        values=dict(chain='0x1',events=[copy.deepcopy(event)],event_header=header,transaction=tx,receipt=receipt,recheck=anchor)
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return original,values,seen,rpc

    def test_exact_filter_full_attribution_alias_and_self_transfer(self):
        original,v,seen,rpc=self.fixture();p=m.collect(rpc,original)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS]);self.assertEqual(len(seen),6)
        self.assertEqual(seen[1][2][0],dict(address=[x[1] for x in m.BRANCHES],fromBlock=hex(m.ANCHOR-4095),
            toBlock=hex(m.ANCHOR),topics=[m.LIQUIDATION]))
        self.assertEqual(p['transaction']['canonical_trove_ids'],['123','456'])
        self.assertTrue(p['transaction']['direct_batch_selector_matches'])
        r=p['receipt'];self.assertEqual(r['gas_fee_wei'],'4200000');self.assertEqual(r['reserve_matching_transfers'],1)
        self.assertEqual(len(r['collateral_matching_transfers']),1);self.assertEqual(r['erc20_shaped_transfer_logs'],3)
        self.assertEqual(r['transfer_ledger'],[[v['transaction']['from'],m.WETH,'47500000000000001','1','47500000000000000']])
        self.assertFalse(r['ledger_covers_balance_changes']);self.assertFalse(p['cash_closed']);self.assertFalse(p['economics'])
        self.assertLess(len(m.encode(dict(p,plan_sha256='a'*64))),16384)

    def test_selection_uses_latest_not_largest_and_rejects_bad_census(self):
        _,v,_,_=self.fixture();e=v['events'][0];older=copy.deepcopy(e)
        older['blockNumber']=hex(m.ANCHOR-20);older['data']=e['data'][:130]+word(10**20)[2:]+e['data'][194:]
        events,selected=m.select_events([older,e]);self.assertEqual(selected['block_number'],m.ANCHOR-10)
        self.assertGreater(int(events[0]['values']['weth_reserve']),int(selected['values']['weth_reserve']))
        for value in ([],[e,e],[e,older],{'rpc_unavailable':-32602},None,[e]*65):
            with self.subTest(value=str(value)[:60]),self.assertRaises(m.Refusal):m.select_events(value)
        for key,value in [('removed',True),('blockNumber',hex(m.ANCHOR-m.WINDOW)),('topics',[m.LIQUIDATION,word(1)]),
                          ('address','0x'+'99'*20),('data',e['data']+'00')]:
            bad=copy.deepcopy(e);bad[key]=value
            with self.subTest(key=key),self.assertRaises((m.Refusal,m.k.Refusal,m.h.Refusal)):m.event(bad)

    def test_ambiguous_reserve_and_other_recipient_not_common_ownership(self):
        original,v,_,rpc=self.fixture();logs=v['receipt']['logs'];extra=copy.deepcopy(logs[1]);extra['logIndex']='0xa';logs.append(extra)
        r=m.collect(rpc,original)['receipt'];self.assertIsNone(r['matched_reserve_transfer']);self.assertIsNone(r['roles']['candidate_reward_recipient'])
        self.assertEqual(r['reserve_matching_transfers'],2)
        original,v,_,rpc=self.fixture();recipient='0x'+'55'*20
        v['receipt']['logs'][1]['topics'][2]=word(int(recipient,16));v['receipt']['logs'][2]['topics'][2]=word(int(recipient,16))
        r=m.collect(rpc,original)['receipt'];self.assertEqual(r['roles']['candidate_reward_recipient'],recipient)
        ledger={row[0]:row[2:] for row in r['transfer_ledger']}
        self.assertEqual(ledger[recipient],['47500000000000000','0','47500000000000000'])
        self.assertEqual(ledger[v['transaction']['from']],['1','1','0']);self.assertFalse(r['related_addresses_share_ownership_proved'])

    def test_receipt_transaction_log_and_anchor_mismatches_stop(self):
        for kind in ('txhash','block','event','order','status','gas','from','anchor'):
            original,v,_,rpc=self.fixture()
            if kind=='txhash':v['transaction']['hash']='0x'+'55'*32
            elif kind=='block':v['receipt']['logs'][1]['blockNumber']=hex(m.ANCHOR-9)
            elif kind=='event':v['receipt']['logs'][0]['data']=word(0)+v['receipt']['logs'][0]['data'][66:]
            elif kind=='order':v['receipt']['logs'].reverse()
            elif kind=='status':v['receipt']['status']='0x0'
            elif kind=='gas':v['receipt']['gasUsed']=hex(200001)
            elif kind=='from':v['receipt']['from']='0x'+'77'*20
            else:v['recheck']['stateRoot']='0x'+'55'*32
            with self.subTest(kind=kind),self.assertRaises((m.Refusal,m.k.Refusal)):m.collect(rpc,original)

    def execute(self,root,failure=None):
        original,values,seen,rpc=self.fixture();m.collect(rpc,original);sent=[]
        if failure=='empty':values['events']=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if failure=='overflow' and name=='receipt' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,m.encode(dict(status=200,headers=[['x-test-padding','x'*1000]])))
            for j in range(0,len(raw),1024):emit(raw[j:j+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m,'inputs',return_value=original),mock.patch.object(m.resource,'setrlimit'), \
             mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,original

    def test_real_capture_replay_tamper_and_body_hash_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,original=self.execute(root);self.assertTrue(ok);self.assertEqual(len(sent),6)
            out=root/m.OUT;p,body,raw=m.replay(out/'raw',original)
            term=m.decode((out/'terminal.json').read_bytes());self.assertEqual((body,raw),(term['body_bytes'],term['raw_bytes']))
            self.assertEqual(len(list((out/'raw').iterdir())),24)
            path=out/'raw/05.receipt.json';r=m.decode(path.read_bytes());r['response_sha256']='0'*64;path.write_bytes(m.encode(r))
            with self.assertRaisesRegex(m.t.Refusal,'incomplete_rpc'):m.replay(out/'raw',original)

    def test_empty_and_receipt_overflow_keep_evidence_without_retry(self):
        for failure,attempts in [('empty',2),('overflow',5)]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent,_=self.execute(root,failure);self.assertFalse(ok);self.assertEqual(len(sent),attempts)
                out=root/m.OUT;self.assertFalse((out/'projection.json').exists());term=m.decode((out/'terminal.json').read_bytes())
                self.assertEqual(term['requests_attempted'],attempts)
                if failure=='overflow':self.assertEqual((out/'raw/05.body').stat().st_size,98305)
                else:self.assertEqual(term['error'],'no_liquidation_events_returned')


if __name__=='__main__':unittest.main()
