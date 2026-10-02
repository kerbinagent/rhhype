import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('new_keeper',ROOT/'scripts/curve_pegkeeper_registry_reward_v1.py')
n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)


def words(*values):return '0x'+''.join(format(v,'064x') for v in values)


class RegistryRewardTests(unittest.TestCase):
    def fixture(self):
        setup=n.inputs();h=setup['original']['block'];c=setup['original']['context']
        header=dict(number=hex(h['number']),hash=h['hash'],parentHash=h['parentHash'],timestamp=hex(h['timestamp']),
            stateRoot=h['stateRoot'],gasLimit=c['gasLimit'],miner=c['feeRecipient'],mixHash=c['prevRandao'],baseFeePerGas=c['baseFeePerGas'])
        values=dict(chain='0x1',anchor=header,recheck=copy.deepcopy(header),
            registry_4=words(int(n.KEEPER,16),int(n.POOL,16),0,1),
            pool=words(int(n.POOL,16)),pegged=words(int(n.k.CRVUSD,16)),regulator=words(int(n.k.REGULATOR,16)),
            caller_share=words(50000),last_change=words(h['timestamp']-100),estimate=words(0),update=words(100))
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return setup,values,seen,rpc

    def test_fifth_only_manifest_and_positive_with_zero_estimate(self):
        setup,values,seen,rpc=self.fixture();p=n.collect(rpc,setup)
        self.assertEqual([x[0] for x in seen],[x[0] for x in n.SLOTS]);self.assertEqual(len(seen),11)
        gas=0
        for name,method,params,optional in seen[2:-1]:
            self.assertEqual(method,'eth_call');self.assertTrue(optional)
            self.assertEqual(params[1],dict(blockHash=setup['original']['block']['hash'],requireCanonical=True))
            call=params[0];self.assertEqual(call['to'],n.k.REGULATOR if name=='registry_4' else n.KEEPER)
            self.assertEqual(call['from'],n.k.DIAGNOSTIC);self.assertEqual(call['gasPrice'],'0x0');gas+=int(call['gas'],16)
        self.assertEqual(gas,5300000)
        self.assertEqual(seen[2][2][0]['input'],n.k.s.selector('peg_keepers(uint256)')+format(4,'064x'))
        self.assertEqual(seen[-2][2][0]['input'],n.k.s.selector('update(address)')+n.k.s.word_address(n.k.DIAGNOSTIC))
        self.assertTrue(p['positive_returned_reward']);self.assertEqual(p['values']['estimate']['value'],'0')
        self.assertTrue(p['pool_matches_registry']);self.assertTrue(p['pegged_and_regulator_match'])
        for flag in ('failed_prior_census_promoted','diagnostic_sender_control_claimed','runtime_equivalence_verified',
                     'token_transfer_or_balance_verified','lp_cash_conversion_verified','gas_cost_measured',
                     'obtainable_inclusion_verified','economics','repeatable_profit'):
            self.assertFalse(p[flag])

    def test_registry_change_or_error_stops_before_new_keeper_calls(self):
        for value in (None,{'rpc_unavailable':3},words(1,int(n.POOL,16),0,1),words(int(n.KEEPER,16),int(n.POOL,16),0,0)):
            setup,values,seen,rpc=self.fixture();values['registry_4']=value
            with self.subTest(value=value),self.assertRaisesRegex(n.Refusal,'registry_recheck_unavailable_or_changed'):
                n.collect(rpc,setup)
            self.assertEqual(len(seen),3)

    def test_update_zero_missing_and_revert_remain_distinct(self):
        for value,expected in ((words(0),False),(None,None),({'rpc_unavailable':3},None)):
            setup,values,seen,rpc=self.fixture();values['update']=value
            with self.subTest(value=value):
                p=n.collect(rpc,setup);self.assertIs(p['positive_returned_reward'],expected);self.assertEqual(len(seen),11)

    def test_metadata_mismatch_and_missing_are_not_runtime_identity(self):
        setup,values,seen,rpc=self.fixture();values['pool']=words(1);values['pegged']=None
        p=n.collect(rpc,setup);self.assertFalse(p['pool_matches_registry']);self.assertIsNone(p['pegged_and_regulator_match'])
        self.assertTrue(p['positive_returned_reward']);self.assertFalse(p['all_fields_available'])

    def test_original_anchor_and_final_recheck_are_required(self):
        for name in ('anchor','recheck'):
            setup,values,seen,rpc=self.fixture();values[name]['hash']='0x'+'99'*32
            with self.subTest(name=name),self.assertRaises((n.Refusal,n.k.s.o.Refusal)):
                n.collect(rpc,setup)

    def execute(self,root,revert=False):
        setup,values,seen,rpc=self.fixture();n.collect(rpc,setup);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(sent);name,method,params,optional=seen[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params));dispatch();sent.append(request)
            if revert and name=='update':raw=n.encode(dict(jsonrpc='2.0',id=i+1,error=dict(code=3,message='execution reverted')))
            else:raw=n.encode(dict(jsonrpc='2.0',id=i+1,result=values[name]))
            observe(200,n.encode(dict(status=200,headers=[['content-length',str(len(raw))]])));emit(raw);return 200,len(raw)
        (root/n.BASE).mkdir(parents=True)
        with mock.patch.object(n,'ROOT',root),mock.patch.object(n,'verify',return_value={'pins':[]}), \
             mock.patch.object(n,'inputs',return_value=setup),mock.patch.object(n.resource,'setrlimit'),mock.patch.object(n.h,'fetch',side_effect=fetch):
            ok=n.run('a'*64)
            with self.assertRaises(FileExistsError):n.run('a'*64)
        return ok,sent,setup

    def test_capture_replay_errors_and_tamper(self):
        for revert in (False,True):
            with self.subTest(revert=revert),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent,setup=self.execute(root,revert);self.assertTrue(ok);self.assertEqual(len(sent),11)
                out=root/n.OUT;p,body,raw=n.replay(out/'raw',setup)
                self.assertIs(p['positive_returned_reward'],None if revert else True)
                self.assertEqual(len(list((out/'raw').iterdir())),44)
                terminal=n.decode((out/'terminal.json').read_bytes())
                self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
                path=out/'raw/03.request.json';saved=n.decode(path.read_bytes());saved['request']['params'][0]['input']=n.k.s.selector('peg_keepers(uint256)')+format(5,'064x')
                path.write_bytes(n.encode(saved))
                with self.assertRaisesRegex(n.t.Refusal,'request_manifest'):n.replay(out/'raw',setup)


if __name__=='__main__':unittest.main()
