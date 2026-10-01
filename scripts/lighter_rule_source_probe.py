"""Bounded read-only primary-source retrieval, never imports downloaded code."""
import gzip,hashlib,json,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/lighter-minimum-rule-source';PLAN=ROOT/'reports/experiment-storage/lighter-minimum-rule-source-v1.json'
def fetch(label,url):
 assert label.replace('-','').replace('_','').isalnum()
 assert url.startswith(('https://api.github.com/repos/elliottech/','https://raw.githubusercontent.com/elliottech/'))
 plan=json.loads(PLAN.read_bytes());OUT.mkdir(exist_ok=True);old=list(OUT.glob('*.json.gz'));assert len(old)<12 and not (OUT/(label+'.json.gz')).exists()
 row={'url':url,'began':time.time(),'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest()}
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'rhhype-public-source-review'})
  with urllib.request.urlopen(req,timeout=20) as r:
   body=r.read(1048577);row.update(status=r.status,body=body[:1048576].decode(errors='replace'),truncated=len(body)>1048576)
 except Exception as exc:row['error']=type(exc).__name__+': '+str(exc)
 row['ended']=time.time();packed=gzip.compress(json.dumps(row).encode(),mtime=0)
 assert sum(p.stat().st_size for p in old)+len(packed)<=196608,'source_archive_cap'
 (OUT/(label+'.json.gz')).write_bytes(packed)
 print(json.dumps({k:v for k,v in row.items() if k!='body'}))
 if 'body' in row:
  if label=='commit':print('commit',json.loads(row['body'])['sha'])
  elif label=='tree':
   obj=json.loads(row['body']);print('truncated_tree',obj.get('truncated'))
   print('\n'.join(x['path'] for x in obj.get('tree',[]) if any(s in x['path'].lower() for s in ('order','position','matching'))))
  else:
   lines=row['body'].splitlines()
   for i,line in enumerate(lines):
    if any(x in line.lower() for x in ('min_quote','min_base','reduce_only','minimum','min_notional')):print(i+1,line[:250])
if __name__=='__main__':fetch(*sys.argv[1:])
