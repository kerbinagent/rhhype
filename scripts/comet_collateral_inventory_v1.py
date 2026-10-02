"""One future fixed parent-only all13 collateral screen. Default dry is offline.

Only reported native inventory; no child, price, quote, account or economic route.
Old helper globals and sources are unchanged; their31-request collector is unused.
"""
import argparse
import hashlib
import io
import math
import multiprocessing
import os
from pathlib import Path
import re
import struct
import sys
import time
import types

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
SOURCE='scripts/comet_collateral_inventory_v1.py'
TEST='tests/test_comet_collateral_inventory_v1.py'
DESIGN='reports/comet-collateral-inventory-v1/design.txt'
PLAN='reports/experiment-storage/comet-collateral-inventory-v1.json'
OUT='reports/comet-collateral-inventory-v1/run-v1'
ALLOCATION={'path':'reports/experiment-storage/comet-collateral-inventory-preparation-v1.json','bytes':5871,
            'sha256':'ff6c15b29607e01639d208dc61668ba03f73bdb0c8580e6e895d2277a4722e5b'}
INPUTS=[
 {'path':'scripts/comet_eligibility_live_v1.py','bytes':25331,'sha256':'fd47105e387bd05bb5a32e59c737d471efc47b91af911956c312bb8e5a00953b'},
 {'path':'reports/comet-reproduction-v1/root-reconciliation.json','bytes':3539,'sha256':'b7b9c7b26ee0efbd8088f1899e88484620a1b7a15509b7a4361045fa2113edfd'},
 {'path':'reports/comet-reproduction-v1/run-v1/projection.json','bytes':8446,'sha256':'30e747aa8da0539e8885cc2ffaf7d74afa9c490d9f4e92353f1cb565432e91ac'},
 {'path':'reports/comet-eligibility-live-v1/root-reconciliation.json','bytes':4116,'sha256':'33c84789ca9e2e5d4f37c932258ec58bed45633252f6e3bda8ca8f7962706c03'},
 {'path':'reports/comet-eligibility-live-v1/run-v1/projection.json','bytes':5091,'sha256':'627eb90ab6b9d15f994bfbb8e6a620c2f84e593b8ac29880e6f3ded75eef8ef0'}]
KNOWN={'assetList':'0xc5a15cdc440fc22e6cf8114ee5771f4ef5e24c7f',
       'assetList_runtime_sha256':'b43f6ddb8609e34a4f7ca44ae6c5e80173abc8071de5942e9843bb751341070c',
       'comet':'0xc3d688b66703497daa19211eedff47f25384cdc3',
       'implementation':'0x63e749153baf1838f63ca22c275370bd2b1ceb15','implementation_runtime_bytes':18599,
       'implementation_runtime_sha256':'b942614560ef7218a52173cc501ce9198f74a558348edf957cda62a218aa20fe','numAssets':13,
       'proxy_runtime_sha256':'882d25cd6d729bac78ed7e63b0f05e2a476394850343864e2dab53a7ecc9812a'}
CAPS={'requests':39,'response_bytes':65536,'cumulative_body_bytes':524288,'raw_bytes':655360,
      'derived_trace_bytes':524288,'projection_bytes':32768,'controls_bytes':65536,'run_controls_bytes':32768,
      'frame_payload_bytes':8192,'header_bytes':8192,'request_seconds':10,'worker_seconds':120,
      'supervisor_seconds':125,'clock_samples':512}
ENDPOINT='https://ethereum-rpc.publicnode.com'
MAGIC=b'COMET-COLLATERAL-INVENTORY-V1\n'
CLAIMS={'source_equivalence_proven':False,'transitive_source_binding_available':False,
        'prices_or_quotes_observed':False,'economic_cash_evaluated':False,'cash_closed':False}

class Refusal(Exception): pass
class ViewError(Exception): pass
class Stop(Exception): pass
class BadTuple(Exception): pass

def sha(b): return hashlib.sha256(b).hexdigest()
def bounded(path,cap):
    if path.is_symlink() or not path.is_file(): raise Refusal('nonregular_file')
    with path.open('rb') as f: raw=f.read(cap+1)
    if len(raw)>cap: raise Refusal('file_cap')
    return raw
