"""Fixed retrospective residual bins and delayed local quote/reference markouts."""
import datetime,gzip,json,math,sys,hashlib
from pathlib import Path
from collections import defaultdict,deque,Counter
from statistics import median
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_broad_relative as broad
from scripts.audit_single_venue_study import pair,midpoint,clock,VS,NS
from scripts.single_venue_strategy import rounded,dec,walk_ioc
from scripts.single_venue_broad_quotes import distribution
PLAN=ROOT/'reports/experiment-storage/single-venue-residual-profile-v1.json'
HORIZONS=(10,60)
BUCKETS=('below1','1to3','atleast3')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def exactmid(b):return (dec(b['bids'][0][0])+dec(b['asks'][0][0]))/2
def sweep(b,side,qty):
    q,value=walk_ioc(b,side,qty,D('Infinity') if side==1 else D(0))[:2]
    return value if qty>0 and q==qty else None

class Basis:
    def __init__(self):
        self.books=defaultdict(dict);self.refs=defaultdict(lambda:deque(maxlen=125));self.last_ref={};self.last_eval={}
    def process(self,e):
        a,v,t=e.get('asset'),e.get('venue'),e['received_ns']
        if e['type']=='invalidate':
            self.books[a].pop(v,None);self.refs[a].clear();self.last_ref.pop(a,None);self.last_eval.pop(a,None)
        if e['type']!='book':return None
        books=self.books[a];books[v]=e
        if not pair(books,t):return None
        basis=10000*math.log(midpoint(books['lighter'])/midpoint(books['rh_lighter']))
        if a not in self.last_ref or t-self.last_ref[a]>=NS:self.refs[a].append((t,basis));self.last_ref[a]=t
        if a in self.last_eval and t-self.last_eval[a]<NS:return None
        self.last_eval[a]=t
        past=[(when,value) for when,value in self.refs[a] if t-122*NS<=when<=t-2*NS]
        if len(past)<60 or past[-1][0]-past[0][0]<89*NS:return None
        return basis-median(x for _,x in past)

