#!/usr/bin/env python3
"""One bounded canonical archive traversal; static fixed-anchor RH/HL feasibility."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import statistics
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rh_maker_events import iter_events
INPUT = ROOT/'data/raw/rh-passive-exit-v1/20260930T0252Z'
METHOD = ROOT/'research/passive-rare-spread-fixed-anchor-method.md'
TESTS = ROOT/'tests/test_passive_rare_spread.py'
PROTOCOL = ROOT/'reports/rh-passive-exit-v1-restart/protocol.json'
ASSETS = ('BTC','ETH','NVDA','XAG')
SIZES = (100,250,500,1000)
NS=1_000_000_000
AGE=2*NS
CAP=16_000_000
EXPECTED_MANIFEST_SHA='5a9e61438df592d895d3cfc5d550241b01f0696fdbd5c83f46666d9ff1274250'
EXPECTED_METADATA_SHA='34249d999bf176b73a2f9e30aa1602f3ab135a7cadc9238a080bfe060f048aba'
EXPECTED_SHA='c92c269e3bc3bb345beeaf834ad55d0a97601339b4506e36a9397287f8407bb6'
FIELDS=['k','asset','budget','valid','reason','quantity','rh_bid','rh_ask','hl_sell','hl_buy','rh_fee','hl_fee','fee_margin','stress','net','positive','excursion','left_censored']
TIMING=['k','asset','rh_source_ns','rh_received_ns','hl_source_ns','hl_received_ns','rh_generation','hl_generation']

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def f(value):
    d=Decimal(str(value))
    if not d.is_finite():raise ValueError('nonfinite')
    return Fraction(d)

def decimal(value):
    # Display only; exact rational decisions occur before conversion.
    with localcontext() as c:
        c.prec=max(50,len(str(abs(value.numerator)))+len(str(value.denominator))+5)
        text=format(Decimal(value.numerator)/Decimal(value.denominator),'f')
        return text.rstrip('0').rstrip('.') if '.' in text else text

def common_step(a,b):
    a,b=f(a),f(b)
    den=math.lcm(a.denominator,b.denominator)
    return Fraction(math.lcm(int(a*den),int(b*den)),den)

def price_valid(p,m):
    if p<=0:return False
    if m['price_tick_semantics']!='hl_perp':return (p/f(m['price_tick'])).denominator==1
    d=Decimal(decimal(p))
    if (p/f(Decimal(10)**-(6-int(m['sz_decimals'])))).denominator!=1:return False
    return p.denominator==1 or len(d.normalize().as_tuple().digits)<=5

def levels(book,side,m):
    result=[]
    for px,sz in book[side]:
        p,s=f(px),f(sz)
        if s<=0 or not price_valid(p,m) or (s/f(m['size_step'])).denominator!=1:raise ValueError('quote_off_grid')
        result.append((p,s))
    if not result:raise ValueError('empty_depth')
    if any((result[i][0]<=result[i+1][0] if side=='bids' else result[i][0]>=result[i+1][0]) for i in range(len(result)-1)):
        raise ValueError('unsorted_or_duplicate_depth')
    return result

def walk(side,q):
    rem=q; value=Fraction(0)
    for p,s in side:
        used=min(rem,s);value+=p*used;rem-=used
        if rem==0:return value
    raise ValueError('insufficient_hl_depth')

def quantity_valid(q,m):
    return (q>0 and (q/f(m['size_step'])).denominator==1 and q>=f(m.get('min_qty') or m['size_step'])
            and (m.get('max_qty') is None or q<=f(m['max_qty'])))

def notional_valid(value,m):
    return value>=f(m['min_notional']) and (m.get('max_quote') is None or value<=f(m['max_quote']))

def score(anchor,rh,hl,r,h,budget,parsed=None):
    row={'valid':False}
    try:
        if rh is None or hl is None:raise ValueError('missing_rh' if rh is None else 'missing_hl')
        for book in (rh,hl):
            source,receipt=book.get('source_ns'),book.get('received_ns')
            if not isinstance(source,int) or not isinstance(receipt,int) or source<=0 or source>receipt or receipt>anchor:
                raise ValueError('invalid_clock')
            if not all(0<=anchor-x<=AGE for x in (source,receipt)):raise ValueError('stale_source_or_receipt')
        if any(abs(rh[key]-hl[key])>AGE for key in ('source_ns','received_ns')):raise ValueError('cross_venue_skew')
        if parsed is None:parsed={}
        def cached(book,side,meta):
            key=(id(book),side)
            if key not in parsed:parsed[key]=levels(book,side,meta)
            return parsed[key]
        rb,ra=cached(rh,'bids',r),cached(rh,'asks',r)
        hb,ha=cached(hl,'bids',h),cached(hl,'asks',h)
        b,a=rb[0][0],ra[0][0]
        if b>=a or hb[0][0]>=ha[0][0]:raise ValueError('crossed_book')
        step=common_step(r['size_step'],h['size_step']);q=(f(budget)/a/step).__floor__()*step
        if not quantity_valid(q,r) or not quantity_valid(q,h):raise ValueError('quantity_below_or_outside_bounds')
        Rb,Ra=q*b,q*a
        if not all(notional_valid(v,r) for v in (Rb,Ra)) or Ra>budget:raise ValueError('rh_notional_bounds')
        S,B=walk(hb,q),walk(ha,q)
        if not all(notional_valid(v,h) for v in (S,B)):raise ValueError('hl_notional_bounds')
        rf=(Rb+Ra)*f(r['maker_fee_bps'])/10000;hf=(S+B)*f(h['taker_fee_bps'])/10000
        margin=Ra-Rb+S-B-rf-hf;stress=max(Rb,S)*Fraction(5,10000);net=margin-Fraction(1,10)-stress
        row.update(valid=True,quantity=decimal(q),rh_bid=decimal(b),rh_ask=decimal(a),hl_sell=decimal(S),hl_buy=decimal(B),
                   rh_fee=decimal(rf),hl_fee=decimal(hf),fee_margin=decimal(margin),stress=decimal(stress),net=decimal(net),positive=net>0)
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:row['reason']=str(exc)
    return row

class Excursions:
    def __init__(self):self.armed=False;self.active=None;self.items=[];self.gaps=0
    def update(self,row,k):
        if not row['valid']:
            if self.active is not None:self.items[self.active-1]['missing_anchors']+=1
            return
        if not row['positive']:self.armed=True;self.active=None;return
        if self.active is None:
            self.items.append({'id':len(self.items)+1,'first_k':k,'last_k':k,'stratum':k//600,
                               'left_censored':not self.armed,'positive_anchors':0,'missing_anchors':0})
            self.active=len(self.items);self.armed=False
        e=self.items[self.active-1];e['positive_anchors']+=1;e['last_k']=k
        row.update(excursion=self.active,left_censored=e['left_censored'])

class Anchors:
    def __init__(self,start,metadata,count=3000):
        self.start=start;self.metadata=metadata;self.count=count;self.k=0;self.books={};self.generations={};self.end=None
        self.excursions={(a,b):Excursions() for a in ASSETS for b in SIZES}
    def apply(self,e):
        venue=e.get('venue');kind=e['type'];asset=e.get('asset')
        if kind=='end':self.end=e;return
        if venue not in ('rh_lighter','hyperliquid'):return
        generation=e.get('generation')
        prior=self.generations.get(venue)
        if generation is not None and prior is not None and generation!=prior:
            self.books={key:value for key,value in self.books.items() if key[0]!=venue}
        if generation is not None:self.generations[venue]=generation
        if kind=='control' and e.get('control') in ('connection_close','connection_error','invalid_json','generation_invalidated'):
            self.books={key:value for key,value in self.books.items() if key[0]!=venue}
        if kind=='invalidate' and e.get('scope')=='book':self.books.pop((venue,asset),None)
        if kind=='book':self.books[(venue,asset)]=e
    def emit(self):
        anchor=self.start+self.k*NS;rows=[];timings=[]
        for a in ASSETS:
            rh=self.books.get(('rh_lighter',a));hl=self.books.get(('hyperliquid',a))
            timing={'k':self.k,'asset':a}
            for prefix,book in (('rh',rh),('hl',hl)):
                for key in ('source_ns','received_ns','generation'):timing[prefix+'_'+key]=book.get(key) if book else None
            timings.append(timing)
            parsed={}  # Shared parsing only within this asset/anchor, not quote selection.
            for b in SIZES:
                row={'k':self.k,'asset':a,'budget':b,**score(anchor,rh,hl,self.metadata['rh_lighter'][a],self.metadata['hyperliquid'][a],b,parsed)}
                self.excursions[(a,b)].update(row,self.k);rows.append(row)
        self.k+=1;return rows,timings
    def traverse(self,events):
        # Emitting only when the next receipt is strictly greater consumes ALL ties.
        for e in events:
            receipt=e['received_ns']
            while self.k<self.count and self.start+self.k*NS<receipt:yield self.emit()
            self.apply(e)
        while self.k<self.count:yield self.emit()
        if self.end is None:raise ValueError('missing_verified_terminal')

def validate_metadata(meta):
    markets=meta['markets']
    for a in ASSETS:
        r,h=markets['rh_lighter'][a],markets['hyperliquid'][a]
        if f(r['maker_fee_bps'])!=0 or f(r['taker_fee_bps'])!=0 or f(r['contract_multiplier'])!=1 or f(r['quote_multiplier'])!=1:raise ValueError('not_validated_standard_rh')
        if f(h['taker_fee_bps'])!=(f('4.5') if a in ('BTC','ETH') else f('.9')):raise ValueError('not_validated_hl_fees')
        if a in ('NVDA','XAG') and (h['growth_mode']!='enabled' or f(h['deployer_fee_scale'])!=1):raise ValueError('not_validated_growth')
        if common_step(r['size_step'],h['size_step'])<=0 or f(r['price_tick'])<=0:raise ValueError('invalid_grid')
    return markets

def summarize(rows,engine):
    result=[]
    for a in ASSETS:
        for b in SIZES:
            selected=[r for r in rows if r['asset']==a and r['budget']==b]
            valid=[r for r in selected if r['valid']];positive=[r for r in valid if r['positive']]
            es=engine.excursions[(a,b)].items;uncensored=[e for e in es if not e['left_censored']]
            strata=[]
            for s in range(5):
                sub=[r for r in selected if r['k']//600==s]
                strata.append({'stratum':s,'possible':len(sub),'valid':sum(r['valid'] for r in sub),'positive':sum(r.get('positive',False) for r in sub),
                               'exclusions':dict(Counter(r['reason'] for r in sub if not r['valid']))})
            ns=[Decimal(r['net']) for r in valid]
            result.append({'asset':a,'budget':b,'possible':len(selected),'valid':len(valid),'positive':len(positive),
                           'exclusions':dict(Counter(r['reason'] for r in selected if not r['valid'])),
                           'median_valid_net':str(statistics.median(ns)) if ns else None,'max_valid_net':str(max(ns)) if ns else None,
                           'excursions':es,'uncensored_excursions':len(uncensored),'uncensored_start_strata':sorted({e['stratum'] for e in uncensored}),
                           'primary_static_recurrence':b==1000 and len(uncensored)>=3 and len({e['stratum'] for e in uncensored})>=2,'strata':strata})
    return {'interpretation':'retrospective_static_quote_feasibility_not_fill_or_profit','possible':len(rows),'valid':sum(r['valid'] for r in rows),
            'positive':sum(r.get('positive',False) for r in rows),'asset_budgets':result,'canonical_terminal':engine.end,
            'decision':'stop_if_zero_valid_positives; recurrence_alone_does_not_justify_capture_or_promotion','candidate_nominations':[]}

def readout(summary,freeze):
    lines=['# Retrospective RH/HL rare-spread fixed-anchor feasibility', '',
           'Completed 0252Z archive only; no independent holdout, matched Core comparison, queue/fill inference, or realized profit. Capital, funding and collateral conversion costs are excluded.', '',
           'Implementation freeze: '+freeze['frozen_at']+'. One canonical traversal; all 3,000 one-second anchors across five fixed ten-minute strata. Equal-receipt events are applied before evaluation; later events cannot repair an anchor.', '',
           f"Possible observations: {summary['possible']}; valid: {summary['valid']}; strictly positive after exact public fees, $0.10 and 5bp stress: {summary['positive']}.", '',
           '| Asset | Budget | Valid / 3000 | Positive anchors | Uncensored excursions | Start strata | Median net | Max net | Primary recurrence |',
           '|---|---:|---:|---:|---:|---|---:|---:|---|']
    for r in summary['asset_budgets']:
        lines.append('| '+ ' | '.join(str(r[key]) for key in ('asset','budget','valid','positive','uncensored_excursions','uncensored_start_strata','median_valid_net','max_valid_net','primary_static_recurrence'))+' |')
    lines += ['', 'Excursions are separate within each asset and budget. Only a valid nonpositive anchor rearms; gaps bridge runs and do not create independent episodes. Initial positives without a prior valid nonpositive anchor are left censored and excluded from recurrence eligibility. Primary static recurrence requires one asset at $1,000 with >=3 uncensored excursions spanning >=2 fixed strata. Smaller sizes cannot be pooled.', '',
              'All 48,000 rows, including failures, are in observations.csv; row keys are k/asset/budget. Absolute anchor UTC nanoseconds = '+str(epoch_ns(json.loads((INPUT/'manifest.json').read_bytes())['started_utc']))+' + k*1,000,000,000; stratum=floor(k/600). timing.csv provides one source/receipt/generation reference per anchor and asset. summary.json retains five-stratum denominators, exclusion reasons, excursion starts/end anchors, missing bridges and canonical terminal counters.', '',
              'The required gate uses unchanged q=floor(budget/RHask/commonlot), two RH maker prices, both recorded HL depth walks, own-leg public Standard fees and stress=max(RH bid opening notional, HL sell opening notional)*0.0005. HL snapshots have only five recorded levels; no unrecorded liquidity is imputed. Maker top size does not establish queue capacity or fill odds. Canonical decimal representations do not recover precision discarded by the frozen decoder.', '',
              'Zero valid positives ends this route-specific feasibility hypothesis. Any positive recurrence only supports further analysis of conditional execution odds; it cannot justify a capture slot or promotion by itself. Dynamic repricing, price drift, queue selection, fill odds and complete public tape are not established.', '',
              'Manifest records unchanged input/dependency hashes. The input gzip is hashed before/after in addition to one bounded canonical traversal; no raw copy or network call was made. Derived CSV records and all source/metadata/report/manifest files share the 16MB limit.']
    return '\n'.join(lines)+'\n'

def epoch_ns(s):
    timestamp=dt.datetime.fromisoformat(s)
    epoch=dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)
    delta=timestamp-epoch
    return (delta.days*86400+delta.seconds)*NS+delta.microseconds*1000

def verify_terminal(end,manifest,hashes,source):
    if (not end.get('raw_sha_verified') or end.get('truncated')
            or end.get('reason')!='duration_limit'
            or end.get('raw_gzip_sha256')!=EXPECTED_SHA
            or end.get('manifest_sha256')!=hashes[str(source/'manifest.json')]
            or end.get('adapter_sha256')!=hashes[str(ROOT/'scripts/rh_maker_events.py')]
            or end.get('book_decoder_sha256')!=hashes[str(ROOT/'scripts/maker_book_archive.py')]
            or end.get('counts',{}).get('decoded_records')!=124019
            or end.get('started_ns')!=epoch_ns(manifest['started_utc'])
            or end.get('stopped_ns')!=epoch_ns(manifest['ended_utc'])):
        raise ValueError('terminal_identity_or_completion_failed')

def bounded_write(directory,name,data):
    raw=data.encode() if isinstance(data,str) else data
    used=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
    if used+len(raw)>CAP-100_000:raise ValueError('derived_cap_before_write')
    (directory/name).write_bytes(raw)

def bounded_csv(directory,name,fields,rows):
    used=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())
    buffer=io.StringIO(newline='');writer=csv.DictWriter(buffer,fieldnames=fields,extrasaction='raise')
    with (directory/name).open('wb') as output:
        for row in [None]+rows:
            if row is None:writer.writeheader()
            else:writer.writerow(row)
            raw=buffer.getvalue().encode();buffer.seek(0);buffer.truncate(0)
            if used+len(raw)>CAP-100_000:raise ValueError('derived_cap_before_write')
            output.write(raw);used+=len(raw)

def run(source,out):
    if out.resolve().parent!=(ROOT/'reports/passive-rare-spread').resolve():raise ValueError('output_must_be_new_diagnostic_report_child')
    if source.resolve()!=INPUT.resolve():raise ValueError('only_frozen_archive_allowed')
    manifest=json.loads((source/'manifest.json').read_bytes());protocol=json.loads(PROTOCOL.read_bytes())
    if sha(source/'manifest.json')!=EXPECTED_MANIFEST_SHA:raise ValueError('known_manifest_hash')
    if (protocol['metadata_normalized_sha256']!=EXPECTED_METADATA_SHA
            or manifest['metadata_normalized_sha256']!=EXPECTED_METADATA_SHA):raise ValueError('known_protocol_metadata_hash')
    if epoch_ns(manifest['ended_utc'])-epoch_ns(manifest['started_utc'])<3000*NS:raise ValueError('incomplete_anchor_coverage')
    if manifest['frames_sha256']!=EXPECTED_SHA or manifest['payload_records']!=124019 or manifest['end_reason']!='duration_limit' or manifest.get('errors'):raise ValueError('wrong_or_incomplete_archive')
    dependencies=[ROOT/p for p in protocol['source_sha256']]
    for p in dependencies:
        if sha(p)!=protocol['source_sha256'][str(p.relative_to(ROOT))]:raise ValueError('frozen_dependency_changed_'+str(p))
    inputs=[p for p in source.rglob('*') if p.is_file()]+dependencies+[PROTOCOL,Path(__file__),METHOD,TESTS]
    hashes={str(p):sha(p) for p in inputs}
    if hashes[str(source/'frames.jsonl.gz')]!=EXPECTED_SHA:raise ValueError('raw_hash')
    if hashes[str(source/'metadata/normalized.json')]!=manifest['metadata_normalized_sha256']:raise ValueError('metadata_hash')
    meta=json.loads((source/'metadata/normalized.json').read_bytes())
    for request in meta['raw_requests'].values():
        if sha(source/'metadata'/request['raw_file'])!=request['sha256']:raise ValueError('metadata_raw_hash')
    markets=validate_metadata(meta)
    destination=out
    if destination.exists():raise ValueError('output_already_exists')
    out=destination.with_name(destination.name+'.building')
    out.mkdir(parents=True,exist_ok=False)
    for name,p in [('source.py',Path(__file__)),('method.md',METHOD),('tests.py',TESTS),('metadata.json',source/'metadata/normalized.json')]: bounded_write(out,name,p.read_bytes())
    freeze={'frozen_at':dt.datetime.now(dt.timezone.utc).isoformat(),'input_hashes':hashes,'anchors':3000,'expected_rows':48000,'bounds':{'archive_bytes':50000000,'decoded_bytes':128000000,'records':124019,'derived_bytes':CAP},'network_calls':0}
    bounded_write(out,'freeze.json',json.dumps(freeze,indent=2)+'\n')
    if any(sha(Path(p))!=h for p,h in hashes.items()):raise ValueError('input_changed_before_scan')
    engine=Anchors(epoch_ns(manifest['started_utc']),markets);rows=[];timings=[]
    for batch,timing in engine.traverse(iter_events(source,expected_raw_sha256=EXPECTED_SHA,max_raw_bytes=50_000_000,max_decoded_bytes=128_000_000,max_records=124019)):
        rows.extend(batch);timings.extend(timing)
    if len(rows)!=48000 or len(timings)!=12000 or any(sum(r['k']//600==s for r in rows)!=9600 for s in range(5)):raise ValueError('denominator')
    verify_terminal(engine.end,manifest,hashes,source)
    summary=summarize(rows,engine)
    for name,fields,data in [('observations.csv',FIELDS,rows),('timing.csv',TIMING,timings)]:
        bounded_csv(out,name,fields,data)
    bounded_write(out,'summary.json',json.dumps(summary,indent=2)+'\n')
    bounded_write(out,'readout.md',readout(summary,freeze))
    unchanged=all(sha(Path(p))==h for p,h in hashes.items())
    if not unchanged:raise ValueError('input_or_dependency_changed_after_scan')
    output_hashes={p.name:sha(p) for p in out.iterdir() if p.is_file()}
    bounded_write(out,'manifest.json',json.dumps({'completed_at':dt.datetime.now(dt.timezone.utc).isoformat(),'input_hashes_unchanged':unchanged,'input_hashes':hashes,'output_hashes':output_hashes,'network_calls':0,'raw_scan_count':1,'derived_cap_bytes':CAP},indent=2)+'\n')
    if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>CAP-100000:raise ValueError('derived_cap_exceeded')
    out.rename(destination)
    print(json.dumps({'out':str(destination),'possible':len(rows),'valid':summary['valid'],'positive':summary['positive']}))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=INPUT);p.add_argument('--out',type=Path,required=True);a=p.parse_args();run(a.input,a.out)
if __name__=='__main__':main()