def pin(p,cap=131072):
    if (not isinstance(p,dict) or set(p)!={'path','bytes','sha256'} or type(p['bytes']) is not int
        or not 0<p['bytes']<=cap or not isinstance(p['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',p['sha256'])): raise Refusal('pin_schema')
    path=ROOT/p['path']
    if not path.resolve().is_relative_to(ROOT) or any(x.is_symlink() for x in (path,*path.parents)): raise Refusal('pin_path')
    raw=bounded(path,cap)
    if len(raw)!=p['bytes'] or sha(raw)!=p['sha256']: raise Refusal('pin_identity')
    return raw

_raw=pin(INPUTS[0],65536)
live=types.ModuleType('comet_inventory_frozen_helpers'); live.__file__=str(ROOT/INPUTS[0]['path'])
exec(compile(_raw,live.__file__,'exec'),live.__dict__); del _raw
abi=live.engine; enc=live.enc; decode=live.decode; alarm=live.alarm; utc=live.utc
SELECTORS={'numAssets()':'a46fe83b','assetList()':'e372f03a','isBuyPaused()':'d8e5f611',
           'getReserves()':'0902f1ac','targetReserves()':'32176c49',
           'getAssetInfo(uint8)':'c8c7fe6b','getCollateralReserves(address)':'9ff567f8'}

def call(sig,*args):
    return {'from':abi.ZERO,'to':KNOWN['comet'],'input':'0x'+SELECTORS[sig]+''.join(
        format(int(a,16) if isinstance(a,str) and a.startswith('0x') else a,'064x') if not str(a).startswith('$') else '$word.'+str(a)[1:] for a in args),
        'gas':hex(200000),'value':'0x0'}

def build_manifest():
    anchor={'blockHash':'$parent.hash','requireCanonical':True}
    prefix=[('chain','eth_chainId',[]),('parent','eth_getBlockByNumber',['latest',False]),
      ('proxy_code','eth_getCode',[KNOWN['comet'],anchor]),
      ('implementation_slot','eth_getStorageAt',[KNOWN['comet'],abi.IMPLEMENTATION_SLOT,anchor]),
      ('implementation_code','eth_getCode',[KNOWN['implementation'],anchor]),
      ('num_assets','eth_call',[call('numAssets()'),anchor]),('asset_list','eth_call',[call('assetList()'),anchor]),
      ('asset_list_code','eth_getCode',[KNOWN['assetList'],anchor]),
      ('buy_pause','eth_call',[call('isBuyPaused()'),anchor]),('base_reserves','eth_call',[call('getReserves()'),anchor]),
      ('target_reserves','eth_call',[call('targetReserves()'),anchor])]
    rows=[{'position':i+1,'name':n,'method':m,'params':p,'condition':'required_until_failure'} for i,(n,m,p) in enumerate(prefix)]
    for i in range(13):
        rows.append({'position':len(rows)+1,'name':f'asset_{i:02d}_info','method':'eth_call','params':[call('getAssetInfo(uint8)',i),anchor],
                     'condition':'required_until_failure','asset_index':i})
        # A placeholder for one ABI word, resolved only from this row's valid tuple.
        obj={'from':abi.ZERO,'to':KNOWN['comet'],'input':'0x'+SELECTORS['getCollateralReserves(address)']+'$asset_word',
             'gas':hex(200000),'value':'0x0'}
        rows.append({'position':len(rows)+1,'name':f'asset_{i:02d}_inventory','method':'eth_call','params':[obj,anchor],
                     'condition':'tuple_valid','asset_index':i})
    rows.extend([{'position':38,'name':'final_implementation','method':'eth_getStorageAt','params':[KNOWN['comet'],abi.IMPLEMENTATION_SLOT,anchor],
                  'condition':'required_until_failure'},
                 {'position':39,'name':'final_parent','method':'eth_getBlockByNumber','params':['$parent.number',False],'condition':'required_until_failure'}])
    return rows

def fixed_pins():
    pin(ALLOCATION,8192)
    for p in INPUTS: pin(p,65536)
    live.fixed_pins()  # only unchanged source/control chain; no old raw body replay

def verify(digest):
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest): raise Refusal('exact_plan_sha_required')
    raw=bounded(ROOT/PLAN,32768)
    if sha(raw)!=digest: raise Refusal('plan_sha')
    p=decode(raw); fixed_pins()
    if (p.get('schema')!='comet-collateral-inventory-v1' or p.get('status')!='frozen_comet_collateral_inventory'
        or p.get('allocation')!=ALLOCATION or p.get('input_pins')!=INPUTS or p.get('known_identity')!=KNOWN
        or p.get('resource_limits')!=CAPS or p.get('endpoint')!=ENDPOINT or p.get('output_dir')!=OUT
        or p.get('manifest_sha256')!=sha(enc(build_manifest())) or p.get('runtime')!=live.identity.runtime_identity()
        or p.get('claims')!=CLAIMS): raise Refusal('frozen_scope')
    pins=p.get('source_pins')
    if not isinstance(pins,list) or len(pins)!=3 or {x.get('path') for x in pins if isinstance(x,dict)}!={SOURCE,TEST,DESIGN}: raise Refusal('exact_source_pins')
    for x in pins: pin(x)
    if Path(sys.executable).absolute()!=ROOT/'.venv/bin/python' or sys.version_info[:3]!=(3,13,9): raise Refusal('python_runtime')
    path=ROOT/OUT
    if any(x.is_symlink() for x in (path,*path.parents)): raise Refusal('output_symlink')
    return p

