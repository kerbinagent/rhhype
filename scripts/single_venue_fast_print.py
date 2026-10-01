"""Exploratory individual-print/depth diagnostic on sealed public data."""
import gzip,json,math,sys
from collections import Counter,deque
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.single_venue_multi import verify,capture,iter_events,sha,ASSETS
from scripts.single_venue_strategy import pair_fresh,mid,NS,VENUES
PLAN=ROOT/'reports/experiment-storage/single-venue-fast-print-v1.json'
HORIZONS=(100,400,1000,5000,10000,30000)
TOLERANCE=250_000_000

def point(books,now):
    out=dict(t=now,sources={v:books[v]['source_ns'] for v in VENUES},
             receipts={v:books[v]['received_ns'] for v in VENUES},
             mids={v:mid(books[v]) for v in VENUES},depth={},spreads={})
    for v in VENUES:
        b=books[v];ask,bid=float(b['asks'][0][0]),float(b['bids'][0][0])
        out['depth'][v]={'buy':sum(float(q) for p,q in b['asks'] if float(p)<=ask*1.0005),
                         'sell':sum(float(q) for p,q in b['bids'] if float(p)>=bid*.9995)}
        out['spreads'][v]=(ask-bid)/out['mids'][v]*10000
    return out

class Probe:
    def __init__(self):
        self.books={};self.history=deque();self.rows=[];self.counts=Counter();self.generation=0

    def process(self,event):
        now=event['received_ns'];kind=event['type']
        while self.history and self.history[0]['t']<now-3*NS:self.history.popleft()
        if kind=='invalidate':
            self.generation+=1;self.books.pop(event['venue'],None);self.history.clear()
        elif kind=='book':self.books[event['venue']]=event
        current=point(self.books,now) if pair_fresh(self.books,now) else None
        if kind=='trade':
            v=event['venue'];self.counts[v+':ordinary_prints']+=1
            if not 0<=now-event['source_ns']<=2*NS:self.counts[v+':invalid_trade_clock']+=1
            else:
                pre=next((p for p in reversed(self.history) if p['t']<=now
                    and all(0<event['source_ns']-p['sources'][k]<=TOLERANCE for k in VENUES)),None)
                if pre is None:self.counts[v+':missing_strict_pre_pair']+=1
                else:
                    self.counts[v+':strict_pre_pair']+=1
                    side='buy' if event['buy_aggressor'] else 'sell'
                    depth=pre['depth'][v][side];ratio=float(event['qty'])/depth if depth else None
                    if ratio is not None and ratio>=.25:
                        self.counts[v+':depth_consuming_print']+=1
                        assert len(self.rows)<2000,'bounded diagnostic row cap'
                        self.rows.append(dict(venue=v,t=now,source_ns=event['source_ns'],
                            price=event['price'],quantity=event['qty'],side=side,
                            direction=-1 if side=='buy' else 1,depth_fraction=ratio,pre=pre,
                            generation=self.generation,decision=None,decision_status='pending',horizons={}))
        for r in self.rows:
            if r['decision_status']=='pending':
                if self.generation!=r['generation']:r['decision_status']='invalidation_crossing'
                elif now>r['t']+TOLERANCE:r['decision_status']='missing_post_pair_in_250ms'
                elif current and all(current['sources'][v]>=r['source_ns'] for v in VENUES):
                    r['decision']=current;r['decision_status']='matched'
                    r['decision_delay_ms']=(now-r['t'])/1e6
                    r['local_impact_bps']=-r['direction']*10000*math.log(current['mids'][r['venue']]/r['pre']['mids'][r['venue']])
                    other=next(v for v in VENUES if v!=r['venue'])
                    r['reference_move_bps']=10000*math.log(current['mids'][other]/r['pre']['mids'][other])
                    r['local_move_and_stable_reference']=r['local_impact_bps']>=2 and abs(r['reference_move_bps'])<=1
            if r['decision_status']!='matched':continue
            base=r['decision']
            for ms in HORIZONS:
                label=str(ms);due=base['t']+ms*1_000_000
                if label in r['horizons'] or now<due:continue
                if self.generation!=r['generation']:r['horizons'][label]={'status':'invalidation_crossing'}
                elif now>due+TOLERANCE:r['horizons'][label]={'status':'missing_source_and_receipt_pair_in_250ms'}
                elif current and all(current['sources'][v]>=due and current['receipts'][v]>=due for v in VENUES):
                    returns={v:r['direction']*10000*math.log(current['mids'][v]/base['mids'][v]) for v in VENUES}
                    other=next(v for v in VENUES if v!=r['venue'])
                    r['horizons'][label]=dict(status='matched',t=now,
                        target_fade_bps=returns[r['venue']],relative_fade_bps=returns[r['venue']]-returns[other],
                        sources=current['sources'],receipts=current['receipts'],mids=current['mids'])
        if kind=='book' and current:self.history.append(current)
        if kind=='end':
            for r in self.rows:
                if r['decision_status']=='pending':r['decision_status']='capture_ended'
                for ms in HORIZONS:r['horizons'].setdefault(str(ms),{'status':'no_decision' if r['decision_status']!='matched' else 'capture_ended'})

    def summary(self):
        result={}
        for v in VENUES:
            rows=[r for r in self.rows if r['venue']==v]
            d=dict(counts={k.split(':',1)[1]:n for k,n in self.counts.items() if k.startswith(v+':')},
                   decision_status=dict(Counter(r['decision_status'] for r in rows)),
                   local_move_and_stable_reference=sum(r.get('local_move_and_stable_reference',False) for r in rows),horizons={})
            for ms in HORIZONS:
                selected=[r['horizons'][str(ms)] for r in rows if r['horizons'][str(ms)]['status']=='matched']
                d['horizons'][str(ms)]=dict(n=len(selected),missing=len(rows)-len(selected),
                    favorable=sum(x['target_fade_bps']>0 for x in selected),
                    mean_target_fade_bps=mean(x['target_fade_bps'] for x in selected) if selected else None,
                    mean_relative_fade_bps=mean(x['relative_fade_bps'] for x in selected) if selected else None)
            d['after_400ms']={}
            for ms in (1000,5000,10000,30000):
                values=[r['horizons'][str(ms)]['target_fade_bps']-r['horizons']['400']['target_fade_bps']
                        for r in rows if r['horizons']['400']['status']=='matched' and r['horizons'][str(ms)]['status']=='matched']
                d['after_400ms'][str(ms)]=dict(n=len(values),mean_remaining_fade_bps=mean(values) if values else None)
            result[v]=d
        return result

