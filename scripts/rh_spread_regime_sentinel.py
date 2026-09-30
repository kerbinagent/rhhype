#!/usr/bin/env python3
"""Prospective public RH spread sentinel. Default is dry; each network stage is explicit."""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter, defaultdict
import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import gzip
import hashlib
import io
import json
from pathlib import Path
import signal
import sys
import time
import aiohttp
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.passive_universe_screen import select, REQUESTS, WS
METHOD=ROOT/'research/rh-spread-regime-sentinel-plan.md'
TESTS=ROOT/'tests/test_rh_spread_regime_sentinel.py'
REFERENCE=ROOT/'reports/passive-universe-screen/20260930T0310Z/universe.json'
REFERENCE_SHA='37fc90d4b66d8fc0aefea3c806b49ff598ab06c986a9db3cec76188da7b1fa83'
DEPENDENCY=ROOT/'scripts/passive_universe_screen.py'
ASSETS=tuple('BTC ETH LIT NVDA SOL HYPE AAPL XAG GOOGL SNDK NEAR ZEC XRP MSFT MU TSLA META CRCL AMD AMZN INTC'.split())
BUDGETS=(100,250,500,1000)
NS=1_000_000_000
AGE=2*NS
LATENESS=250_000_000
META_AGE=120*NS
SLOTS=20
DURATION=1200*NS
CAP=500_000
LIMITS={'control':90_000,'metadata':280_000,'samples':80_000,'derived':40_000,'logs':10_000}
NORMAL_SAMPLE_LIMIT=75_000
MAX_DECODED_SAMPLES=2_000_000
NORMAL_DECODED_SAMPLES=1_750_000
MAX_SAMPLE_LINE=65_536
WS_MESSAGE_LIMIT=32_768
INGRESS_LIMIT=64_000_000
MESSAGE_LIMIT=100_000
ROW_FIELDS=('k','asset','budget','valid','reason','quantity','optimistic_budget','positive','paired_hedge_status')