class Frames(live.Frames):
    def __init__(self,out):
        self.out=out; self.path=out/'responses.frames.pending'; self.handle=self.path.open('xb')
        self.handle.write(MAGIC); self.handle.flush(); os.fsync(self.handle.fileno()); self.bytes=len(MAGIC)
        self.body_bytes=0; self.attempts=0

class Transport(live.Transport):
    def __call__(self,request,timeout):
        if self.frames.attempts>=39 or not 0<timeout<=10: raise Refusal('transport_admission_cap')
        stream=live.Stream(self,request,timeout); return stream.status,stream

def asset_info(value):
    try:
        raw=abi.hex_bytes(value,256); words=['0x'+raw[i:i+32].hex() for i in range(0,256,32)]
        result=dict(zip(('offset','asset','price_feed','scale','borrow_factor','liquidate_factor','liquidation_factor','supply_cap'),
          (abi.uint(words[0],8),abi.address(words[1]),abi.address(words[2],nonzero=False),abi.uint(words[3],64),
           abi.uint(words[4],64),abi.uint(words[5],64),abi.uint(words[6],64),abi.uint(words[7],128))))
        if result['scale']==0: raise BadTuple('zero_scale')
        return result
    except (abi.GateError,ValueError,TypeError) as exc: raise BadTuple('noncanonical_asset_tuple') from exc

