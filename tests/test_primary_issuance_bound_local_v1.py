"""Focused synthetic provider responses; no real RPC or economic fixtures."""
import base64
import contextlib
import copy
import gzip
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import primary_issuance_bound_local_v1 as b

WALL = 1700000000000000000
PARENT = dict(number='0x100', hash='0x'+'11'*32, parentHash='0x'+'22'*32,
              stateRoot='0x'+'33'*32, timestamp=hex(WALL//10**9))
NUMBERS = [100*10**18,20*10**18,120*10**18,30*10**18,10**18,0,20*10**18,1000000,5000000000]
FAKE_CODE = '0x6000'


def word(n):
    return '0x'+format(n,'064x')


def address_word(addr):
    return word(int(addr,16))


def child(numbers, parent=PARENT):
    calls = [dict(status='0x1', returnData=word(n), gasUsed=hex(25000), logs=[]) for n in numbers]
    return [dict(number=hex(b.quantity(parent['number'])+1), parentHash=parent['hash'],
        timestamp=hex(b.quantity(parent['timestamp'])+12), miner=b.RECIPIENT,
        baseFeePerGas=hex(1000000000), gasLimit=hex(30000000), withdrawals=[],
        gasUsed=hex(len(calls)*25000), calls=calls)]


def domain():
    return b.domain_values(child(NUMBERS),PARENT)


def arm(principal, quote=None):
    d=domain();m=principal*d['internal_shares']//d['internal_ether']
    balance=m*(d['internal_ether']+principal)//(d['internal_shares']+m)
    return child([0,m,balance,principal-2 if quote is None else quote,d['fee']])


class Clock:
    def __init__(self):self.now=0.
    def monotonic(self):return self.now
    def sleep(self,seconds):self.now+=seconds
    def wall(self):return WALL+int(self.now*10**9)


class Peer:
    def __init__(self,changes=None):self.requests=[];self.changes=changes or {}
    def __call__(self,request,timeout,limit):
        self.requests.append(copy.deepcopy(request));i=request['id']
        values={1:'0x1',2:PARENT,3:'0x',4:'0x',5:FAKE_CODE,6:address_word(b.IMPL),
            7:FAKE_CODE,8:FAKE_CODE,9:word(2),10:word(4),11:word(18),
            12:address_word(b.NATIVE),13:address_word(b.LIDO),14:child(NUMBERS),19:PARENT}
        value=values.get(i)
        if 15<=i<=18:value=arm(b.ARMS[i-15])
        value=self.changes.get(i,value)
        return 200,b.encoded(dict(jsonrpc='2.0',id=i,result=value))


class Tests(unittest.TestCase):
    def test_exact_manifest_and_abi_overrides(self):
        manifest=b.build_manifest()
        self.assertEqual(len(manifest),19)
        self.assertEqual(b.sha(b.encoded(manifest)), '2887172d8a04339a05f39540c8716f7d24160f39e89850d5f583b16df89c5861')
        self.assertEqual([x['method'] for x in manifest[:3]],['eth_chainId','eth_getBlockByNumber','eth_getCode'])
        self.assertEqual(manifest[-1]['params'],['$parent.number',False])
        from Crypto.Hash import keccak
        for signature,selector in b.SELECTORS.items():
            k=keccak.new(digest_bits=256);k.update(signature.encode())
            self.assertEqual(k.hexdigest()[:8],selector)
        for i,item in enumerate(manifest[13:18]):
            payload=item['params'][0];block=payload['blockStateCalls'][0]
            self.assertTrue(payload['validation']);self.assertFalse(payload['traceTransfers'])
            self.assertEqual(block['stateOverrides'],{b.SENDER:{'balance':hex(11*10**18),'nonce':'0x0'}})
            self.assertEqual(block['blockOverrides']['feeRecipient'],b.RECIPIENT)
            self.assertEqual(block['blockOverrides']['withdrawals'],[])
            calls=block['calls'];self.assertEqual(len(calls),9 if i==0 else 5)
            self.assertEqual([c['nonce'] for c in calls],[hex(n) for n in range(len(calls))])
            self.assertTrue(all(c['gas']==hex(1000000) for c in calls))
            if i:
                self.assertEqual(int(calls[1]['value'],16),b.ARMS[i-1])
                self.assertEqual(calls[3]['input'],b.data('get_dy(int128,int128,uint256)',1,0,b.ARMS[i-1]))
            resolved=b.resolve(item,PARENT)
            self.assertEqual(resolved['params'][1],PARENT['number'])
            self.assertEqual(resolved['params'][0]['blockStateCalls'][0]['blockOverrides']['time'],hex(WALL//10**9+12))

    def test_all_four_bounds_and_failed_post_submit_unknown(self):
        for principal in b.ARMS:
            for q,negative in ((principal-2,True),(principal-1,True),(principal,False)):
                row=b.arm_result(arm(principal,q),PARENT,principal,domain())
                self.assertEqual(row['upper_payout_wei'],str(q+1));self.assertEqual(row['nonpositive_bound'],negative)
                self.assertLessEqual(int(row['displayed_balance_wei']),principal)
            for position,value in ((0,1),(1,0),(2,principal+1),(4,10**10+1)):
                changed=arm(principal);changed[0]['calls'][position]['returnData']=word(value)
                with self.assertRaises(b.ArmUnavailable):b.arm_result(changed,PARENT,principal,domain())
            failed=arm(principal);failed[0]['calls'][2].update(status='0x0',returnData='0x',error={'code':3,'message':'synthetic revert'})
            with self.assertRaisesRegex(b.ArmUnavailable,'simulation_call_failed'):
                b.arm_result(failed,PARENT,principal,domain())
        for field,value in (('miner',b.CURVE),('timestamp',hex(WALL//10**9+13)),('withdrawals',[{}]),('gasUsed','0x0')):
            invalid=child(NUMBERS);invalid[0][field]=value
            with self.assertRaises(b.Refusal):b.domain_values(invalid,PARENT)
        invalid=arm(b.ARMS[0]);invalid[0]['calls'][0]['returnData']='0x01'
        with self.assertRaises(b.helper.ProbeError):b.arm_result(invalid,PARENT,b.ARMS[0],domain())

    def test_domains_and_clock_refusal(self):
        for index,value in ((0,NUMBERS[1]),(1,NUMBERS[0]),(2,NUMBERS[3]),(5,2),(7,10**10+1),(8,10**10+1)):
            numbers=list(NUMBERS);numbers[index]=value
            with self.assertRaises(b.Refusal):b.domain_values(child(numbers),PARENT)
        for changed in ({'staking_paused':True},{'stake_limit':0},
                        {'buffered_ether':b.LIMIT128-1},{'total_shares':b.LIMIT128-1}):
            d=domain();d.update(changed)
            with self.assertRaises(b.ArmUnavailable):b.arm_domain(b.ARMS[-1],d)
        with tempfile.TemporaryDirectory() as temp:
            clock=Clock();peer=Peer();study=b.Study(Path(temp),'a'*64,100,peer,clock.monotonic,clock.sleep,lambda:WALL+12000000000)
            with self.assertRaisesRegex(b.Refusal,'fixed_child_before'):study.execute()
            self.assertEqual(len(peer.requests),2)
            self.assertEqual(len(study.summary('inconclusive','clock',True)['arms']),4)
        with tempfile.TemporaryDirectory() as temp:
            clock=Clock();peer=Peer();study=b.Study(Path(temp),'a'*64,100,peer,clock.monotonic,clock.sleep,clock.wall)
            study.parent=PARENT;study.decision_mono=0
            study.rpc(14)
            self.assertGreaterEqual(study.last_start,.4)

    def test_pipeline_independent_arms_final_barrier_and_denominator(self):
        failed=arm(b.ARMS[0]);failed[0]['calls'][1].update(status='0x0',returnData='0x',error={'code':3})
        changed_header=dict(PARENT,hash='0x'+'44'*32)
        for changes,valid,all_negative in (({},4,True),({15:arm(b.ARMS[0],b.ARMS[0])},4,False),
                                          ({15:failed},3,False),({19:changed_header},0,False)):
            with tempfile.TemporaryDirectory() as temp:
                clock=Clock();peer=Peer(changes);study=b.Study(Path(temp),'a'*64,100,peer,clock.monotonic,clock.sleep,clock.wall)
                with patch.dict(b.CODE_SHA,{addr:b.sha(bytes.fromhex(FAKE_CODE[2:])) for addr in b.CODE_SHA}):
                    if 19 in changes:
                        with self.assertRaisesRegex(b.Refusal,'final_parent_changed'):study.execute()
                    else:study.execute()
                result=study.summary('finished',None,True)
                self.assertEqual(result['valid_arms'],valid);self.assertEqual(result['all_four_nonpositive'],all_negative)
                self.assertEqual(len(peer.requests),19);self.assertEqual(len(result['arms']),4)
                for request in peer.requests[14:18]:
                    block=request['params'][0]['blockStateCalls'][0]
                    self.assertEqual(request['params'][1],PARENT['number'])
                    self.assertEqual(block['stateOverrides'][b.SENDER]['nonce'],'0x0')
                self.assertTrue(all(x['request_start_monotonic']>=n for n,x in enumerate(study.trace.records)))
                self.assertFalse(study.summary('finished',None,False)['all_four_nonpositive'])

    def test_response_caps_partial_trace_and_atomic_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);clock=Clock();seen=[]
            def transport(request,timeout,limit):seen.append(limit);return 200,b'abc'
            study=b.Study(out,'a'*64,100,transport,clock.monotonic,clock.sleep,clock.wall)
            study.total_bytes=b.CAPS['cumulative_response_bytes']-3
            with self.assertRaisesRegex(b.Refusal,'unproven_eof_boundary'):study.rpc(0)
            self.assertEqual(seen,[3]);self.assertEqual(study.total_bytes,b.CAPS['cumulative_response_bytes'])
            record=study.trace.records[-1];self.assertEqual(base64.b64decode(record['response_body_base64']),b'abc')
            previous=(out/'trace.json.gz').read_bytes()
            with patch.dict(b.CAPS,trace_plaintext_bytes_in_memory=4200):
                with self.assertRaises(b.Refusal):study.trace.put({'response_body_base64':base64.b64encode(b'x'*6000).decode()})
            self.assertEqual((out/'trace.json.gz').read_bytes(),previous)
            b.publish(out,'one.json',{'observations':None})
            with self.assertRaises(FileExistsError):b.publish(out,'one.json',{})
            self.assertFalse((out/'one.json.pending').exists())
        with tempfile.TemporaryDirectory() as temp:
            clock=Clock()
            def partial(*_):raise b.helper.TransportError('synthetic',partial=b'ab',status=200)
            study=b.Study(Path(temp),'a'*64,100,partial,clock.monotonic,clock.sleep,clock.wall)
            with self.assertRaisesRegex(b.Refusal,'transport_failure'):study.rpc(0)
            self.assertEqual(study.total_bytes,2)
            self.assertEqual(base64.b64decode(study.trace.records[-1]['response_body_base64']),b'ab')
        with tempfile.TemporaryDirectory() as temp:
            clock=Clock();peer=Peer();study=b.Study(Path(temp),'a'*64,0,peer,clock.monotonic,clock.sleep,clock.wall)
            with self.assertRaisesRegex(b.Refusal,'request_work_deadline'):study.rpc(0)
            self.assertEqual(peer.requests,[])

    def test_dry_frozen_pins_and_no_scope_widening(self):
        with patch.object(b.helper,'http_transport',side_effect=AssertionError('HTTP')),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(b.main([]),0)
        self.assertEqual(json.loads(output.getvalue())['http_requests'],0)
        with self.assertRaises(b.Refusal):b.verify(None)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);fixtures=[]
            for name,payload in ((b.SOURCE,b'runner fixture'),(b.TEST,b'test fixture'),
                (b.HELPER['path'],b'helper fixture'),(b.DESIGN['path'],b'design fixture'),
                (b.PRIOR['path'],b.encoded({'status':'metadata_compatibility_confirmed_full_route_unproven'}))):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
                fixtures.append(dict(path=name,bytes=len(payload),sha256=b.sha(payload)))
            maps={x['path']:x for x in fixtures}
            plan=dict(schema='primary-issuance-bound-local-v1',status='frozen_primary_issuance_bound',
                endpoint=b.ENDPOINT,output_dir=b.OUT,resource_limits=b.CAPS,
                fixed_principals_wei=[str(x) for x in b.ARMS],domain_views=list(b.DOMAIN),
                design=maps[b.DESIGN['path']],prior_metadata_receipt=maps[b.PRIOR['path']],
                runtime=b.runtime_identity(),request_manifest=b.build_manifest(),source_pins=fixtures)
            file=root/b.PLAN;file.parent.mkdir(parents=True,exist_ok=True)
            def save():raw=b.encoded(plan);file.write_bytes(raw);return b.sha(raw)
            with patch.object(b,'ROOT',root),patch.object(b,'HELPER',maps[b.HELPER['path']]), \
                patch.object(b,'DESIGN',maps[b.DESIGN['path']]),patch.object(b,'PRIOR',maps[b.PRIOR['path']]):
                self.assertEqual(b.verify(save())['source_pins'],fixtures)
                baseline=copy.deepcopy(plan)
                for mutate in (lambda:plan.update(status='offline_implementation_only'),
                    lambda:plan.update(endpoint='https://unapproved.invalid'),
                    lambda:plan['source_pins'].pop(),lambda:plan['runtime'].update(python_version='wrong'),
                    lambda:plan['request_manifest'][14]['params'][0]['blockStateCalls'][0]['stateOverrides'].update({b.CURVE:{'balance':'0x1'}})):
                    plan.clear();plan.update(copy.deepcopy(baseline));mutate()
                    with self.assertRaises(b.Refusal):b.verify(save())
                plan.clear();plan.update(baseline);digest=save()
                (root/b.TEST).write_bytes(b'changed')
                with self.assertRaises(b.Refusal):b.verify(digest)
                (root/b.TEST).write_bytes(b'test fixture');(root/b.OUT).mkdir()
                with patch.object(b.multiprocessing,'get_context',side_effect=AssertionError('worker')):
                    with self.assertRaises(FileExistsError):b.run(digest)

    def test_protected_worker_terminal_post_pin_failure_and_interruption_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);study=b.Study(out,'a'*64,time.monotonic()+100)
            study.parent=PARENT;study.domain=domain();study.arms=[b.arm_result(arm(p),PARENT,p,study.domain) for p in b.ARMS]
            study.final_parent_verified=True
            with patch.object(b,'Study',return_value=study),patch.object(study,'execute'), \
                 patch.object(b,'verify',side_effect=[{},b.Refusal('changed')]):
                b.worker('a'*64,out,time.monotonic()+100)
            summary=json.loads((out/'summary.json').read_bytes());terminal=json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['code'],'post_run_pin_check_failed')
            self.assertFalse(summary['all_four_nonpositive']);self.assertEqual(summary['valid_arms'],0)
            self.assertTrue(all(x['upper_payout_wei'] is None for x in summary['arms']))
        class Dead:
            exitcode=1
            def __init__(self,alive=False):self.alive=alive
            def start(self):pass
            def join(self,*_):pass
            def is_alive(self):return self.alive
            def kill(self):self.alive=False;self.exitcode=-9
        class Context:
            def __init__(self,alive=False):self.alive=alive
            def Process(self,**_):return Dead(self.alive)
        with tempfile.TemporaryDirectory() as temp,patch.object(b,'ROOT',Path(temp)), \
            patch.object(b,'verify',return_value={'source_pins':[]}), \
            patch.object(b.multiprocessing,'get_context',return_value=Context()):
            result=b.run('a'*64);out=Path(temp)/b.OUT
            self.assertEqual(result['status'],'worker_failed_without_terminal')
            summary=json.loads((out/'summary.json').read_bytes());terminal=json.loads((out/'terminal.json').read_bytes())
            self.assertIsNone(summary['requests_attempted']);self.assertIsNone(terminal['requests_attempted'])
            self.assertEqual(len(summary['arms']),4);self.assertFalse(summary['all_four_nonpositive'])
            self.assertLessEqual(sum(x.stat().st_size for x in out.glob('*.json')),16384)
        with tempfile.TemporaryDirectory() as temp,patch.object(b,'ROOT',Path(temp)), \
            patch.object(b,'verify',return_value={'source_pins':[]}), \
            patch.object(b.multiprocessing,'get_context',return_value=Context(True)):
            result=b.run('a'*64)
            self.assertEqual(result['status'],'process_deadline')
            self.assertIsNone(json.loads((Path(temp)/b.OUT/'terminal.json').read_bytes())['requests_attempted'])


if __name__=='__main__':unittest.main()
