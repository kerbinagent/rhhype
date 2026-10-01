"""Reuse independently checked audit logic on the frozen replication paths."""
import hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import scripts.core_maker_lit_capture as capture
capture.OUT=ROOT/'reports/core-maker-lit-replication/capture'
capture.PLAN=ROOT/'reports/experiment-storage/core-maker-lit-replication-v1.json'
from scripts.core_maker_lit_replication import configure
configure()
if sys.argv[1:]==['fills']:
 p=ROOT/'scripts/audit_core_maker_lit_ioc_coordinator.py'
 assert hashlib.sha256(p.read_bytes()).hexdigest()=='53edb4a1134289d33011b03b2109b42d31ea89c900ead866db0cbc836caa821c'
 source=p.read_text()
 old="   scoped=[f for f in ff if episode['decided_ns']<=f['ns']<=episode['flat_ns']]"
 new="""   starts=[i for i,r in enumerate(rows) if r['event']=='quote_requested']
   start=starts[episode['number']-1]
   stop=next(i for i in range(start+1,len(rows)) if rows[i]['event']=='episode_flat')
   assert rows[start]['ns']==episode['decided_ns'] and rows[stop]['ns']==episode['flat_ns']
   assert not any(r['event']=='quote_requested' for r in rows[start+1:stop])
   scoped=[r for r in rows[start+1:stop] if r['event']=='fill']"""
 assert source.count(old)==1;source=source.replace(old,new)
elif sys.argv[1:]==['quotes']:
 p=ROOT/'scripts/audit_lit_ioc_quote_gates.py';source=p.read_text()
else:raise SystemExit('Use fills or quotes')
assert source.count("R=ROOT/'reports/core-maker-lit-ioc-coordinator'")==1
source=source.replace("R=ROOT/'reports/core-maker-lit-ioc-coordinator'","R=ROOT/'reports/core-maker-lit-replication/result'")
exec(compile(source,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