class Inventory:
    def __init__(self,transport,clock=time.monotonic):
        self.transport=transport; self.clock=clock; self.started=None; self.current_name=None; self.used=False
        self.trace=[{**x,'outcome':'not_reached'} for x in build_manifest()]
        self.rows=[{'index':i,'tuple':None,'tuple_valid':False,'model_issues':[],'inventory_native':None,
                    'inventory_observation':'not_reached','reason':'not_reached'} for i in range(13)]
        self.metadata={'identity':{},'global_views':{}}; self.total=0; self.attempts=0; self.parent=None
    def params(self,obj,index=None):
        if isinstance(obj,list): return [self.params(x,index) for x in obj]
        if isinstance(obj,dict): return {k:self.params(v,index) for k,v in obj.items()}
        if obj=='$parent.hash': return self.parent['hash']
        if obj=='$parent.number': return self.parent['number']
        if isinstance(obj,str) and '$asset_word' in obj:
            return obj.replace('$asset_word',self.rows[index]['tuple']['asset'][2:].rjust(64,'0'))
        return obj
    def rpc(self,position):
        row=self.trace[position-1]; self.current_name=row['name']
        remaining=524288-self.total
        if remaining<=0 or self.attempts>=39 or self.clock()-self.started>=110: raise Stop('request_body_or_time_admission_cap')
        request={'jsonrpc':'2.0','id':self.attempts+1,'method':row['method'],'params':self.params(row['params'],row.get('asset_index'))}
        if len(enc(request))>8192 or len(enc(self.trace))+4096>524288: raise Stop('derived_trace_admission_cap')
        row.update(request=request,outcome='admitted'); self.attempts+=1
        started=self.clock(); raw=bytearray(); eof=False
        try:
            timeout=min(10,110-(started-self.started)); status,stream=self.transport(request,timeout)
            limit=min(65537,remaining)
            with stream:
                while len(raw)<limit:
                    n=min(8192,limit-len(raw)); b=stream.read(n)
                    if not isinstance(b,bytes) or len(b)>n: raise Stop('read_contract')
                    if not b: eof=True; break
                    raw.extend(b)
            if not eof or len(raw)>65536 or status!=200 or self.clock()-started>10: raise Stop('response_status_body_eof_or_deadline')
            obj=decode(raw)
            if (not isinstance(obj,dict) or obj.get('jsonrpc')!='2.0' or type(obj.get('id')) is not int or obj['id']!=request['id']
                or set(obj) not in ({'jsonrpc','id','result'},{'jsonrpc','id','error'})): raise Stop('rpc_envelope')
            row['response']=obj
            if 'error' in obj:
                error=obj['error']
                if (not isinstance(error,dict) or not {'code','message'}<=set(error)<={'code','message','data'}
                    or type(error.get('code')) is not int or not isinstance(error.get('message'),str)): raise Stop('rpc_error_schema')
                row['outcome']='view_error'
                if row['method']!='eth_call': raise Stop('rpc_nonview_error')
                raise ViewError('well_formed_rpc_view_error')
            if row['method']=='eth_getBlockByNumber':
                # Keep full raw block response but bound the derived trace as in old engine.
                value=obj['result']; row['response']={**obj,'result':{k:value.get(k) for k in ('number','hash','parentHash','timestamp','stateRoot')} if isinstance(value,dict) else value}
                row['header_projection_only']=True
            row['outcome']='received'; return obj['result']
        except ViewError: raise
        except Exception as exc:
            row['outcome']='failed'; row['failure']=type(exc).__name__+':'+str(exc)[:160]
            raise Stop(row['failure']) from exc
        finally:
            self.total+=len(raw); row.update(body_bytes=len(raw),body_sha256=sha(raw),eof=eof,elapsed_seconds=self.clock()-started)
            if len(enc(self.trace))>524288-2048:
                row.pop('response',None); row['response_omitted_for_cap']=True; raise Stop('derived_trace_cap')
    def code(self,position,role,expected_sha,expected_length=None):
        value=self.rpc(position); raw=abi.hex_bytes(value)
        target=self.trace[position-1]['request']['params'][0]
        match=bool(raw) and sha(raw)==expected_sha and (expected_length is None or len(raw)==expected_length)
        self.metadata['identity'][role]={'address':target,'runtime_bytes':len(raw),'runtime_sha256':sha(raw),'fingerprint_constraint_matched':match}
        if not match: raise Stop(role+'_fingerprint_mismatch')
    def execute(self):
        if self.used: raise Refusal('one_run_consumed')
        self.used=True; self.started=self.clock(); complete=False; error=None
        try:
            if self.rpc(1)!='0x1': raise Stop('wrong_chain')
            self.parent=abi.header(self.rpc(2)); self.metadata['parent']=self.parent
            self.code(3,'proxy',KNOWN['proxy_runtime_sha256'])
            implementation=abi.address(self.rpc(4)); self.metadata['identity']['implementation_slot']=implementation
            if implementation!=KNOWN['implementation']: raise Stop('implementation_address_mismatch')
            self.code(5,'implementation',KNOWN['implementation_runtime_sha256'],KNOWN['implementation_runtime_bytes'])
            if abi.uint(self.rpc(6),8)!=13: raise Stop('num_assets_mismatch')
            self.metadata['identity']['numAssets']=13
            if abi.address(self.rpc(7))!=KNOWN['assetList']: raise Stop('asset_list_address_mismatch')
            self.metadata['identity']['assetList']=KNOWN['assetList']
            self.code(8,'asset_list',KNOWN['assetList_runtime_sha256'])
            globals_=self.metadata['global_views']
            globals_['buy_paused']=abi.boolean(self.rpc(9))
            globals_['signed_base_reserves']=str(abi.sint(self.rpc(10)))
            globals_['target_reserves']=str(abi.uint(self.rpc(11)))
            globals_['reported_unpaused_below_target']=not globals_['buy_paused'] and int(globals_['signed_base_reserves'])<int(globals_['target_reserves'])
            seen={}
            for i,row in enumerate(self.rows):
                info_pos=12+2*i; inventory_pos=info_pos+1
                try:
                    row['tuple']=asset_info(self.rpc(info_pos))
                    row['tuple_valid']=True; row['reason']=None
                    if row['tuple']['offset']!=i:
                        row['model_issues'].append('offset_index_mismatch'); row['tuple_valid']=False
                    asset=row['tuple']['asset']
                    if asset in seen:
                        previous=self.rows[seen[asset]]
                        previous['model_issues'].append('duplicate_asset'); previous['tuple_valid']=False; previous['reason']='tuple_model_inconsistent'
                        row['model_issues'].append('duplicate_asset'); row['tuple_valid']=False
                    else: seen[asset]=i
                    if not row['tuple_valid']: row['reason']='tuple_model_inconsistent'
                except (ViewError,BadTuple) as exc:
                    row['tuple_valid']=False; row['reason']=str(exc); row['inventory_observation']='tuple_unavailable'
                if not row['tuple_valid']:
                    self.trace[inventory_pos-1]['outcome']='skipped_tuple_unavailable'; row['inventory_observation']='tuple_unavailable'; continue
                try:
                    value=self.rpc(inventory_pos)
                    try: stock=abi.uint(value)
                    except (abi.GateError,ValueError,TypeError) as exc: raise BadTuple('noncanonical_inventory_word') from exc
                    row['inventory_native']=str(stock); row['inventory_observation']='returned_zero' if stock==0 else 'returned_positive'; row['reason']=None
                except (ViewError,BadTuple) as exc: row['inventory_observation']='view_unavailable'; row['reason']=str(exc)
            if abi.address(self.rpc(38))!=implementation: raise Stop('final_implementation_mismatch')
            if abi.header(self.rpc(39))!=self.parent: raise Stop('final_parent_mismatch')
            self.metadata['final_parent_and_implementation_rechecked']=True; complete=True
        except Exception as exc:
            error=type(exc).__name__+':'+str(exc)[:200]
            self.metadata['final_parent_and_implementation_rechecked']=False
        return self.result(complete,error)
    def result(self,complete,error):
        global_gate=self.metadata['global_views'].get('reported_unpaused_below_target')
        for row in self.rows:
            available=row['tuple_valid'] and row['inventory_native'] is not None
            row['inventory_available']=available
            row['admitted_inventory_available']=complete and available
            row['stock_over_scale']=({'numerator':row['inventory_native'],'denominator':str(row['tuple']['scale'])} if available else None)
            row['reported_sale_prerequisites_present']=(global_gate and int(row['inventory_native'])>0 if complete and available and global_gate is not None else None)
            row['interpretation']='native selected-parent observation only; no price/size/transfer/cash proof'
        outcomes={k:sum(x['outcome']==k for x in self.trace) for k in sorted({x['outcome'] for x in self.trace})}
        return {'status':'parent_inventory_pass_complete' if complete else 'unavailable','error':error,'parent_only':True,
                'manifest_complete':complete,'all13_inventory_available':complete and all(x['inventory_available'] for x in self.rows),
                'rows':self.rows,'metadata':self.metadata,'maximum_steps':39,'row_denominator':13,'requests_attempted':self.attempts,
                'skipped_steps':outcomes.get('skipped_tuple_unavailable',0),'not_reached_steps':outcomes.get('not_reached',0),
                'step_outcomes':outcomes,'trace_sha256':sha(enc(self.trace)),'engine_body_bytes':self.total,
                'source_binding':'unavailable','adapter_transport_model':'direct_fixed_anonymous_https_jsonrpc',**CLAIMS}

