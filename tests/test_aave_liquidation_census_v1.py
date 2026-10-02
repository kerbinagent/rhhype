import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

P = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('census', P/'scripts/aave_liquidation_census_v1.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def hx(n):
    return '0x' + format(n, '064x')


def head(n):
    return dict(number=hex(n), hash=hx(n), parentHash=hx(n-1),
                timestamp=hex(100000 + n*12), stateRoot=hx(777))


def log(n, index):
    return dict(address=c.POOL, blockNumber=hex(n), blockHash=hx(n),
                transactionHash=hx(n+100000), transactionIndex='0x1', logIndex=hex(index),
                removed=False, topics=[c.TOPIC, hx(101), hx(102), hx(index+1000)],
                data='0x'+''.join(format(v, '064x') for v in (1000000, 1100000, 103, 0)))


def health_words(hf=10**18-1, debt=100):
    return '0x' + ''.join(format(v, '064x') for v in (200, debt, 0, 8000, 7500, hf))


class Fixture:
    def __init__(self, count=10):
        self.logs = [log(900+i*10, i) for i in range(count)]
        self.calls = []
        self.before_missing = set()
        self.before_healthy = set()
        self.after_error = set()
        self.anchor_change = False
        self.bad_receipt = False

    def __call__(self, name, method, params, allow_unavailable=False):
        self.calls.append((name, method, copy.deepcopy(params)))
        if name == 'chain': return '0x1'
        if name in ('anchor', 'anchor_reread'):
            v = head(8000)
            if name == 'anchor_reread' and self.anchor_change: v['hash'] = hx(99)
            return v
        if name == 'pool_code': return '0x6000'
        if name == 'pool_provider': return '0x' + c.PROVIDER[2:].rjust(64, '0')
        if name.startswith('logs_'):
            lo, hi = int(params[0]['fromBlock'], 16), int(params[0]['toBlock'], 16)
            return [copy.deepcopy(x) for x in reversed(self.logs) if lo <= int(x['blockNumber'],16) <= hi]
        if name == 'range_start': return head(801)
        i = int(name.split('_')[1])
        row = self.logs[i]
        n = int(row['blockNumber'],16)
        if name.endswith('_receipt'):
            rec = dict(transactionHash=row['transactionHash'], blockHash=row['blockHash'],
                       blockNumber=row['blockNumber'], transactionIndex=row['transactionIndex'],
                       status='0x1', gasUsed=hex(200000), effectiveGasPrice=hex(1000000000), logs=[row])
            if self.bad_receipt: rec['blockHash'] = hx(99999)
            return rec
        if name.endswith('_before_block'): return head(n-1)
        if name.endswith('_block'): return head(n)
        if name.endswith('_health_before'):
            if i in self.before_missing: return dict(rpc_unavailable=-32000)
            return health_words(10**18+1 if i in self.before_healthy else 10**18-1)
        if name.endswith('_health_after'):
            if i in self.after_error: return None
            return health_words(11*10**17)
        raise AssertionError(name)


class CensusTests(unittest.TestCase):
    def test_all_pages_and_first_eight_no_outcome_replacement(self):
        f = Fixture()
        f.before_healthy = {0, 1, 2, 3, 4, 5, 6, 7}
        d = c.collect(f)
        self.assertEqual(len(f.calls),62)
        self.assertEqual(d['event_count'],10)
        self.assertEqual(d['selected_event_count'],8)
        self.assertEqual([x['event']['log_index'] for x in d['samples']],list(range(8)))
        self.assertEqual(d['historical_simulation_candidates'],0)
        pages = [x[2][0] for x in f.calls if x[0].startswith('logs_')]
        self.assertEqual(int(pages[0]['fromBlock'],16),801)
        self.assertEqual(int(pages[-1]['toBlock'],16),8000)
        self.assertTrue(all(int(b['fromBlock'],16)==int(a['toBlock'],16)+1 for a,b in zip(pages,pages[1:])))

    def test_empty_census_not_missing_census(self):
        f=Fixture(0); d=c.collect(f)
        self.assertEqual(len(f.calls),22)
        self.assertEqual(d['page_counts'],[0]*16)
        self.assertEqual(d['samples'],[])
        self.assertFalse(d['economics'])

    def test_missing_state_retained_without_replacement(self):
        f=Fixture(); f.before_missing={1}; f.after_error={2}
        d=c.collect(f)
        self.assertEqual(d['selected_event_count'],8)
        self.assertEqual(d['missing_preceding_health'],1)
        self.assertEqual(d['historical_simulation_candidates'],7)
        self.assertFalse(d['samples'][2]['end_of_event_block_health']['available'])
        self.assertEqual(d['samples'][0]['receipt']['whole_transaction_fee_wei'],'200000000000000')

    def test_canonical_log_encoding_and_identity(self):
        good=log(900,0)
        cases=[]
        for key,value in [('removed',True),('address','0x'+'00'*20),('blockNumber','0x4000')]:
            bad=copy.deepcopy(good);bad[key]=value;cases.append(bad)
        bad=copy.deepcopy(good);bad['topics'][1]=hx(2**160);cases.append(bad)
        bad=copy.deepcopy(good);bad['data']=good['data'][:-64]+format(2,'064x');cases.append(bad)
        for bad in cases:
            with self.assertRaises((c.Refusal,c.h.Refusal)):c.event(bad,801,1250)

    def test_duplicate_log_and_receipt_mismatch_rejected(self):
        f=Fixture(1);f.logs.append(copy.deepcopy(f.logs[0]))
        with self.assertRaisesRegex(c.Refusal,'duplicate'):c.collect(f)
        f=Fixture(1);f.bad_receipt=True
        with self.assertRaisesRegex(c.Refusal,'receipt_identity'):c.collect(f)

    def test_changed_anchor_rejected(self):
        f=Fixture(1);f.anchor_change=True
        with self.assertRaisesRegex(c.Refusal,'anchor_changed'):c.collect(f)

    def test_health_integer_boundary_and_zero_debt(self):
        self.assertTrue(c.health(health_words(10**18-1))['debt_positive_and_health_below_one'])
        self.assertFalse(c.health(health_words(10**18))['debt_positive_and_health_below_one'])
        self.assertFalse(c.health(health_words(1,0))['debt_positive_and_health_below_one'])
        self.assertFalse(c.health('0x') ['available'])

    def test_rpc_identity_error_and_null_rules(self):
        err=c.encode(dict(jsonrpc='2.0',id=1,error=dict(code=-32000,message='history unavailable')))
        self.assertEqual(c.rpc_result(err,1,True),{'rpc_unavailable':-32000})
        with self.assertRaisesRegex(c.Refusal,'no_retry'):c.rpc_result(err,1,False)
        with self.assertRaisesRegex(c.Refusal,'identity'):c.rpc_result(err,2,True)
        with self.assertRaisesRegex(c.Refusal,'null'):c.rpc_result(c.encode(dict(jsonrpc='2.0',id=1,result=None)),1,False)

    def test_raw_replay_and_missing_terminal_rejected(self):
        fixture=Fixture(2)
        with tempfile.TemporaryDirectory() as tmp:
            frames=c.Frames(Path(tmp));n=0
            def rpc(name,method,params,allow_unavailable=False):
                nonlocal n
                n+=1;req=dict(jsonrpc='2.0',id=n,method=method,params=params)
                result=fixture(name,method,params,allow_unavailable)
                body=c.encode(dict(jsonrpc='2.0',id=n,result=result))
                frames.append(b'B',c.encode(dict(name=name,request=req)))
                frames.append(b'H',c.encode(dict(status=200,headers=[])))
                for i in range(0,len(body),4096):frames.append(b'D',body[i:i+4096])
                frames.append(b'E',c.encode(dict(error=None,http_status=200,dispatch_attempted=True,
                    response_bytes=len(body),response_sha256=c.sha(body))))
                return result
            expected=c.collect(rpc);frames.close()
            got,pin,total=c.replay(frames.path)
            self.assertEqual(expected,got)
            self.assertGreater(total,0)
            raw=frames.path.read_bytes()
            frames.path.write_bytes(raw[:-1])
            with self.assertRaises(c.Refusal):c.replay(frames.path)

    def _run_fixture(self, temporary_root, fail_slot=None):
        fixture=Fixture(1); queue=[]
        def prepare(name,method,params,allow_unavailable=False):
            v=fixture(name,method,params,allow_unavailable)
            queue.append((method,params,v))
            return v
        c.collect(prepare)
        requests=[]
        def fetch(request,cap,seconds,emit,observe,dispatch):
            i=len(requests);requests.append(request)
            method,params,value=queue[i]
            self.assertEqual(request,dict(jsonrpc='2.0',id=i+1,method=method,params=params))
            dispatch()
            status=403 if i+1==fail_slot else 200
            observe(status,c.encode(dict(status=status,headers=[])))
            raw=b'bounded rejection' if status==403 else c.encode(dict(jsonrpc='2.0',id=i+1,result=value))
            for at in range(0,len(raw),100):emit(raw[at:at+100])
            return status,len(raw)
        (temporary_root/'reports/aave-liquidation-census-v1').mkdir(parents=True)
        with mock.patch.object(c,'ROOT',temporary_root), mock.patch.object(c,'verify',return_value={'pins':[]}), \
             mock.patch.object(c.resource,'setrlimit'), mock.patch.object(c.h,'fetch',side_effect=fetch):
            result=c.run('a'*64)
            # The output claim is consumed, including after failure.
            with self.assertRaises(FileExistsError):c.run('a'*64)
        return result,requests

    def test_bounded_run_replays_and_consumes_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,requests=self._run_fixture(root)
            self.assertTrue(ok);self.assertEqual(len(requests),27)
            out=root/c.OUT
            terminal=json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['status'],'historical_census_complete')
            d=json.loads((out/'projection.json').read_bytes())
            self.assertEqual(d['selected_event_count'],1)
            self.assertLess(sum(p.stat().st_size for p in out.iterdir()),131072)

    def test_http_failure_preserves_prefix_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ok,requests=self._run_fixture(root,3)
            self.assertFalse(ok);self.assertEqual(len(requests),3)
            out=root/c.OUT
            terminal=json.loads((out/'terminal.json').read_bytes())
            self.assertEqual(terminal['status'],'unavailable')
            self.assertEqual(terminal['requests_attempted'],3)
            self.assertFalse((out/'projection.json').exists())
            self.assertIn(b'bounded rejection',(out/'responses.frames').read_bytes())


if __name__=='__main__':unittest.main()
