"""All completed batch closes: exact midpoint reference accounting, not causality."""
import gzip,json,hashlib,sys
from pathlib import Path
from decimal import Decimal as D
from collections import defaultdict,Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth_events as adapter
from scripts import single_venue_depth_capture as capture
from scripts.single_venue_strategy import pair_fresh
PLAN=ROOT/'reports/experiment-storage/single-venue-batch-reference-v2.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def decode(p):return json.loads(gzip.decompress(p.read_bytes()))

def main():
    plan=json.loads(PLAN.read_bytes())
    for pin in plan['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    rows=[]
    for window in plan['windows']:
        source=ROOT/window['capture'];manifest=json.loads((source/'manifest.json').read_bytes())
        capture.SELECTED=manifest['selected_markets'];adapter.HARD_BYTES=window['hard_bytes']
        episodes=[];wanted=set();books={};snapshots={}
        for name in window['samples']:
            directory=ROOT/'reports/single-venue-research'/name
            summary=decode(directory/'summary.json.gz');audit=json.loads((directory/'independent-audit.json').read_bytes())
            assert audit['status']=='passed' and audit['summary_sha256']==sha(directory/'summary.json.gz')
            assert summary['manifest_sha256']==window['manifest_sha256'] and not summary['error']
            for arm,r in summary['arms'].items():
                for ep in r['episodes']:
                    venue=arm.split(':')[1]
                    episodes.append((name,arm,ep))
                    for kind in ('entry_ns','exit_ns'):wanted.add((venue,ep[kind]))
        ended=None
        for event in adapter.iter_events(source,expected_manifest_sha256=window['manifest_sha256'],max_raw_bytes=window['hard_bytes']):
            kind=event['type'];v=event.get('venue');t=event['received_ns']
            if kind=='invalidate':books.pop(v,None)
            if kind=='book':
                books[v]=event
                if (v,t) in wanted:
                    assert (v,t) not in snapshots
                    snapshots[v,t]=dict(pair_fresh=pair_fresh(books,t),
                        mids={x:str((D(str(b['bids'][0][0]))+D(str(b['asks'][0][0])))/2) for x,b in books.items()},
                        sources={x:b['source_ns'] for x,b in books.items()},receipts={x:b['received_ns'] for x,b in books.items()})
            if kind=='end':ended=event
        assert ended
        for name,arm,ep in episodes:
            v=arm.split(':')[1];other='rh_lighter' if v=='lighter' else 'lighter'
            en=snapshots.get((v,ep['entry_ns']));ex=snapshots.get((v,ep['exit_ns']))
            row=dict(window=window['index'],sample=name,arm=arm,side=ep['side'],entry_ns=ep['entry_ns'],exit_ns=ep['exit_ns'],
                entry_value=ep['entry_value'],entry_pair=en,exit_pair=ex,actual_gross=ep['gross'],
                net=ep['cash_after_capital'],stressed_net=ep['stressed_net'])
            if not en or not ex or not en['pair_fresh'] or not ex['pair_fresh']:row['status']='missing_fresh_execution_pair'
            elif ep['exit_attempts']!=1:row['status']='multiple_exit_callbacks'
            else:
                before,after=D(en['mids'][other]),D(ex['mids'][other])
                tick=D(ended['metadata']['markets'][other]['LIT']['price_tick'])/2
                assert before%tick==0 and after%tick==0
                reference=D(ep['side'])*D(ep['quantity'])*(after-before)
                residual=D(ep['gross'])-reference
                costs=D(ep['entry_fee'])+D(ep['exit_fee'])+D(ep['capital'])
                assert reference+residual-costs==D(ep['cash_after_capital'])
                assert reference+residual-costs-D(ep['stress'])==D(ep['stressed_net'])
                row.update(status='matched',reference_midpoint_gross=str(reference),fill_relative_residual=str(residual),fees_and_capital=str(costs))
            rows.append(row)
    assert len(rows)==52
    groups=defaultdict(list)
    for r in rows:groups[r['arm']].append(r)
    totals=[]
    for arm,members in sorted(groups.items()):
        matched=[r for r in members if r['status']=='matched']
        totals.append(dict(arm=arm,closed=len(members),status_counts=dict(Counter(r['status'] for r in members)),
            matched_actual_gross=str(sum((D(r['actual_gross']) for r in matched),D(0))),
            matched_reference_gross=str(sum((D(r['reference_midpoint_gross']) for r in matched),D(0))),
            matched_fill_residual=str(sum((D(r['fill_relative_residual']) for r in matched),D(0)))))
    result=dict(plan_sha256=sha(PLAN),scope=plan['scope'],rows=rows,totals=totals)
    blob=gzip.compress((json.dumps(result,separators=(',',':'))+'\n').encode(),mtime=0);assert len(blob)<=8192
    out=ROOT/'reports/single-venue-research/depth-batch-reference.json.gz';assert not out.exists();out.write_bytes(blob)
    print(json.dumps(totals,indent=2))

if __name__=='__main__':main()
