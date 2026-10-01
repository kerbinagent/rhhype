"""Independent quote filter reconstruction plus the unchanged cash audit fork."""
import math
from decimal import Decimal as D, ROUND_FLOOR, ROUND_HALF_EVEN
from scripts.audit_single_venue_depth import SignalAudit,tracked
from scripts import audit_single_venue_executable_cash as cash

class ExecutableAudit(SignalAudit):
    def __init__(self,metadata):
        super().__init__();self.metadata=metadata

    def verify(self,s,books,refs,points,flows,now):
        original=dict(s,rule='depth_fade');original.pop('execution_filter')
        super().verify(original,books,refs,points,flows,now)
        v=s['venue'];other='rh_lighter' if v=='lighter' else 'lighter';side=s['direction']
        raw,pre,_,_,_,_=self.accepted[v,s['print']['trade_id']]
        m=self.metadata[v]['LIT'];tick=D(m['price_tick']);step=D(m['qty_step'])
        midpoint=D(str(pre['mids'][v]));width=midpoint*D(str(pre['spreads'][v]))/10000
        px=midpoint+width*D(side)/2
        old=(px/tick).quantize(D(1),rounding=ROUND_HALF_EVEN)*tick
        assert abs(px-old)<D('1e-8')
        current=D(str(books[v]['asks' if side==1 else 'bids'][0][0]))
        impact=-side*10000*math.log(float(current/old))
        qty=(D(100)/(D(str(books[v]['asks'][0][0]))*D('1.01'))/step).to_integral_value(rounding=ROUND_FLOOR)*step
        def sum_depth(levels):
            left=qty;value=D(0)
            for price,size in levels:
                amount=min(left,D(str(size)));left-=amount;value+=amount*D(str(price))
                if left==0:break
            return qty-left,value
        q,value=sum_depth(books[v]['asks' if side==1 else 'bids'])
        oq,reference=sum_depth(books[other]['bids' if side==1 else 'asks'])
        full=bool(qty>0 and q==qty and oq==qty and value>0)
        edge=D(side)*(reference/value-1)*10000 if full else None
        f=s['execution_filter']
        for key,expected in dict(pre_entry_side_quote=old,decision_entry_side_quote=current,
            entry_side_impact_bps=impact,benchmark_quantity=qty,local_quantity=q,
            reference_quantity=oq,local_value=value,reference_value=reference).items():cash.near(expected,f[key])
        assert f['full_depth']==full
        if edge is None:assert f['reference_depth_edge_bps'] is None
        else:cash.near(edge,f['reference_depth_edge_bps'])
        assert s['rule'] in ('baseline_fade','side_fade','priced_fade')
        if s['rule']!='baseline_fade':assert impact>=2
        if s['rule']=='priced_fade':assert full and D(side)*(reference-value)*10000>=5*value

def run_audit(index,digest):
    from scripts import single_venue_executable_shock as driver
    from scripts import single_venue_compact_evidence as compact
    study=driver.study
    def inputs(*args):
        source,manifest,metadata,start,events=study.multi_inputs(*args)
        tracker=ExecutableAudit(metadata);cash.verify_signal=tracker.verify
        return source,manifest,metadata,start,tracked(events,tracker)
    cash.PLAN=driver.PLAN;cash.inputs=inputs;cash.match_book=compact.match_compact
    cash.audit(study.NAMES['LIT'],digest)
