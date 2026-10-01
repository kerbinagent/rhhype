"""Fixed-clock directional benchmarks; unchanged Portfolio execution and cash."""
import json,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth_batch as batch
from scripts import single_venue_depth as study
from scripts import single_venue_compact_evidence as compact
from scripts import audit_single_venue_study as auditor
from scripts.single_venue_strategy import Portfolio,pair_fresh,VENUES,NS
PLAN=ROOT/'reports/experiment-storage/single-venue-clock-control-v1.json'
OFFSETS=(122,182,242,302,362,422)
WINDOWS=(2,3)

class ClockStudy:
    def __init__(self,metadata,start,emit):
        self.start=start;self.books={};self.next={v:0 for v in VENUES};self.counts=Counter()
        self.arms={(rule,v):Portfolio(rule,v,metadata[v]['LIT'],start,emit)
            for rule in ('clock_long','clock_short') for v in VENUES}

    def process(self,event):
        for arm in self.arms.values():arm.process(event)
        now=event['received_ns'];venue=event.get('venue')
        if event['type']=='invalidate':self.books.pop(venue,None)
        if event['type']=='book':self.books[venue]=event
        for v in VENUES:
            while self.next[v]<len(OFFSETS) and now>self.start+(OFFSETS[self.next[v]]+1)*NS:
                self.counts['missing_clock_pair:'+v]+=1;self.next[v]+=1
        if event['type']!='book' or self.next[venue]>=len(OFFSETS):return
        scheduled=self.start+OFFSETS[self.next[venue]]*NS
        if now<scheduled or not pair_fresh(self.books,now):return
        self.counts['clock_opportunity:'+venue]+=1;self.next[venue]+=1
        for rule,direction in (('clock_long',1),('clock_short',-1)):
            signal=dict(t=now,venue=venue,rule=rule,direction=direction,scheduled_ns=scheduled)
            self.arms[rule,venue].admit(signal,event,now)

    def summary(self):
        return dict(feature_counts=dict(self.counts),arms={p.label:p.summary() for p in self.arms.values()})

class ClockAudit:
    """Independently identify first eligible target callback for each fixed clock."""
    def __init__(self,start):
        self.books={};self.remaining={v:[start+x*10**9 for x in OFFSETS] for v in auditor.VS};self.accepted={}

    def observe(self,event):
        self.accepted={};now=event['received_ns'];v=event.get('venue');kind=event['type']
        if kind=='invalidate':self.books.pop(v,None)
        if kind=='book':self.books[v]=event
        for venue,queue in self.remaining.items():
            while queue and queue[0]+10**9<now:queue.pop(0)
        if kind=='book' and self.remaining[v] and self.remaining[v][0]<=now and auditor.pair(self.books,now):
            self.accepted[v]=(now,self.remaining[v].pop(0))

    def verify(self,signal,books,refs,points,flows,now):
        assert self.accepted[signal['venue']]==(now,signal['scheduled_ns'])
        assert signal['t']==now and auditor.pair(books,now)
        assert signal['rule'] in ('clock_long','clock_short')
        assert signal['direction']==(1 if signal['rule']=='clock_long' else -1)

def configure(index):
    assert index in WINDOWS
    batch.verify(index)
    study.PLAN=PLAN;study.NAMES={'LIT':f'single-venue-clock-control-{index}-lit'};study.Study=ClockStudy
    study.verify()

def audit(index,digest):
    compact.configure();auditor.PLAN=PLAN
    def inputs(*args):
        source,manifest,metadata,start,events=study.multi_inputs(*args)
        tracker=ClockAudit(start);auditor.verify_signal=tracker.verify
        def observed():
            for event in events:tracker.observe(event);yield event
        return source,manifest,metadata,start,observed()
    auditor.inputs=inputs
    auditor.audit(study.NAMES['LIT'],digest)

def main(action,index,digest):
    index=int(index);configure(index)
    terminal=json.loads((batch.OUT/'terminal.json').read_bytes())
    assert terminal['state']=='finished' and any(r['window']==index and r['normal_endpoint'] for r in terminal['results'])
    if action=='replay':study.replay(digest)
    elif action=='audit':audit(index,digest)
    else:raise ValueError(action)

if __name__=='__main__':main(*sys.argv[1:])
