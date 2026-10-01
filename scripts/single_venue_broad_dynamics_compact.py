"""Conditional midpoint basis paths, never execution or cash returns."""
import bisect,datetime,gzip,json,sys
from pathlib import Path
from collections import defaultdict
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_broad as broad
from scripts.single_venue_broad_quotes import distribution,sha
from scripts.single_venue_strategy import pair_fresh
PLAN=ROOT/'reports/experiment-storage/single-venue-broad-dynamics-v2.json'

def summarize(path):
    times=[r['t'] for r in path];minutes=defaultdict(list);horizons=[]
    for r in path:minutes[r['second']//60].append(D(r['basis_bps']))
    for seconds in (10,60):
        basis=[];rh=[];core=[];missing=0
        for r in path:
            j=bisect.bisect_left(times,r['t']+seconds*10**9)
            if j==len(path) or times[j]>r['t']+(seconds+1)*10**9:missing+=1;continue
            after=path[j];basis.append(D(after['basis_bps'])-D(r['basis_bps']))
            rh.append((D(after['rh_mid'])/D(r['rh_mid'])-1)*10000)
            core.append((D(after['core_mid'])/D(r['core_mid'])-1)*10000)
        horizons.append(dict(seconds=seconds,matched=len(basis),missing=missing,
            basis_change_bps=distribution(basis),rh_mid_return_bps=distribution(rh),
            core_mid_return_bps=distribution(core),basis_decrease_count=sum(x<0 for x in basis)))
    return dict(samples=len(path),first=path[0] if path else None,last=path[-1] if path else None,
        basis_bps=distribution([D(r['basis_bps']) for r in path]),
        minute_medians={str(k):distribution(v)['p50'] for k,v in minutes.items()},horizons=horizons)

def main():
    broad.verify();plan=json.loads(PLAN.read_bytes())
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    source=ROOT/plan['capture'];manifest=json.loads((source/'manifest.json').read_bytes())
    start=broad.events._epoch_ns(manifest['started_utc']);books=defaultdict(dict);last={};paths=defaultdict(list);sampled=defaultdict(int);end=None
    for e in broad.broad_events(source,expected_manifest_sha256=plan['manifest_sha256'],max_raw_bytes=broad.HARD_BYTES):
        a=e.get('asset');v=e.get('venue');t=e['received_ns'];kind=e['type']
        if kind=='end':end=e;continue
        if kind=='invalidate':books[a].pop(v,None)
        if kind!='book':continue
        books[a][v]=e
        if v!='rh_lighter':continue
        second=(t-start)//10**9
        if not 3<=second<570 or last.get(a)==second:continue
        last[a]=second;sampled[a]+=1
        if not pair_fresh(books[a],t):continue
        mids={v:(D(str(b['bids'][0][0]))+D(str(b['asks'][0][0])))/2 for v,b in books[a].items()}
        basis=(mids['lighter']/mids['rh_lighter']-1)*10000
        paths[a].append(dict(t=t,second=second,rh_mid=str(mids['rh_lighter']),core_mid=str(mids['lighter']),basis_bps=str(basis)))
    assert end
    rows=[dict(asset=a,sampled_target_seconds=sampled[a],**summarize(paths[a])) for a in broad.ASSETS]
    result=dict(plan_sha256=sha(PLAN),scope=plan['scope'],rows=rows,near_sample_columns=['t','second','rh_mid','core_mid'],near_sample_path=[[r[k] for k in ('t','second','rh_mid','core_mid')] for r in paths['NEAR']])
    blob=gzip.compress((json.dumps(result,indent=2)+'\n').encode(),mtime=0);assert len(blob)<=plan['output_max_bytes']
    out=ROOT/'reports/single-venue-research/broad-basis-dynamics.json.gz';assert not out.exists();out.write_bytes(blob)
    print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
