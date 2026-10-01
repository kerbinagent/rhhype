"""Retrospective paired midpoint context for all depth-study closed episodes."""
import datetime,gzip,hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_depth_events as adapter
from scripts.single_venue_strategy import pair_fresh,mid
PLAN=ROOT/'reports/experiment-storage/single-venue-depth-context-v1.json'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    plan=json.loads(PLAN.read_bytes())
    for row in plan['pins']:assert sha(ROOT/row['path'])==row['sha256'],row['path']
    results=[]
    for sample in plan['samples']:
        wanted={};books={};snapshots={};episodes=[]
        for source in sample['summaries']:
            summary=json.loads(gzip.decompress((ROOT/source).read_bytes()))
            asset=summary['asset'];books[asset]={}
            for arm,result in summary['arms'].items():
                for ep in result['episodes']:
                    episodes.append((asset,arm,ep))
                    for key in ('entry_ns','exit_ns'):wanted[(asset,ep[key])]=True
        adapter.HARD_BYTES=sample['hard_bytes']
        for event in adapter.iter_events(ROOT/sample['capture'],
                expected_manifest_sha256=sample['manifest_sha256'],max_raw_bytes=sample['hard_bytes']):
            asset=event.get('asset')
            if asset not in books:continue
            if event['type']=='invalidate':books[asset].pop(event['venue'],None)
            if event['type']!='book':continue
            books[asset][event['venue']]=event
            key=(asset,event['received_ns'])
            if key not in wanted:continue
            snapshots[key]=dict(pair_fresh=pair_fresh(books[asset],event['received_ns']),
                mids={v:mid(b) for v,b in books[asset].items()},
                sources={v:b['source_ns'] for v,b in books[asset].items()},
                receipts={v:b['received_ns'] for v,b in books[asset].items()})
        rows=[]
        for asset,arm,ep in episodes:
            venue=arm.split(':')[1];other='rh_lighter' if venue=='lighter' else 'lighter'
            en=snapshots.get((asset,ep['entry_ns']));ex=snapshots.get((asset,ep['exit_ns']))
            row=dict(asset=asset,arm=arm,side=ep['side'],entry_ns=ep['entry_ns'],exit_ns=ep['exit_ns'],
                entry_pair=en,exit_pair=ex,net=ep['cash_after_capital'],stress_net=ep['stressed_net'])
            if en and ex and en['pair_fresh'] and ex['pair_fresh']:
                target=ep['side']*10000*math.log(ex['mids'][venue]/en['mids'][venue])
                reference=ep['side']*10000*math.log(ex['mids'][other]/en['mids'][other])
                row.update(status='matched',signed_target_mid_return_bps=target,
                    signed_reference_mid_return_bps=reference,signed_relative_mid_return_bps=target-reference)
            else:row['status']='missing_fresh_execution_pair'
            rows.append(row)
        assert len(rows)==sum(len(json.loads(gzip.decompress((ROOT/f).read_bytes()))['arms'][a]['episodes'])
            for f in sample['summaries'] for a in json.loads(gzip.decompress((ROOT/f).read_bytes()))['arms'])
        results.append(dict(sample=sample['name'],complete_capture=sample['complete_capture'],rows=rows))
    result=dict(recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        plan_sha256=sha(PLAN),scope=plan['scope'],samples=results)
    blob=gzip.compress((json.dumps(result,separators=(',',':'),allow_nan=False)+'\n').encode(),mtime=0)
    assert len(blob)<=8192
    out=ROOT/'reports/single-venue-research/depth-combined-execution-context.json.gz'
    assert not out.exists();out.write_bytes(blob)
    for sample in results:
        for row in sample['rows']:
            print(json.dumps(dict(sample=sample['sample'],**{k:v for k,v in row.items()
                if k not in ('entry_pair','exit_pair')})))

if __name__=='__main__':main()
