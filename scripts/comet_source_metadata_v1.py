"""One future, root-frozen metadata GET. Default dry has no I/O."""
import argparse,contextlib,hashlib,http.client,json,multiprocessing,os,re,signal,ssl,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parents[1]
S='scripts/comet_source_metadata_v1.py'; T='tests/test_comet_source_metadata_v1.py'
D='reports/comet-source-metadata-v1/design.txt'
P='reports/experiment-storage/comet-source-metadata-v1.json'; O='reports/comet-source-metadata-v1/run-v1'
U='https://ipfs.io/ipfs/QmdEXQFo6fLbUtMWGcpZ8Csb97ocAin4buQSCggLq5DGHg'
M='1220dd4d8e5db53112439967db2c464c1ea494a86bff16c12971539081501f5c3643'
A={'path':'reports/experiment-storage/comet-source-metadata-v1-allocation.json','bytes':2491,
   'sha256':'bcef87b2721373045e6443edf67337c638cb7adf2d6f4107c1692d68d32f1c92'}
AM={'path':'reports/experiment-storage/comet-source-metadata-v1-category-amendment.json','bytes':1512,
    'sha256':'389b0752e2e5653930815cbb60948f82d92643e4df0956b371011a8c98c4479f'}
C=65536
class Refusal(Exception): pass
def h(b): return hashlib.sha256(b).hexdigest()
def enc(x): return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def read(p,n):
    if p.is_symlink() or not p.is_file(): raise Refusal('nonregular_file')
    with p.open('rb') as f: b=f.read(n+1)
    if len(b)>n: raise Refusal('file_cap')
    return b
def js(b):
    def pairs(items):
        d={}
        for k,v in items:
            if k in d: raise ValueError('duplicate_key')
            d[k]=v
        return d
    def bad(_): raise ValueError('nonfinite')
    def flt(s):
        import math
        x=float(s)
        if not math.isfinite(x): bad(s)
        return x
    x=json.loads(b.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=bad,parse_float=flt)
    if not isinstance(x,dict): raise ValueError('nonobject')
    q=[(x,0)]; count=0
    while q:
        v,depth=q.pop(); count+=1
        if depth>32 or count>4096: raise ValueError('json_complexity')
        if isinstance(v,dict): q.extend((z,depth+1) for z in v.values())
        elif isinstance(v,list): q.extend((z,depth+1) for z in v)
    return x
def vi(n):
    b=bytearray()
    while n>127: b.append((n&127)|128); n>>=7
    return bytes(b)+bytes([n])
def cid(raw):
    n=len(raw)
    if n>C: raise Refusal('body_cap')
    inner=b'\x08\x02'+(b'\x12'+vi(n)+raw if n else b'')+b'\x18'+vi(n)
    return '1220'+h(b'\x0a'+vi(len(inner))+inner)
def project(raw,digest):
    if cid(raw)!=M: raise Refusal('cid_mismatch')
    x=js(raw); co=x.get('compiler'); st=x.get('settings'); so=x.get('sources')
    if not all(isinstance(v,dict) for v in (co,st,so)) or len(so)>128: raise Refusal('metadata_shape')
    if any(not isinstance(k,str) or len(k)>256 or not isinstance(v,dict) for k,v in so.items()): raise Refusal('source_shape')
    y={'schema':'comet-source-metadata-v1-projection','status':'content_address_verified_metadata',
       'plan_sha256':digest,'multihash_hex':M,'raw_sha256':h(raw),'body_bytes':len(raw),
       'compiler_claim':co.get('version') if isinstance(co.get('version'),str) else None,
       'compiler_sha256':h(enc(co)),'settings_sha256':h(enc(st)),
       'source_hashes':{k:h(enc(v)) for k,v in sorted(so.items())},
       'source_equivalence':False,'eligibility':False,'economics':False,'source_urls_followed':False}
    if len(enc(y))>8192: raise Refusal('projection_cap')
    return y
def verify(digest):
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest): raise Refusal('plan_sha_required')
    b=read(R/P,8192)
    if h(b)!=digest: raise Refusal('plan_sha_mismatch')
    x=js(b)
    if (x.get('schema')!='comet-source-metadata-v1' or x.get('status')!='frozen_root_only'
        or x.get('url')!=U or x.get('expected_multihash_hex')!=M or x.get('output_dir')!=O
        or x.get('allocation')!=A or x.get('category_amendment')!=AM
        or x.get('request')!={'method':'GET','accept_encoding':'identity'}
        or x.get('claims')!={'source_equivalence':False,'eligibility':False,'economics':False}): raise Refusal('plan_scope')
    pins=x.get('source_pins')
    if not isinstance(pins,list) or len(pins)!=3 or {p.get('path') for p in pins if isinstance(p,dict)}!={S,T,D}:
        raise Refusal('pins')
    for p in pins:
        if (not isinstance(p,dict) or set(p)!={'path','bytes','sha256'} or type(p['bytes']) is not int
            or not 0<p['bytes']<=16384 or not isinstance(p['sha256'],str)
            or not re.fullmatch('[0-9a-f]{64}',p['sha256'])): raise Refusal('pin_schema')
        path=R/p['path']
        if any(v.is_symlink() for v in [path,*path.parents]): raise Refusal('pin_symlink')
        data=read(path,16384)
        if len(data)!=p['bytes'] or h(data)!=p['sha256']: raise Refusal('pin_mismatch')
    b=read(R/A['path'],8192)
    if len(b)!=A['bytes'] or h(b)!=A['sha256']: raise Refusal('allocation_pin')
    b=read(R/AM['path'],8192)
    if len(b)!=AM['bytes'] or h(b)!=AM['sha256']: raise Refusal('amendment_pin')
    return x
