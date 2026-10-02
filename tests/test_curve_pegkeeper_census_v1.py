import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('census',ROOT/'scripts/curve_pegkeeper_census_v1.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def words(*values):return '0x'+''.join(format(x,'064x') for x in values)


def event(n,txi,logi,txhash,keeper=None,kind='Provide',amount=1):
    return dict(blockNumber=hex(n),transactionIndex=hex(txi),logIndex=hex(logi),
        blockHash='0x'+format(n,'064x'),transactionHash='0x'+format(txhash,'064x'),
        address=keeper or m.k.KEEPERS[0][1],removed=False,topics=[m.c.keccak_hex(kind+'(uint256)')],data=words(amount))


class CensusTests(unittest.TestCase):
    def fixture(self):
        setup=m.inputs()
        context=setup['context'];header=setup['block']
        anchor=dict(number=hex(header['number']),hash=header['hash'],parentHash=header['parentHash'],
            timestamp=hex(header['timestamp']),stateRoot=header['stateRoot'],gasLimit=context['gasLimit'],
            miner=context['feeRecipient'],mixHash=context['prevRandao'],baseFeePerGas=context['baseFeePerGas'])
        lower=dict(anchor,number=hex(m.ANCHOR-m.WINDOW+1),timestamp=hex(header['timestamp']-86400),hash='0x'+'aa'*32)
        values=dict(chain='0x1',anchor=anchor,lower=lower,lower_recheck=copy.deepcopy(lower),anchor_recheck=copy.deepcopy(anchor),
            stablecoin=words(int(m.k.CRVUSD,16)),paused=words(0),events=[])
        for i in range(8):
            values['registry_'+str(i)]=(words(int(m.k.KEEPERS[i][1],16),int('33'*20,16),0,0)
                                       if i<4 else dict(rpc_unavailable=3))
        seen=[]
        def rpc(name,method,params,allow_unavailable=False):
            seen.append((name,method,copy.deepcopy(params),allow_unavailable));return copy.deepcopy(values[name])
        return setup,values,seen,rpc

    def test_fixed_registry_and_window_manifest(self):
        setup,values,seen,rpc=self.fixture();p=m.collect(rpc,setup)
        self.assertEqual([x[0] for x in seen],[x[0] for x in m.SLOTS]);self.assertEqual(len(seen),16)
        self.assertEqual(p['available_registry_slots'],4)
        self.assertTrue(p['registry_addresses_unique']);self.assertFalse(p['active_universe_proved'])
        self.assertTrue(p['unavailable_registry_slot_is_not_absence_proof'])
        for i in range(8):
            name,method,params,optional=seen[2+i]
            self.assertEqual(method,'eth_call');self.assertTrue(optional)
            self.assertEqual(params[1],dict(blockHash=setup['block']['hash'],requireCanonical=True))
            self.assertEqual(params[0]['input'],m.k.s.selector('peg_keepers(uint256)')+format(i,'064x'))
            self.assertEqual(int(params[0]['gas'],16),300000)
        query=seen[13][2][0]
        self.assertEqual(query,dict(fromBlock=hex(26100612),toBlock=hex(26107811),
            address=sorted(x[1] for x in m.k.KEEPERS),topics=[list(m.TOPICS)]))

    def test_registry_tuple_width_and_unknowns(self):
        for value in (None,'0x',words(1,2,3,0),words(0,2,0,0),words(1,2**160,0,0),words(1,2,0,0)+'00'):
            self.assertFalse(m.registry_result(value)['available'])
        parsed=m.registry_result(words(1,2,1,0));self.assertTrue(parsed['available']);self.assertTrue(parsed['is_inverse'])
        self.assertEqual(m.registry_result({'rpc_unavailable':3})['reason'],'rpc_error_not_proven_absence')

    def test_union_includes_new_registry_address_and_originals(self):
        setup,values,seen,rpc=self.fixture();extra='0x'+'55'*20
        values['registry_4']=words(int(extra,16),int('66'*20,16),1,1)
        p=m.collect(rpc,setup);self.assertEqual(p['available_registry_slots'],5)
        self.assertEqual(p['query_addresses'],sorted([extra]+[x[1] for x in m.k.KEEPERS]))
        self.assertFalse(p['economics']);self.assertFalse(p['maintenance_amount_is_caller_reward'])
        self.assertEqual(p['selected_first_three_transactions'],[])

    def test_first_three_distinct_transactions_ignore_amount_and_group_repeats(self):
        setup,values,seen,rpc=self.fixture();n=m.ANCHOR-20
        values['events']=[event(n,0,1,1,amount=0),event(n,0,2,1,kind='Withdraw'),
                          event(n,2,3,2,amount=2**255),event(n+1,0,0,3),event(n+2,0,0,4)]
        p=m.collect(rpc,setup)
        self.assertEqual(p['event_count'],5);self.assertEqual(p['distinct_transaction_count'],4)
        selected=p['selected_first_three_transactions'];self.assertEqual([int(x['transaction_hash'],16) for x in selected],[1,2,3])
        self.assertEqual(selected[0]['amount_raw'],'0')
        self.assertEqual(p['event_counts_by_keeper'][m.k.KEEPERS[0][1]],dict(Provide=4,Withdraw=1))

    def test_malformed_removed_wrong_topics_and_duplicate_logs_rejected(self):
        for kind in ('removed','address','topic','width','range','duplicate','block_hash','tx_hash','tx_position','log_order'):
            a=event(m.ANCHOR-1,0,1,1);b=event(m.ANCHOR-1,1,2,2)
            if kind=='removed':b['removed']=True
            if kind=='address':b['address']='0x'+'99'*20
            if kind=='topic':b['topics']=['0x'+'99'*32]
            if kind=='width':b['data']='0x1'
            if kind=='range':b['blockNumber']=hex(m.ANCHOR+1)
            if kind=='duplicate':b=copy.deepcopy(a)
            if kind=='block_hash':b['blockHash']='0x'+'99'*32
            if kind=='tx_hash':b['transactionHash']=a['transactionHash']
            if kind=='tx_position':b['transactionIndex']=a['transactionIndex']
            if kind=='log_order':b['logIndex']='0x0'
            with self.subTest(kind=kind),self.assertRaises((m.Refusal,m.h.Refusal)):
                m.parse_events([a,b],[x[1] for x in m.k.KEEPERS],m.ANCHOR-m.WINDOW+1,m.ANCHOR)

    def test_header_recheck_and_anchor_pin(self):
        for name in ('anchor','lower_recheck','anchor_recheck'):
            setup,values,seen,rpc=self.fixture();values[name]['hash']='0x'+'bb'*32
            with self.subTest(name=name),self.assertRaises((m.Refusal,m.k.s.o.Refusal)):
                m.collect(rpc,setup)

    def test_boundary_events_match_pinned_headers(self):
        for name,n in (('anchor',m.ANCHOR),('lower',m.ANCHOR-m.WINDOW+1)):
            setup,values,seen,rpc=self.fixture();row=event(n,0,1,1)
            row['blockHash']=values[name]['hash'];values['events']=[row]
            self.assertEqual(m.collect(rpc,setup)['event_count'],1)
            row['blockHash']='0x'+'99'*32
            with self.subTest(name=name),self.assertRaisesRegex(m.Refusal,'boundary_event_hash'):
                m.collect(rpc,setup)

    def test_enum_and_registry_duplicates_reported_honestly(self):
        setup,values,seen,rpc=self.fixture();values['paused']=words(4);values['registry_1']=values['registry_0']
        p=m.collect(rpc,setup);self.assertFalse(p['paused']['available']);self.assertFalse(p['registry_addresses_unique'])
        self.assertEqual(len(p['query_addresses']),4);self.assertFalse(p['active_universe_proved'])

    def execute(self,root,failure=None):
        setup,values,seen,rpc=self.fixture();m.collect(rpc,setup);sent=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            index=len(sent);name,method,params,optional=seen[index]
            self.assertEqual(request,dict(jsonrpc='2.0',id=index+1,method=method,params=params));dispatch();sent.append(request)
            value=values[name]
            if failure=='sentinel' and name=='events':raw=b'x'*(cap+1)
            elif failure=='rpc' and name=='events':raw=m.encode(dict(jsonrpc='2.0',id=index+1,error=dict(code=-32000,message='unavailable')))
            elif isinstance(value,dict) and 'rpc_unavailable' in value:
                raw=m.encode(dict(jsonrpc='2.0',id=index+1,error=dict(code=value['rpc_unavailable'],message='revert')))
            else:raw=m.encode(dict(jsonrpc='2.0',id=index+1,result=value))
            observe(200,m.encode(dict(status=200,headers=[['content-length',str(len(raw))]])))
            emit(raw)
            if len(raw)>cap:raise m.h.Refusal('response_cap_sentinel_retained')
            return 200,len(raw)
        (root/m.BASE).mkdir(parents=True)
        with mock.patch.object(m,'ROOT',root),mock.patch.object(m,'verify',return_value={'pins':[]}), \
             mock.patch.object(m,'inputs',return_value=setup),mock.patch.object(m.resource,'setrlimit'),mock.patch.object(m.h,'fetch',side_effect=fetch):
            ok=m.run('a'*64)
            with self.assertRaises(FileExistsError):m.run('a'*64)
        return ok,sent,setup

    def test_exact_replay_with_unknown_registry_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,sent,setup=self.execute(root);self.assertTrue(ok);self.assertEqual(len(sent),16)
            out=root/m.OUT;p,body,raw=m.replay(out/'raw',setup)
            terminal=m.decode((out/'terminal.json').read_bytes())
            self.assertEqual((body,raw),(terminal['body_bytes'],terminal['raw_bytes']))
            self.assertEqual(len(list((out/'raw').iterdir())),64)
            path=out/'raw/14.request.json';saved=m.decode(path.read_bytes());saved['request']['params'][0]['toBlock']='latest'
            path.write_bytes(m.encode(saved))
            with self.assertRaisesRegex(m.t.Refusal,'request_manifest'):m.replay(out/'raw',setup)

    def test_log_failures_preserved_without_narrowing(self):
        for failure in ('sentinel','rpc'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);ok,sent,setup=self.execute(root,failure);self.assertFalse(ok);self.assertEqual(len(sent),14)
                out=root/m.OUT;self.assertFalse((out/'projection.json').exists())
                self.assertEqual(m.decode((out/'terminal.json').read_bytes())['status'],'unavailable')
                if failure=='sentinel':self.assertEqual((out/'raw/14.body').stat().st_size,65537)


if __name__=='__main__':unittest.main()
