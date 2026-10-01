"""Frozen $100 Paradex/Core short-term Core/RH paper experiment. Public data, no orders."""
from __future__ import annotations
import asyncio, copy, gzip, hashlib, json, math, statistics, sys, time
import tempfile
from paradex_sbe_preflight import Decoder
from collections import Counter, deque
from decimal import Decimal as D
from pathlib import Path
import aiohttp
from paper_engine import PaperEngine, EngineConfig, key
from paper_streams import StreamManager, WS_URLS
from monitor import walk

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/'reports/experiment-storage/paradex-core-shortterm-allocation-v1.json'
OUT=ROOT/'reports/paradex-core-shortterm'
ASSETS=['BTC','ETH']
IDS={'lighter':{},'paradex':{}}
URLS={'lighter':'https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails',
      'paradex':'https://api.prod.paradex.trade/v1/markets'}

def encode(x):return (json.dumps(x,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class CapError(Exception):pass

class Archive:
    def __init__(self,path,cap):
        self.file=path.open('xb');self.bytes=0;self.count=0;self.cap=cap
        self.written=0;self.pending=b'';self.packed=b'';self.pending_count=0
    def add(self,row):
        candidate=self.pending+encode(row)
        b=gzip.compress(candidate,mtime=0)
        if self.written+len(b)>self.cap:raise CapError('raw_hard_cap')
        self.pending=candidate;self.packed=b;self.pending_count+=1
        self.bytes=self.written+len(b);self.count+=1
        if self.pending_count>=30 or len(candidate)>=32768:self.flush()
    def flush(self):
        if not self.pending:return
        self.file.write(self.packed);self.file.flush();self.written+=len(self.packed)
        self.pending=b'';self.packed=b'';self.pending_count=0;self.bytes=self.written
    def close(self):self.flush();self.file.close()

def fresh(book,now):
    return bool(book and book.get('valid') and book.get('engine_time') is not None
        and 0<=now-book['received']<=2 and 0<=now-book['engine_time']<=2
        and book['engine_time']<=book['received'] and book['bids'] and book['asks']
        and book['bids'][0][0]<book['asks'][0][0])

def pair_fresh(a,b,now):
    return fresh(a,now) and fresh(b,now) and max(abs(a['received']-b['received']),
        abs(a['engine_time']-b['engine_time']))<=.25

def basis_reference(history,now):
    prior=[(t,v) for t,v in history if now-122<=t<=now-2]
    if len(prior)<90 or prior[-1][0]-prior[0][0]<89:return None
    return statistics.median(v for _,v in prior)

def forecast(entry_buy,entry_sell,exit_buy,exit_sell,q,current_basis,expected_basis):
    return entry_sell-entry_buy+exit_buy-exit_sell+q*(current_basis-expected_basis)

class Branch(PaperEngine):
    def __init__(self,pairs,budget,horizon,shared):
        super().__init__(pairs,EngineConfig(notional=budget,capital_usd=6*budget,
            max_positions=1,max_matched_notional=budget,holding_seconds=horizon,
            take_profit_usd=budget/10000,extra_cost_bps=0,capital_rate=.05,
            aster_processing_ms=300,max_skew=.25,signal_interval=.2,evidence_levels=10,
            latency_probes_ms=(),strategies=('standard',)))
        self.label=f'{budget}-{horizon}';self.shared=shared;self.last_entry={}
        self.gates=Counter();self.closes=[];self.retail_requests=deque()
    def retail_allowed(self,now):
        return all(sum(t>now-window for t in self.retail_requests)<limit for window,limit in ((1,3),(60,30),(3600,300),(86400,1000)))
    def _exit_intent(self,pos,leg,now):
        if leg['venue']=='paradex':
            if not self.retail_allowed(now):self.gates['retail_rate_limit']+=1;return
            self.retail_requests.append(now)
        super()._exit_intent(pos,leg,now)
    def _track_signal(self,*args,**kwargs):pass
    def _signal(self,p,buy,sell,bb,sb,strategy,now,quantity=None):
        self.gates['evaluated_directions']+=1
        if not pair_fresh(bb,sb,now):self.gates['clock_or_skew']+=1;return None
        ref=basis_reference(self.shared['history'][p['asset']],now)
        if ref is None:self.gates['warmup']+=1;return None
        s=super()._signal(p,buy,sell,bb,sb,strategy,now,quantity)
        if s is None:self.gates['depth_or_size']+=1;return None
        funding=self.shared['funding'][p['asset']]
        if not funding_recent(funding,now):self.gates['funding_feed_stale']+=1;return None
        q=s['quantity'];c=walk(bb['bids'],q);d=walk(sb['asks'],q)
        if c is None or d is None:self.gates['exit_depth']+=1;return None
        bm=sum(bb[side][0][0] for side in ('bids','asks'))/2
        sm=sum(sb[side][0][0] for side in ('bids','asks'))/2
        core_mid=bm if buy['venue']=='lighter' else sm
        expected=ref*core_mid/10000*(1 if buy['venue']=='lighter' else -1)
        excursion=(sm-bm-expected)/core_mid*10000
        if excursion<5:self.gates['excursion_under_5bp']+=1;return None
        s['favorable_excursion_bps']=excursion
        gross=forecast(s['buy_value'],s['sell_value'],c,d,q,sm-bm,expected)
        fees=(s['buy_value']+c)*s['buy_fee_bps']/10000+(s['sell_value']+d)*s['sell_fee_bps']/10000
        capital=(s['buy_value']+s['sell_value'])*.05*self.config.holding_seconds/(365*86400)
        hurdle=max(s['buy_value'],s['sell_value'])/10000
        s.update(historical_basis_bps=ref,forecast_gross=gross,forecast_cash=gross-fees,
            forecast_capital=capital,forecast_hurdle=hurdle,net_edge_usd=gross-fees-capital-hurdle,
            net_edge_bps=(gross-fees-capital-hurdle)/s['buy_value']*10000)
        f=funding[-1];expected_funding=(-1 if buy['venue']=='paradex' else 1)*q*f['premium']*self.config.holding_seconds/(f['period_hours']*3600)
        s['forecast_funding_estimated']=expected_funding;s['funding_reference']=f
        s['net_edge_usd']+=expected_funding;s['net_edge_bps']=s['net_edge_usd']/s['buy_value']*10000
        self.gates['forecast_pass' if s['net_edge_usd']>0 else 'forecast_fail']+=1
        return s
    def _maybe_enter(self,pair,ident,s,strategy,now):
        reason=None
        if not self.shared['admissions']:reason='admissions_closed'
        elif not self.retail_allowed(now):reason='retail_rate_limit'
        elif not funding_recent(self.shared['funding'][pair['asset']],now):reason='funding_feed_stale'
        elif now-self.shared['start']<122:reason='warmup_clock'
        elif now-self.shared['start']>=700:reason='entry_window_ended'
        elif self.sequence>=30:reason='attempt_cap'
        elif now-self.last_entry.get(ident,0)<30:reason='cooldown'
        elif math.floor(now/3600)!=math.floor((now+120)/3600):reason='funding_boundary_guard'
        if reason:self.gates[reason]+=1;return
        before=self.sequence
        super()._maybe_enter(pair,ident,s,strategy,now)
        if self.sequence>before:
            self.last_entry[ident]=now
            self.retail_requests.append(now)
            self.shared['archive'].add({'kind':'admission','branch':self.label,'signal':s,
                'history':list(self.shared['history'][pair['asset']]),
                'books':[self._book_evidence(self.books[k]) for k in (s['buy'],s['sell'])]})

def normalise(data,venue,now):
    if venue=='paradex':return normalise_paradex(data,now)
    assert data['code']==200
    rows={r['symbol']:r for r in data['order_book_details']}
    IDS[venue]={a:int(rows[a]['market_id']) for a in ASSETS if a in rows}
    out={}
    for asset,mid in IDS[venue].items():
        r=rows[asset]
        assert r['symbol']==asset and r['status']=='active' and r['market_type']=='perp'
        assert D(str(r['multiplier']))==1 and D(str(r['quote_multiplier']))==1
        assert D(str(r['maker_fee']))==0 and D(str(r['taker_fee']))==0
        sd=r['supported_size_decimals'];pd=r['supported_price_decimals']
        assert r['size_decimals']==sd and r['price_decimals']==pd and 0<=sd<=12 and 0<=pd<=12
        out[asset]={'venue':venue,'market':mid,'asset':asset,'step':str(D(10)**-sd),
            'price_tick':str(D(10)**-pd),'min_qty':float(r['min_base_amount']),
            'min_notional':float(r['min_quote_amount']),'max_quote':float(r['order_quote_limit']),
            'fee_bps':0,'published_fee_floor_bps':0,'collateral':'USDC',
            'metadata_timestamp':now,'maximum_base_quantity_unknown':True}
    return out

async def receive(session,manager,venue,markets,stop,counters):
    if venue=='paradex':return await receive_paradex(session,manager,markets,stop,counters)
    for attempt in range(3):
        if stop.is_set():break
        generation=f'{venue}:{attempt+1}'
        counters[f'{venue}_connections']+=1
        try:
            async with session.ws_connect(WS_URLS[venue],heartbeat=30,max_msg_size=4*1024*1024) as ws:
                for m in markets:
                    await ws.send_json({'type':'subscribe','channel':f"order_book/{m['market']}"})
                ping=time.monotonic()
                while not stop.is_set():
                    if time.monotonic()-ping>=25:
                        await ws.send_json({'type':'ping'});ping=time.monotonic()
                    try:frame=await ws.receive(timeout=1)
                    except asyncio.TimeoutError:continue
                    if frame.type in (aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR):break
                    if frame.type!=aiohttp.WSMsgType.TEXT:continue
                    counters['ingress_bytes']+=len(frame.data.encode())
                    counters['messages']+=1
                    if counters['ingress_bytes']>128_000_000 or counters['messages']>250_000:
                        counters['ingress_cap']+=1;stop.set();break
                    data=json.loads(frame.data)
                    if data.get('type')=='ping':await ws.send_json({'type':'pong'})
                    else:manager.process_message(venue,data,generation)
                    for k in list(manager.resubscribe):
                        if k[0]!=venue:continue
                        manager.resubscribe.remove(k)
                        await ws.send_json({'type':'unsubscribe','channel':f'order_book/{k[1]}'})
                        await ws.send_json({'type':'subscribe','channel':f'order_book/{k[1]}'})
                        counters['resubscriptions']+=1
        except (aiohttp.ClientError,asyncio.TimeoutError,OSError,ValueError) as exc:
            counters[f'{venue}_errors']+=1
            counters[f'error_{type(exc).__name__}']+=1
        finally:
            for m in markets:manager._invalidate((venue,str(m['market'])),'disconnected',generation)
        if not stop.is_set():await asyncio.sleep(1)
    if not stop.is_set():counters[f'{venue}_exhausted']=1;stop.set()

def normalise_paradex(data,now):
    rows={r['symbol']:r for r in data['results']};out={}
    for asset in ASSETS:
        symbol=asset+'-USD-PERP';r=rows[symbol]
        assert r['base_currency']==asset and r['quote_currency']=='USD' and r['settlement_currency']=='USDC'
        assert r['asset_kind']=='PERP' and r['expiry_at']==0 and r['trading_mode']=='STANDARD'
        assert D(r['fee_config']['interactive_fee']['taker_fee']['fee'])==0
        assert D(r['max_order_size'])>0 and D(r['order_size_increment'])>0 and D(r['price_tick_size'])>0
        IDS['paradex'][asset]=symbol
        out[asset]={'venue':'paradex','market':symbol,'asset':asset,'step':r['order_size_increment'],
            'price_tick':r['price_tick_size'],'min_qty':float(r['order_size_increment']),
            'min_notional':float(r['min_notional']),'max_qty':float(r['max_order_size']),
            'fee_bps':0,'collateral':'USDC','metadata_timestamp':now,
            'fee_condition':'Interactive retail JWT eligibility assumed; no authentication performed; ordinary API fee not zero',
            'continuous_funding':True,'funding_period_hours':r['funding_period_hours']}
    return out

def funding_recent(rows,now):
    return bool(rows and 0<=now-rows[-1]['created']<=7 and 0<=now-rows[-1]['received']<=7)

def interpolate_index(rows,t):
    before=[r for r in rows if r['created']<=t];after=[r for r in rows if r['created']>=t]
    if not before or not after:return None
    a=before[-1];b=after[0];gap=b['created']-a['created']
    if not 0<=gap<=6:return None
    value=a['index'] if gap==0 else a['index']+(b['index']-a['index'])*(t-a['created'])/gap
    return {'timestamp':t,'index':value,'before':a,'after':b,'method':'linear interpolation of public5s observations; estimated'}

def funding_settlement(pos,rows,now):
    events=[];cash=0.
    for leg in pos['legs']:
        if not leg['quantity']:continue
        if leg['venue']=='lighter':
            if any(math.floor(leg['entry_time']/3600)!=math.floor(f['timestamp']/3600) for f in leg['exit_fills']):return None
            continue
        entry=interpolate_index(rows,leg['entry_time'])
        if not entry:return None
        for fill in leg['exit_fills']:
            end=interpolate_index(rows,fill['timestamp'])
            if not end:return None
            amount=-fill['quantity']*(1 if leg['side']=='long' else -1)*(end['index']-entry['index'])
            cash+=amount;events.append({'venue':'paradex','cashflow_usd':amount,'quantity':fill['quantity'],'side':leg['side'],'entry':entry,'exit':end})
    return {'complete':True,'cashflow_usd':cash,'estimated':True,'events':events,
        'reason':'Core intervals avoid hourly settlement; Paradex public5second index interpolated to modeled fills. Funding is estimated, not exact account settlement.'}

async def receive_paradex(session,manager,markets,stop,counters):
    schema=ROOT/'reports/paradex-sbe-preflight/schema.xml.gz'
    decoder=Decoder(gzip.decompress(schema.read_bytes()));shared=manager.paradex_shared
    for attempt in range(3):
        if stop.is_set():break
        generation=f'paradex:{attempt+1}';counters['paradex_connections']+=1;last={}
        try:
            async with session.ws_connect('wss://ws-public.api.prod.paradex.trade/v1?sbeSchemaId=1&sbeSchemaVersion=1',heartbeat=25,max_msg_size=262144) as ws:
                channels=[c for m in markets for c in (f"order_book.{m['market']}.snapshot@15@100ms",f"funding_data.{m['market']}")]
                for i,channel in enumerate(channels):await ws.send_json({'jsonrpc':'2.0','id':i+1,'method':'subscribe','params':{'channel':channel}})
                while not stop.is_set():
                    try:msg=await ws.receive(timeout=1)
                    except asyncio.TimeoutError:continue
                    now=time.time()
                    if msg.type in (aiohttp.WSMsgType.CLOSE,aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR):break
                    if msg.type==aiohttp.WSMsgType.TEXT:
                        data=json.loads(msg.data)
                        if data.get('error'):raise ValueError('subscription_error:'+str(data['error']))
                        continue
                    if msg.type!=aiohttp.WSMsgType.BINARY:continue
                    counters['ingress_bytes']+=len(msg.data);counters['messages']+=1
                    if counters['ingress_bytes']>128_000_000 or counters['messages']>250_000:stop.set();counters['ingress_cap']+=1;break
                    d=decoder.decode(msg.data)
                    if d.get('unsupported'):counters['unsupported_sbe']+=1;continue
                    symbol=d['market'];asset=symbol.split('-')[0];assert asset in ASSETS
                    source=d['ts']/1e6;label=(d['template'],symbol)
                    assert d['seq']>=last.get(label,-1) and source<=now
                    last[label]=d['seq']
                    if d['template']==5:
                        created=d['createdAt']/1e6;assert created<=source
                        row={'created':created,'published':source,'received':now,'index':d['fundingIndex'],'premium':d['fundingPremium'],'period_hours':d['fundingPeriodHours'],'sequence':d['seq'],'generation':generation}
                        history=shared['funding'][asset]
                        if history and created==history[-1]['created']:
                            assert row['index']==history[-1]['index'];continue
                        assert not history or created>history[-1]['created']
                        history.append(row);shared['archive'].add({'kind':'funding_index','asset':asset,'data':row});continue
                    assert d['template']==3 and d['pkgType']==0
                    bids=[(x['price'],x['size']) for x in d['bids']];asks=[(x['price'],x['size']) for x in d['asks']]
                    valid=bool(bids and asks and bids[0][0]<asks[0][0] and all(p>0 and q>0 for p,q in bids+asks) and all(bids[i][0]>bids[i+1][0] for i in range(len(bids)-1)) and all(asks[i][0]<asks[i+1][0] for i in range(len(asks)-1)))
                    manager.paradex_callback({'venue':'paradex','market':symbol,'received':now,'engine_time':source,'valid':valid,'generation':generation,'sequence':d['seq'],'bids':bids[:10],'asks':asks[:10],'timestamp_semantics':'published SBE ts'})
        except (aiohttp.ClientError,asyncio.TimeoutError,OSError,ValueError,AssertionError) as exc:
            counters['paradex_errors']+=1;counters['error_'+type(exc).__name__]+=1
            shared['archive'].add({'kind':'transport_error','venue':'paradex','error':type(exc).__name__+':'+str(exc),'t':time.time()})
        finally:
            for m in markets:
                manager.paradex_callback({'venue':'paradex','market':m['market'],'received':time.time(),'engine_time':None,'valid':False,'generation':generation,'sequence':None,'bids':[],'asks':[],'reason':'disconnected'})
        if not stop.is_set():await asyncio.sleep(1)
    if not stop.is_set():counters['paradex_exhausted']=1;stop.set()

async def run():
    plan=json.loads(PLAN.read_bytes())
    for pin in plan['source_pins']:assert sha(ROOT/pin['path'])==pin['sha256']
    OUT.mkdir(exist_ok=False)
    archive=Archive(OUT/'events.jsonl.gz',plan['categories_bytes']['raw'])
    shared={'start':None,'admissions':True,'archive':archive,'history':{a:deque(maxlen=125) for a in ASSETS},'funding':{a:deque(maxlen=240) for a in ASSETS}}
    counters=Counter();branches=[];tasks=[];metadata=[];stop=asyncio.Event();error=None
    timeout=aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout,headers={'User-Agent':'rhhype-paper-research/1.0'}) as session:
            normalized={};meta_bytes=0
            for venue,url in URLS.items():
                began=time.time()
                async with session.get(url) as response:
                    response.raise_for_status();body=await response.read()
                    assert len(body)<=2_000_000
                packed=gzip.compress(body,mtime=0);meta_bytes+=len(packed)
                assert meta_bytes<=plan['categories_bytes']['metadata']
                path=OUT/f'{venue}-metadata.json.gz';path.write_bytes(packed)
                metadata.append({'venue':venue,'url':url,'started':began,'received':time.time(),'sha256':sha(path),'bytes':len(packed)})
                normalized[venue]=normalise(json.loads(body),venue,time.time())
            pairs=[{'asset':a,'hl':normalized['lighter'][a],'other':normalized['paradex'][a],'metadata_timestamp':time.time()} for a in ASSETS if a in normalized['lighter'] and a in normalized['paradex']]
            assert pairs, 'no_matching_crypto_markets'
            shared['selection']={'included':[p['asset'] for p in pairs], 'missing':[a for a in ASSETS if a not in {p['asset'] for p in pairs}]}
            markets=[m for p in pairs for m in (p['hl'],p['other'])]
            rules={key(m):m for m in markets};watermarks={}
            (OUT/'metadata.json').write_bytes(encode({'requests':metadata,'pairs':pairs,'selection':shared['selection']}))
            shared['start']=time.time();start_mono=time.monotonic()
            branches=[Branch(pairs,b,h,shared) for b in plan['budgets'] for h in plan['horizons']]
            def on_book(book):
                k=f"{book['venue']}:{book['market']}";now=book['received']
                source=book.get('engine_time');reason=None
                if book.get('valid'):
                    if source is None or source>now or source<watermarks.get(k,0):reason='source_clock'
                    elif any(abs(D(str(px))/D(rules[k]['price_tick'])-round(D(str(px))/D(rules[k]['price_tick'])))>D('0.000001') for side in ('bids','asks') for px,_ in book[side]):reason='price_grid'
                    else:watermarks[k]=source
                if reason:book=book|{'valid':False,'reason':reason,'bids':[],'asks':[]}
                if not book.get('valid'):
                    counters['invalidations']+=1
                    archive.add({'kind':'invalid','book':book})
                    for asset in IDS[book['venue']]:
                        if str(IDS[book['venue']][asset])==str(book['market']):shared['history'][asset].clear()
                interested=[branch.label for branch in branches if any(leg['key']==k and (leg.get('intent') or (pos['status']=='EXITING' and leg['remaining']>0)) for pos in branch.positions.values() for leg in pos['legs'])]
                if interested:archive.add({'kind':'candidate_book','branches':interested,'book':book})
                for branch in branches:branch.receive(book)
            manager=StreamManager(session,markets,on_book,lambda *args:None,max_levels=10)
            manager.paradex_callback=on_book;manager.paradex_shared=shared
            tasks=[asyncio.create_task(receive(session,manager,v,[m for m in markets if m['venue']==v],stop,counters)) for v in URLS]
            next_sample=0
            while not stop.is_set() and time.monotonic()-start_mono<900:
                now=time.time();elapsed=time.monotonic()-start_mono
                for task in tasks:
                    if task.done() and not task.cancelled() and task.exception() is not None:
                        raise task.exception()
                if abs(now-shared['start']-elapsed)>.25:raise ValueError('wall_monotonic_clock_shift')
                if archive.bytes>=plan['raw_soft_cap']:shared['admissions']=False
                if elapsed>=next_sample:
                    slot=next_sample;next_sample=math.floor(elapsed)+1
                    for p in pairs:
                        a,b=(branches[0].books.get(key(p[v])) for v in ('hl','other'))
                        good=elapsed-slot<=.25 and pair_fresh(a,b,now)
                        row={'kind':'sample','slot':slot,'t':now,'asset':p['asset'],'valid':good}
                        if good:
                            am=(a['bids'][0][0]+a['asks'][0][0])/2;bm=(b['bids'][0][0]+b['asks'][0][0])/2
                            basis=(bm/am-1)*10000;shared['history'][p['asset']].append((now,basis))
                            row.update(basis_bps=basis,books=[{k:x.get(k) for k in ('received','engine_time','sequence','generation')}|{'bids':x['bids'][:1],'asks':x['asks'][:1]} for x in (a,b)])
                        archive.add(row)
                for branch in branches:
                    branch.tick(now)
                    for pos in branch.funding_due():
                        settlement=funding_settlement(pos,shared['funding'][pos['asset']],now)
                        if settlement:branch.settle_funding(pos['id'],settlement,now)
                    for _,payload,kind,t in branch.evidence:
                        archive.add({'kind':kind,'branch':branch.label,'t':t,'data':payload})
                    branch.evidence.clear();branch.signals.clear()
                    for row in branch.transitions:
                        if row['status'] in ('CLOSED','CLOSED_ESTIMATED','ABORTED'):
                            archive.add({'kind':'terminal_position','branch':branch.label,'data':row})
                            branch.closes.append(row)
                    branch.transitions.clear();branch.finished.clear()
                if int(elapsed)%30==0:
                    status={'elapsed':elapsed,'raw_bytes':archive.bytes,'branches':{b.label:{'attempts':b.sequence,'open':len(b.positions),'closed':len(b.closes)} for b in branches},'counters':dict(counters)}
                    (OUT/'status.json').write_bytes(encode(status))
                await asyncio.sleep(.05)
            shared['admissions']=False
            counters['runtime_completed']=int(time.monotonic()-start_mono>=900)
    except Exception as exc:error=type(exc).__name__+':'+str(exc)
    finally:
        stop.set()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        archive.close()
        summary={'error':error,'started_at':shared['start'],'ended_at':time.time(),'actual_pnl':None,
            'paper_model_only':True,'funding_interpolation_estimated':True,'Paradex_retail_fee_eligibility_conditional':True,'raw_bytes':archive.bytes,'records':archive.count,
            'raw_sha256':sha(OUT/'events.jsonl.gz'),'source_sha256':sha(__file__),'plan_sha256':sha(PLAN),
            'metadata':metadata,'selection':shared.get('selection'),'counters':dict(counters),'branches':[]}
        pending={b.label:list(b.positions.values()) for b in branches}
        pending_bytes=gzip.compress(encode(pending),mtime=0)
        assert len(pending_bytes)<=32768
        (OUT/'unresolved.json.gz').write_bytes(pending_bytes)
        summary['unresolved_sha256']=sha(OUT/'unresolved.json.gz')
        for b in branches:
            closed=[r for r in b.closes if r['status'] in ('CLOSED','CLOSED_ESTIMATED')]
            cash=[r['price_pnl']-r['fees_usd']+r['funding_usd'] for r in closed]
            stressed=[c-r['capital_costs_usd']-.0005*max(l['entry_value'] for l in r['legs']) for c,r in zip(cash,closed)]
            summary['branches'].append({'branch':b.label,'attempts':b.sequence,'closed':len(closed),
                'aborted':sum(r['status']=='ABORTED' for r in b.closes),'cash_pnl':sum(cash),'cash_wins':sum(c>0 for c in cash),'funding_estimated_closes':sum(r['status']=='CLOSED_ESTIMATED' for r in closed),'funding_sum':sum(r['funding_usd'] for r in closed),
                'after_capital_and_stress':sum(stressed),'stressed_wins':sum(v>0 for v in stressed),
                'paired_closes':sum(r.get('exit_reason')!='entry_failure' for r in closed),
                'rescue_closes':sum(r.get('exit_reason')=='entry_failure' for r in closed),
                'below_public_exit_minimum_cases':sum(any(fill['quantity']<leg['min_qty'] or fill['value']<leg['min_notional']
                    for leg in r['legs'] for fill in leg['exit_fills']) for r in closed),
                'unresolved':[{'id':p['id'],'status':p['status'],'asset':p['asset'],
                    'legs':[{'venue':l['venue'],'remaining':l['remaining'],'quantity':l['quantity']} for l in p['legs']]} for p in b.positions.values()],
                'gates':dict(b.gates),'stats':dict(b.stats),'ledger':b.ledgers,'retail_request_times':list(b.retail_requests)})
        out=encode(summary)
        assert len(out)+len(pending_bytes)<=plan['categories_bytes']['output']-8192
        (OUT/'summary.json').write_bytes(out)
        print(json.dumps({k:summary[k] for k in ('error','raw_bytes','records','counters')}),flush=True)
        for b in summary['branches']:print(b['branch'],b['attempts'],b['closed'],b['cash_pnl'],b['after_capital_and_stress'],flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['run']:asyncio.run(run())
    else:print(PLAN.read_text())
