import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_flow',ROOT/'scripts/uniswap_fee_release_native_flow_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class NativeTests(unittest.TestCase):
    def fixture(self):
        old=m.inputs();sender=old['transaction']['sender'];target=old['event']['recipient']
        fee=m.k.k.addr(m.s.o.context(old['header'])['feeRecipient']);nonce=old['tx_nonce']
        gas=int(old['ledger']['gas_fee_wei']);burn=old['ledger']['gas_used']*int(old['header']['baseFeePerGas'],16)
        # Synthetic native funds flow: executor receives 1000, builder 200, sender pays fee+1200.
        diff=dict(pre={sender:dict(balance=hex(10**18),nonce=nonce),target:dict(balance='0x0'),fee:dict(balance='0x0')},
            post={sender:dict(balance=hex(10**18-gas-1200),nonce=nonce+1),target:dict(balance=hex(1000)),
                  fee:dict(balance=hex(gas-burn+200))})
        values=dict(chain='0x1',native_diff=diff,recheck=copy.deepcopy(old['header']));seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return old,values,seen,rpc

    def test_fee_conservation_and_standard_weth_adjustment(self):
        old,v,seen,rpc=self.fixture();p=m.collect(rpc,old);n=p['native'];w=p['weth']
        self.assertEqual(n['conditional_group_delta_wei'],str(-int(old['ledger']['gas_fee_wei'])-200))
        self.assertEqual(n['fee_recipient_delta_excluding_priority_fee_wei'],'200')
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        self.assertEqual(seen[1][2],[old['event']['transaction_hash'],m.OPTIONS])
        self.assertEqual(len(w['events']),4);self.assertTrue(all(r[4]=='0' for r in w['rows']))
        executor=next(r for r in w['rows'] if r[0]==old['event']['recipient'])
        self.assertEqual(executor[1:4],['1303072183111482590','3180814575657816053','4483886758769298643'])
        self.assertEqual(w['other_transfer_net_nonzero_rows'],[]);self.assertFalse(p['cash_closed'])

    def test_omitted_balances_creation_deletion_and_aliases(self):
        old,v,_,_=self.fixture();d=v['native_diff'];a='0x'+'11'*20;b='0x'+'22'*20;c='0x'+'33'*20
        d['pre'][a]=dict(balance='0x7',nonce=1);d['post'][a]=dict(nonce=2)
        d['pre'][b]=dict(balance='0x5');d['post'][c]=dict(balance='0x5')
        n=m.native_diff(d,old);rows={r[0]:r[1:] for r in n['accounts']}
        self.assertEqual(rows[a],['7','7','0']);self.assertEqual(rows[b],['5','0','-5']);self.assertEqual(rows[c],['0','5','5'])
        old['event']['recipient']=old['transaction']['sender'];n=m.native_diff(d,old)
        self.assertEqual(n['conditional_group_members'],[old['transaction']['sender']])
        self.assertEqual(n['conditional_group_delta_wei'],n['sender_delta_wei'])

    def test_invalid_or_incomplete_diffs_are_unavailable(self):
        for failure in ('rpc','nonce','missing_pre','noncanonical','storage','code','overflow','sum','union'):
            old,v,_,_=self.fixture();d=v['native_diff'];sender=old['transaction']['sender']
            if failure=='rpc':d={'rpc_unavailable':{'code':-32601}}
            elif failure=='nonce':d['post'][sender]['nonce']=True
            elif failure=='missing_pre':del d['pre'][sender]['balance']
            elif failure=='noncanonical':d['pre'][sender.upper()]=d['pre'].pop(sender)
            elif failure=='storage':d['post'][sender]['storage']={'0x00':'0x01'}
            elif failure=='code':d['post'][sender]['code']='0x01'
            elif failure=='overflow':d['pre'][sender]['balance']=hex(2**256)
            elif failure=='sum':d['post'][sender]['balance']=hex(10**18)
            else:
                for i in range(30):d['pre']['0x'+format(i,'040x')]=dict(balance='0x0')
            with self.subTest(failure=failure),self.assertRaises(Exception):m.native_diff(d,old)

    def execute(self,root,mode='normal'):
        old,values,seen,rpc=self.fixture();m.collect(rpc,old);sent=[]
        if mode=='reserve':
            # Strictly valid account data padded via 29 changed zero balances, still below 32-address cap.
            for i in range(29):
                a='0x'+format(i,'040x');values['native_diff']['pre'][a]=dict(balance='0x'+'f'*64,nonce=0,codeHash='0x'+'a'*64)
                values['native_diff']['post'][a]=dict(balance='0x'+'f'*64,nonce=1,codeHash='0x'+'a'*64)
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if mode=='overflow' and name=='native_diff' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            if mode=='rpc' and name=='native_diff':raw=m.encode(dict(jsonrpc='2.0',id=i+1,error=dict(code=-32601,message='unsupported')))
            observe(200,m.encode(dict(status=200,headers=[['x-test','x'*512]])))
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

    def test_bounded_capture_replay_tamper_and_reorg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,old=self.execute(root);out=root/m.OUT
            self.assertTrue(ok,(out/'terminal.json').read_text());self.assertEqual(len(sent),3)
            p,body,raw=m.replay(out/'raw',old);terminal=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            self.assertEqual(len(list((out/'raw').iterdir())),12)
            path=out/'raw/02.request.json';v=m.decode(path.read_bytes());v['request']['params'][1]['reexec']=1;path.write_bytes(m.encode(v))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',old)
        old,v,_,rpc=self.fixture();v['recheck']['stateRoot']='0x'+'55'*32
        with self.assertRaises(m.s.o.Refusal):m.collect(rpc,old)

    def test_failures_retain_evidence_and_stop_before_later_dispatch(self):
        for mode in ('overflow','reserve','rpc'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent,_=self.execute(root,mode);out=root/m.OUT
                self.assertFalse(ok);self.assertEqual(len(sent),2)
                self.assertFalse((out/'projection.json').exists());self.assertFalse((out/'raw/03.body').exists())
                if mode=='overflow':self.assertEqual((out/'raw/02.body').stat().st_size,32769)
                if mode=='reserve':self.assertEqual(m.decode((out/'terminal.json').read_bytes())['error'],'reserve_before_dispatch')


if __name__=='__main__':unittest.main()
