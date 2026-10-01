"""Conservative request-count bound; does not send requests or alter execution rules."""
import collections,gzip,hashlib,json,sys
from pathlib import Path

def run(result_dir):
 r=Path(result_dir)
 summary=json.loads(gzip.decompress((r/'summary.json.gz').read_bytes()))
 assert not summary['error'] and summary['completion_marker_received']
 packed=(r/'audit.jsonl.gz').read_bytes()
 assert hashlib.sha256(packed).hexdigest()==summary['audit_sha256']
 rows=[json.loads(x) for x in gzip.decompress(packed).splitlines()]
 assert len(rows)==summary['audit_records']
 weights={'quote_requested':1,'cancel_requested':1,'hedge_scheduled':1,'exit_requested':2,'exit_result':1,'hedge_result':1}
 streams=collections.defaultdict(list)
 for row in rows:
  if row['event'] in weights:streams[row['branch']].append((row['ns'],weights[row['event']]))
 peaks={}
 for asset in summary['branches']:
  stream=streams[asset];assert stream==sorted(stream)
  left=total=peak=0
  for right,(now,weight) in enumerate(stream):
   total+=weight
   while stream[left][0]<now-66*10**9:total-=stream[left][1];left+=1
   peak=max(peak,total)
  peaks[asset]=peak
 out={'audit':'passed' if all(v<=40 for v in peaks.values()) else 'requires_precise_intent_count','conservative_request_upper_bound_per_66_seconds':peaks,'published_standard_per_60_seconds':60,'published_default_transaction_type_per_60_seconds':40,'source':'https://apidocs.lighter.xyz/docs/rate-limits','summary_sha256':hashlib.sha256((r/'summary.json.gz').read_bytes()).hexdigest(),'method':'Quote/cancel/hedge requests counted once, exit requests twice, exit and hedge results each counted once more for retries or late covering.66seconds allows up to3seconds displacement at both ends. Bound applies separately to each independent portfolio; no actual order requests sent.'}
 with (r/'request-rate-audit.json').open('x') as f:json.dump(out,f,indent=2);f.write('\n')
 print(json.dumps(out,indent=2))
if __name__=='__main__':run(sys.argv[1])
