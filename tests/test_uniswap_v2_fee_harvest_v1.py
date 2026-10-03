import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('v2fees',ROOT/'scripts/uniswap_v2_fee_harvest_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def word(n):return '0x'+format(n,'064x')


def available(n):return dict(available=True,value=str(n))


def pair():
    return dict(token0='0x'+'1'*40,token1='0x'+'2'*40,reserves=dict(available=True,value=['10000','40000','0']),
                supply=available(1000000),k_last=available(100000000),pair_lp=available(0),
                balance0=available(10000),balance1=available(40000))


class V2FeeTests(unittest.TestCase):
    def fixture(self):
        assets=m.inputs();header=m.decode((ROOT/'reports/uniswap-fee-collect-v1/run-v1/raw/06.body').read_bytes())['result']
        values=dict(chain='0x1',block=header,recheck=copy.deepcopy(header),fee_to=word(int(m.JAR,16)),
                    releaser=word(int(m.FIREPIT,16)),threshold=word(4000*10**18),nonce=word(1400))
        for i,a in enumerate(assets):values['jar_'+str(i)]='0x0' if a==m.ZERO else word(10000)
        for i,a in enumerate(assets[:4]):
            pre='pair_'+str(i)+'_'
            fields=dict(token0=word(10+2*i),token1=word(11+2*i),canonical_pair=word(int(a,16)),
                        reserves=word(10000)+word(40000)[2:]+word(123)[2:],supply=word(1000000),k_last=word(100000000),
                        pair_lp=word(0),balance0=word(10000),balance1=word(40000))
            values.update({pre+k:v for k,v in fields.items()})
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return assets,values,seen,rpc

    def test_fee_dilution_deposit_rounding_and_no_second_fee(self):
        p=pair();r=m.model(p,available(10000),True,[])
        self.assertTrue(r['admitted']);self.assertEqual(r['fee_lp'],'90909');self.assertEqual(r['deposit_native'],['1','1'])
        self.assertEqual(r['caller_lp_minted'],'27');self.assertEqual(r['lp_burned'],'100936')
        self.assertEqual(r['supply_at_burn'],'1090936');self.assertEqual(r['underlying_out_native'],['925','3700'])
        self.assertEqual(r['net_underlying_after_deposit'],['924','3699']);self.assertEqual(r['additional_burn_fee_lp'],'0')
        self.assertFalse(r['cash_closed']);self.assertFalse(r['resource_payment_included'])
        # Integer-root boundary: growth below the next square earns no fee.
        self.assertEqual(m.pending_fee(1000,10,12,100),0)
        self.assertEqual(m.pending_fee(1000,11,11,100),15)
        self.assertEqual(m.pending_fee(1000,10,12,120),0)
        self.assertEqual(m.pending_fee(1000,100,100,0),0)

    def test_unknown_nonstandard_balance_ownership_and_overflow_gates(self):
        for kind in ('unknown','donation','pair_lp','supply','cross','overflow','reserve','config'):
            p=pair();candidates=[];config=True
            if kind=='unknown':p['k_last']=dict(available=False,reason='rpc_error')
            elif kind=='donation':p['balance0']=available(10001)
            elif kind=='pair_lp':p['pair_lp']=available(1)
            elif kind=='supply':p['supply']=available(1000)
            elif kind=='cross':candidates=[p['token0']]
            elif kind=='overflow':p['supply']=available(m.MAX256)
            elif kind=='reserve':p['reserves']['value'][0]='0'
            else:config=None
            with self.subTest(kind=kind):self.assertFalse(m.model(p,available(10000),config,candidates)['admitted'])

    def test_fixed63_calls_and_canonical_hash_all_state_queries(self):
        assets,v,seen,rpc=self.fixture();p=m.collect(rpc,assets)
        self.assertEqual(len(seen),63);self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS])
        state=dict(blockHash=p['block']['hash'],requireCanonical=True);calls=[x for x in seen if x[1]=='eth_call']
        self.assertEqual(len(calls),59);self.assertEqual(sum(int(x[2][0]['gas'],16) for x in calls),17700000)
        for x in seen:
            if x[1] in ('eth_call','eth_getBalance'):self.assertEqual(x[2][1],state)
        self.assertEqual([x for x in seen if x[1]=='eth_getBalance'][0][2],[m.JAR,state])
        self.assertEqual(p['modeled_pairs'],4);self.assertTrue(p['expected_configuration_matches'])
        self.assertFalse(p['old_v3_state_combined']);self.assertFalse(p['economics'])
        self.assertLess(len(m.encode(dict(p,plan_sha256='a'*64))),12288)

    def test_optional_unknown_is_not_zero_and_identity_mismatch_stops(self):
        assets,v,seen,rpc=self.fixture();v['fee_to']={'rpc_unavailable':-32000};p=m.collect(rpc,assets)
        self.assertIsNone(p['expected_configuration_matches']);self.assertEqual(p['modeled_pairs'],0)
        assets,v,seen,rpc=self.fixture();v['jar_0']='0x';p=m.collect(rpc,assets)
        self.assertFalse(p['inventory'][0]['balance']['available']);self.assertEqual(p['modeled_pairs'],3)
        assets,v,seen,rpc=self.fixture();v['pair_0_canonical_pair']=word(0)
        with self.assertRaisesRegex(m.Refusal,'candidate_not_canonical_pair'):m.collect(rpc,assets)
        self.assertEqual(len(seen),29)
        assets,v,seen,rpc=self.fixture();v['recheck']['stateRoot']='0x'+'88'*32
        with self.assertRaises((m.Refusal,m.s.o.Refusal)):m.collect(rpc,assets)

    def execute(self,root,failure=None):
        assets,values,seen,rpc=self.fixture();m.collect(rpc,assets);sent=[]
        if failure=='identity':values['pair_0_canonical_pair']=word(0)
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            raw=b'x'*(cap+1) if failure=='overflow' and name=='block' else m.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,m.encode(dict(status=200,headers=[['x-test-padding','x'*1000]])))
            for j in range(0,len(raw),1024):emit(raw[j:j+1024])
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={}), \
             mock.patch.object(m,'inputs',return_value=assets),mock.patch.object(m.resource,'setrlimit'), \
             mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,assets

    def test_capture_with_real_sized_headers_replay_and_manifest_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,assets=self.execute(root);self.assertTrue(ok);self.assertEqual(len(sent),63)
            out=root/m.OUT;p,body,raw=m.replay(out/'raw',assets);term=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(term['body_bytes'],term['raw_bytes']));self.assertEqual(len(list((out/'raw').iterdir())),252)
            path=out/'raw/03.request.json';v=m.decode(path.read_bytes());v['request']['params'][1]['requireCanonical']=False;path.write_bytes(m.encode(v))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',assets)

    def test_partial_failures_retained_no_retry_or_projection(self):
        for failure,attempts in [('overflow',2),('identity',29)]:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent,_=self.execute(root,failure);self.assertFalse(ok);self.assertEqual(len(sent),attempts)
                out=root/m.OUT;self.assertFalse((out/'projection.json').exists());term=m.decode((out/'terminal.json').read_bytes())
                self.assertEqual(term['requests_attempted'],attempts)
                if failure=='overflow':self.assertEqual((out/'raw/02.body').stat().st_size,32769)


if __name__=='__main__':unittest.main()