@contextlib.contextmanager
def alarm(seconds):
    def expired(*_): raise TimeoutError('deadline')
    old=signal.signal(signal.SIGALRM,expired)
    remaining=signal.getitimer(signal.ITIMER_REAL)[0]
    prior=signal.setitimer(signal.ITIMER_REAL,max(0.000001,min(seconds,remaining) if remaining else seconds))
    start=time.monotonic()
    try: yield
    finally:
        signal.setitimer(signal.ITIMER_REAL,0); signal.signal(signal.SIGALRM,old)
        if prior[0]: signal.setitimer(signal.ITIMER_REAL,max(0.000001,prior[0]-(time.monotonic()-start)),prior[1])
def pub(out,name,value,limit):
    b=enc(value)+b'\n'
    if len(b)>limit: raise Refusal('control_cap')
    q=out/(name+'.pending')
    with q.open('xb') as f: f.write(b); f.flush(); os.fsync(f.fileno())
    os.link(q,out/name); q.unlink()
def finish(out):
    q=out/'body.raw.pending'; p=out/'body.raw'
    if q.exists() and not p.exists(): os.link(q,p); q.unlink()
def fetch(emit,factory=http.client.HTTPSConnection):
    conn=None; n=0
    with alarm(60):
        try:
            conn=factory('ipfs.io',timeout=60,context=ssl.create_default_context())
            conn.request('GET','/ipfs/QmdEXQFo6fLbUtMWGcpZ8Csb97ocAin4buQSCggLq5DGHg',
                         headers={'Accept-Encoding':'identity','Accept':'application/json'})
            r=conn.getresponse(); length=r.getheader('Content-Length')
            if r.getheader('Content-Encoding') not in (None,'identity'): raise Refusal('encoding')
            if length is not None and (not re.fullmatch('[0-9]+',length) or int(length)>C): raise Refusal('length_cap')
            while n<=C:
                limit=min(4096,C+1-n)
                try: b=r.read1(limit)
                except http.client.IncompleteRead as e:
                    b=e.partial
                    if isinstance(b,bytes) and b:
                        emit(b[:limit])
                    raise Refusal('incomplete_body') from None
                if not isinstance(b,bytes) or len(b)>limit: raise Refusal('read_contract')
                if not b:
                    if length is not None and n!=int(length): raise Refusal('incomplete_body')
                    if r.status!=200: raise Refusal('http_status')
                    return n
                emit(b); n+=len(b)
                if n>C: raise Refusal('oversize')
        finally:
            if conn is not None: conn.close()
def worker(digest,out):
    status='unavailable'; reason=None; n=0; f=None
    try:
        with alarm(60):
            verify(digest); f=(out/'body.raw.pending').open('xb')
            def emit(b):
                nonlocal n
                if n+len(b)>C+1: raise Refusal('raw_cap')
                f.write(b); f.flush(); os.fsync(f.fileno()); n+=len(b)
            fetch(emit); f.close(); f=None; finish(out)
            raw=read(out/'body.raw',C)
            if len(raw)!=n: raise Refusal('raw_length')
            value=project(raw,digest); verify(digest); pub(out,'projection.json',value,8192)
            verify(digest); status='content_address_verified_metadata'
    except BaseException as e:
        reason=str(e)[:120] if isinstance(e,Refusal) else ('timeout' if isinstance(e,TimeoutError) else 'worker_failure')
    finally:
        if f is not None: f.close()
        finish(out)
        try: verify(digest)
        except Exception: status='unavailable'; reason='post_run_pin_failure'
        p=out/'body.raw'; b=read(p,C+1) if p.exists() else None
        pub(out,'terminal.json',{'status':status,'reason':reason,'plan_sha256':digest,
            'received_bytes':n,'raw':{'bytes':len(b),'sha256':h(b)} if b is not None else None,
            'source_equivalence':False,'eligibility':False,'economics':False},2048)
def run(digest):
    with alarm(65):
        plan=verify(digest); out=R/O; out.mkdir(parents=True,exist_ok=False)
        pub(out,'claim.json',{'plan_sha256':digest,'source_pins':plan['source_pins'],
            'claimed_ns':time.time_ns(),'one_get':True},2048)
        proc=multiprocessing.get_context('fork').Process(target=worker,args=(digest,out)); started=False
        try: proc.start(); started=True; proc.join(62)
        except TimeoutError: raise
        except Exception: pass
        finally:
            if started and proc.is_alive(): proc.kill(); proc.join(0.5)
        finish(out)
        if not (out/'terminal.json').exists():
            pub(out,'terminal.json',{'status':'unavailable','reason':'worker_no_terminal',
                'plan_sha256':digest,'received_bytes':None,'raw_partial_retained':(out/'body.raw').exists()},2048)
        terminal=js(read(out/'terminal.json',2048)); good=proc.exitcode==0 and terminal['status']=='content_address_verified_metadata'
        try: verify(digest)
        except Exception: good=False
        pub(out,'supervisor.json',{'status':'content_address_verified_metadata' if good else 'unavailable',
            'plan_sha256':digest,'worker_exitcode':proc.exitcode,'terminal_sha256':h(read(out/'terminal.json',2048)),
            'source_equivalence':False,'eligibility':False,'economics':False},2048)
        return good
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('--run',action='store_true'); p.add_argument('--plan-sha256')
    a=p.parse_args(argv)
    if not a.run: print(enc({'status':'dry','network_requests':0,'writes':0}).decode()); return 0
    try:
        good=run(a.plan_sha256); print(enc({'status':'content_address_verified_metadata' if good else 'unavailable'}).decode())
        return 0 if good else 1
    except Exception:
        print(enc({'status':'unavailable'}).decode()); return 1
if __name__=='__main__': sys.exit(main())