def encoded(value):return (json.dumps(value,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def utc():return time.time_ns()
def f(x):
    if isinstance(x,bool):raise ValueError('boolean_numeric')
    text=str(x)
    if len(text)>80:raise ValueError('numeric_representation_bound')
    d=Decimal(text)
    if not d.is_finite():raise ValueError('nonfinite')
    if len(d.as_tuple().digits)>40 or abs(d.as_tuple().exponent)>18 or abs(d.adjusted())>18:raise ValueError('numeric_magnitude_bound')
    return Fraction(d)
def display(x):
    with localcontext() as c:
        c.prec=max(50,len(str(abs(x.numerator)))+len(str(x.denominator))+5)
        s=format(Decimal(x.numerator)/Decimal(x.denominator),'f')
        return s.rstrip('0').rstrip('.') if '.' in s else s

def median(values):
    values=sorted(values);n=len(values)
    return None if not n else values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2

class CapReached(ValueError):pass
class Store:
    """All category and aggregate checks precede writes, including complete gzip trailers."""
    def __init__(self,path):
        self.path=Path(path);self.index=self.path/'storage.json'
        self.entries=json.loads(self.index.read_bytes()) if self.index.exists() else {}
        expected=set(self.entries)|({'storage.json'} if self.index.exists() else set())
        actual={p.name for p in self.path.iterdir() if p.is_file()}
        if actual!=expected or any(p.is_symlink() or p.is_dir() for p in self.path.iterdir()):raise ValueError('unmanaged_stage_file')
        for name,v in self.entries.items():
            if sha(self.path/name)!=v['sha256'] or (self.path/name).stat().st_size!=v['bytes']:raise ValueError('stage_storage_hash')
    def write(self,name,data,category,*,final=False):
        if name=='storage.json' or Path(name).name!=name or category not in LIMITS:raise ValueError('unsafe_store_name')
        raw=data if isinstance(data,bytes) else encoded(data)
        entries=dict(self.entries);entries[name]={'bytes':len(raw),'category':category,'sha256':hashlib.sha256(raw).hexdigest()}
        index=encoded(entries)
        totals=Counter()
        for e in entries.values():totals[e['category']]+=e['bytes']
        totals['control']+=max(len(index),self.index.stat().st_size if self.index.exists() else 0)
        if totals['control']>LIMITS['control']-(0 if final else 8000) or any(totals[k]>LIMITS[k] for k in LIMITS) or sum(totals.values())>CAP:raise CapReached('artifact_category_or_total_cap')
        # Replacement writes do not truncate first; new bytes are completely checked above.
        (self.path/name).write_bytes(raw);self.index.write_bytes(index);self.entries=entries
    def bytes(self):return sum(p.stat().st_size for p in self.path.iterdir() if p.is_file())
    def verify(self):
        Store(self.path)
        if self.bytes()>CAP:raise CapReached('total_cap')

def dependencies():return [Path(__file__),METHOD,TESTS,DEPENDENCY,REFERENCE]
def input_hashes():return {str(p):sha(p) for p in dependencies()}
def verify_inputs(hashes):
    if set(hashes)!={str(p) for p in dependencies()} or any(sha(Path(p))!=h for p,h in hashes.items()):raise ValueError('source_or_reference_changed')
    if sha(REFERENCE)!=REFERENCE_SHA:raise ValueError('original_universe_changed')
def reference():
    if sha(REFERENCE)!=REFERENCE_SHA:raise ValueError('original_universe_changed')
    rows=json.loads(REFERENCE.read_bytes())['selected']
    if tuple(r['asset'] for r in rows)!=ASSETS:raise ValueError('original_identity_denominator')
    return rows

def stage_path(path,new=False):
    path=Path(path).resolve()
    if path.parent!=(ROOT/'reports/rh-spread-regime-sentinel').resolve():raise ValueError('stage_must_be_new_sentinel_report_child')
    if new:path.mkdir(parents=True,exist_ok=False)
    elif not path.is_dir():raise ValueError('missing_stage')
    return path

def eligibility(responses):
    original=reference()
    plan={'pairs':[{'asset':m['asset'],'other':{'venue':'rh_lighter','market':m['rh_market']},'hl':{'venue':'hyperliquid','market':m['hl_market']}} for m in original]}
    numeric_failures={}
    rb={str(r['market_id']):r for r in responses['rh_order_book_details']['order_book_details']}
    hb={}
    for name in ('hl_meta_native','hl_meta_xyz'):
        meta,ctxs=responses[name]
        for h,c in zip(meta['universe'],ctxs):hb[h['name']]=(h,c)
    for old in original:
        try:
            r=rb[old['rh_market']];h,c=hb[old['hl_market']]
            for key in ('multiplier','quote_multiplier','maker_fee','daily_quote_token_volume','index_price','min_base_amount','min_quote_amount','order_quote_limit'):f(r[key])
            for key in ('dayNtlVlm','oraclePx'):f(c[key])
            if old['hl_market'].startswith('xyz:'):f(h['deployerFeeScale'])
            if r.get('daily_trades_count') is not None:f(r['daily_trades_count'])
            for obj,keys,maximum in ((r,('supported_price_decimals','supported_size_decimals','price_decimals','size_decimals','supported_quote_decimals'),24),(h,('szDecimals',),6)):
                for key in keys:
                    if isinstance(obj[key],bool) or not isinstance(obj[key],int) or not 0<=obj[key]<=maximum:raise ValueError('metadata_integer_grid_bound')
        except (ValueError,KeyError,TypeError,ArithmeticError) as exc:numeric_failures[old['asset']]='numeric_or_missing_metadata_'+str(exc)[:100]
    plan['pairs']=[p for p in plan['pairs'] if p['asset'] not in numeric_failures]
    fresh=select(plan,responses)
    found={m['asset']:m for m in fresh['selected']};failed={m['asset']:m['reason'] for m in fresh['excluded']}|numeric_failures
    rows=[]
    for old in original:
        a=old['asset'];m=found.get(a);reason=failed.get(a)
        if m is not None:
            try:
                for key in ('rh_market','hl_market','unit','rh_price_tick','rh_size_step','hl_size_step','common_step'):
                    if m[key]!=old[key]:raise ValueError('changed_original_'+key)
                if f(m['rh_maker_fee_bps'])!=0:raise ValueError('changed_standard_rh_maker_fee')
            except ValueError as exc:reason=str(exc)
        rows.append({'asset':a,'eligible':m is not None and reason is None,'reason':reason or ('missing_metadata' if m is None else None),
                     'reference':{key:old[key] for key in ('asset','rh_market','hl_market','unit','rh_price_tick','rh_size_step','hl_size_step','common_step')},'market':m})
    return rows

def client_session(timeout):
    trace=aiohttp.TraceConfig()
    async def reject_redirect(session,context,params):raise ValueError('redirect_forbidden')
    trace.on_request_redirect.append(reject_redirect)
    session=aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout),trace_configs=[trace])
    # The installed aiohttp may retry an idempotent stale connection internally.
    session._retry_connection=False
    return session

