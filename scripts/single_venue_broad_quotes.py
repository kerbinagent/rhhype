"""Descriptive executable-depth quote costs; no fills or profitability claim."""
import datetime,gzip,json,hashlib,sys
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_broad as broad
from scripts.single_venue_strategy import pair_fresh,rounded,walk_ioc,dec
PLAN=ROOT/'reports/experiment-storage/single-venue-broad-quotes-v1.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def values(books,v,d,qty):
    other='rh_lighter' if v=='lighter' else 'lighter'
    def sweep(venue,side):
        return walk_ioc(books[venue],side,qty,D('Infinity') if side==1 else D(0))[:2]
    q,entry=sweep(v,d);oq,reference=sweep(other,-d);cq,close=sweep(v,-d)
    if qty<=0 or q!=qty or oq!=qty or cq!=qty or entry<=0:return None
    return dict(edge=D(d)*(reference-entry)/entry*10000,
                cost=D(d)*(entry-close)/entry*10000)

def distribution(xs):
    xs=sorted(xs)
    if not xs:return dict(n=0)
    return dict(n=len(xs),mean=str(sum(xs,D(0))/len(xs)),
                **{f'p{p}':str(xs[(len(xs)-1)*p//100]) for p in (0,50,90,99,100)})

def diagnose(stream,metadata,start,assets):
    books=defaultdict(dict);last={};pending=defaultdict(list);samples=defaultdict(list);counts=defaultdict(Counter);end=None
    for e in stream:
        a=e.get('asset');v=e.get('venue');t=e['received_ns'];kind=e['type']
        if kind=='end':end=e;continue
        if kind=='invalidate':
            books[a].pop(v,None)
            for key in list(pending):
                if key[0]==a:
                    counts[key]['delayed_invalidated']+=len(pending.pop(key))
        if kind!='book':continue
        books[a][v]=e;pair=books[a]
        for d in (1,-1):
            key=(a,v,d);due=[old for old in pending[key] if t>=old['t']+400_000_000]
            pending[key]=[old for old in pending[key] if t<old['t']+400_000_000]
            for old in due:
                if t>old['t']+2_000_000_000 or not pair_fresh(pair,t):counts[key]['delayed_missing']+=1
                else:
                    val=values(pair,v,d,old['qty'])
                    if val is None:counts[key]['delayed_depth_missing']+=1
                    else:
                        counts[key]['delayed_full']+=1
                        for b in (0,5):
                            if old['edge']>=b:
                                counts[key][f'initial_ge{b}_with_delayed_full']+=1
                                counts[key][f'initial_ge{b}_still_ge{b}']+=int(val['edge']>=b)
        sec=(t-start)//1_000_000_000
        if not 3<=sec<570 or last.get((a,v))==sec:continue
        last[a,v]=sec
        for d in (1,-1):counts[a,v,d]['sampled_target_seconds']+=1
        if not pair_fresh(pair,t):continue
        m=metadata[v][a];qty=rounded(D(100)/(dec(e['asks'][0][0])*D('1.01')),m['qty_step'])
        for d in (1,-1):
            key=(a,v,d);counts[key]['fresh_pair']+=1
            if qty<dec(m['min_qty']) or qty*dec(e['bids'][0][0])<dec(m['min_notional']):
                counts[key]['native_minimum_reject']+=1;continue
            val=values(pair,v,d,qty)
            if val is None:counts[key]['initial_depth_missing']+=1;continue
            samples[key].append(val)
            for b in (0,5):counts[key][f'initial_ge{b}']+=int(val['edge']>=b)
            pending[key].append(dict(t=t,qty=qty,edge=val['edge']))
    assert end
    for key in pending:counts[key]['delayed_unresolved_at_end']+=len(pending[key])
    rows=[]
    for a in assets:
        for v in broad.SELECTED:
            for d in (1,-1):
                key=(a,v,d);s=samples[key]
                assert len(s)==sum(counts[key][x] for x in ('delayed_full','delayed_missing','delayed_depth_missing','delayed_invalidated','delayed_unresolved_at_end'))
                rows.append(dict(asset=a,venue=v,direction=d,counts=dict(counts[key]),
                    reference_edge_bps=distribution([x['edge'] for x in s]),
                    local_roundtrip_cost_bps=distribution([x['cost'] for x in s])))
    return rows

def main():
    broad.verify();plan=json.loads(PLAN.read_bytes());source=ROOT/plan['capture']
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    assert sha(source/'manifest.json')==plan['manifest_sha256']
    assert sha(source/'frames.jsonl.gz')==plan['raw_sha256']
    manifest=json.loads((source/'manifest.json').read_bytes())
    start=broad.events._epoch_ns(manifest['started_utc'])
    metadata=json.loads((source/'metadata/normalized.json').read_bytes())['markets']
    rows=diagnose(broad.broad_events(source,expected_manifest_sha256=plan['manifest_sha256'],
        max_raw_bytes=broad.HARD_BYTES),metadata,start,broad.ASSETS)
    report=dict(plan_sha256=sha(PLAN),source_sha256=sha(Path(__file__)),scope=plan['scope'],rows=rows)
    blob=gzip.compress((json.dumps(report,indent=2)+'\n').encode(),mtime=0);assert len(blob)<=plan['output_max_bytes']
    out=ROOT/'reports/single-venue-research/broad-quote-costs.json.gz';assert not out.exists();out.write_bytes(blob)
    print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