def run(digest):
    verify();p=json.loads(PLAN.read_bytes())
    assert digest==p['manifest_sha256']
    for pin in p['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    probes={a:Probe() for a in ASSETS};ended=None
    for event in iter_events(capture.OUT,expected_manifest_sha256=digest,max_raw_bytes=capture.HARD_BYTES):
        if event['type']=='end':
            for probe in probes.values():probe.process(event)
            ended=event
        elif event.get('asset') in probes:probes[event['asset']].process(event)
    assert ended
    out=dict(schema='single-venue-fast-print-v1',retrospective=True,manifest_sha256=digest,
        plan_sha256=sha(PLAN),summary={a:p.summary() for a,p in probes.items()},rows={a:p.rows for a,p in probes.items()},
        limitations='Individual prints may be fragments or overlap. Selection uses strict prior-source clocks and25%displayed-depth ratio only, no future outcomes. No volume baseline. Decision requires post-print source coverage within250ms of print receipt; horizons require both source and receipt at or after due, within250ms. Actual timestamps retained. Midpoints only, no fees/spread/latency-adjusted execution profits. Missing clocks are not evidence of absent economic events. Local impact cannot establish causality; visible liquidity may replenish or cancel.')
    data=gzip.compress((json.dumps(out,separators=(',',':'),allow_nan=False)+'\n').encode(),mtime=0)
    assert len(data)<=196608
    path=ROOT/'reports/single-venue-research/fast-print-diagnostic.json.gz'
    assert not path.exists();path.write_bytes(data)
    print(json.dumps(out['summary'],indent=2))

if __name__=='__main__':run(*sys.argv[1:])
