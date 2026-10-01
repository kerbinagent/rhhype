"""Descriptive check of every detected shock, including unadmitted ones."""
import datetime, json, sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import single_venue_depth_batch as batch
from scripts.single_venue_depth_strategy import Detector
from scripts.single_venue_depth_events import iter_events

def main():
    terminal=json.loads((batch.OUT/'terminal.json').read_bytes())
    assert terminal['all_windows_normal']
    rows=[]
    for index in batch.WINDOWS:
        batch.verify(index)
        source=batch.OUT/f'window-{index}'/'capture'
        digest=batch.study.sha(source/'manifest.json')
        manifest=json.loads((source/'manifest.json').read_bytes())
        start=int(datetime.datetime.fromisoformat(manifest['started_utc']).timestamp()*10**9)
        detector=Detector();counts=Counter();shocks=[];end=None
        for event in iter_events(source,expected_manifest_sha256=digest,max_raw_bytes=batch.HARD_BYTES):
            for s in detector.process(event):
                if s['rule']!='depth_fade':continue
                offset=(s['t']-start)/1e9
                bucket='before_122s' if offset<122 else 'at_or_after_480s' if offset>=480 else 'admission_period'
                counts[s['venue']+':'+bucket]+=1
                shocks.append(dict(venue=s['venue'],offset_seconds=offset,period=bucket,trade_id=s['print']['trade_id']))
            if event['type']=='end':end=event
        assert end
        rows.append(dict(window=index,manifest_sha256=digest,counts=dict(counts),shocks=shocks))
    result=dict(schema='single-venue-batch-timing-v1',retrospective=True,source_sha256=batch.study.sha(Path(__file__)),
        scope='All detector shocks, one row per fade/follow pair, classified by frozen admission times. No outcome selection or execution change.',windows=rows)
    data=(json.dumps(result,indent=2)+'\n').encode();assert len(data)<=32768
    target=ROOT/'reports/single-venue-research/depth-batch-timing.json';assert not target.exists();target.write_bytes(data)
    print(json.dumps([dict(window=r['window'],counts=r['counts']) for r in rows],indent=2))

if __name__=='__main__':main()
