"""Bounded synthetic sources/HTTP responses only; no real inputs or live calls."""
import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('inventory',ROOT/'scripts/comet_collateral_inventory_v1.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
KNOWN={**m.KNOWN,'implementation_runtime_bytes':3,'implementation_runtime_sha256':m.sha(b'imp'),
       'proxy_runtime_sha256':m.sha(b'px'),'assetList_runtime_sha256':m.sha(b'list')}
PARENT={'number':'0x123','hash':'0x'+'ab'*32,'parentHash':'0x'+'cd'*32,'timestamp':'0x456','stateRoot':'0x'+'ef'*32,
        'transactions':[],'extraData':'0x00'}
def word(v): return '0x'+(v%(1<<256)).to_bytes(32,'big').hex()
def address(v): return '0x'+'00'*12+v[2:]
def asset(i): return '0x'+format(i+100,'040x')
def info(i,offset=None,duplicate=None,scale=None):
    vals=[word(i if offset is None else offset),address(asset(i if duplicate is None else duplicate)),address('0x'+'22'*20),
          word(10**(6+i%13) if scale is None else scale),word(5*10**17),word(6*10**17),word(7*10**17),word(10**25)]
    return '0x'+''.join(x[2:] for x in vals)

class Server:
    def __init__(self,overrides=None,paused=False,reserves=-1): self.overrides=overrides or {}; self.paused=paused; self.reserves=reserves; self.requests=[]; self.codes={KNOWN['comet']:b'px',KNOWN['implementation']:b'imp',KNOWN['assetList']:b'list'}
    def response(self,request):
        self.requests.append(copy.deepcopy(request)); method=request['method']; params=request['params']; position=None
        if method=='eth_chainId': name='chain'; result='0x1'
        elif method=='eth_getBlockByNumber': name='parent' if params[0]=='latest' else 'final_parent'; result=copy.deepcopy(PARENT)
        elif method=='eth_getStorageAt':
            name='final_implementation' if any(r['method']=='eth_getStorageAt' for r in self.requests[:-1]) else 'implementation_slot'; result=address(KNOWN['implementation'])
        elif method=='eth_getCode': name={KNOWN['comet']:'proxy_code',KNOWN['implementation']:'implementation_code',KNOWN['assetList']:'asset_list_code'}[params[0]]; result='0x'+self.codes[params[0]].hex()
        else:
            assert method=='eth_call'; obj=params[0]; selector=obj['input'][2:10]; arg=int(obj['input'][10:] or '0',16)
            names={v:k for k,v in m.SELECTORS.items()}; sig=names[selector]
            assert obj['from']==m.abi.ZERO and obj['to']==KNOWN['comet'] and obj['value']=='0x0' and obj['gas']=='0x30d40'
            if sig=='getAssetInfo(uint8)': name=f'asset_{arg:02d}_info'; result=info(arg)
            elif sig=='getCollateralReserves(address)':
                i=arg-100; name=f'asset_{i:02d}_inventory'; result=word(0 if i==0 else i*123)
            else:
                name={'numAssets()':'num_assets','assetList()':'asset_list','isBuyPaused()':'buy_pause','getReserves()':'base_reserves','targetReserves()':'target_reserves'}[sig]
                result={'numAssets()':word(13),'assetList()':address(KNOWN['assetList']),'isBuyPaused()':word(self.paused),'getReserves()':word(self.reserves),'targetReserves()':word(0)}[sig]
        if method in ('eth_call','eth_getStorageAt','eth_getCode'): assert params[-1]=={'blockHash':PARENT['hash'],'requireCanonical':True}
        result=self.overrides.get(name,result)
        if isinstance(result,dict) and 'error' in result: return {'jsonrpc':'2.0','id':request['id'],'error':result['error']}
        if isinstance(result,dict) and 'envelope' in result: return result['envelope']
        return {'jsonrpc':'2.0','id':request['id'],'result':result}

class Response:
    def __init__(self,body=b'',status=200,parts=None): self.body=io.BytesIO(body); self.parts=None if parts is None else list(parts); self.status=status; self.reads=[]
    def getheaders(self): return [('X-Test','a'),('X-Test','b')]
    def getheader(self,k): return None
    def read1(self,n):
        self.reads.append(n)
        if self.parts is None: return self.body.read(n)
        if not self.parts: return b''
        v=self.parts.pop(0)
        if isinstance(v,Exception): raise v
        if len(v)>n: self.parts.insert(0,v[n:]); return v[:n]
        return v

class Factory:
    def __init__(self,server=None,response=None): self.server=server; self.response=response; self.connections=[]
    def __call__(self,host,**kw):
        factory=self
        class Connection:
            closed=False
            def request(self,method,path,body,headers): assert method=='POST' and path=='/'; self.req=m.decode(body)
            def getresponse(self): return factory.response if factory.response is not None else Response(m.enc(factory.server.response(self.req)))
            def close(self): self.closed=True
        assert host=='ethereum-rpc.publicnode.com'; c=Connection(); self.connections.append(c); return c

def collect(out,server=None,factory=None):
    frames=m.Frames(out); clock=m.live.Clock(); server=server or Server(); factory=factory or Factory(server)
    collector=m.Inventory(None,clock); collector.transport=m.Transport(frames,lambda:collector.current_name,factory)
    result=collector.execute(); frames.finish(); return result,collector,clock,frames,factory

class Tests(unittest.TestCase):
    def test_exact39_all13_zero_native_rational_and_replay(self):
        old_limits=copy.deepcopy(m.live.CAPS)
        with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
            out=Path(d); result,collector,clock,frames,factory=collect(out)
            self.assertEqual(result['status'],'parent_inventory_pass_complete'); self.assertTrue(result['all13_inventory_available'])
            self.assertEqual(result['requests_attempted'],39); self.assertEqual(sum(result['step_outcomes'].values()),39)
            self.assertEqual([r['index'] for r in result['rows']],list(range(13)))
            self.assertEqual(result['rows'][0]['inventory_native'],'0'); self.assertFalse(result['rows'][0]['reported_sale_prerequisites_present'])
            self.assertEqual(result['rows'][1]['stock_over_scale'],{'numerator':'123','denominator':'10000000'})
            replayed,trace,raw_sha,total=m.replay(out/'responses.frames',clock.samples)
            self.assertEqual(m.enc(result),m.enc(replayed)); self.assertEqual(m.enc(collector.trace),m.enc(trace))
            projection=m.projection(result,'0'*64,raw_sha,total); self.assertTrue(projection['observed_implementation_matched'])
            records,_,_=m.parse_frames(out/'responses.frames'); self.assertEqual(records[1]['body'],m.enc({'jsonrpc':'2.0','id':2,'result':PARENT}))
            self.assertEqual(records[0]['http']['headers'],[['X-Test','a'],['X-Test','b']]); self.assertTrue(all(c.closed for c in factory.connections))
        self.assertEqual(m.live.CAPS,old_limits); self.assertEqual(m.live.CAPS['requests'],31)

    def test_view_error_bad_tuple_skip_and_inventory_error_continue(self):
        error={'error':{'code':-32000,'message':'revert'}}
        for overrides,count,missing in [({'asset_03_info':error},38,3),({'asset_04_info':'0x00'},38,4),
                                       ({'asset_05_inventory':error},39,5),({'asset_06_inventory':'0x00'},39,6)]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                out=Path(d); result,collector,clock,_,_=collect(out,Server(overrides))
                self.assertTrue(result['manifest_complete']); self.assertFalse(result['all13_inventory_available']); self.assertIsNone(result['error'])
                self.assertEqual(result['requests_attempted'],count); self.assertEqual(sum(result['step_outcomes'].values()),39)
                self.assertFalse(result['rows'][missing]['inventory_available']); self.assertIsNone(result['rows'][missing]['inventory_native'])
                self.assertEqual(result['rows'][12]['inventory_native'],str(12*123)); self.assertTrue(result['metadata']['final_parent_and_implementation_rechecked'])
                replayed,trace,_,_=m.replay(out/'responses.frames',clock.samples); self.assertEqual(m.enc(replayed),m.enc(result)); self.assertEqual(m.enc(trace),m.enc(collector.trace))

    def test_offset_duplicate_scale_width_are_explicit_model_errors(self):
        for overrides,indices in [({'asset_05_info':info(5,offset=6)},[5]),({'asset_07_info':info(7,duplicate=2)},[2,7]),
                                  ({'asset_04_info':info(4,scale=0)},[4]),({'asset_03_info':info(3,scale=1<<64)},[3])]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                result,collector,_,_,_=collect(Path(d),Server(overrides))
                self.assertTrue(result['manifest_complete']); self.assertFalse(result['all13_inventory_available'])
                for i in indices: self.assertFalse(result['rows'][i]['tuple_valid']); self.assertIsNone(result['rows'][i]['reported_sale_prerequisites_present'])
                if indices==[2,7]:
                    self.assertEqual(result['rows'][2]['inventory_native'],'246'); self.assertEqual(result['rows'][2]['inventory_observation'],'returned_positive')
                    self.assertIsNone(result['rows'][2]['stock_over_scale']); self.assertEqual(collector.trace[26]['outcome'],'skipped_tuple_unavailable')

    def test_pause_not_for_sale_do_not_suppress_rows_global_errors_fatal(self):
        for paused,reserves in [(True,-1),(False,0),(False,1)]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                result,_,_,_,_=collect(Path(d),Server(paused=paused,reserves=reserves))
                self.assertEqual(result['requests_attempted'],39); self.assertTrue(result['all13_inventory_available'])
                self.assertFalse(any(r['reported_sale_prerequisites_present'] for r in result['rows']))
        with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
            result,_,_,_,_=collect(Path(d),Server({'base_reserves':{'error':{'code':-32000,'message':'revert'}}}))
            self.assertFalse(result['manifest_complete']); self.assertEqual(result['requests_attempted'],10)
            self.assertEqual(result['not_reached_steps'],29); self.assertTrue(all(r['inventory_native'] is None for r in result['rows']))

    def test_identity_constraints_and_final_failure_stop_no_admission(self):
        cases=[({'proxy_code':'0x00'},3),({'implementation_slot':address('0x'+'11'*20)},4),({'implementation_code':'0x00'},5),
               ({'num_assets':word(12)},6),({'asset_list':address('0x'+'11'*20)},7),({'asset_list_code':'0x00'},8),
               ({'final_implementation':address('0x'+'11'*20)},38),({'final_parent':{**PARENT,'stateRoot':'0x'+'aa'*32}},39)]
        for overrides,count in cases:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                result,_,_,_,_=collect(Path(d),Server(overrides)); self.assertFalse(result['manifest_complete']); self.assertEqual(result['requests_attempted'],count)
                self.assertEqual(len(result['rows']),13); self.assertEqual(sum(result['step_outcomes'].values()),39)
                self.assertFalse(any(r['admitted_inventory_available'] for r in result['rows']))
                if count>=38: self.assertEqual(result['rows'][12]['inventory_native'],str(12*123)); self.assertIsNone(result['rows'][12]['reported_sale_prerequisites_present'])

    def test_envelope_error_transport_timeout_prefix_never_row_continue(self):
        with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
            bad={'envelope':{'jsonrpc':'2.0','id':99,'result':info(0)}}
            result,_,_,_,_=collect(Path(d),Server({'asset_00_info':bad})); self.assertEqual(result['requests_attempted'],12)
            self.assertFalse(result['manifest_complete']); self.assertEqual(result['not_reached_steps'],27)
        for exception in [TimeoutError('drip'),m.live.http.client.IncompleteRead(b'cd')]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                response=Response(parts=[b'ab',exception]); factory=Factory(response=response)
                result,_,_,_,_=collect(Path(d),factory=factory)
                self.assertEqual(result['requests_attempted'],1); self.assertEqual(len(factory.connections),1)
                expected=b'abcd' if isinstance(exception,m.live.http.client.IncompleteRead) else b'ab'
                raw=(Path(d)/'responses.frames').read_bytes(); pos=len(m.MAGIC); fragments=[]
                while pos<len(raw):
                    kind=raw[pos]; n=m.struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5; payload=raw[pos:pos+n]; pos+=n
                    if kind==ord('D'): fragments.append(payload)
                self.assertEqual(b''.join(fragments),expected)
                self.assertTrue(factory.connections[0].closed); self.assertFalse(result['manifest_complete'])

    def test_worker_success_partial_replay_and_fatal_projection(self):
        for overrides,status,all_known in [(None,'parent_inventory_pass_complete',True),({'asset_03_info':'0x00'},'parent_inventory_pass_complete',False),({'proxy_code':'0x00'},'unavailable',False)]:
            with tempfile.TemporaryDirectory() as d,patch.object(m,'KNOWN',KNOWN):
                out=Path(d); factory=Factory(Server(overrides)); original=m.Transport
                with patch.object(m,'verify'),patch.object(m,'Transport',side_effect=lambda frames,name:original(frames,name,factory)):
                    m.worker('0'*64,out,m.time.monotonic()+5)
                terminal=m.decode((out/'terminal.json').read_bytes()); projected=m.decode((out/'projection.json').read_bytes())
                self.assertEqual(terminal['status'],status); self.assertEqual(projected['result']['all13_inventory_available'],all_known)
                self.assertEqual(len(projected['result']['rows']),13); self.assertEqual(sum(projected['result']['step_outcomes'].values()),39)
                self.assertLess(sum(p.stat().st_size for p in out.iterdir()),160000)

    def test_caps_dry_refusal_and_hard_cleanup_no_zero_attempt_fabrication(self):
        with patch.object(m,'fixed_pins'),patch.object(m,'run',side_effect=AssertionError('run')),patch('sys.stdout',io.StringIO()): self.assertEqual(m.main([]),0)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/m.OUT).mkdir(parents=True)
            with patch.object(m,'ROOT',root),patch.object(m,'verify'): 
                with self.assertRaises(FileExistsError): m.run('0'*64)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            def interrupted(digest,out,deadline):
                frames=m.Frames(out); frames.frame(ord('B'),m.enc({'request':{'id':1}})); frames.handle.close(); m.time.sleep(0.2)
            began=m.time.monotonic()
            with patch.object(m,'_worker',interrupted): m.worker('0'*64,out,began+0.03)
            self.assertLess(m.time.monotonic()-began,0.15); self.assertFalse((out/'terminal.json').exists()); m.live.identity.finalize_partial(out)
            self.assertTrue((out/'responses.frames').exists())

    def test_supervisor_exact_admission_and_unrecovered_denominators(self):
        for terminal in [{'status':'parent_inventory_pass_complete','error':'failure','plan_sha256':'0'*64},
                         {'status':'wrong_stage','error':None,'plan_sha256':'0'*64},
                         {'status':'parent_inventory_pass_complete','error':None,'plan_sha256':'1'*64},None]:
            with tempfile.TemporaryDirectory() as d:
                root=Path(d); (root/Path(m.OUT).parent).mkdir(parents=True)
                def worker(digest,out,deadline):
                    if terminal is not None: m.live.publish(out,'terminal.json',terminal,8192)
                with patch.object(m,'ROOT',root),patch.object(m,'verify',return_value={'source_pins':[]}),patch.object(m,'worker',worker):
                    self.assertFalse(m.run('0'*64))
                out=root/m.OUT; supervisor=m.decode((out/'supervisor.json').read_bytes()); self.assertEqual(supervisor['status'],'unavailable')
                if terminal is None:
                    fallback=m.decode((out/'terminal.json').read_bytes()); self.assertIsNone(fallback['requests_attempted'])
                    self.assertEqual((fallback['row_denominator'],fallback['step_denominator']),(13,39)); self.assertFalse(fallback['row_values_available'])

if __name__=='__main__': unittest.main()
