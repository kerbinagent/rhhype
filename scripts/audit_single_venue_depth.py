"""Independent depth-signal reconstruction plus the frozen IOC/cash auditor."""
import math
from collections import deque
from scripts import audit_single_venue_study as base

class SignalAudit:
    def __init__(self):
        self.books={};self.past=deque();self.waiting=[];self.accepted={}

    def observe(self,e):
        self.accepted={};t=e['received_ns'];kind=e['type']
        while self.past and self.past[0]['t']<t-3*10**9:self.past.popleft()
        if kind=='invalidate':
            self.books.pop(e['venue'],None);self.past.clear();self.waiting=[]
        if kind=='book':self.books[e['venue']]=e
        if kind=='trade' and 0<=t-e['source_ns']<=2*10**9:
            previous=None
            for p in reversed(self.past):
                if p['t']<=t and all(0<e['source_ns']-p['sources'][v]<=250_000_000 for v in base.VS):
                    previous=p;break
            if previous:
                side='buy' if e['buy_aggressor'] else 'sell';depth=previous['depth'][e['venue']][side]
                if depth>0 and float(e['qty'])/depth>=.25:self.waiting.append((e,previous,depth))
        q=None
        if kind=='book' and base.pair(self.books,t):
            q=dict(t=t,sources={v:self.books[v]['source_ns'] for v in base.VS},
                receipts={v:self.books[v]['received_ns'] for v in base.VS},
                mids={v:base.midpoint(self.books[v]) for v in base.VS},depth={},spreads={})
            for v in base.VS:
                b=self.books[v];ask,bid=float(b['asks'][0][0]),float(b['bids'][0][0])
                q['depth'][v]={'buy':sum(float(qty) for px,qty in b['asks'] if float(px)<=ask*1.0005),
                               'sell':sum(float(qty) for px,qty in b['bids'] if float(px)>=bid*.9995)}
                q['spreads'][v]=(ask-bid)/q['mids'][v]*10000
        keep=[]
        for trade,pre,depth in self.waiting:
            if t-trade['received_ns']>250_000_000:continue
            if q and t>trade['received_ns'] and all(q['sources'][v]>=trade['source_ns'] for v in base.VS):
                v=trade['venue'];other=next(x for x in base.VS if x!=v);sign=1 if trade['buy_aggressor'] else -1
                impact=sign*10000*math.log(q['mids'][v]/pre['mids'][v])
                ref=10000*math.log(q['mids'][other]/pre['mids'][other])
                if impact>=2 and abs(ref)<=1:self.accepted[(v,trade['trade_id'])]=(trade,pre,q,depth,impact,ref)
            else:keep.append((trade,pre,depth))
        self.waiting=keep
        if q:self.past.append(q)

    def verify(self,s,books,refs,points,flows,now):
        raw,pre,q,depth,impact,ref=self.accepted[(s['venue'],s['print']['trade_id'])]
        assert s['t']==now==q['t'] and base.pair(books,now)
        assert all(raw[k]==value for k,value in s['print'].items())
        assert s['pre']==pre and s['decision']==q
        base.near(s['depth_fraction'],float(raw['qty'])/depth)
        base.near(s['local_impact_bps'],impact);base.near(s['reference_move_bps'],ref)
        assert s['rule'] in ('depth_fade','depth_follow')
        sign=1 if raw['buy_aggressor'] else -1
        assert s['direction']==(-sign if s['rule']=='depth_fade' else sign)

def tracked(events,tracker):
    for e in events:tracker.observe(e);yield e

def run_audit(asset,digest):
    from scripts.single_venue_depth import PLAN,NAMES,multi_inputs
    tracker=SignalAudit()
    def inputs(*args):
        source,manifest,metadata,start,events=multi_inputs(*args)
        return source,manifest,metadata,start,tracked(events,tracker)
    base.PLAN=PLAN;base.inputs=inputs;base.verify_signal=tracker.verify
    base.audit(NAMES[asset],digest)
