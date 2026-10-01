"""Descriptive displayed-liquidity comparison; no trades or future returns."""
import datetime,gzip,json,math,sys
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.single_venue_multi import verify,capture,iter_events,sha,ASSETS
from scripts.single_venue_strategy import fresh,mid,NS,VENUES
PLAN=ROOT/'reports/experiment-storage/single-venue-liquidity-diagnostic-v1.json'

def measure(book):
    m=mid(book); result={'mid':m,'spread_bps':(float(book['asks'][0][0])-float(book['bids'][0][0]))/m*10000}
    for side,field,sign in [('buy','asks',1),('sell','bids',-1)]:
        levels=book[field];best=float(levels[0][0]);depth=0.;left=100/m;value=0.;filled=0.
        for price,quantity in levels:
            p,q=float(price),float(quantity)
            if sign*(p/best-1)<=.0005+1e-12:depth+=p*q
            take=min(left,q);value+=take*p;filled+=take;left-=take
        result[side]={'depth_within_5bps_notional':depth,'target_quantity':100/m,
            'filled_quantity':filled,'full_displayed_depth':left<=1e-10,
            'vwap_cost_from_mid_bps':sign*(value/filled/m-1)*10000 if filled and left<=1e-10 else None,
            'vwap_cost_from_best_bps':sign*(value/filled/best-1)*10000 if filled and left<=1e-10 else None}
    return result

def dist(xs):
    xs=sorted(x for x in xs if x is not None)
    return dict(n=len(xs),minimum=xs[0],median=median(xs),p90=xs[max(0,math.ceil(.9*len(xs))-1)],maximum=xs[-1]) if xs else {'n':0}

def run(digest):
    verify();p=json.loads(PLAN.read_bytes())
    for pin in p['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    source=capture.OUT;assert sha(source/'manifest.json')==digest
    manifest=json.loads((source/'manifest.json').read_bytes())
    assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
    start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*NS)
    rows=[];seen=set();ended=None
    for event in iter_events(source,expected_manifest_sha256=digest,max_raw_bytes=capture.HARD_BYTES):
        if event['type']=='end':ended=event
        if event['type']!='book' or not fresh(event,event['received_ns']):continue
        second=(event['received_ns']-start)//NS
        if not 0<=second<600:continue
        key=event['asset'],event['venue'],second
        if key in seen:continue
        seen.add(key)
        rows.append(dict(asset=key[0],venue=key[1],second=second,
            received_ns=event['received_ns'],source_ns=event['source_ns'],
            generation=event['generation'],sequence=event['sequence'],**measure(event)))
    assert ended
    summary={}
    for asset in ASSETS:
        summary[asset]={}
        for venue in VENUES:
            selected=[r for r in rows if r['asset']==asset and r['venue']==venue]
            item={'sampled_seconds':len(selected),'missing_seconds':600-len(selected),
                'spread_bps':dist(r['spread_bps'] for r in selected)}
            for side in ('buy','sell'):
                item[side]={'incomplete_visible_depth':sum(not r[side]['full_displayed_depth'] for r in selected)}
                for field in ('depth_within_5bps_notional','vwap_cost_from_mid_bps','vwap_cost_from_best_bps'):
                    item[side][field]=dist(r[side][field] for r in selected)
            summary[asset][venue]=item
    output=dict(manifest_sha256=digest,plan_sha256=sha(PLAN),summary=summary,rows=rows,
        limitations='First fresh book per asset/venue per capture-relative second; missing seconds retained. Venues need not be synchronous. Depth is displayed only. Fixed quantity100/mid benchmark ignores native lot/minimum rules, fees, queue changes and latency, and is not a submitted order or profit estimate. Five-bp depth measured from each own best quote, not midpoint. No future returns or causal inference.')
    packed=gzip.compress((json.dumps(output,separators=(',',':'),allow_nan=False)+'\n').encode(),mtime=0)
    assert len(packed)<=131072
    out=ROOT/'reports/single-venue-research/multi-liquidity-diagnostic.json.gz'
    assert not out.exists();out.write_bytes(packed)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':run(*sys.argv[1:])
