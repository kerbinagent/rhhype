"""Independently reconcile diagnostic quote/print references and return math."""
import gzip,json,math,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.single_venue_multi_events import iter_events
from scripts.single_venue_multi_capture import OUT,HARD_BYTES
from scripts.run_single_venue_study import sha
VENUES=('lighter','rh_lighter')

def close(a,b):assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),(a,b)

def run():
    path=ROOT/'reports/single-venue-research/fast-print-diagnostic.json.gz'
    report=json.loads(gzip.decompress(path.read_bytes()));refs=set();wanted=Counter();actual=Counter();books={}
    for asset,rows in report['rows'].items():
        for r in rows:
            wanted[(asset,r['venue'],r['t'],r['source_ns'],r['price'],r['quantity'],r['side'])]+=1
            for p in [r['pre'],r['decision']]+[h for h in r['horizons'].values() if h['status']=='matched']:
                if p is None:continue
                for v in VENUES:refs.add((asset,v,p['receipts'][v],p['sources'][v]))
    ended=False
    for e in iter_events(OUT,expected_manifest_sha256=report['manifest_sha256'],max_raw_bytes=HARD_BYTES):
        if e['type']=='end':ended=True
        if e['type']=='book':
            key=(e['asset'],e['venue'],e['received_ns'],e['source_ns'])
            if key in refs:
                if key in books:assert books[key]['bids']==e['bids'] and books[key]['asks']==e['asks']
                books[key]=e
        if e['type']=='trade':
            key=(e['asset'],e['venue'],e['received_ns'],e['source_ns'],e['price'],e['qty'],'buy' if e['buy_aggressor'] else 'sell')
            if key in wanted:actual[key]+=1
    assert ended and refs==set(books)
    assert all(actual[k]>=n for k,n in wanted.items())
    counts=Counter()
    def check_point(asset,p):
        assert max(p['sources'].values())-min(p['sources'].values())<=250_000_000
        assert max(p['receipts'].values())-min(p['receipts'].values())<=250_000_000
        for v in VENUES:
            b=books[(asset,v,p['receipts'][v],p['sources'][v])]
            assert 0<=p['t']-b['received_ns']<=2_000_000_000
            assert 0<=p['t']-b['source_ns']<=2_000_000_000
            assert b['source_ns']<=b['received_ns'] and b['valid'] and b['clock_valid']
            ask,bid=float(b['asks'][0][0]),float(b['bids'][0][0]);assert ask>bid
            midpoint=(ask+bid)/2;close(midpoint,p['mids'][v])
            if 'depth' in p:
                close(p['depth'][v]['buy'],sum(float(q) for px,q in b['asks'] if float(px)<=ask*1.0005))
                close(p['depth'][v]['sell'],sum(float(q) for px,q in b['bids'] if float(px)>=bid*.9995))
                close(p['spreads'][v],(ask-bid)/midpoint*10000)
            counts['raw_quote_references']+=1
    for asset,rows in report['rows'].items():
        for r in rows:
            pre=r['pre'];check_point(asset,pre)
            assert pre['t']<=r['t'] and 0<=r['t']-r['source_ns']<=2_000_000_000
            assert all(0<r['source_ns']-s<=250_000_000 for s in pre['sources'].values())
            close(r['depth_fraction'],r['quantity']/pre['depth'][r['venue']][r['side']]);assert r['depth_fraction']>=.25
            assert r['direction']==(-1 if r['side']=='buy' else 1)
            counts['candidate_prints']+=1
            if r['decision_status']!='matched':continue
            d=r['decision'];check_point(asset,d)
            assert 0<=d['t']-r['t']<=250_000_000 and all(s>=r['source_ns'] for s in d['sources'].values())
            close(r['decision_delay_ms'],(d['t']-r['t'])/1e6)
            other=next(v for v in VENUES if v!=r['venue'])
            close(r['local_impact_bps'],-r['direction']*10000*math.log(d['mids'][r['venue']]/pre['mids'][r['venue']]))
            close(r['reference_move_bps'],10000*math.log(d['mids'][other]/pre['mids'][other]))
            assert r['local_move_and_stable_reference']==(r['local_impact_bps']>=2 and abs(r['reference_move_bps'])<=1)
            for ms,h in r['horizons'].items():
                if h['status']!='matched':counts['missing_horizons']+=1;continue
                check_point(asset,h);due=d['t']+int(ms)*1_000_000
                assert 0<=h['t']-due<=250_000_000
                assert all(s>=due for s in h['sources'].values()) and all(s>=due for s in h['receipts'].values())
                returns={v:r['direction']*10000*math.log(h['mids'][v]/d['mids'][v]) for v in VENUES}
                close(h['target_fade_bps'],returns[r['venue']])
                close(h['relative_fade_bps'],returns[r['venue']]-returns[other])
                counts['matched_horizons']+=1
    output=dict(status='passed',counts=dict(counts),manifest_sha256=report['manifest_sha256'],diagnostic_sha256=sha(path),
        limits='Validates all recorded candidate print multiplicities, raw quote references, source/receipt inequalities, depth fractions and return arithmetic. Does not independently rescan candidate completeness or first eligible observation selection. No private fills, PnL, causal or independent-sample claim.')
    target=path.with_name('fast-print-independent-reference-audit.json');assert not target.exists()
    target.write_text(json.dumps(output,indent=2)+'\n');print(json.dumps(output,indent=2))

if __name__=='__main__':run()
