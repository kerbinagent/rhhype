#!/usr/bin/env python3
"""Bounded post-capture Core/RH paired quotes; default plan does no raw I/O."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
from decimal import Decimal, localcontext
from fractions import Fraction
import gzip
import hashlib
import heapq
import importlib.metadata
import itertools
import json
import math
from pathlib import Path
import statistics
import signal
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0, str(ROOT))
from scripts.maker_book_archive import BookRebuilder, selected_markets

NS = 1_000_000_000
AGE, SKEW, DELAY = 2*NS, NS, NS//2
DURATION, WALL = 420*NS, 900
SCHEMA = 'core-rh-delayed-taker-quote-diagnostic-v1'
VENUES = ('rh_lighter', 'lighter')
ASSETS = ('BTC', 'ETH', 'NVDA', 'XAG')
IDS = {'rh_lighter':dict(BTC='1', ETH='0', NVDA='15', XAG='41'),
       'lighter':dict(BTC='1', ETH='0', NVDA='110', XAG='93')}
METHOD = ROOT/'research/core-rh-delayed-taker-quote-plan.md'
TESTS = ROOT/'tests/test_analyze_core_rh_delayed_taker.py'
OUTPUT_PARENT = ROOT/'reports/core-rh-delayed-taker'
CAP = 600_000
LIMITS = dict(source=190_000, rows=250_000, summary=30_000,
              provenance=60_000, failure=30_000)
# Ten thousand source bytes and twenty thousand summary/audit bytes remain
# reserved for root approval notes and future independent derived verification.
EXTERNAL_RESERVE = 40_000
SOURCES = {
 'scripts/maker_book_archive.py':'8c9b86a8024298b78f6a6890cb2ad97a267dacd357ee992432a52f9a9c756dd2',
 'scripts/paper_streams.py':'c601270e365cc11ce04124095650a4bc79ceaffa8d4792bdd83cf7d9382a3734',
 'scripts/maker_capture.py':'a4930f7a672ca668e9286eb2d270bc246cf7d672c44415b1a33d54532e0fd9b9',
 'scripts/analyze_maker_equity.py':'85d4de8cfd523b4a4497e3e2f6411b05f3737f2133d4c167ddce708af363843f',
 'scripts/analyze_maker_capture.py':'d87ce8f116e039976b7afac20ede5704d14b3d49eb626473d214a7d47811b359',
 'scripts/analyze_maker_roundtrip.py':'d7d23b255fcffc294069a77486cc944a9a64a32d6755cc515a960d1ae03a9c93'}
SMALL_PINS = {
 'data/raw/maker-capture/20260929T1939Z/manifest.json':'163f2ea666025b5661becb51fbe27a5050df3e8564d37aa2159143db87e5e351',
 'data/raw/maker-capture/20260929T2022Z/manifest.json':'a3f83c319f5e71938ffa9ae6ec170eb48b3024123147e554ee4c20296cade898',
 'reports/maker-roundtrip-v1/market-plan.json':'e4f059ae0fc9b3957779b42c5b35a04aa42fc220f2a74fb76a68d3669f06e2fe',
 'reports/maker-roundtrip-v1/market-plan-provenance.json':'62bfe2f5139782ed9b83c84b94c985e36859ef293575abfa04f0d5d4b599157b',
 'reports/maker-roundtrip-v1/frozen-method-manifest.json':'2dc9709c5fae1af2c8fad650102fc8c2e3212bc8240ef2c0261c616fc5fecd00',
 'reports/maker-equity-v2/market-plan.json':'8764b8c656ab1ebf6772eedfb22ab541eef28b81c9fa116056fea67366e5c93f',
 'reports/maker-equity-v2/unit-provenance.json':'dd2fd61f18e7ae6558ec6dd4f7fa0e618e71da3eaa8610635a69971879470094',
 'reports/maker-equity-v2/frozen-manifest.json':'fcffad0124a2679afd2e2e73c6aa28390ebe3b46ddbeccb69b1fd17f284da3f0'}
EXPECTED = (
 dict(name='1939Z', directory=ROOT/'data/raw/maker-capture/20260929T1939Z',
      start=1790710744105998000, assets=('BTC','ETH'), records=64081, bytes=23644715,
      raw_sha='5f6ade0523703efe0ecd40c17ead0782eccc3bf7f780ae17364d8c26fc56567d'),
 dict(name='2022Z', directory=ROOT/'data/raw/maker-capture/20260929T2022Z',
      start=1790713376780854000, assets=('NVDA','XAG'), records=10619, bytes=3755149,
      raw_sha='3a1ffe9e3578899df800bf8fceec7beda8fc82b136a6c00edc64a20a8316f775'))


def rat(value):
    return value if isinstance(value, Fraction) else Fraction(str(value))


def text_number(value):
    value = rat(value)
    divisor = value.denominator
    for prime in (2,5):
        while divisor % prime == 0:
            divisor //= prime
    if divisor != 1:
        return f'{value.numerator}/{value.denominator}'
    with localcontext() as ctx:
        ctx.prec = 128
        result = format(Decimal(value.numerator)/Decimal(value.denominator), 'f')
    return result.rstrip('0').rstrip('.') if '.' in result else result


def epoch(value):
    delta = dt.datetime.fromisoformat(value)-dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)
    return (delta.days*86400+delta.seconds)*NS+delta.microseconds*1000


def grid(specs=EXPECTED):
    for spec in specs:
        for offset in range(0,420,5):
            for asset in spec['assets']:
                for budget in (100,250,500,1000):
                    if budget != 1000 and offset % 30:
                        continue
                    for long in VENUES:
                        yield dict(id=f"{spec['name']}:{asset}:{long}:{budget}:{offset}",
                            archive=spec['name'], asset=asset, long_venue=long,
                            budget=budget, anchor_ns=spec['start']+offset*NS,
                            stratum=offset//105, status='not_evaluated_archive_abort',funding_unknown=True,
                            funding_inclusive_net=None,legality_unknown=True,
                            rule_spec_refs={v:f"{spec['name']}:{v}:{asset}" for v in VENUES})


def decimal(value):
    literal = str(value)
    if isinstance(value,bool) or len(literal)>64:
        raise ValueError('numeric_token_bound')
    try:x = Decimal(literal)
    except ArithmeticError as exc:raise ValueError('numeric_token_schema') from exc
    if (not x.is_finite() or x.copy_abs()>10**12 or len(x.as_tuple().digits)>32 or
        abs(x.as_tuple().exponent)>18):
        raise ValueError('numeric_token_bound')
    return x


def economics(a,b,c,d,long_rate,short_rate,elapsed):
    a,b,c,d = map(rat,(a,b,c,d))
    lr,sr = rat(long_rate)/10000,rat(short_rate)/10000
    fees = (a*lr,b*sr,c*lr,d*sr)
    gross = b-a+c-d
    stress = max(a,b)/2000
    capital = (a+b)*Fraction(5,100)*elapsed/(365*86400*NS)
    return dict(zip(('gross','entry_long_fee','entry_short_fee','exit_long_fee',
        'exit_short_fee','fee_only_net','stress','capital','adjusted_quote_net_ex_funding'),
        map(text_number,(gross,*fees,gross-sum(fees),stress,capital,
                         gross-sum(fees)-stress-capital))))


class QuoteEngine:
    def __init__(self, markets, rows, end_ns):
        self.markets, self.rows, self.end_ns = markets,rows,end_ns
        if len(rows)>1008 or len({r['id'] for r in rows})!=len(rows):
            raise ValueError('candidate_bound_or_identity')
        self.by_id = {r['id']:r for r in rows}
        self.books, self.last_source, self.generation = {},{},{}
        self.timers, self.serial = [],itertools.count()
        self.timer_counts=Counter()
        self.active = {'entry':defaultdict(set),'exit':defaultdict(set)}
        self.pending, self.now, self.finished = set(),None,False
        self.changed=set();self.receipt=None
        for row in rows:
            self.schedule(row['anchor_ns'],'anchor',row['id'])

    def schedule(self,when,kind,identity):
        category='anchor' if kind=='anchor' else 'stage'
        self.timer_counts[category]+=1
        if self.timer_counts[category]>(1008 if category=='anchor' else 2016):
            raise ValueError('separate_timer_bound')
        heapq.heappush(self.timers,(when,next(self.serial),kind,identity))
        if len(self.timers)>3024:
            raise ValueError('timer_bound')

    def pop_timer(self):
        item=heapq.heappop(self.timers)
        self.timer_counts['anchor' if item[2]=='anchor' else 'stage']-=1
        return item

    def finish_row(self,row,status):
        row['status']=status
        self.pending.discard(row['id'])
        for stage in self.active.values():
            stage[row['asset']].discard(row['id'])

    def invalidate(self,venue,asset,reason):
        self.books.pop((venue,asset),None)
        for identity in tuple(self.pending):
            row=self.by_id[identity]
            if row['asset']==asset:
                self.finish_row(row,('exit' if 'entry_ns' in row else 'entry')+'_gap:'+reason)

    def reference(self,asset):
        return {v:{k:self.books[v,asset][k] for k in
                   ('source_ns','receipt_ns','generation','sequence')} for v in VENUES}

    def pair_reason(self,row,now,baseline=None,due=None):
        pair=[self.books.get((v,row['asset'])) for v in VENUES]
        if any(b is None for b in pair): return 'missing_book'
        if any(not 0<=now-b[k]<=AGE for b in pair for k in ('receipt_ns','source_ns')):
            return 'stale_source_or_receipt'
        if any(abs(pair[0][k]-pair[1][k])>SKEW for k in ('receipt_ns','source_ns')):
            return 'cross_venue_skew'
        if baseline:
            for venue,book in zip(VENUES,pair):
                if book['generation']!=baseline[venue]['generation']: return 'generation_change'
                if any(book[k]<due or book[k]<=baseline[venue][k] for k in ('receipt_ns','source_ns')):
                    return 'not_advanced_or_before_due'
        return None

    def legs(self,row,entry,stage):
        long=row['long_venue']; short=next(v for v in VENUES if v!=long)
        q=rat(row['quantity']); values=[]; rules={}
        for venue in (long,short):
            meta=self.markets[venue][row['asset']];book=self.books[venue,row['asset']]
            rules[venue]={'price_grid':book['price_grid'],
                'quantity_grid':('known_fail' if book['quantity_grid']=='known_fail' or
                    (q/rat(meta['size_step'])).denominator!=1 else 'known_pass'),
                'minimum_quantity':'known_pass' if q>=rat(meta['min_qty']) else 'known_fail',
                'minimum_notional':'unknown','maximum_quote':'unknown','maximum_base':'unknown'}
        row[stage+'_rules']=rules
        for venue,side in ((long,'asks' if entry else 'bids'),(short,'bids' if entry else 'asks')):
            meta=self.markets[venue][row['asset']]; book=self.books[venue,row['asset']]
            checks=rules[venue]
            if 'known_fail' in checks.values(): raise ValueError('known_rule_violation')
            remain=q; value=Fraction(0)
            for price,size in book[side]:
                take=min(remain,rat(size)); value+=take*rat(price); remain-=take
                if not remain: break
            if remain: raise ValueError('depth')
            checks['minimum_notional']='known_pass' if value>=rat(meta['min_notional']) else 'known_fail'
            checks['maximum_quote']=('unknown' if meta['max_quote'] is None else
                'known_pass' if value<=rat(meta['max_quote']) else 'known_fail')
            if 'known_fail' in checks.values(): raise ValueError('known_rule_violation')
            values.append(value)
        return values

    def anchor(self,row,now):
        reason=self.pair_reason(row,now)
        if reason: return self.finish_row(row,'anchor_'+reason)
        steps=[rat(self.markets[v][row['asset']]['size_step']) for v in VENUES]
        divisor=math.lcm(*(s.denominator for s in steps))
        step=Fraction(math.lcm(*(int(s*divisor) for s in steps)),divisor)
        ask=rat(self.books[row['long_venue'],row['asset']]['asks'][0][0])
        q=(rat(row['budget'])/ask/step).__floor__()*step
        row.update(quantity=text_number(q),anchor_long_best_ask=text_number(ask),
            common_lot=text_number(step),anchor_refs=self.reference(row['asset']),
            rule_spec_refs={v:f"{row['archive']}:{v}:{row['asset']}" for v in VENUES})
        if q<=0: return self.finish_row(row,'anchor_quantity')
        try: a,b=self.legs(row,True,'anchor')
        except ValueError as exc: return self.finish_row(row,'anchor_'+str(exc))
        row.update(status='entry_pending',
            anchor_long_buy=text_number(a),anchor_short_sell=text_number(b),
            anchor_notional_exceeds_budget=a>row['budget'])
        self.pending.add(row['id'])
        if len(self.pending)>1008:raise ValueError('pending_candidate_bound')
        self.schedule(now+DELAY,'entry_due',row['id']);self.schedule(now+2*NS,'entry_deadline',row['id'])

    def attempt(self,row,stage,now):
        base=row['anchor_refs'] if stage=='entry' else row['entry_refs']
        request=row['anchor_ns'] if stage=='entry' else row['entry_ns']+10*NS
        if self.pair_reason(row,now,base,request+DELAY): return
        row[stage+'_refs']=self.reference(row['asset'])
        row[stage+'_selected_ns']=now
        try: a,b=self.legs(row,stage=='entry',stage)
        except ValueError as exc: return self.finish_row(row,stage+'_'+str(exc))
        if stage=='entry':
            row.update(status='exit_pending',entry_ns=now,entry_long_buy=text_number(a),
                entry_short_sell=text_number(b),entry_notional_exceeds_budget=a>row['budget'],
                entry_drift_from_anchor_walk=text_number(a-rat(row['anchor_long_buy'])))
            self.active['entry'][row['asset']].discard(row['id'])
            self.schedule(now+10*NS+DELAY,'exit_due',row['id'])
            self.schedule(now+12*NS,'exit_deadline',row['id'])
        else:
            long=row['long_venue'];short=next(v for v in VENUES if v!=long)
            row.update(exit_ns=now,exit_long_sell=text_number(a),exit_short_buy=text_number(b),
                **economics(row['entry_long_buy'],row['entry_short_sell'],a,b,
                    self.markets[long][row['asset']]['taker_fee_bps'],
                    self.markets[short][row['asset']]['taker_fee_bps'],now-row['entry_ns']),
                funding_unknown=True,funding_inclusive_net=None,legality_unknown=True,
                utc_hour_boundary_crossed=row['entry_ns']//(3600*NS)!=now//(3600*NS),
                funding_boundary_tie=row['entry_ns']%(3600*NS)==0 or now%(3600*NS)==0)
            self.finish_row(row,'conditional_quote_complete')

    def ingest(self,events):
        for event in events:
            venue,asset=event['venue'],event['asset'];self.changed.add(asset)
            key=(venue,asset)
            if event['type']=='invalidate':
                self.invalidate(venue,asset,event['reason']);continue
            source=event['source_ns'];generation=event['generation']
            if key in self.generation and self.generation[key]!=generation:
                self.invalidate(venue,asset,'generation_change');self.last_source.pop(key,None)
            if key in self.last_source and source<self.last_source[key]:
                self.invalidate(venue,asset,'source_regression');continue
            if not 0<source<=event['receipt_ns']:
                self.invalidate(venue,asset,'invalid_source_or_clock');continue
            self.books[key]=event;self.last_source[key]=source;self.generation[key]=generation

    def at(self,now,events=()):
        self.ingest(events)
        changed=self.changed;self.changed=set()
        deadlines=[]
        while self.timers and self.timers[0][0]==now:
            _,_,kind,identity=self.pop_timer();row=self.by_id[identity]
            if kind=='anchor': self.anchor(row,now)
            elif kind.endswith('_due'):
                stage=kind[:-4]
                if row['status']==('entry_pending' if stage=='entry' else 'exit_pending'):
                    self.active[stage][row['asset']].add(identity);changed.add(row['asset'])
            else: deadlines.append((kind,row))
        for asset in changed:
            for stage in ('entry','exit'):
                for identity in sorted(self.active[stage][asset]):
                    self.attempt(self.by_id[identity],stage,now)
        for kind,row in deadlines:
            stage=kind.split('_')[0]
            if row['status']==('entry_pending' if stage=='entry' else 'exit_pending'):
                self.finish_row(row,stage+'_missing')
        self.now=now

    def record(self,now,events):
        """Apply each record immediately; retain only changed asset identities."""
        if self.receipt is not None and now<self.receipt:raise ValueError('backward_batch')
        if self.receipt!=now:
            if self.receipt is not None:self.batch(self.receipt,())
            if not self.finished:
                while self.timers and self.timers[0][0]<min(now,self.end_ns):self.at(self.timers[0][0])
                if now>self.end_ns:self.finish()
            self.receipt=now
        if not self.finished:self.ingest(events)

    def batch(self,now,events):
        if self.now is not None and now<self.now: raise ValueError('backward_batch')
        if self.finished: return
        while self.timers and self.timers[0][0]<min(now,self.end_ns): self.at(self.timers[0][0])
        if now>self.end_ns: self.finish();return
        self.at(now,events)
        if now==self.end_ns: self.finish()

    def finish(self):
        if self.finished:return
        while self.timers and self.timers[0][0]<=self.end_ns:self.at(self.timers[0][0])
        for row in self.rows:
            if row['status'] in ('entry_pending','exit_pending'):
                self.finish_row(row,row['status'].split('_')[0]+'_eof')
            if row['status']=='not_evaluated_archive_abort':raise ValueError('unvisited_anchor')
        self.finished=True


def integer(value,clock=False):
    if isinstance(value,bool) or not isinstance(value,(str,int)):
        raise ValueError('integer_schema')
    literal=str(value)
    if len(literal)>32 or not literal.isascii() or not literal.isdigit():
        raise ValueError('integer_bound')
    result=int(literal)
    if clock and not 1577836800000000000<=result<=4102444800000000000:
        raise ValueError('clock_range')
    return result


class Adapter:
    """Transactional raw price identity checks before the frozen float decoder."""
    def __init__(self,manifest,markets,end_ns):
        self.manifest,self.markets,self.end_ns=manifest,markets,end_ns
        self.output=[];self.registry={};self.row=None;self.override=None;self.last_source={}
        self.rebuilder=BookRebuilder([m for m in selected_markets(manifest) if m['venue'] in VENUES],self.emit)
        self.identities={(v,str(IDS[v][a])):a for v in VENUES for a in markets[v]}
        self.seen_generations=set();self.counts=Counter()

    def clear(self,venue,market=None):
        for key in list(self.registry):
            if key[0]==venue and (market is None or key[1]==market):
                del self.registry[key]

    def emit(self,event):
        venue,asset=event['venue'],event['asset']
        if venue not in VENUES:return
        key=(venue,str(event['market']))
        common=dict(venue=venue,asset=asset,receipt_ns=event['receipt_utc_ns'],
            source_ns=event['source_utc_ns'],generation=event['generation'],sequence=event['sequence'])
        if not event['valid']:
            self.clear(*key)
            self.output.append(dict(type='invalidate',reason=self.override or event['reason'] or 'invalid_book',**common))
            return
        meta=self.markets[venue][asset]
        price_grid='unknown' if meta['price_tick'] is None else 'known_pass'
        quantity_grid='known_pass'
        with localcontext() as ctx:
            ctx.prec=128
            tick=None if meta['price_tick'] is None else Decimal(meta['price_tick'])
            step=Decimal(meta['size_step'])
            for side in ('bids','asks'):
                levels=event[side]
                if not 0<len(levels)<=5000:raise ValueError('decoded_level_bound')
                previous=None
                for price,size in levels:
                    p,s=decimal(price),decimal(size)
                    if p<=0 or s<=0 or previous is not None and (p>=previous if side=='bids' else p<=previous):
                        raise ValueError('decoder_structural_contradiction')
                    if tick is not None and p%tick:price_grid='known_fail'
                    if s%step:quantity_grid='known_fail'
                    previous=p
        if rat(event['bids'][0][0])>=rat(event['asks'][0][0]):
            raise ValueError('decoder_crossed_contradiction')
        self.output.append(dict(type='book',bids=event['bids'],asks=event['asks'],
            price_grid=price_grid,quantity_grid=quantity_grid,**common))

    def gap(self,row,reason):
        self.clear(row['venue'],str(row.get('market')))
        self.override=reason;self.rebuilder.current=row
        self.rebuilder.manager._invalidate((row['venue'],str(row['market'])),reason,row['generation'])
        self.override=None

    def prepare(self,row):
        venue,market=row['venue'],str(row['market']);payload=row['payload']
        if payload.get('channel')!='order_book:'+market or payload.get('type') not in ('subscribed/order_book','update/order_book'):
            raise ValueError('selected_book_payload_identity')
        body=payload.get('order_book')
        if not isinstance(body,dict):raise ValueError('book_body_schema')
        integer(body['nonce'])
        if payload['type']=='update/order_book':integer(body['begin_nonce'])
        integer(integer(body['last_updated_at'])*1000,True)
        annotation=row.get('annotation')
        if (not isinstance(annotation,dict) or annotation.get('channel')!='order_book' or
            str(annotation.get('market'))!=market):raise ValueError('selected_annotation_identity')
        for field in ('source_max_ns','source_min_ns'):
            if annotation.get(field) is not None:
                if type(annotation[field]) is not int:raise ValueError('noninteger_annotation_clock')
                integer(annotation[field],True)
        snapshot=payload['type']=='subscribed/order_book'
        operations={};fresh={}
        for side in ('bids','asks'):
            levels=body.get(side)
            if not isinstance(levels,list):raise ValueError('raw_level_schema')
            if len(levels)>5000:raise ArithmeticError('raw_level_overflow')
            key=(venue,market,side)
            prior={} if snapshot else self.registry.get(key,{})
            proposed={};seen=set()
            for item in levels:
                if not isinstance(item,dict):raise ValueError('raw_level_schema')
                p,s=decimal(item['price']),decimal(item['size'])
                if p<=0 or s<0 or snapshot and not s:raise ArithmeticError('nonpositive_raw_book')
                fp=float(p)
                if p in seen:raise ArithmeticError('exact_duplicate_price')
                seen.add(p)
                if fp in proposed or fp in prior and prior[fp]!=p:
                    raise ArithmeticError('float_price_collision')
                proposed[fp]=(p,s)
            count=len(prior)+sum(1 if s and fp not in prior else -1 if not s and fp in prior else 0
                                 for fp,(_,s) in proposed.items())
            if count>5000:raise ArithmeticError('raw_state_overflow')
            operations[key]=proposed
            if snapshot:fresh[key]={}
        return operations,fresh

    def process(self,row):
        self.row=row;self.output=[]
        kind,venue,generation=row.get('kind'),row.get('venue'),row.get('generation')
        if venue not in ('hyperliquid',*VENUES) or not isinstance(generation,str) or not 0<len(generation)<=128:
            raise ValueError('record_venue_generation')
        declared={(g['venue'],g['generation']) for g in self.manifest['generations']}
        if (venue,generation) not in declared:raise ValueError('undeclared_generation')
        self.seen_generations.add((venue,generation));self.counts[str(kind)]+=1
        if kind not in ('frame','connection_open','connection_close','connection_error','invalid_json','generation_invalidated'):
            raise ValueError('unknown_control_schema')
        prior=self.rebuilder.last_generation.get(venue)
        if prior is not None and prior!=generation:self.clear(venue)
        if kind=='generation_invalidated':
            if row.get('scope')=='trade':return []
            if row.get('scope') not in (None,'book','venue','generation'):raise ValueError('invalidation_scope_schema')
            reason=row.get('reason') or kind
            if not isinstance(reason,str) or len(reason)>256:raise ValueError('control_reason_bound')
            market=row.get('market')
            if market is not None:
                if (venue,str(market)) not in self.identities:raise ValueError('invalidation_market_identity')
                self.gap(dict(row,market=str(market)),reason);return self.output
            self.clear(venue);self.override=reason
            self.rebuilder.process(dict(row,kind='connection_error'))
            self.override=None;return self.output
        if kind in ('connection_close','connection_error','invalid_json'):
            self.clear(venue)
            planned=(kind=='connection_close' and row['receipt_utc_ns']>=self.end_ns and
                any(g['venue']==venue and g['generation']==generation and
                    epoch(g['closed_utc'])>=self.end_ns for g in self.manifest['generations']))
            self.rebuilder.process(row)
            self.override=None
            if planned:self.output=[]
            return self.output
        if kind=='frame':
            payload=row.get('payload')
            if not isinstance(payload,dict):raise ValueError('frame_payload_schema')
            if len(json.dumps(payload,separators=(',',':'),ensure_ascii=False,allow_nan=False,default=str).encode())>4*1024*1024:
                raise ValueError('frame_byte_bound')
            if venue=='hyperliquid':return []
            declared_book=(payload.get('type') in ('subscribed/order_book','update/order_book') or
                           str(payload.get('channel','')).startswith('order_book:'))
            if declared_book and row.get('channel')!='order_book':raise ValueError('book_envelope_identity_conflict')
            if venue in VENUES and row.get('channel')=='order_book':
                key=(venue,str(row.get('market')))
                if key not in self.identities:raise ValueError('unknown_selected_book_market')
                try:operations,fresh=self.prepare(row)
                except ArithmeticError as exc:
                    self.gap(row,str(exc));return self.output
                source=row['annotation'].get('source_max_ns')
                watermark=(venue,key[1],generation)
                if source is None or source>row['receipt_utc_ns']:
                    self.gap(row,'invalid_source_or_clock');return self.output
                if watermark in self.last_source and source<self.last_source[watermark]:
                    self.gap(row,'source_regression');return self.output
                self.rebuilder.process(row)
                accepted=any(e['type']=='book' for e in self.output)
                if accepted:
                    self.last_source[watermark]=source
                    for key,changes in operations.items():
                        state=fresh.get(key,self.registry.get(key,{}))
                        for fp,(p,s) in changes.items():
                            if s:state[fp]=p
                            else:state.pop(fp,None)
                        self.registry[key]=state
                elif any(e['type']=='invalidate' for e in self.output):self.clear(*key[:2])
                return self.output
        self.rebuilder.process(row)
        return self.output


def finite_json_float(literal):
    # Preserve the raw numeric lexeme through identity/resource validation.
    # float conversion is performed only by the pinned decoder afterwards.
    if len(literal)>64:raise ValueError('numeric_token_bound')
    value=Decimal(literal)
    if not value.is_finite():raise ValueError('nonfinite_json_number')
    return value


def load_json(path,limit=1_000_000):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:raise ValueError('small_input_path_bound')
    return json.loads(path.read_text(),parse_float=finite_json_float,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite_json_number')))


def sha(path,limit=25_000_000):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>limit:raise ValueError('hash_path_bound')
    result=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1<<20),b''):result.update(block)
    return result.hexdigest()


def wall(started):
    if time.monotonic()-started>WALL:raise TimeoutError('900_second_wall_bound')


def traverse(spec,manifest,markets,rows,started,decoded_total):
    engine=QuoteEngine(markets,rows,spec['start']+DURATION)
    adapter=Adapter(manifest,markets,engine.end_ns)
    prior=None;records=decoded=0
    with gzip.open(spec['directory']/'frames.jsonl.gz','rb') as handle:
        while True:
            wall(started)
            line=handle.readline(8*1024*1024+1)
            if not line:break
            records+=1;decoded+=len(line);decoded_total[0]+=len(line)
            if (len(line)>8*1024*1024 or decoded>256*1024*1024 or
                decoded_total[0]>512*1024*1024 or records>spec['records']):
                raise ValueError('decoded_stream_bound')
            if not line.endswith(b'\n'):raise ValueError('record_newline_required')
            row=json.loads(line,parse_float=finite_json_float,
                parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite_json_number')))
            if not isinstance(row,dict):raise ValueError('record_object_schema')
            now=integer(row.get('receipt_utc_ns'),True)
            if type(row.get('receipt_utc_ns')) is not int:raise ValueError('noninteger_raw_receipt')
            if prior is not None and now<prior:raise ValueError('nonmonotone_raw_receipt')
            if now<spec['start'] or now>epoch(manifest['ended_utc']):raise ValueError('receipt_outside_manifest')
            prior=now;engine.record(now,adapter.process(row))
    if prior is not None:engine.batch(prior,())
    engine.finish()
    if records!=spec['records'] or adapter.seen_generations!={(g['venue'],g['generation']) for g in manifest['generations']}:
        raise ValueError('terminal_record_or_generation_mismatch')
    return dict(verified=True,records=records,decoded_bytes=decoded,gzip_eof=True,
        raw_sha256=spec['raw_sha'],manifest_sha256=spec['manifest_sha'],
        decoder_counts=dict(adapter.rebuilder.counts),control_counts=dict(adapter.counts))


def metadata(spec,manifest,unit_path,hashes):
    plan_path=Path(manifest['market_plan']);plan=load_json(plan_path)
    if hashes[str(plan_path)]!=manifest['market_plan_sha256']:raise ValueError('market_plan_digest')
    markets={v:{} for v in VENUES}
    for pair in plan.get('pairs',[]):
        source=pair.get('other',{});venue=source.get('venue');asset=pair.get('asset')
        if venue not in VENUES:continue
        if asset not in spec['assets'] or asset in markets[venue] or str(source.get('market'))!=IDS[venue][asset]:
            raise ValueError('metadata_market_identity')
        if rat(source.get('fee_bps'))!=0:raise ValueError('public_standard_fee')
        values={k:text_number(source[field]) for k,field in
                (('size_step','step'),('min_qty','min_qty'),('min_notional','min_notional'))}
        if any(decimal(value)<=0 for value in values.values()):raise ValueError('metadata_quantity_rules')
        provenance={rule:dict(value=values[field],source_path=str(plan_path),
            source_sha256=hashes[str(plan_path)],field=f'pairs[{asset}].other.{source_field}')
            for rule,field,source_field in (('quantity_grid','size_step','step'),
                ('minimum_quantity','min_qty','min_qty'),('minimum_notional','min_notional','min_notional'))}
        provenance.update({rule:dict(value=None,source_path=None,source_sha256=None,field=None)
                           for rule in ('price_grid','maximum_quote','maximum_base')})
        markets[venue][asset]=dict(market=IDS[venue][asset],**values,price_tick=None,
            max_quote=None,max_qty=None,taker_fee_bps='0',provenance=provenance,
            fee_provenance=dict(value='0',source_path=str(plan_path),source_sha256=hashes[str(plan_path)],
                                field=f'pairs[{asset}].other.fee_bps'))
    if any(set(markets[v])!=set(spec['assets']) for v in VENUES):raise ValueError('metadata_selected_set')
    if 'NVDA' in spec['assets']:
        units=load_json(unit_path)
        for venue in VENUES:
            body=units[venue]
            if epoch(body['retrieved_at'])>=spec['start']:raise ValueError('postcapture_unit_rules')
            details={row['symbol']:row for row in body['selected_market_details']}
            if set(details)!=set(spec['assets']):raise ValueError('unit_selected_set')
            for asset in spec['assets']:
                row=details[asset];meta=markets[venue][asset]
                if (str(row['market_id'])!=IDS[venue][asset] or row.get('status')!='active' or
                    row.get('market_type')!='perp' or rat(row['multiplier'])!=1 or
                    rat(row.get('quote_multiplier'))!=1 or rat(row['taker_fee'])!=0):
                    raise ValueError('unit_contract_identity')
                digits=integer(row['supported_price_decimals']);size_digits=integer(row['supported_size_decimals'])
                if digits>18 or size_digits>18:raise ValueError('metadata_grid_bound')
                if (rat(meta['size_step'])!=Fraction(1,10**size_digits) or
                    rat(meta['min_qty'])!=rat(row['min_base_amount']) or
                    rat(meta['min_notional'])!=rat(row['min_quote_amount'])):
                    raise ValueError('plan_unit_rule_conflict')
                meta['price_tick']=text_number(Fraction(1,10**digits))
                meta['max_quote']=text_number(decimal(row['order_quote_limit']))
                if rat(meta['max_quote'])<=0:raise ValueError('quote_ceiling_schema')
                for rule,field,raw_field in (('price_grid','price_tick','supported_price_decimals'),
                                             ('maximum_quote','max_quote','order_quote_limit')):
                    meta['provenance'][rule]=dict(value=meta[field],source_path=str(unit_path),
                        source_sha256=hashes[str(unit_path)],field=f'{venue}.selected_market_details[{asset}].{raw_field}')
    return markets


AUDITOR = ROOT/'scripts/audit_core_rh_delayed_taker.py'
AUDIT_TESTS = ROOT/'tests/test_audit_core_rh_delayed_taker.py'


def admit(specs,small_pins,unit_path):
    hashes={}
    for name,expected in {**{str(ROOT/name):digest for name,digest in SOURCES.items()},**small_pins}.items():
        actual=sha(name,1_000_000)
        if actual!=expected:raise ValueError('pinned_small_source_changed:'+name)
        hashes[str(Path(name))]=actual
    for path in (Path(__file__),TESTS,METHOD,AUDITOR,AUDIT_TESTS):
        hashes[str(path)]=sha(path,200_000)
    manifests={};markets={}
    for spec in specs:
        path=spec['directory'];manifest=load_json(path/'manifest.json')
        expected={v:{a:IDS[v][a] for a in spec['assets']} for v in VENUES}
        expected['hyperliquid']={a:a if a in ('BTC','ETH') else 'xyz:NVDA' if a=='NVDA' else 'xyz:SILVER'
                                for a in spec['assets']}
        if (manifest.get('schema')!='maker-public-capture-v1' or manifest.get('read_only') is not True or
            manifest.get('end_reason')!='duration_limit' or manifest.get('truncated') is not False or
            manifest.get('errors') or manifest.get('invalidations') or
            manifest.get('omitted_record_count_keys')!=0 or manifest.get('omitted_invalidation_keys')!=0 or
            manifest.get('dropped_complete_frame_on_cap')!=0 or manifest.get('configured_seconds')!=420 or
            manifest.get('configured_total_compressed_bytes')!=25_000_000 or
            manifest.get('selected_markets')!=expected or
            type(manifest.get('payload_records')) is not int or manifest['payload_records']!=spec['records'] or
            type(manifest.get('compressed_payload_bytes')) is not int or manifest['compressed_payload_bytes']!=spec['bytes'] or
            epoch(manifest['started_utc'])!=spec['start'] or
            not spec['start']+DURATION<=epoch(manifest['ended_utc'])<=spec['start']+421*NS):
            raise ValueError('stopped_capture_identity')
        generations=manifest.get('generations')
        if (not isinstance(generations,list) or len(generations)!=3 or
            {g['venue'] for g in generations}!=set(expected) or
            any(not isinstance(g['generation'],str) or not 0<len(g['generation'])<=128 or
                not spec['start']<=epoch(g['opened_utc'])<=spec['start']+2*NS or
                not spec['start']+DURATION<=epoch(g['closed_utc'])<=epoch(manifest['ended_utc']) for g in generations)):
            raise ValueError('manifest_generation_closure')
        owned=list(path.iterdir())
        if (len(owned)>16 or any(p.is_symlink() or not p.is_file() for p in owned) or
            sum(p.stat().st_size for p in owned)>25_000_000 or
            (path/'frames.jsonl.gz').stat().st_size!=spec['bytes']):raise ValueError('owned_archive_bound')
        spec['manifest_sha']=hashes[str(path/'manifest.json')]
        manifests[spec['name']]=manifest
        markets[spec['name']]=metadata(spec,manifest,unit_path,hashes)
    return manifests,markets,hashes


def stats(rows):
    complete=[r for r in rows if r['status']=='conditional_quote_complete']
    values=[rat(r['adjusted_quote_net_ex_funding']) for r in complete]
    rule_counts=Counter(status for row in rows for stage in ('anchor','entry','exit')
        for checks in row.get(stage+'_rules',{}).values() for status in checks.values())
    return dict(original_candidates=len(rows),statuses=dict(Counter(r['status'] for r in rows)),
        rule_check_status_counts=dict(rule_counts),
        known_rule_violation_candidates=sum(r['status'].endswith('_known_rule_violation') for r in rows),
        entry_pair_selected=sum('entry_selected_ns' in r for r in rows),
        entry_quote_complete=sum('entry_ns' in r for r in rows),
        exit_pair_selected=sum('exit_selected_ns' in r for r in rows),
        conditional_quote_complete=len(complete),historical_legality_unknown=len(complete),
        fully_verified_executable_count=0,
        fee_only_positive=sum(rat(r['fee_only_net'])>0 for r in complete),
        adjusted_positive=sum(v>0 for v in values),target_positive=sum(v>=Fraction(1,10) for v in values),
        adjusted_min=text_number(min(values)) if values else None,
        adjusted_median=text_number(statistics.median(values)) if values else None,
        adjusted_max=text_number(max(values)) if values else None)


def summary(rows,terminals,fixture):
    groups=defaultdict(list);strata=defaultdict(list)
    for row in rows:
        key=(row['asset'],row['long_venue'],row['budget'])
        groups[key].append(row);strata[key+(row['stratum'],)].append(row)
    return dict(schema=SCHEMA,status='complete_quote_diagnostic',classification=(
        'synthetic_fixture_quote_feasibility' if fixture else 'exploratory_post_capture_quote_feasibility'),
        actual_fills_observed=False,private_ack_observed=False,executable_profit_claim=False,
        funding_inclusive_net=None,summed_portfolio_net=None,clock_sync_performed=False,
        clock_qualifier='receipt/source ages are uncalibrated observed clocks, not private execution or measured latency',
        **stats(rows),primary_candidates=sum(r['budget']==1000 for r in rows),
        smaller_candidates=sum(r['budget']!=1000 for r in rows),
        archive_denominators=dict(Counter(r['archive'] for r in rows)),
        stratum_denominators=dict(Counter(r['stratum'] for r in rows)),
        group_key=['asset','long_venue','budget'],stratum_group_key=['asset','long_venue','budget','stratum'],
        groups=[dict(key=key,**stats(value)) for key,value in sorted(groups.items())],
        stratum_groups=[dict(key=key,**stats(value)) for key,value in sorted(strata.items())],
        terminals=terminals,wall_seconds_bound=WALL)


class OutputCapError(ValueError):
    pass


class Output:
    def __init__(self,stage,source_bytes,external_freeze_bytes=0):
        self.stage=Path(stage);self.source_bytes=source_bytes;self.external_freeze_bytes=external_freeze_bytes
        self.used=source_bytes+external_freeze_bytes
        self.categories=Counter(source=source_bytes,provenance=external_freeze_bytes)
        self.check('source',0)
        self.check('provenance',0)

    def check(self,category,size):
        projected=self.used+size;category_projected=self.categories[category]+size
        if category_projected>LIMITS[category] or projected>CAP-EXTERNAL_RESERVE:
            raise OutputCapError(json.dumps(dict(category=category,requested_bytes=size,
                projected_category_bytes=category_projected,projected_total_bytes=projected,
                category_cap=LIMITS[category],aggregate_cap=CAP-EXTERNAL_RESERVE),sort_keys=True))

    def write(self,name,body,category):
        data=body.encode() if isinstance(body,str) else body
        self.check(category,len(data));path=self.stage/name
        if path.exists() or path.is_symlink():raise ValueError('staged_path_exists')
        with path.open('xb') as handle:handle.write(data)
        self.used+=len(data);self.categories[category]+=len(data)

    def compressed(self,name,rows,category,decoded_limit=8*1024*1024):
        compressor=zlib.compressobj(6,zlib.DEFLATED,31);pieces=[];size=decoded=0
        for row in rows:
            body=(json.dumps(row,separators=(',',':'),sort_keys=True,allow_nan=False)+'\n').encode()
            decoded+=len(body)
            if decoded>decoded_limit:raise ValueError('output_decoded_bound')
            chunk=compressor.compress(body);size+=len(chunk);self.check(category,size);pieces.append(chunk)
        chunk=compressor.flush();size+=len(chunk);self.check(category,size);pieces.append(chunk)
        self.write(name,b''.join(pieces),category)

    def remove(self,name,category):
        path=self.stage/name
        if path.is_file():
            size=path.stat().st_size;path.unlink();self.used-=size;self.categories[category]-=size

    def reconcile(self):
        categories={'sources.jsonl.gz':'source','freeze.json':'provenance','manifest.json':'provenance',
            'quotes.jsonl.gz':'rows','summary.json.gz':'summary','failure-roster.jsonl.gz':'failure',
            'fallback-roster.jsonl.gz':'failure','failure.json':'failure'}
        self.categories=Counter(source=self.source_bytes,provenance=self.external_freeze_bytes)
        for path in self.stage.iterdir():self.categories[categories[path.name]]+=path.stat().st_size
        self.used=sum(self.categories.values())


def json_body(value):
    return json.dumps(value,separators=(',',':'),sort_keys=True,allow_nan=False)+'\n'


def plan():
    return dict(schema=SCHEMA,mode='dry_plan',raw_reads=0,raw_traversals=0,network_calls=0,
        candidates=1008,primary=672,smaller=336,horizon_seconds=10,
        quote_delay_ms=500,hard_deadline_ms=2000,wall_seconds=WALL,
        total_new_physical_bytes_cap=CAP,reserved_external_bytes=EXTERNAL_RESERVE,
        instruction='Separate --prepare source freeze, root review/commit and --run --freeze/--freeze-sha256 required.')


def runtime():
    return dict(python=sys.version,aiohttp=importlib.metadata.version('aiohttp'),dont_write_bytecode=sys.dont_write_bytecode)


def context(fixture_inputs):
    fixture=fixture_inputs is not None
    specs=[dict(s) for s in (EXPECTED if not fixture else fixture_inputs['specs'])]
    pins=({str(ROOT/name):digest for name,digest in SMALL_PINS.items()} if not fixture else fixture_inputs['small_pins'])
    unit=ROOT/'reports/maker-equity-v2/unit-provenance.json' if not fixture else fixture_inputs['unit_path']
    return specs,pins,unit


def spec_inventory(specs):
    return [dict(name=s['name'],directory=str(s['directory']),start=s['start'],assets=list(s['assets']),
                 records=s['records'],bytes=s['bytes'],raw_sha=s['raw_sha']) for s in specs]


def owned_inventory(specs):
    result={}
    for spec in specs:
        files=list(spec['directory'].iterdir())
        if len(files)>16 or any(p.is_symlink() or not p.is_file() for p in files):raise ValueError('owned_archive_inventory')
        sizes={p.name:p.stat().st_size for p in files}
        if sum(sizes.values())>25_000_000 or sizes.get('frames.jsonl.gz')!=spec['bytes']:
            raise ValueError('owned_archive_bytes')
        result[spec['name']]=sizes
    return result


def prepare(path,*,fixture_inputs=None):
    """Freeze small inputs/sources only; never open either raw gzip stream."""
    path=Path(path);fixture=fixture_inputs is not None
    if (path.exists() or path.is_symlink() or path.parent.is_symlink() or
        not fixture and path.parent.resolve()!=OUTPUT_PARENT.resolve()):raise ValueError('new_freeze_child_required')
    specs,pins,unit=context(fixture_inputs)
    manifests,markets,hashes=admit(specs,pins,unit)
    freeze=dict(schema=SCHEMA,classification='synthetic_fixture' if fixture else 'exploratory_post_capture',
        frozen_at=dt.datetime.now(dt.timezone.utc).isoformat(),prospective_freeze_claimed=False,
        actual_dependency_and_small_input_sha256=hashes,
        expected_raw_sha256={str(s['directory']/'frames.jsonl.gz'):s['raw_sha'] for s in specs},
        rule_specs={f'{name}:{v}:{a}':meta for name,byvenue in markets.items() for v,assets in byvenue.items() for a,meta in assets.items()},
        captures=spec_inventory(specs),owned_archive_inventory=owned_inventory(specs),
        grid=plan(),runtime=runtime(),source_inventory_count=11,
        clock_sync_performed=False,raw_reads=0)
    body=json_body(freeze).encode()
    if len(body)>30_000:raise ValueError('external_freeze_bound')
    baseline=sum(p.stat().st_size for p in (Path(__file__),TESTS,METHOD,AUDITOR,AUDIT_TESTS))
    if baseline>LIMITS['source'] or baseline+len(body)>CAP-EXTERNAL_RESERVE:raise ValueError('preparation_resource_bound')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as handle:handle.write(body)
    return dict(schema=SCHEMA,status='prepared_zero_raw_reads',freeze=str(path),sha256=hashlib.sha256(body).hexdigest(),
                bytes=len(body),source_repository_bytes=baseline,raw_reads=0)


def run(out,*,freeze_path,freeze_sha256,fixture_inputs=None):
    """Fixture inputs use the production gates/decoder, with explicit test labels."""
    started=time.monotonic();out=Path(out);fixture=fixture_inputs is not None
    specs,pins,unit_path=context(fixture_inputs)
    rows=list(grid(specs))
    if len(rows)!=1008:raise ValueError('full_grid_required')
    parent=out.parent
    if (out.exists() or out.is_symlink() or parent.is_symlink() or
        not fixture and parent.resolve()!=OUTPUT_PARENT.resolve() or
        out.name.startswith('.')):raise ValueError('new_output_child_required')
    stage=out.with_name(out.name+'.building')
    if stage.exists() or stage.is_symlink():raise ValueError('staging_exists')
    for spec in specs:
        protected=spec['directory'].resolve();resolved=out.resolve()
        if protected==resolved or protected in resolved.parents or resolved in protected.parents:
            raise ValueError('output_input_overlap')
    new_files=(Path(__file__),TESTS,METHOD,AUDITOR,AUDIT_TESTS)
    baseline=sum(p.stat().st_size for p in new_files)
    parent.mkdir(parents=True,exist_ok=True);stage.mkdir(exist_ok=False)
    freeze_path=Path(freeze_path)
    writer=Output(stage,baseline,freeze_path.stat().st_size)
    def terminate(_signum,_frame):raise TimeoutError('supervised_sigterm')
    old_handler=signal.signal(signal.SIGTERM,terminate)
    try:
        writer.compressed('fallback-roster.jsonl.gz',(dict(id=r['id'],status=r['status'],economics=None) for r in rows),'failure')
        if sha(freeze_path,30_000)!=freeze_sha256:raise ValueError('prepared_freeze_digest')
        freeze=load_json(freeze_path,30_000)
        if (freeze.get('schema')!=SCHEMA or freeze.get('captures')!=spec_inventory(specs) or
            freeze.get('owned_archive_inventory')!=owned_inventory(specs) or
            freeze.get('runtime')!=runtime() or freeze.get('grid')!=plan() or
            freeze.get('classification')!=('synthetic_fixture' if fixture else 'exploratory_post_capture')):
            raise ValueError('prepared_freeze_identity_runtime')
        if any(sha(p,1_000_000)!=digest for p,digest in freeze['actual_dependency_and_small_input_sha256'].items()):
            raise ValueError('source_changed_since_preparation')
        manifests,markets,hashes=admit(specs,pins,unit_path)
        if hashes!=freeze['actual_dependency_and_small_input_sha256']:raise ValueError('prepared_source_inventory')
        writer.compressed('sources.jsonl.gz',(dict(path=str(p),sha256=hashes[str(p)],text=p.read_text()) for p in new_files),
                          'source',decoded_limit=200_000)
        writer.write('freeze.json',json_body(freeze),'provenance')
        # Both compressed inputs are verified before either decoded traversal.
        for spec in specs:
            wall(started)
            if sha(spec['directory']/'frames.jsonl.gz')!=spec['raw_sha']:raise ValueError('raw_digest_before_decode')
        if any(sha(p,1_000_000)!=digest for p,digest in hashes.items()):raise ValueError('source_changed_before_decode')
        terminals={};decoded_total=[0]
        for spec in specs:
            subset=[r for r in rows if r['archive']==spec['name']]
            terminals[spec['name']]=traverse(spec,manifests[spec['name']],markets[spec['name']],subset,started,decoded_total)
        wall(started)
        result=summary(rows,terminals,fixture)
        writer.compressed('quotes.jsonl.gz',rows,'rows')
        writer.compressed('summary.json.gz',[result],'summary',decoded_limit=256*1024)
        writer.remove('fallback-roster.jsonl.gz','failure')
        outputs={p.name:dict(bytes=p.stat().st_size,sha256=sha(p,600_000)) for p in stage.iterdir()}
        manifest=dict(schema=SCHEMA,status='complete_quote_diagnostic',completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            classification=freeze['classification'],outputs=outputs,source_repository_bytes=baseline,
            new_physical_bytes_before_manifest=writer.used,category_bytes_before_manifest=dict(writer.categories),
            reserved_external_bytes=EXTERNAL_RESERVE,total_new_bytes_cap=CAP,wall_seconds=time.monotonic()-started,
            terminal_verified=True,original_candidates=1008,external_freeze_sha256=freeze_sha256,
            external_freeze_bytes=freeze_path.stat().st_size,external_freeze_path=str(freeze_path))
        writer.write('manifest.json',json_body(manifest),'provenance')
        if any(sha(p,1_000_000)!=digest for p,digest in hashes.items()):raise ValueError('source_changed_before_publication')
        for spec in specs:
            if sha(spec['directory']/'frames.jsonl.gz')!=spec['raw_sha']:raise ValueError('raw_changed_before_publication')
        if (sha(freeze_path,30_000)!=freeze_sha256 or runtime()!=freeze['runtime'] or
            owned_inventory(specs)!=freeze['owned_archive_inventory']):
            raise ValueError('freeze_or_runtime_changed_before_publication')
        wall(started)
        if out.exists() or out.is_symlink():raise ValueError('output_appeared_before_publication')
        stage.rename(out)
        return dict(status='complete_quote_diagnostic',output=str(out),new_physical_bytes=writer.used,
                    conditional_complete=result['conditional_quote_complete'])
    except BaseException as exc:
        # Stage never becomes a completed result. Remove any staged economics,
        # preserving frozen sources and a full null-economic failure roster.
        for name,category in (('quotes.jsonl.gz','rows'),('summary.json.gz','summary'),('manifest.json','provenance')):
            writer.remove(name,category)
        writer.reconcile()
        failure_rows=(dict(id=r['id'],status=r['status'],evaluation_status=(
            'not_evaluated_archive_abort' if r['status']=='not_evaluated_archive_abort' else 'partial_evidence_only'),
            economics=None) for r in rows)
        writer.compressed('failure-roster.jsonl.gz',failure_rows,'failure')
        writer.write('failure.json',json_body(dict(schema=SCHEMA,status='failed_no_economic_result',
            error_type=type(exc).__name__,error=str(exc)[:2000],candidates=1008,all_economics_null=True,
            failed_at=dt.datetime.now(dt.timezone.utc).isoformat())),'failure')
        raise
    finally:
        signal.signal(signal.SIGTERM,old_handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--run',action='store_true');mode.add_argument('--prepare',action='store_true')
    parser.add_argument('--out',type=Path);parser.add_argument('--freeze',type=Path);parser.add_argument('--freeze-sha256')
    parser.add_argument('--synthetic-fixture',type=Path,help='Explicit synthetic-only context under /tmp; never real-capture classification.')
    args=parser.parse_args()
    fixture=None
    if args.synthetic_fixture:
        if not args.synthetic_fixture.resolve().is_relative_to(Path('/tmp')):parser.error('synthetic fixture must be under /tmp')
        fixture=load_json(args.synthetic_fixture,60_000)
        fixture['unit_path']=Path(fixture['unit_path'])
        for spec in fixture['specs']:spec['directory']=Path(spec['directory'])
    if args.run:
        if args.out is None or args.freeze is None or not args.freeze_sha256:parser.error('--run requires --out, --freeze and --freeze-sha256')
        print(json_body(run(args.out,freeze_path=args.freeze,freeze_sha256=args.freeze_sha256,fixture_inputs=fixture)),end='')
    elif args.prepare:
        if args.freeze is None:parser.error('--prepare requires --freeze')
        print(json_body(prepare(args.freeze,fixture_inputs=fixture)),end='')
    else:print(json_body(plan()),end='')


if __name__=='__main__':main()
