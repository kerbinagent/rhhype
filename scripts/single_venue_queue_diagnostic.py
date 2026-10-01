"""Offline queue imbalance versus delayed executable quote changes, not fills."""
import datetime,gzip,json,hashlib,sys
from pathlib import Path
from collections import defaultdict,Counter
from decimal import Decimal as D
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_broad as broad
from scripts.single_venue_strategy import rounded,walk_ioc,dec,fresh
from scripts.single_venue_broad_quotes import distribution
PLAN=ROOT/'reports/experiment-storage/single-venue-queue-diagnostic-v1.json'
NS=1_000_000_000
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def imbalance(book):
    bid,ask=dec(book['bids'][0][1]),dec(book['asks'][0][1])
    return (bid-ask)/(bid+ask)
def sweep(book,side,qty):
    q,value=walk_ioc(book,side,qty,D('Infinity') if side==1 else D(0))[:2]
    return value if q==qty and qty>0 else None
def diagnose(stream,metadata,start,assets):
    last={};pending=defaultdict(list);counts=defaultdict(Counter);values=defaultdict(list);end=None
    for e in stream:
        a,v,t=e.get('asset'),e.get('venue'),e['received_ns'];key=(a,v)
        if e['type']=='end':end=e;continue
        if e['type']=='invalidate':
            for old in pending.pop(key,[]):counts[old['group']]['invalidated']+=1
        if e['type']!='book':continue
        keep=[]
        for old in pending[key]:
            if t<old['due'] or e['source_ns']<old['due']:keep.append(old);continue
            group=old['group']
            if t>old['due']+2*NS or not fresh(e,t):counts[group]['missing_first_eligible']+=1;continue
            if e['generation']!=old['generation']:counts[group]['generation_changed']+=1;continue
            side=old['side'] if old['stage']=='entry' else -old['side']
            value=sweep(e,side,old['qty'])
            if value is None:counts[group]['insufficient_depth']+=1;continue
            if old['stage']=='entry' and value>D(100):counts[group]['entry_quote_above_cap']+=1;continue
            mid=(dec(e['bids'][0][0])+dec(e['asks'][0][0]))/2
            if old['stage']=='entry':
                old.update(stage='exit',entry=value,mid=mid,due=t+10*NS+400_000_000)
                counts[group]['delayed_entry_quote']+=1;keep.append(old)
            else:
                quote=D(old['side'])*(value-old['entry'])/old['entry']*10000
                move=D(old['side'])*(mid-old['mid'])/old['mid']*10000
                values[group].append((move,quote));counts[group]['matched']+=1
                counts[group]['quote_positive']+=int(quote>0)
                counts[group]['quote_above_5bp']+=int(quote>5)
        pending[key]=keep
        sec=(t-start)//NS
        if not 3<=sec<570 or last.get(key)==sec:continue
        last[key]=sec
        if not fresh(e,t):continue
        i=imbalance(e);bucket='low' if abs(i)<D('.2') else 'medium' if abs(i)<D('.6') else 'high'
        group=(a,v,bucket);counts[group]['sampled']+=1
        if i==0:counts[group]['zero_imbalance']+=1;continue
        m=metadata[v][a];qty=rounded(D(100)/(dec(e['asks'][0][0])*D('1.01')),m['qty_step'])
        if qty<dec(m['min_qty']) or qty*dec(e['bids'][0][0])<dec(m['min_notional']):counts[group]['native_minimum_reject']+=1;continue
        counts[group]['admitted']+=1
        pending[key].append(dict(group=group,side=1 if i>0 else -1,qty=qty,generation=e['generation'],stage='entry',due=t+400_000_000))
    assert end
    for items in pending.values():
        for old in items:counts[old['group']]['unresolved_at_end']+=1
    rows=[]
    for a in assets:
        for v in broad.SELECTED:
            for bucket in ('low','medium','high'):
                group=(a,v,bucket);c=counts[group];s=values[group]
                assert c['sampled']==c['admitted']+c['zero_imbalance']+c['native_minimum_reject']
                assert c['admitted']==sum(c[x] for x in ('matched','invalidated','missing_first_eligible','generation_changed','insufficient_depth','entry_quote_above_cap','unresolved_at_end'))
                rows.append(dict(asset=a,venue=v,bucket=bucket,counts=dict(c),
                    signed_delayed_midpoint_bps=distribution([x[0] for x in s]),
                    signed_delayed_quote_bps=distribution([x[1] for x in s])))
    return rows
def main():
    broad.verify();plan=json.loads(PLAN.read_bytes());source=ROOT/plan['capture']
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    assert sha(source/'manifest.json')==plan['manifest_sha256']
    assert sha(source/'frames.jsonl.gz')==plan['raw_sha256']
    manifest=json.loads((source/'manifest.json').read_bytes());start=broad.events._epoch_ns(manifest['started_utc'])
    metadata=json.loads((source/'metadata/normalized.json').read_bytes())['markets']
    rows=diagnose(broad.broad_events(source,expected_manifest_sha256=plan['manifest_sha256'],max_raw_bytes=broad.HARD_BYTES),metadata,start,broad.ASSETS)
    report=dict(plan_sha256=sha(PLAN),source_sha256=sha(Path(__file__)),scope=plan['scope'],rows=rows)
    blob=gzip.compress((json.dumps(report,indent=2)+'\n').encode(),mtime=0);assert len(blob)<=24576
    out=ROOT/'reports/single-venue-research/broad-queue-diagnostic.json.gz';assert not out.exists();out.write_bytes(blob)
    print(json.dumps(rows,indent=2))
if __name__=='__main__':main()