async def read_response(response,remaining):
    chunks=[];total=0
    async for part in response.content.iter_chunked(16_384):
        total+=len(part)
        if total>remaining:raise CapReached('metadata_ingress_cap')
        chunks.append(part)
    return b''.join(chunks)

def failed_preparation(store,reason,calls):
    rows=[{'k':k,'asset':a,'budget':b,'valid':False,'reason':'preparation_failed','paired_hedge_status':'unknown'} for k in range(SLOTS) for a in ASSETS for b in BUDGETS]
    write_rows(store,rows,final=True)
    store.write('failure.json',{'status':'preparation_failed','reason':reason[:300],'metadata_attempts':calls,'planned_rows':1680,'economics_evaluated':False},'logs',final=True)

async def prepare(path):
    path=stage_path(path,new=True);store=Store(path);calls=0
    hashes=input_hashes();verify_inputs(hashes)
    for name,p in [('source.py',Path(__file__)),('method.md',METHOD),('tests.py',TESTS)]:store.write(name,p.read_bytes(),'control')
    store.write('source-freeze.json',{'created_ns':utc(),'input_hashes':hashes,'network_calls_before_freeze':0,'limits':LIMITS,'python':sys.version,'aiohttp':aiohttp.__version__},'control')
    # Preserve >=30KB of the control category for eligibility and all final manifests.
    if sum(v['bytes'] for v in store.entries.values())+store.index.stat().st_size>60_000:raise CapReached('control_finalization_reserve')
    provenance={};responses={};raw_used=0
    try:
        async with client_session(20) as session:
            for name,(method,url,body) in REQUESTS.items():
                calls+=1;started=utc()
                provenance[name]={'method':method,'url':url,'body':body,'started_ns':started,'status':None,'error':None}
                store.write('requests.json',provenance,'control')
                try:
                    async with session.request(method,url,json=body,allow_redirects=False) as response:
                        provenance[name]['status']=response.status
                        raw=await read_response(response,LIMITS['metadata']-raw_used)
                        completed=utc();completed_mono=time.monotonic_ns();status=response.status
                except (Exception,asyncio.CancelledError) as exc:
                    provenance[name].update(completed_ns=utc(),completed_mono_ns=time.monotonic_ns(),error=type(exc).__name__+':'+str(exc)[:160])
                    store.write('requests.json',provenance,'control');raise
                store.write(name+'.json',raw,'metadata');raw_used+=len(raw)
                provenance[name]={'method':method,'url':url,'body':body,'started_ns':started,'completed_ns':completed,'completed_mono_ns':completed_mono,'status':status,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                store.write('requests.json',provenance,'control')
                if status!=200:raise ValueError('metadata_http_'+str(status))
                responses[name]=json.loads(raw)
        markets=eligibility(responses);verify_inputs(hashes)
        store.write('eligibility.json',markets,'control')
        store.write('prepared.json',{'status':'prepared','metadata_attempts':calls,'metadata_successes':3,'prepared_ns':utc(),'inputs':hashes,
             'prepared_hashes':{name:v['sha256'] for name,v in store.entries.items()},'rows':1680,'no_quote_connection':True},'control')
        store.verify()
        print(json.dumps({'stage':str(path),'bytes':store.bytes(),'eligible':[r['asset'] for r in markets if r['eligible']],
                          'excluded':{r['asset']:r['reason'] for r in markets if not r['eligible']},'responses_completed_ns':{n:p['completed_ns'] for n,p in provenance.items()},'ready_for_root_review':True}))
    except (Exception,asyncio.CancelledError) as exc:
        if calls:
            provenance[name].setdefault('completed_ns',utc())
            provenance[name].setdefault('completed_mono_ns',time.monotonic_ns())
            provenance[name]['error']=provenance[name].get('error') or (type(exc).__name__+':'+str(exc))[:180]
            store.write('requests.json',provenance,'control',final=True)
        failed_preparation(store,type(exc).__name__+':'+str(exc),calls);raise

def prepared(path):
    store=Store(path);p=json.loads((path/'prepared.json').read_bytes());verify_inputs(p['inputs'])
    versions=json.loads((path/'source-freeze.json').read_bytes())
    if versions['python']!=sys.version or versions['aiohttp']!=aiohttp.__version__:raise ValueError('runtime_version_changed')
    if p['status']!='prepared' or p['metadata_successes']!=3 or p['metadata_attempts']!=3:raise ValueError('requires_three_successful_metadata')
    for name,h in p['prepared_hashes'].items():
        if sha(path/name)!=h:raise ValueError('prepared_evidence_changed')
    requests=json.loads((path/'requests.json').read_bytes());markets=json.loads((path/'eligibility.json').read_bytes())
    if len(requests)!=3 or tuple(r['asset'] for r in markets)!=ASSETS:raise ValueError('prepared_identity')
    return store,p,requests,markets

def metadata_fresh(requests,t0,t0_mono):
    return len(requests)==3 and all(all(isinstance(r.get(key),int) and not isinstance(r[key],bool) and 0<=now-r[key]<=META_AGE
               for key,now in (('completed_ns',t0),('completed_mono_ns',t0_mono))) for r in requests.values())

def freeze(path):
    path=stage_path(path);store,p,requests,markets=prepared(path)
    if (path/'root-freeze.json').exists() or (path/'schedule.json').exists():raise ValueError('stage_already_frozen_or_run')
    if not metadata_fresh(requests,utc()+10*NS,time.monotonic_ns()+10*NS):
        failed_preparation(store,'metadata_expired_at_freeze_no_refetch',3)
        return
    try:
        store.write('root-freeze.json',{'frozen_ns':utc(),'prepared_sha256':sha(path/'prepared.json'),'inputs':p['inputs'],
              'stage_hashes':{name:v['sha256'] for name,v in store.entries.items()},'economic_rules':'committed_method_unchanged','metadata_max_age_ns_at_t0':META_AGE},'control')
    except CapReached:
        failed_preparation(store,'freeze_control_finalization_reserve',3);return
    print(json.dumps({'frozen':str(path),'next_action':'separate_root_run','metadata_expires_before_t0_ns':min(r['completed_ns'] for r in requests.values())+META_AGE}))

class Clock:
    def __init__(self,utc_ns,mono_ns):self.utc_ns=utc_ns;self.mono_ns=mono_ns
    def mapped(self,mono):return self.utc_ns+mono-self.mono_ns
    def valid(self,now,mono):return abs(now-self.mapped(mono))<=LATENESS

class Feed:
    def __init__(self,markets,clock):
        self.markets={r['reference']['rh_market']:r for r in markets};self.clock=clock;self.latest={};self.watermarks={};self.failures={};self.counters=Counter();self.generation='rh:1';self.stop_reason=None;self.subscribed=set();self.connected_seen=False
    def clear(self,reason,mid=None):
        keys=[mid] if mid in self.markets else list(self.markets)
        for key in keys:self.latest.pop(key,None);self.failures[key]=reason
        self.counters[reason]+=1
    def stop(self,reason):self.stop_reason=self.stop_reason or reason;self.clear(self.stop_reason)
    def accept(self,raw,receipt,mono):
        if self.stop_reason:return
        try:
            payload=json.loads(raw,parse_float=Decimal)
            if not isinstance(payload,dict):raise ValueError('malformed_ticker')
            kind=payload.get('type','')
            if not isinstance(kind,str):raise ValueError('malformed_ticker')
            if 'error' in kind.lower():self.stop('server_or_subscription_error');return
            if kind in ('ping','pong'):return
            if kind=='connected':
                if self.connected_seen:self.stop('unexpected_connection_generation')
                self.connected_seen=True;return
            channel=payload.get('channel','')
            if not isinstance(channel,str):raise ValueError('malformed_ticker')
            if not channel.startswith('ticker:'):raise ValueError('unidentifiable_ticker')
            mid=channel.split(':',1)[1]
            if mid not in self.markets:raise ValueError('unidentifiable_ticker')
            market=self.markets[mid]
            if kind=='subscribed/ticker':
                if mid in self.subscribed:self.stop('unexpected_subscription_generation');return
                self.subscribed.add(mid)
            if not self.clock.valid(receipt,mono):self.clear('receipt_clock_mapping');return
            if not market['eligible']:return
            if payload.get('type') not in ('subscribed/ticker','update/ticker'):raise ValueError('ticker_type')
            ticker=payload['ticker'];source=ticker['last_updated_at']
            if isinstance(source,bool) or not isinstance(source,int) or source<=0:raise ValueError('source_shape')
            source*=1000
            if source>receipt:raise ValueError('future_source')
            if source<self.watermarks.get(mid,0):raise ValueError('source_regression')
            m=market['market']
            if ticker['s']!=market['asset']:raise ValueError('ticker_symbol')
            for side in ('b','a'):
                px,sz=f(ticker[side]['price']),f(ticker[side]['size'])
                if min(px,sz)<=0 or (px/f(m['rh_price_tick'])).denominator!=1 or (sz/f(m['rh_size_step'])).denominator!=1:raise ValueError('ticker_grid_or_positive_shape')
            if f(ticker['b']['price'])>=f(ticker['a']['price']):raise ValueError('crossed_rh')
            self.watermarks[mid]=source
            self.latest[mid]={'source_ns':source,'receipt_ns':receipt,'receipt_mono_ns':mono,'generation':self.generation,'raw':raw}
            self.failures.pop(mid,None);self.counters['accepted_tickers']+=1
        except (ValueError,TypeError,KeyError,ArithmeticError) as exc:
            self.clear(str(exc),locals().get('mid'))
    def snapshot(self,k,planned_mono,actual_utc,actual_mono):
        reason=None
        if not 0<=actual_mono-planned_mono<=LATENESS:reason='dispatch_late'
        if not self.clock.valid(actual_utc,actual_mono):reason='sample_clock_mapping';self.clear(reason)
        rows=[]
        for a in ASSETS:
            market=next(m for m in self.markets.values() if m['asset']==a);mid=market['reference']['rh_market'];tick=self.latest.get(mid)
            why=('metadata_'+str(market['reason'])) if not market['eligible'] else reason or self.stop_reason
            if why is None:
                if tick is None:why=self.failures.get(mid,'missing_ticker')
                elif tick['receipt_ns']>actual_utc or tick['receipt_mono_ns']>actual_mono:why='invalid_sample_clock'
                elif not (0<tick['source_ns']<=tick['receipt_ns'] and 0<=actual_utc-tick['source_ns']<=AGE and 0<=actual_utc-tick['receipt_ns']<=AGE):why='stale_source_or_receipt'
            if why in ('invalid_sample_clock','stale_source_or_receipt'):
                self.latest.pop(mid,None);self.failures[mid]=why
            rows.append({'k':k,'asset':a,'planned_utc_ns':self.clock.mapped(planned_mono),'planned_mono_ns':planned_mono,
               'sample_utc_ns':actual_utc,'sample_mono_ns':actual_mono,'reason':why,'ticker':dict(tick) if tick is not None else None})
        return rows

def missing_slots(samples,clock,t0_mono,reason):
    by={(r['k'],r['asset']):r for r in samples}
    return [by.get((k,a),{'k':k,'asset':a,'planned_utc_ns':clock.mapped(t0_mono+k*60*NS),'planned_mono_ns':t0_mono+k*60*NS,
            'sample_utc_ns':None,'sample_mono_ns':None,'reason':reason,'ticker':None}) for k in range(SLOTS) for a in ASSETS]

def compressed_samples(samples,normal=False):
    lines=[encoded(r) for r in samples]
    if any(len(l)>MAX_SAMPLE_LINE for l in lines) or sum(map(len,lines))>(NORMAL_DECODED_SAMPLES if normal else MAX_DECODED_SAMPLES):raise CapReached('sample_decoded_or_line_cap')
    return gzip.compress(b''.join(lines),mtime=0)

def score(sample,market,budget,economic=True):
    row={'k':sample['k'],'asset':sample['asset'],'budget':budget,'valid':False,'paired_hedge_status':'unknown'}
    if not economic:return row|{'reason':sample.get('reason') or 'economics_unadjudicated_early_stop'}
    if sample.get('reason'):return row|{'reason':sample['reason']}
    try:
        tick=json.loads(sample['ticker']['raw'],parse_float=Decimal)['ticker'];m=market['market']
        b,a=f(tick['b']['price']),f(tick['a']['price']);step=f(market['reference']['common_step']);q=(f(budget)/a/step).__floor__()*step
        if q<=0 or q<f(m['rh_min_qty']) or (q/f(m['rh_size_step'])).denominator!=1:raise ValueError('rh_quantity_bounds')
        if min(q*b,q*a)<f(m['rh_min_notional']) or max(q*b,q*a)>f(m['rh_max_quote']) or q*a>budget:raise ValueError('rh_notional_bounds')
        U=q*(a-b)-Fraction(1,10)-Fraction(5,10000)*q*b
        return row|{'valid':True,'quantity':display(q),'optimistic_budget':display(U),'positive':U>0}
    except (ValueError,TypeError,KeyError,ArithmeticError) as exc:return row|{'reason':str(exc)}

def summarize(rows,economic):
    groups=[]
    for a in ASSETS:
        for b in BUDGETS:
            group=[r for r in rows if r['asset']==a and r['budget']==b];valid=[r for r in group if r['valid']]
            values=[f(r['optimistic_budget']) for r in valid];blocks=[]
            for block in range(4):
                sub=[r for r in group if r['k']//5==block];v=[f(r['optimistic_budget']) for r in sub if r['valid']];med=median(v)
                blocks.append({'block':block,'possible':5,'valid':len(v),'median':display(med) if med is not None else None,'passes':len(v)>=4 and med>0})
            med=median(values)
            groups.append({'asset':a,'budget':b,'possible':20,'valid':len(valid),'positive':sum(r.get('positive',False) for r in group),
                'exclusions':dict(Counter(r['reason'] for r in group if not r['valid'])),'median':display(med) if med is not None else None,
                'maximum':display(max(values)) if values else None,'blocks':blocks,
                'primary_prerequisite':bool(economic and b==1000 and len(valid)>=16 and med>0 and sum(x['passes'] for x in blocks)>=3)})
    return {'scope':'prospective_RH_only_ex_funding_ex_credits_necessary_static_budget','planned_rows':1680,'actual_rows':len(rows),
      'economics_evaluated':economic,'valid_rh_size_observations':sum(r['valid'] for r in rows),'unknown_paired_hedge_rows':1680,
      'groups':groups,'later_cost_screen_candidates':[r['asset'] for r in groups if r['primary_prerequisite']],
      'automatic_followup':False,'profit_or_fill_claim':False}

def write_rows(store,rows,*,final=False):
    if len(rows)!=1680 or {(r['k'],r['asset'],r['budget']) for r in rows}!={(k,a,b) for k in range(SLOTS) for a in ASSETS for b in BUDGETS}:raise ValueError('planned_denominator_mismatch')
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=ROW_FIELDS);writer.writeheader();writer.writerows(rows)
    raw=out.getvalue().encode()
    if len(raw)>1_000_000:raise CapReached('derived_decoded_cap')
    store.write('observations.csv.gz',gzip.compress(raw,mtime=0),'derived',final=final)

async def receive(feed,user_stop,done):
    bytes_in=0;messages=0;ws=None;keeper=None
    async def ping():
        while not done.is_set():
            await asyncio.sleep(30)
            try:await ws.send_json({'type':'ping'});feed.counters['outbound_application_pings']+=1
            except Exception:feed.stop('ping_failed');await ws.close();return
    try:
        async with client_session(10) as session:
            async with session.ws_connect(WS,max_msg_size=WS_MESSAGE_LIMIT,autoping=False) as socket:
                ws=socket;feed.counters['websocket_connections']+=1
                for mid,m in feed.markets.items():
                    if m['eligible']:await ws.send_json({'type':'subscribe','channel':'ticker/'+mid});feed.counters['ticker_subscriptions']+=1
                keeper=asyncio.create_task(ping())
                async for msg in ws:
                    now,mono=utc(),time.monotonic_ns()
                    if done.is_set() or user_stop.is_set():break
                    size=len(msg.data.encode()) if isinstance(msg.data,str) else len(msg.data) if isinstance(msg.data,bytes) else 0
                    bytes_in+=size;messages+=1
                    feed.counters['ingress_bytes']=bytes_in;feed.counters['ingress_messages']=messages
                    if size>WS_MESSAGE_LIMIT or bytes_in>INGRESS_LIMIT or messages>MESSAGE_LIMIT:feed.stop('ingress_cap');break
                    if msg.type==aiohttp.WSMsgType.PING:await ws.pong(msg.data);continue
                    if msg.type==aiohttp.WSMsgType.PONG:continue
                    if msg.type==aiohttp.WSMsgType.BINARY:feed.stop('unexpected_binary');break
                    if msg.type==aiohttp.WSMsgType.TEXT:
                        try:payload=json.loads(msg.data)
                        except (ValueError,TypeError):feed.clear('invalid_json');continue
                        if isinstance(payload,dict) and payload.get('type')=='ping':await ws.send_json({'type':'pong'})
                        else:feed.accept(msg.data,now,mono)
                        if feed.stop_reason:break
                    elif msg.type in (aiohttp.WSMsgType.ERROR,aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.CLOSE):break
    except asyncio.CancelledError:raise
    except Exception as exc:feed.stop('socket_'+type(exc).__name__)
    finally:
        if keeper:keeper.cancel();await asyncio.gather(keeper,return_exceptions=True)
        if ws is not None:feed.counters['socket_close_code']=ws.close_code or 0
        if not done.is_set() and not user_stop.is_set():feed.stop('socket_closed')
        if ws is not None:await ws.close()

async def wait_deadline(deadline,stop):
    remaining=(deadline-time.monotonic_ns())/NS
    if remaining<=0:return not stop.is_set()
    try:await asyncio.wait_for(stop.wait(),remaining);return False
    except asyncio.TimeoutError:return True

def readout(summary,status):
    lines=['# Prospective RH spread-regime sentinel', '', 'Status: '+status+'. New sampled network study; all planned rows retained. No Core/HL depth or fill evidence. U excludes funding, credits/rebates, transfers, capital and conversion; USDG parity is conditional.', '',
           'Economics evaluated: '+str(summary['economics_evaluated'])+'. Primary gate: >=16/20 valid, positive full-window median, >=3/4 blocks with >=4/5 valid and positive median.', '',
           '| Asset | Budget | Valid / 20 | Median U | Maximum U | Primary prerequisite |','|---|---:|---:|---:|---:|---|']
    for r in summary['groups']:lines.append('| '+' | '.join(str(r[k]) for k in ('asset','budget','valid','median','maximum','primary_prerequisite'))+' |')
    lines += ['', 'A positive prerequisite does not trigger another study, capture or promotion. Smaller sizes cannot rescue the primary gate. See summary.json.gz for all blocks/exclusions; observations.csv.gz has all1,680 keys. samples.jsonl.gz retains fixed-sample raw ticker messages, not the intervening stream.']
    return '\n'.join(lines)+'\n'

async def run(path):
    path=stage_path(path);store,p,requests,markets=prepared(path)
    freeze=json.loads((path/'root-freeze.json').read_bytes());verify_inputs(freeze['inputs'])
    if freeze['prepared_sha256']!=sha(path/'prepared.json') or (path/'schedule.json').exists():raise ValueError('not_new_reviewed_run')
    for name,h in freeze['stage_hashes'].items():
        if sha(path/name)!=h:raise ValueError('reviewed_stage_changed')
    now,mono=utc(),time.monotonic_ns();clock=Clock(now,mono);t0_mono=mono+10*NS;t0_utc=clock.mapped(t0_mono)
    if not metadata_fresh(requests,t0_utc,t0_mono):
        failed_preparation(store,'metadata_expired_no_refetch',3);return
    try:
        store.write('schedule.json',{'run_activation_utc_ns':now,'run_activation_mono_ns':mono,'t0_utc_ns':t0_utc,'t0_mono_ns':t0_mono,
           'endpoint_utc_ns':t0_utc+DURATION,'endpoint_mono_ns':t0_mono+DURATION,'slot_count':20,'interval_ns':60*NS,'max_dispatch_lateness_ns':LATENESS},'control')
    except CapReached:
        failed_preparation(store,'schedule_control_finalization_reserve',3);return
    verify_inputs(freeze['inputs'])
    control_used=sum(v['bytes'] for v in store.entries.values() if v['category']=='control')+store.index.stat().st_size
    if control_used>LIMITS['control']-10000:
        failed_preparation(store,'pre_ws_control_finalization_reserve',3);return
    feed=Feed(markets,clock);stop=asyncio.Event();done=asyncio.Event();samples=[]
    loop=asyncio.get_running_loop()
    def abort():feed.stop('user_stop');stop.set()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,abort)
    receiver=asyncio.create_task(receive(feed,stop,done));economic=False
    try:
        for k in range(SLOTS):
            deadline=t0_mono+k*60*NS
            if not await wait_deadline(deadline,stop):break
            batch=feed.snapshot(k,deadline,utc(),time.monotonic_ns());samples.extend(batch)
            try:
                raw=compressed_samples(samples,normal=True)
                if len(raw)>NORMAL_SAMPLE_LIMIT:raise CapReached('sample_compressed_reserve')
                store.write('samples.jsonl.gz',raw,'samples')
            except CapReached:
                for r in batch:r['ticker']=None;r['reason']='sample_output_cap'
                feed.stop('sample_output_cap');done.set();receiver.cancel()
                store.write('samples.jsonl.gz',compressed_samples(samples),'samples')
        if not stop.is_set():economic=await wait_deadline(t0_mono+DURATION,stop)
    finally:
        done.set();receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)
        for sig in (signal.SIGINT,signal.SIGTERM):loop.remove_signal_handler(sig)
    samples=missing_slots(samples,clock,t0_mono,feed.stop_reason or 'collector_stopped')
    store.write('samples.jsonl.gz',compressed_samples(samples),'samples')
    status='completed' if economic and feed.stop_reason is None else 'incomplete'
    rows=[score(s,next(m for m in markets if m['asset']==s['asset']),b,economic=economic) for s in samples for b in BUDGETS]
    write_rows(store,rows,final=True);summary=summarize(rows,economic)
    summary.update(status=status,metadata_ineligible_assets=[m['asset'] for m in markets if not m['eligible']],feed_counters=dict(feed.counters),stop_reason=feed.stop_reason,
                   sampled_asset_references=sum(r['sample_mono_ns'] is not None for r in samples),planned_asset_references=420)
    store.write('summary.json.gz',gzip.compress(encoded(summary),mtime=0),'derived',final=True);store.write('readout.md',readout(summary,status).encode(),'logs',final=True)
    verify_inputs(freeze['inputs']);prepared(path)
    store.write('manifest.json',{'status':status,'completed_utc_ns':utc(),'economic_endpoint_reached':economic,'metadata_attempts':3,'websocket_attempts':1,
         'input_hashes_unchanged':True,'input_hashes':freeze['inputs'],'output_hashes':{n:v['sha256'] for n,v in store.entries.items()},
         'cap_bytes':CAP,'no_automatic_followup':True,'failure_denominator_rows':1680,'source_study':'new_sampled_public_network_evidence'},'control',final=True)
    store.verify()
    print(json.dumps({'stage':str(path),'status':status,'bytes':store.bytes(),'primary_prerequisites':summary['later_cost_screen_candidates'],'economics_evaluated':economic}))

def dry():
    print(json.dumps({'mode':'dry','network_calls':0,'assets':list(ASSETS),'budgets':BUDGETS,'slots':20,'size_rows':1680,
         'duration_seconds':1200,'metadata_requests_max':3,'ws_connections_max':1,'total_cap_bytes':CAP,'category_caps':LIMITS,'stage_sequence':['prepare','root_review','freeze','run']}))

def main():
    parser=argparse.ArgumentParser(description=__doc__);m=parser.add_mutually_exclusive_group();m.add_argument('--prepare',action='store_true');m.add_argument('--freeze',action='store_true');m.add_argument('--run',action='store_true');parser.add_argument('--stage',type=Path);args=parser.parse_args()
    if not (args.prepare or args.freeze or args.run):dry();return
    if args.stage is None:parser.error('--stage required for explicit stages')
    if args.prepare:asyncio.run(prepare(args.stage))
    elif args.freeze:freeze(args.stage)
    else:asyncio.run(run(args.stage))
if __name__=='__main__':main()