def parse_frames(path):
    raw=bounded(path,655360)
    if not raw.startswith(MAGIC): raise Refusal('raw_magic')
    pos=len(MAGIC); records=[]; active=None; total=0
    while pos<len(raw):
        if len(raw)-pos<5: raise Refusal('truncated_frame')
        kind=raw[pos]; length=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        if length>8192: raise Refusal('frame_cap')
        payload=raw[pos:pos+length]; pos+=length
        if len(payload)!=length: raise Refusal('truncated_payload')
        if kind==ord('B'):
            if active is not None or len(records)>=39: raise Refusal('frame_request_order')
            active={'begin':decode(payload),'http':None,'body':bytearray()}
        elif kind==ord('H'):
            if active is None or active['http'] is not None: raise Refusal('frame_header_order')
            active['http']=decode(payload)
        elif kind==ord('D'):
            if active is None or active['http'] is None: raise Refusal('frame_body_order')
            active['body'].extend(payload); total+=length
            if len(active['body'])>65537 or total>524288: raise Refusal('raw_body_cap')
        elif kind==ord('E'):
            if active is None: raise Refusal('frame_end_order')
            end=decode(payload); body=bytes(active['body'])
            if (end.get('body_bytes')!=len(body) or end.get('body_sha256')!=sha(body) or end.get('outcome')!='received'
                or end.get('error') is not None or end.get('eof') is not True or end.get('http_status')!=200
                or active['http'] is None or active['http'].get('http_status')!=200): raise Refusal('raw_unavailable')
            records.append({**active,'body':body}); active=None
        else: raise Refusal('frame_kind')
    if active is not None: raise Refusal('raw_incomplete')
    return records,sha(raw),total

