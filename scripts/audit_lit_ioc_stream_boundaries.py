"""Run pinned independent auditor with ordered episode boundaries at equal timestamps."""
import hashlib
from pathlib import Path
p=Path(__file__).with_name('audit_core_maker_lit_ioc_coordinator.py')
source=p.read_text()
assert hashlib.sha256(p.read_bytes()).hexdigest()=='53edb4a1134289d33011b03b2109b42d31ea89c900ead866db0cbc836caa821c'
old="   scoped=[f for f in ff if episode['decided_ns']<=f['ns']<=episode['flat_ns']]"
new="""   starts=[i for i,r in enumerate(rows) if r['event']=='quote_requested']
   start=starts[episode['number']-1]
   stop=next(i for i in range(start+1,len(rows)) if rows[i]['event']=='episode_flat')
   assert rows[start]['ns']==episode['decided_ns'] and rows[stop]['ns']==episode['flat_ns']
   assert not any(r['event']=='quote_requested' for r in rows[start+1:stop])
   scoped=[r for r in rows[start+1:stop] if r['event']=='fill']"""
assert source.count(old)==1
exec(compile(source.replace(old,new),str(p),'exec'),{'__name__':'__main__','__file__':str(p)})