def diagnose(stream,metadata,start,assets):
    basis=Basis();pending=defaultdict(list);counts=defaultdict(Counter);values=defaultdict(list);end=None
    for e in stream:
        a,v,t=e.get('asset'),e.get('venue'),e['received_ns'];key=(a,v)
        if e['type']=='end':end=e;continue
        residual=basis.process(e)
        if e['type']=='invalidate':
            # Only the execution venue invalidates local quote obligations.
            # Other-venue invalidation removes reference accounting availability.
            for old in pending.pop(key,[]):counts[old['group']]['invalidated']+=1
        if e['type']!='book':continue
        keep=[];books=basis.books[a]
        for old in pending[key]:
            if t<old['due'] or e['source_ns']<old['due']:keep.append(old);continue
            g=old['group'];c=counts[g]
            if t>old['due']+2*NS or not clock(e,t):c['missing_first_eligible']+=1;continue
            if e['generation']!=old['generation']:c['generation_changed']+=1;continue
            side=old['side'] if old['stage']=='entry' else -old['side']
            value=sweep(e,side,old['qty'])
            if value is None:c['insufficient_depth']+=1;continue
            if old['stage']=='entry' and value>D(100):c['entry_quote_above_cap']+=1;continue
            other=next(x for x in VS if x!=v)
            refmid=exactmid(books[other]) if pair(books,t) else None
            mid=exactmid(e)
            if old['stage']=='entry':
                old.update(stage='exit',entry=value,mid=mid,refmid=refmid,entry_t=t,
                    entry_delay_ms=D(t-old['decision'])/1_000_000,due=t+g[-1]*NS+400_000_000)
                c['delayed_entry_quote']+=1;keep.append(old)
            else:
                sign=D(old['side']);quote=sign*(value-old['entry'])/old['entry']*10000
                move=sign*(mid-old['mid'])/old['mid']*10000
                obs=dict(mid=move,quote=quote,entry_delay_ms=old['entry_delay_ms'],holding_seconds=D(t-old['entry_t'])/NS)
                if refmid is not None and old['refmid'] is not None:
                    common=sign*old['qty']*(refmid-old['refmid'])/old['entry']*10000
                    obs.update(reference=common,residual=quote-common);c['reference_matched']+=1
                else:c['reference_missing']+=1
                values[g].append(obs);c['matched']+=1;c['long_matched' if old['side']==1 else 'short_matched']+=1
                c['quote_positive']+=int(quote>0);c['quote_above_5bp']+=int(quote>5)
        pending[key]=keep
        if residual is None or not 122*NS<=t-start<480*NS:continue
        bucket=BUCKETS[0] if abs(residual)<1 else BUCKETS[1] if abs(residual)<3 else BUCKETS[2]
        for venue in VS:
            book=books[venue];m=metadata[venue][a]
            qty=rounded(D(100)/(dec(book['asks'][0][0])*D('1.01')),m['qty_step'])
            for horizon in HORIZONS:
                g=(a,venue,bucket,horizon);c=counts[g];c['sampled']+=1
                if residual==0:c['zero_residual']+=1;continue
                if qty<dec(m['min_qty']) or qty*dec(book['bids'][0][0])<dec(m['min_notional']):c['native_minimum_reject']+=1;continue
                side=(-1 if residual>0 else 1)*(1 if venue=='lighter' else -1)
                c['admitted']+=1;c['long_admitted' if side==1 else 'short_admitted']+=1
                pending[a,venue].append(dict(group=g,side=side,qty=qty,generation=book['generation'],
                    stage='entry',decision=t,due=t+400_000_000))
    assert end
    for items in pending.values():
        for old in items:counts[old['group']]['unresolved_at_end']+=1
    rows=[]
    for a in assets:
        for v in VS:
            for bucket in BUCKETS:
                for horizon in HORIZONS:
                    g=(a,v,bucket,horizon);c=counts[g];s=values[g]
                    assert c['sampled']==c['admitted']+c['zero_residual']+c['native_minimum_reject']
                    assert c['admitted']==sum(c[x] for x in ('matched','invalidated','missing_first_eligible','generation_changed','insufficient_depth','entry_quote_above_cap','unresolved_at_end'))
                    assert c['matched']==c['reference_matched']+c['reference_missing']==c['long_matched']+c['short_matched']
                    rows.append(dict(asset=a,venue=v,bucket=bucket,horizon=horizon,counts=dict(c),
                        **{name:distribution([x[field] for x in s if field in x]) for name,field in (
                            ('signed_midpoint_bps','mid'),('signed_quote_bps','quote'),('signed_reference_bps','reference'),
                            ('quote_minus_reference_bps','residual'),('entry_delay_ms','entry_delay_ms'),('holding_seconds','holding_seconds'))}))
    return rows

def main():
    broad.verify();plan=json.loads(PLAN.read_bytes())
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    reports=[]
    for w in plan['windows']:
        p=ROOT/w['capture'];manifest=json.loads((p/'manifest.json').read_bytes())
        assert manifest['end_reason']=='duration_limit' and not manifest['truncated']
        assert sha(p/'frames.jsonl.gz')==w['raw_sha256']
        start=broad.events._epoch_ns(manifest['started_utc'])
        metadata=json.loads((p/'metadata/normalized.json').read_bytes())['markets']
        assert all(dec(m['taker_fee_bps'])==0 for markets in metadata.values() for m in markets.values())
        rows=diagnose(broad.broad_events(p,expected_manifest_sha256=w['manifest_sha256'],max_raw_bytes=broad.HARD_BYTES),metadata,start,broad.ASSETS)
        reports.append(dict(window=w['index'],started_utc=manifest['started_utc'],ended_utc=manifest['ended_utc'],rows=rows))
        print(json.dumps(dict(window=w['index'],rows=len(rows),matched_quote_profiles=sum(r['counts'].get('matched',0) for r in rows))),flush=True)
    output=dict(plan_sha256=sha(PLAN),scope=plan['scope'],windows=reports)
    payload=gzip.compress((json.dumps(output,indent=2)+'\n').encode(),mtime=0);assert len(payload)<=114688
    p=ROOT/'reports/single-venue-research/residual-profile.json.gz';assert not p.exists();p.write_bytes(payload)
if __name__=='__main__':main()
