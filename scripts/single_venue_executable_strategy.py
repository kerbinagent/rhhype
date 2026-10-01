"""Prospective quote-conditioned fades; every arm keeps its own cash ledger."""
import math
from collections import Counter
from decimal import Decimal as D
from scripts.single_venue_strategy import Portfolio, NS, VENUES, dec, rounded, walk_ioc
from scripts.single_venue_depth_strategy import Detector

RULES=('baseline_fade','side_fade','priced_fade')

class WideAdmissionPortfolio(Portfolio):
    # Only the admission interval differs from Portfolio.admit.
    def admit(self, signal, book, now):
        reason = None
        if self.unknown or self.pending or self.position:
            reason = 'occupied_or_unknown'
        elif not 3*NS <= now-self.start < 570*NS:
            reason = 'outside_window'
        elif now-self.last_flat < 30*NS:
            reason = 'cooldown'
        elif self.attempts >= 20:
            reason = 'attempt_cap'
        elif now//(3600*NS) != (now+120*NS)//(3600*NS):
            reason = 'funding_guard'
        if reason:
            self.counts[reason] += 1
            return
        qty = rounded(D(100)/(dec(book['asks'][0][0])*D('1.01')), self.market['qty_step'])
        if not self.minimum(qty, dec(book['bids'][0][0])):
            self.counts['entry_minimum'] += 1
            return
        if self.cash < D(100):
            self.counts['cash_shortfall'] += 1
            return
        self.log('signal', signal=signal)
        if self.submit('entry', signal['direction'], qty, book, now):
            self.attempts += 1

def quote_features(signal, books, market):
    v=signal['venue'];other=next(x for x in VENUES if x!=v)
    direction=signal['direction'];pre=signal['pre'];m=dec(pre['mids'][v]);spread=dec(pre['spreads'][v])
    # For a fade buy inspect the ask; for a fade short inspect the bid.
    raw_pre=m*(1+D(direction)*spread/20000)
    tick=dec(market['price_tick']);prior=(raw_pre/tick).to_integral_value()*tick
    assert abs(prior-raw_pre)<D('1e-8')
    book=books[v];quote=dec(book['asks' if direction==1 else 'bids'][0][0])
    impact=-direction*10000*math.log(float(quote/prior))
    qty=rounded(D(100)/(dec(book['asks'][0][0])*D('1.01')),market['qty_step'])
    q,value,_=walk_ioc(book,direction,qty,D('Infinity') if direction==1 else D(0))
    oq,reference,_=walk_ioc(books[other],-direction,qty,D('Infinity') if direction==-1 else D(0))
    full=bool(qty>0 and q==qty and oq==qty and value>0)
    edge=D(direction)*(reference-value)/value*10000 if full else None
    return dict(pre_entry_side_quote=str(prior),decision_entry_side_quote=str(quote),
        entry_side_impact_bps=impact,benchmark_quantity=str(qty),local_quantity=str(q),
        reference_quantity=str(oq),local_value=str(value),reference_value=str(reference),
        full_depth=full,reference_depth_edge_bps=str(edge) if edge is not None else None)

class ExecutableStudy:
    def __init__(self,metadata,start,emit):
        self.metadata=metadata;self.detector=Detector();self.counts=Counter()
        self.arms={(r,v):WideAdmissionPortfolio(r,v,metadata[v]['LIT'],start,emit) for r in RULES for v in VENUES}

    def process(self,event):
        for arm in self.arms.values():arm.process(event)
        for signal in self.detector.process(event):
            if signal['rule']!='depth_fade':continue
            v=signal['venue'];f=quote_features(signal,self.detector.books,self.metadata[v]['LIT'])
            side=f['entry_side_impact_bps']>=2
            priced=side and f['full_depth'] and D(f['reference_depth_edge_bps'])>=5
            self.counts['all_shocks:'+v]+=1
            self.counts['side_pass:'+v]+=int(side);self.counts['priced_pass:'+v]+=int(priced)
            for rule,passes in zip(RULES,(True,side,priced)):
                if passes:
                    s=dict(signal,rule=rule,execution_filter=f)
                    self.arms[rule,v].admit(s,self.detector.books[v],signal['t'])

    def summary(self):
        return dict(feature_counts={**self.detector.counts,**self.counts},arms={a.label:a.summary() for a in self.arms.values()})
