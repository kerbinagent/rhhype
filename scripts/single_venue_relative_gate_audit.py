"""Independent reconstruction of the common necessary gate, including non-signals."""
import datetime,gzip,json,math,sys,hashlib
from pathlib import Path
from collections import defaultdict,deque,Counter
from statistics import median
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_broad_relative as broad
from scripts.audit_single_venue_study import pair,midpoint,VS,NS
PLAN=ROOT/'reports/experiment-storage/single-venue-relative-gate-audit-v1.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def scan(stream,start):
    books=defaultdict(dict);refs=defaultdict(lambda:deque(maxlen=125));last_ref={};last_eval={}
    counts=defaultdict(Counter);rows={};end=None
    for e in stream:
        a,v,t=e.get('asset'),e.get('venue'),e['received_ns']
        if e['type']=='end':end=e;continue
        if e['type']=='invalidate':
            books[a].pop(v,None);refs[a].clear();last_ref.pop(a,None);last_eval.pop(a,None)
        if e['type']!='book':continue
        books[a][v]=e
        if not pair(books[a],t):counts[a]['nonfresh']+=1;continue
        basis=10000*math.log(midpoint(books[a]['lighter'])/midpoint(books[a]['rh_lighter']))
        if a not in last_ref or t-last_ref[a]>=NS:refs[a].append((t,basis));last_ref[a]=t
        if a in last_eval and t-last_eval[a]<NS:continue
        last_eval[a]=t
        past=[(when,value) for when,value in refs[a] if t-122*NS<=when<=t-2*NS]
        if len(past)<60 or past[-1][0]-past[0][0]<89*NS:counts[a]['warmup']+=1;continue
        residual=abs(basis-median(x for _,x in past));counts[a]['evaluated']+=1
        for venue in VS:
            key=(a,venue);r=rows.setdefault(key,dict(asset=a,venue=venue,evaluated=0,admission_evaluated=0,
                common_gate_pass=0,admission_common_gate_pass=0,gap_rule_pass=0,admission_gap_rule_pass=0,
                max_abs_residual_bp=0.,max_cost_margin_bp=None))
            b=books[a][venue];spread=(float(b['asks'][0][0])-float(b['bids'][0][0]))/midpoint(b)*10000
            margin=residual-spread-4;passed=residual>=spread+4;gap=passed and residual>=5
            inside=122*NS<=t-start<480*NS
            r['evaluated']+=1;r['admission_evaluated']+=int(inside)
            r['common_gate_pass']+=int(passed);r['admission_common_gate_pass']+=int(passed and inside)
            r['gap_rule_pass']+=int(gap);r['admission_gap_rule_pass']+=int(gap and inside)
            r['max_abs_residual_bp']=max(r['max_abs_residual_bp'],residual)
            r['max_cost_margin_bp']=margin if r['max_cost_margin_bp'] is None else max(r['max_cost_margin_bp'],margin)
    assert end
    return [rows[k] for k in sorted(rows)],{a:dict(c) for a,c in counts.items()}
def main():
    broad.verify();p=json.loads(PLAN.read_bytes())
    for pin in p['pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    capture=ROOT/'reports/single-venue-broad-relative/capture'
    manifest=json.loads((capture/'manifest.json').read_bytes());start=broad.events._epoch_ns(manifest['started_utc'])
    rows,counts=scan(broad.broad_events(capture,expected_manifest_sha256=p['manifest_sha256'],max_raw_bytes=broad.HARD_BYTES),start)
    assert len(rows)==20
    for a in broad.ASSETS:
        summary=json.loads(gzip.decompress((ROOT/f'reports/single-venue-research/single-venue-broad-relative-{a.lower()}/summary.json.gz').read_bytes()))
        fc=summary['feature_counts'];c=counts[a]
        assert fc.get('reference_warmup',0)==c.get('warmup',0)
        assert fc.get('nonfresh_pair_callbacks',0)==c.get('nonfresh',0)
        for v in VS:assert fc.get('gap_fade:evaluated:'+v,0)==c.get('evaluated',0)
    report=dict(plan_sha256=sha(PLAN),rows=rows,counts=counts,
        all_common_gates_failed=all(r['common_gate_pass']==0 for r in rows),
        admission_common_gates_failed=all(r['admission_common_gate_pass']==0 for r in rows),scope=p['scope'])
    payload=(json.dumps(report,indent=2)+'\n').encode();assert len(payload)<=16384
    out=ROOT/'reports/single-venue-research/relative-gate-audit.json';assert not out.exists();out.write_bytes(payload)
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
