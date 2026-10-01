"""New prospective depth-shock direction comparison; unchanged IOC ledgers."""
from collections import Counter,deque
import math
from scripts.single_venue_strategy import Portfolio,pair_fresh,VENUES,NS
from scripts.single_venue_fast_print import point
RULES=('depth_fade','depth_follow')
PRINT_FIELDS=('trade_id','asset','venue','market','received_ns','source_ns','price','qty','buy_aggressor')

class Detector:
    def __init__(self):
        self.books={};self.history=deque();self.pending=[];self.counts=Counter()

    def process(self,e):
        now=e['received_ns'];kind=e['type'];signals=[]
        while self.history and self.history[0]['t']<now-3*NS:self.history.popleft()
        if kind=='invalidate':
            self.books.pop(e['venue'],None);self.history.clear()
            self.counts['pending_invalidated']+=len(self.pending);self.pending=[]
        elif kind=='book':self.books[e['venue']]=e
        if kind=='trade':
            v=e['venue'];self.counts['ordinary_prints:'+v]+=1
            if 0<=now-e['source_ns']<=2*NS:
                pre=next((p for p in reversed(self.history) if p['t']<=now and
                    all(0<e['source_ns']-s<=250_000_000 for s in p['sources'].values())),None)
                if pre:
                    self.counts['strict_pre:'+v]+=1;side='buy' if e['buy_aggressor'] else 'sell'
                    depth=pre['depth'][v][side]
                    if depth and float(e['qty'])>=.25*depth:
                        self.counts['depth_candidate:'+v]+=1
                        self.pending.append(dict(print={k:e[k] for k in PRINT_FIELDS},pre=pre,
                            depth_fraction=float(e['qty'])/depth))
        current=point(self.books,now) if kind=='book' and pair_fresh(self.books,now) else None
        remaining=[]
        for p in self.pending:
            trade=p['print'];v=trade['venue'];sign=1 if trade['buy_aggressor'] else -1
            if now>trade['received_ns']+250_000_000:self.counts['missing_post:'+v]+=1;continue
            if current and now>trade['received_ns'] and all(s>=trade['source_ns'] for s in current['sources'].values()):
                self.counts['post_pair:'+v]+=1
                impact=sign*10000*math.log(current['mids'][v]/p['pre']['mids'][v])
                other=next(x for x in VENUES if x!=v)
                ref_move=10000*math.log(current['mids'][other]/p['pre']['mids'][other])
                if impact>=2 and abs(ref_move)<=1:
                    self.counts['local_shock:'+v]+=1
                    for rule,direction in (('depth_fade',-sign),('depth_follow',sign)):
                        signals.append(dict(t=now,venue=v,rule=rule,direction=direction,**p,
                            decision=current,local_impact_bps=impact,reference_move_bps=ref_move))
                else:self.counts['impact_or_reference_rejection:'+v]+=1
            else:remaining.append(p)
        self.pending=remaining
        if current:self.history.append(current)
        if kind=='end':self.counts['unanchored_at_end']+=len(self.pending);self.pending=[]
        return signals

class DepthStudy:
    def __init__(self,metadata,start,emit):
        self.detector=Detector()
        self.arms={(r,v):Portfolio(r,v,metadata[v]['LIT'],start,emit) for r in RULES for v in VENUES}

    def process(self,event):
        for arm in self.arms.values():arm.process(event)
        for signal in self.detector.process(event):
            self.arms[signal['rule'],signal['venue']].admit(signal,self.detector.books[signal['venue']],signal['t'])

    def summary(self):
        return dict(feature_counts=dict(self.detector.counts),arms={a.label:a.summary() for a in self.arms.values()})
