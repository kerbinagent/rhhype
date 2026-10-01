from pathlib import Path
import gzip,json,math
from scripts.single_venue_depth_events import iter_events
from scripts.single_venue_depth_capture import OUT,HARD_BYTES
from scripts.single_venue_strategy import pair_fresh,mid
root=Path('.');episodes=[];needed=set();snapshots={};books={a:{} for a in ('LIT','VVV','ZEC')}
for asset in books:
 s=json.loads(gzip.decompress((root/'reports/single-venue-research'/('single-venue-depth-'+asset.lower())/'summary.json.gz').read_bytes()))
 for arm,result in s['arms'].items():
  for ep in result['episodes']:
   episodes.append(dict(asset=asset,arm=arm,episode=ep))
   needed.update((asset,ep[k]) for k in ('entry_ns','exit_ns'))
for e in iter_events(OUT,expected_manifest_sha256='e7c0982131996cffc4dace5c3359a976055f27b165db0f43e706dc386be4c36e',max_raw_bytes=HARD_BYTES):
 a=e.get('asset')
 if a not in books:continue
 if e['type']=='invalidate':books[a].pop(e['venue'],None)
 elif e['type']=='book':
  books[a][e['venue']]=e;key=(a,e['received_ns'])
  if key in needed:
   snapshots[key]=dict(pair_fresh=pair_fresh(books[a],e['received_ns']),mids={v:mid(b) for v,b in books[a].items()},sources={v:b['source_ns'] for v,b in books[a].items()},receipts={v:b['received_ns'] for v,b in books[a].items()})
rows=[]
for x in episodes:
 a,arm,ep=x['asset'],x['arm'],x['episode'];v=arm.split(':')[1];other='rh_lighter' if v=='lighter' else 'lighter'
 en=snapshots[(a,ep['entry_ns'])];ex=snapshots[(a,ep['exit_ns'])]
 row=dict(asset=a,arm=arm,entry_ns=ep['entry_ns'],exit_ns=ep['exit_ns'],entry_pair=en,exit_pair=ex)
 if en['pair_fresh'] and ex['pair_fresh']:
  row['signed_target_mid_return_bps']=ep['side']*10000*math.log(ex['mids'][v]/en['mids'][v])
  row['signed_reference_mid_return_bps']=ep['side']*10000*math.log(ex['mids'][other]/en['mids'][other])
  row['signed_relative_mid_return_bps']=row['signed_target_mid_return_bps']-row['signed_reference_mid_return_bps']
 rows.append(row)
out=dict(scope='Posthoc context for ALL completed paper episodes, using latest other-venue quote at exact target execution callbacks. No future lookup, new signals or economic changes. Not an execution return or causal decomposition. Missing freshness retained.',manifest_sha256='e7c0982131996cffc4dace5c3359a976055f27b165db0f43e706dc386be4c36e',rows=rows)
data=gzip.compress((json.dumps(out,separators=(',',':'))+'\n').encode(),mtime=0);assert len(data)<=8192
p=root/'reports/single-venue-research/depth-episode-context.json.gz';assert not p.exists();p.write_bytes(data)
for r in rows:print(json.dumps({k:v for k,v in r.items() if k not in ('entry_pair','exit_pair')},separators=(',',':')))