def replay(path,samples):
    records,raw_sha,total=parse_frames(path); clock=live.Clock(samples); index=0
    def transport(request,timeout):
        nonlocal index
        if index>=len(records): raise Refusal('replay_exhausted')
        row=records[index]; index+=1
        if enc(request)!=enc(row['begin'].get('request')) or row['begin'].get('name')!=collector.current_name or row['begin'].get('timeout_seconds')!=timeout: raise Refusal('replay_request')
        return 200,io.BytesIO(row['body'])
    collector=Inventory(transport,clock=clock); result=collector.execute()
    if index!=len(records) or clock.index!=len(samples): raise Refusal('replay_unused_raw_or_clock')
    return result,collector.trace,raw_sha,total

def projection(result,digest,raw_sha,total):
    if len(result['rows'])!=13 or [x['index'] for x in result['rows']]!=list(range(13)) or sum(result['step_outcomes'].values())!=39: raise Refusal('all39_all13_denominators')
    matched=result['metadata']['identity'].get('implementation',{}).get('fingerprint_constraint_matched',False)
    return {'schema':'comet-collateral-inventory-v1-projection','status':result['status'],'plan_sha256':digest,
            'expected_identity_constraints':KNOWN,'observed_implementation_matched':matched,'result':result,
            'raw_sha256':raw_sha,'retained_body_bytes':total,
            'canonicality':'provider asserted; five-field parent comparison; no hash recomputation/independent consensus',**CLAIMS}

def _worker(digest,out,deadline):
    frames=None; result=None; error=None; status='unavailable'; clock=live.Clock(); start=utc(); began=time.monotonic(); attempts=total=None
    try:
        with alarm(max(0.000001,deadline-2-time.monotonic())):
            verify(digest); frames=Frames(out); collector=Inventory(None,clock)
            collector.transport=Transport(frames,lambda:collector.current_name); result=collector.execute()
            attempts=frames.attempts; total=frames.body_bytes; frames.finish(); frames=None
            live.publish(out,'clock-samples.json',{'samples':clock.samples},16384)
            live.publish(out,'trace.json',collector.trace,524288,kind='trace')
            raw_sha=sha(bounded(out/'responses.frames',655360)); projected=projection(result,digest,raw_sha,total)
            if result['manifest_complete']:
                reproduced,trace,rsha,rtotal=replay(out/'responses.frames',clock.samples)
                if enc(result)!=enc(reproduced) or enc(trace)!=enc(collector.trace) or rsha!=raw_sha or rtotal!=total: raise Refusal('raw_reproduction')
            verify(digest); live.publish(out,'projection.json',projected,32768,kind='projection'); verify(digest)
            if result['manifest_complete']: status='parent_inventory_pass_complete'
            else: error=result['error'] or 'inventory_pass_unavailable'
    except Exception as exc: status='unavailable'; error=type(exc).__name__+':'+str(exc)[:160]
    finally:
        if frames is not None: attempts=frames.attempts; total=frames.body_bytes; frames.finish()
        live.identity.finalize_partial(out)
        live.publish(out,'terminal.json',{'schema':'comet-collateral-inventory-v1-terminal','status':status,'error':error,'plan_sha256':digest,
                'requests_attempted':attempts,'attempt_meaning':'transport helper invocations, not authenticated wire dispatch','retained_body_bytes':total,
                'row_denominator':13,'step_denominator':39,'all13_inventory_available':result.get('all13_inventory_available') if result else None,
                'worker_start_utc':start,'worker_end_utc':utc(),'worker_start_monotonic':began,'worker_end_monotonic':time.monotonic(),**CLAIMS},8192)

def worker(digest,out,deadline):
    try:
        with alarm(max(0.000001,deadline-time.monotonic())): _worker(digest,out,deadline)
    except BaseException: return  # no child log; missing terminal is unavailable, even exit0

def run(digest):
    began=time.monotonic(); start=utc(); failure=None
    with alarm(125):
        plan=verify(digest); out=ROOT/OUT; out.mkdir(parents=True,exist_ok=False)
        live.publish(out,'claim.json',{'schema':'comet-collateral-inventory-v1-claim','plan_sha256':digest,'source_pins':plan['source_pins'],
                'start_utc':start,'launch_context':live.context(),'manifest_sha256':sha(enc(build_manifest())),**CLAIMS},8192)
        process=multiprocessing.get_context('fork').Process(target=worker,args=(digest,out,began+120))
        good=False; terminal={'status':'unavailable','requests_attempted':None}
        try:
            with alarm(max(0.000001,began+123-time.monotonic())):
                process.start(); process.join(max(0,began+122-time.monotonic()))
                if process.is_alive(): raise TimeoutError('worker_deadline')
                if (out/'terminal.json').exists(): terminal=decode(bounded(out/'terminal.json',8192))
                verify(digest)
                good=(process.exitcode==0 and terminal.get('status')=='parent_inventory_pass_complete'
                      and terminal.get('plan_sha256')==digest and terminal.get('error','missing') is None)
                if good:
                    saved=decode(bounded(out/'projection.json',32768)); samples=decode(bounded(out/'clock-samples.json',16384))['samples']
                    result,trace,raw_sha,total=replay(out/'responses.frames',samples)
                    if enc(saved)!=enc(projection(result,digest,raw_sha,total)) or enc(trace)!=enc(decode(bounded(out/'trace.json',524288))): raise Refusal('supervisor_reproduction')
                verify(digest)
        except Exception as exc: good=False; failure=type(exc).__name__+':'+str(exc)[:120]
        finally:
            if process.pid is not None and process.is_alive(): process.kill(); process.join(timeout=0.25)
            live.identity.finalize_partial(out)
            if not (out/'terminal.json').exists(): live.publish(out,'terminal.json',{'schema':'comet-collateral-inventory-v1-terminal',
                    'status':'unavailable','error':failure or 'worker_exit_without_terminal','plan_sha256':digest,'requests_attempted':None,
                    'row_denominator':13,'step_denominator':39,'per_request_dispatch_available':False,'row_values_available':False,
                    'raw_partial_retained':(out/'responses.frames').exists(),**CLAIMS},8192)
            live.publish(out,'supervisor.json',{'schema':'comet-collateral-inventory-v1-supervisor','status':'parent_inventory_pass_complete' if good else 'unavailable',
                    'error':failure,'plan_sha256':digest,'exitcode':process.exitcode,'requests_attempted':terminal.get('requests_attempted'),
                    'terminal_sha256':sha(bounded(out/'terminal.json',8192)),'start_utc':start,'end_utc':utc(),
                    'start_monotonic':began,'end_monotonic':time.monotonic(),'launch_context':live.context(),**CLAIMS},8192)
        return good

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--run',action='store_true'); p.add_argument('--plan-sha256'); a=p.parse_args(argv)
    if not a.run:
        fixed_pins(); print(enc({'status':'dry','requests':0,'outputs':0,'prospective_max_requests':39,'row_denominator':13,**CLAIMS}).decode()); return 0
    try:
        good=run(a.plan_sha256); print(enc({'status':'parent_inventory_pass_complete' if good else 'unavailable',**CLAIMS}).decode()); return 0 if good else 1
    except Exception as exc:
        print(enc({'status':'refused_or_unavailable','error':type(exc).__name__+':'+str(exc)[:120],**CLAIMS}).decode()); return 1

if __name__=='__main__': raise SystemExit(main())
