#!/usr/bin/env python3
"""Frozen exploratory queue OFI: past features, OLS, delayed native quotes.

QueueFeatures and ofi are independently importable past-only measurements.
Importing this module neither reads research data nor imports numpy.
"""
from collections import Counter,defaultdict,deque
from contextlib import contextmanager
from decimal import Decimal as D,ROUND_FLOOR
from pathlib import Path
import datetime,gzip,hashlib,json,math,platform,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts import single_venue_ordinary_events as ordinary
from scripts import single_venue_inventory_context as inventory
from scripts import rolling_research_capture as rolling
from scripts.single_venue_residual_profile import sweep
PLAN=ROOT/'reports/experiment-storage/single-venue-queue-ofi-v1.json'
VALIDATION_SHA='f8b045d2692cf5641a83a72f734d3b0fc4936db13986379f0d6fd88f9d845dfd'
METHOD_SHA='fb7d1e6cefe75b05579d9d9db820dc6996d1124e820f4da19d893349bdabd01f'
ASSETS=tuple(rolling.ASSETS);VENUES=('lighter','rh_lighter');NS=10**9
FEATURES=('own_backward_mid_return_bps','current_queue_imbalance',
    'start_queue_difference_over_D_start','current_queue_difference_over_D_start',
    'ordinary_trade_imbalance','normalized_ofi')
FIT=('chunk-000001','chunk-000002','chunk-000003');EVALUATION=('chunk-000007','chunk-000008','chunk-000009')
PARAMS=dict(anchor_start_seconds=30,anchor_stop_seconds_inclusive=570,anchor_step_seconds=20,
    lookback_ns=NS,book_age_ns=250000000,max_interbook_gap_ns=500000000,max_trade_age_ns=500000000,
    entry_delay_ns=400000000,exit_delay_ns=400000000,hold_ns=10000000000,
    max_execution_lateness_ns=2000000000,maximum_profile_span_ns=14800000000,
    notionals=['100','1000','10000'],sizing_headroom='1.01',annual_capital_rate='0.05',
    year_seconds=31536000,extra_cost_stress_bps=[1,2,5],minimum_training_labels=40,
    ols_rcond=1e-10,maximum_design_condition_number=100000000,
    max_decoded_bytes_per_chunk=1073741824,max_records_per_chunk=1000000,max_ids_per_chunk=500000,
    max_history_records_per_market=10000,max_same_receipt_events=10000,max_profiles_per_chunk=4000)
CAPS=dict(source=65536,tests=32768,protocol=16384,gzip_per_chunk=262144,model=32768,
    summary=98304,readout=32768,provenance=32768,control=8192)

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def encode(value):return inventory.encode(value)
def digest(path):return rolling.digest(Path(path))
def publish(path,value,cap,*,compressed=False,decoded_cap=None):
    body=encode(value)
    if decoded_cap is not None and len(body)>decoded_cap:raise ValueError('decoded_output_byte_cap')
    if compressed:body=gzip.compress(body,mtime=0)
    if len(body)>cap:raise ValueError('output_byte_cap')
    if path.exists() or path.with_name('.'+path.name+'.tmp').exists():raise FileExistsError(path)
    inventory.publish(path,body)
    return hashlib.sha256(body).hexdigest()
def number(value):
    if isinstance(value,bool):raise ValueError('boolean_native_number')
    x=D(str(value))
    if not x.is_finite():raise ValueError('nonfinite_native_number')
    return x
def grid(value,step):return value>0 and value%step==0
def native_bbo(book,market):
    if not book.get('valid') or not book.get('clock_valid'):raise ValueError('invalid_book')
    tick,step=number(market['price_tick']),number(market['qty_step'])
    if tick<=0 or step<=0:raise ValueError('invalid_native_grid')
    bid,bq=map(number,book['bids'][0]);ask,aq=map(number,book['asks'][0])
    if not all((grid(bid,tick),grid(ask,tick),grid(bq,step),grid(aq,step))) or bid>=ask:
        raise ValueError('non_native_or_crossed_bbo')
    return bid,bq,ask,aq
def native_book(book,market):
    bbo=native_bbo(book,market);tick,step=number(market['price_tick']),number(market['qty_step'])
    for side in ('bids','asks'):
        previous=None
        for p,q in book[side]:
            p,q=number(p),number(q)
            if not grid(p,tick) or not grid(q,step):raise ValueError('non_native_depth')
            if previous is not None and not (p<previous if side=='bids' else p>previous):
                raise ValueError('unordered_native_depth')
            previous=p
    return bbo
def midpoint(bbo):return (bbo[0]+bbo[2])/2
def fresh(book,when,age):
    return bool(book and isinstance(book.get('received_ns'),int) and isinstance(book.get('source_ns'),int)
        and 0<=when-book['received_ns']<=age and 0<=when-book['source_ns']<=age
        and book['source_ns']<=book['received_ns'])
def ofi(old,new):
    b0,qb0,a0,qa0=old;b1,qb1,a1,qa1=new
    return (qb1 if b1>=b0 else D(0))-(qb0 if b1<=b0 else D(0))-(qa1 if a1<=a0 else D(0))+(qa0 if a1>=a0 else D(0))

class QueueFeatures:
    """Past-only local histories. No labels, models, quote profiles or writes."""
    def __init__(self,metadata,params=PARAMS):
        self.metadata=metadata;self.p=params;self.states={};self.counts=Counter()
    def state(self,key):
        return self.states.setdefault(key,dict(books=deque(),trades=deque(),trade_since=None,trade_generation=None))
    def process(self,event):
        key=(event.get('asset'),event.get('venue'))
        if key[0] not in self.metadata.get(key[1],{}):return
        s=self.state(key);now=event['received_ns'];kind=event['type']
        if kind=='invalidate':
            if event['scope']=='book':s['books'].clear()
            elif event['scope']=='trade':s['trades'].clear();s['trade_since']=None;s['trade_generation']=None
            self.counts['reset:'+event['scope']+':'+str(event.get('reason'))]+=1;return
        if kind=='book':
            try:bbo=native_bbo(event,self.metadata[key[1]][key[0]])
            except (ValueError,KeyError,IndexError):s['books'].clear();self.counts['invalid_feature_bbo']+=1;return
            previous=s['books'][-1] if s['books'] else None
            reset=bool(event.get('book_snapshot') or previous and
                (previous['book']['generation']!=event['generation'] or now-previous['book']['received_ns']>self.p['max_interbook_gap_ns']))
            if reset:s['books'].clear();previous=None;self.counts['book_history_reset']+=1
            valid_clock=fresh(event,now,self.p['book_age_ns'])
            e=ofi(previous['bbo'],bbo) if previous is not None else None
            unchanged=bool(previous and bbo[0]==previous['bbo'][0] and bbo[2]==previous['bbo'][2])
            # Retain only BBO states in history, never duplicate native full depth.
            small={k:event[k] for k in ('received_ns','source_ns','generation')}
            s['books'].append(dict(book=small,bbo=bbo,e=e,unchanged=unchanged,valid_clock=valid_clock))
        elif kind=='trade':
            if s['trade_generation']!=event['generation']:
                s['trades'].clear();s['trade_since']=None;s['trade_generation']=event['generation']
            valid=fresh(event,now,self.p['max_trade_age_ns'])
            if valid and s['trade_since'] is None:s['trade_since']=now
            qty=number(event['qty'])
            if qty<=0:raise ValueError('invalid_ordinary_quantity')
            s['trades'].append(dict(t=now,qty=qty,sign=1 if event['buy_aggressor'] else -1,valid=valid))
        cutoff=now-self.p['lookback_ns']-self.p['book_age_ns']
        while len(s['books'])>1 and s['books'][1]['book']['received_ns']<=cutoff:s['books'].popleft()
        while s['trades'] and s['trades'][0]['t']<=now-self.p['lookback_ns']:s['trades'].popleft()
        if max(len(s['books']),len(s['trades']))>self.p['max_history_records_per_market']:
            raise ValueError('feature_history_record_cap')
    def at(self,asset,venue,now):
        s=self.state((asset,venue));left=now-self.p['lookback_ns'];history=s['books']
        starts=[x for x in history if x['book']['received_ns']<=left]
        if not starts:return None,'missing_start_book'
        start=starts[-1];end=history[-1]
        if not fresh(start['book'],left,self.p['book_age_ns']) or not fresh(end['book'],now,self.p['book_age_ns']):
            return None,'stale_boundary_book'
        transitions=[x for x in history if left<x['book']['received_ns']<=now]
        if start['book']['generation']!=end['book']['generation'] or any(x['e'] is None or not x['valid_clock'] for x in transitions):
            return None,'unusable_book_transition'
        if any(b['book']['received_ns']-a['book']['received_ns']>self.p['max_interbook_gap_ns'] for a,b in zip([start]+transitions,transitions)):
            return None,'interbook_gap'
        if s['trade_since'] is None or s['trade_since']>left:return None,'unknown_trade_history'
        trades=[x for x in s['trades'] if left<x['t']<=now]
        if any(not x['valid'] for x in trades):return None,'stale_trade_window'
        b0,qb0,a0,qa0=start['bbo'];b1,qb1,a1,qa1=end['bbo'];depth=(qb0+qa0)/2
        total=sum((x['qty'] for x in trades),D(0));flow=sum((x['sign']*x['qty'] for x in trades),D(0))
        unchanged=sum((x['e'] for x in transitions if x['unchanged']),D(0))
        changing=sum((x['e'] for x in transitions if not x['unchanged']),D(0));all_ofi=unchanged+changing
        values=[D(10000)*(midpoint(end['bbo'])-midpoint(start['bbo']))/midpoint(start['bbo']),
            (qb1-qa1)/(qb1+qa1),(qb0-qa0)/depth,(qb1-qa1)/depth,flow/total if total else D(0),all_ofi/depth]
        converted=[float(v) for v in values]
        if not all(math.isfinite(v) for v in converted):return None,'nonfinite_feature'
        return dict(values=converted,ofi=str(all_ofi),depth_start=str(depth),
            unchanged_price_ofi=str(unchanged),price_changing_ofi=str(changing),
            zero_flow=total==0,zero_ofi=all_ofi==0,all_prices_unchanged=all(x['unchanged'] for x in transitions),
            start_received_ns=start['book']['received_ns'],end_received_ns=end['book']['received_ns'],
            start_source_ns=start['book']['source_ns'],end_source_ns=end['book']['source_ns'],
            generation=end['book']['generation']),None

@contextmanager
def adapter_configuration():
    replacements={ordinary:dict(HARD_BYTES=inventory.RAW_CAP,HARD_SECONDS=600,METADATA_MAX_BYTES=131072,
        MAX_DECODED_BYTES=PARAMS['max_decoded_bytes_per_chunk'],MAX_RECORDS=PARAMS['max_records_per_chunk'],MAX_TRADE_IDS=PARAMS['max_ids_per_chunk']),
        inventory.capture:dict(SELECTED=rolling.SELECTED,HARD_BYTES=inventory.RAW_CAP,METADATA_MAX_BYTES=131072)}
    saved={module:{k:getattr(module,k) for k in values} for module,values in replacements.items()}
    original_common,original_trade=ordinary._common,ordinary._trade
    def common(row,*args,**kwargs):
        result=original_common(row,*args,**kwargs)
        if row.get('channel')=='order_book':result['book_snapshot']=(row.get('payload') or {}).get('type')=='subscribed/order_book'
        return result
    def trade(row,raw,*args,**kwargs):
        result=original_trade(row,raw,*args,**kwargs)
        qty=number(raw['size'])
        if qty<=0:raise ValueError('invalid_exact_ordinary_quantity')
        return dict(result,qty=str(qty))
    try:
        for module,values in replacements.items():
            for k,v in values.items():setattr(module,k,v)
        ordinary._common=common;ordinary._trade=trade;yield
    finally:
        ordinary._common=original_common;ordinary._trade=original_trade
        for module,values in saved.items():
            for k,v in values.items():setattr(module,k,v)

def funding_crosses(now,p=PARAMS):return (now//(3600*NS)+1)*(3600*NS)<=now+p['maximum_profile_span_ns']
def quantity(market,book,N):
    step=number(market['qty_step']);ask=number(book['asks'][0][0])
    return (N/(ask*number(PARAMS['sizing_headroom']))/step).to_integral_value(rounding=ROUND_FLOOR)*step
def quote_value(book,market,q,side,N,*,entry):
    if not grid(q,number(market['qty_step'])) or q<number(market['min_qty']):return None,'native_minimum_reject'
    if market.get('max_qty') is not None and q>number(market['max_qty']):return None,'maximum_quantity_reject'
    value=sweep(book,side,q)
    if value is None:return None,'insufficient_depth'
    if value<number(market['min_notional']):return None,'native_minimum_notional_reject'
    if market.get('max_quote') is not None and value>number(market['max_quote']):return None,'maximum_quote_reject'
    if entry and value>N:return None,'entry_quote_above_cap'
    return value,None
def fee_rate(market):
    fee=number(market['taker_fee_bps'])
    if fee<0:raise ValueError('negative_taker_fee')
    return fee/D(10000)
def decision_profiles(book,market,p=PARAMS):
    profiles=[];costs={}
    try:bbo=native_book(book,market);native_error=None
    except (ValueError,KeyError,IndexError) as exc:bbo=None;native_error=str(exc)
    for target in p['notionals']:
        N=number(target);q=quantity(market,book,N) if native_error is None else D(0)
        buys={};values={}
        for side in (1,-1):
            value,failure=(None,'decision_native_book_failure') if native_error else quote_value(book,market,q,side,N,entry=True)
            values[side]=value;buys[side]=failure
            profiles.append(dict(target=target,direction=side,quantity=str(q),
                maximum_base_quantity_unknown=bool(market.get('maximum_base_quantity_unknown',market.get('max_qty') is None)),
                status='pending_entry' if failure is None else failure,decision_value=None if value is None else str(value)))
        if native_error or any(buys.values()):costs[target]=dict(failure=native_error or next(v for v in buys.values() if v))
        else:
            spread=values[1]-values[-1];fees=(values[1]+values[-1])*fee_rate(market)
            capital=N*number(p['annual_capital_rate'])*D(p['maximum_profile_span_ns'])/(NS*p['year_seconds'])
            costs[target]=dict(failure=None,quantity=str(q),mid=str(midpoint(bbo)),spread_cash=str(spread),
                estimated_fee_cash=str(fees),estimated_capital_cash=str(capital))
    return profiles,costs

def predict(cell,features,model):
    fit=cell['models'][model]
    if fit['status']!='available':return None
    xs=[(features[i]-cell['means'][i])/cell['scales'][i] for i in fit['columns']]
    value=fit['coefficients'][0]+sum(a*b for a,b in zip(fit['coefficients'][1:],xs))
    if not math.isfinite(value):raise ValueError('nonfinite_frozen_prediction')
    return value
def policies(cell,features,costs):
    result={}
    for model in ('baseline','augmented'):
        forecast=predict(cell,features,model) if cell is not None else None
        for target in PARAMS['notionals']:
            c=costs[target];direction=None if forecast is None else (1 if forecast>0 else -1 if forecast<0 else 0)
            row=dict(predicted_y=forecast,direction=direction,admitted=False,score_cash=None)
            if forecast is None:row['status']='model_unavailable'
            elif direction==0:row['status']='zero_forecast'
            elif c['failure']:row['status']='decision_cost_failure'
            else:
                score=number(abs(forecast))*number(c['quantity'])*number(c['mid'])/10000
                score-=sum((number(c[k]) for k in ('spread_cash','estimated_fee_cash','estimated_capital_cash')),D(0))
                row.update(score_cash=str(score),admitted=score>0,status='admitted' if score>0 else 'nonpositive_predicted_cash')
            result[model+':'+target]=row
    return result

class Study:
    def __init__(self,metadata,start,chunk,models=None,assets=ASSETS,p=PARAMS):
        self.metadata=metadata;self.start=start;self.chunk=chunk;self.models=models;self.assets=assets;self.p=p
        self.features=QueueFeatures(metadata,p);self.books={};self.rows=[];self.pending=defaultdict(list)
        self.next_anchor=start+p['anchor_start_seconds']*NS;self.profile_count=0;self.last_group=None
    def anchor(self,now):
        slot=(now-self.start-self.p['anchor_start_seconds']*NS)//(self.p['anchor_step_seconds']*NS)
        for asset in self.assets:
            for venue in VENUES:
                key=(asset,venue);feature,failure=self.features.at(asset,venue,now)
                row=dict(chunk=self.chunk,slot=slot,asset=asset,venue=venue,decision_ns=now,features=feature,
                    feature_failure=failure,label_status='feature_unavailable' if failure else 'pending_entry',label=None,
                    profiles=[],decision_costs={},policies={})
                self.rows.append(row)
                if funding_crosses(now,self.p):row['label_status']='funding_excluded';continue
                if failure:continue
                book=self.books.get(key)
                if book is None:row['label_status']='decision_book_missing';continue
                market=self.metadata[venue][asset]
                row['profiles'],row['decision_costs']=decision_profiles(book,market,self.p)
                self.profile_count+=len(row['profiles'])
                if self.profile_count>self.p['max_profiles_per_chunk']:raise ValueError('profile_count_cap')
                if self.models is not None:
                    row['policies']=policies(self.models['cells'][asset+':'+venue],feature['values'],row['decision_costs'])
                row.update(generation=book['generation'],decision_mid=str(midpoint(native_bbo(book,market))),
                    decision_book_received_ns=book['received_ns'],decision_book_source_ns=book['source_ns'],
                    due_ns=now+self.p['entry_delay_ns'])
                self.pending[key].append(row)
    def fire(self,now,inclusive=False):
        stop=self.start+self.p['anchor_stop_seconds_inclusive']*NS
        while self.next_anchor<=stop and (self.next_anchor<now or inclusive and self.next_anchor==now):
            self.anchor(self.next_anchor);self.next_anchor+=self.p['anchor_step_seconds']*NS
    def fail(self,row,status):
        row['failed_label_stage']=row['label_status'];row['label_status']=status
        for profile in row['profiles']:
            if profile['status'] in ('pending_entry','pending_exit'):
                profile['failed_stage']=profile['status'];profile['status']=status
    def process(self,event):
        kind=event['type'];now=event['received_ns'];key=(event.get('asset'),event.get('venue'))
        self.features.process(event)
        if kind=='end':
            for rows in self.pending.values():
                for row in rows:self.fail(row,'unresolved_at_end')
            self.pending.clear();return
        if kind=='invalidate' and event['scope']=='book':
            self.books.pop(key,None)
            for row in self.pending.pop(key,[]):self.fail(row,'invalidated')
        if kind!='book' or key[0] not in self.metadata.get(key[1],{}):return
        if event.get('book_snapshot'):
            for row in self.pending.pop(key,[]):self.fail(row,'snapshot_reset')
        market=self.metadata[key[1]][key[0]]
        try:native_bbo(event,market)
        except (ValueError,KeyError,IndexError):
            self.books.pop(key,None)
            for row in self.pending.pop(key,[]):self.fail(row,'invalid_native_bbo')
            return
        self.books[key]=event;keep=[];bbo=None;native_error=None;validated=False
        for row in self.pending[key]:
            if now<row['due_ns'] or event['source_ns']<row['due_ns']:keep.append(row);continue
            failure=None
            if now>row['due_ns']+self.p['max_execution_lateness_ns'] or not fresh(event,now,self.p['book_age_ns']):failure='missing_first_eligible'
            elif event['generation']!=row['generation'] or event.get('book_snapshot'):failure='generation_or_snapshot_changed'
            if not failure:
                if not validated:
                    try:bbo=native_book(event,market)
                    except (ValueError,KeyError,IndexError) as exc:native_error=str(exc)
                    validated=True
                if native_error:failure='endpoint_native_book_failure'
            if failure:self.fail(row,failure);continue
            entry=row['label_status']=='pending_entry';mid=midpoint(bbo)
            observation=dict(received_ns=now,source_ns=event['source_ns'],midpoint=str(mid))
            if entry:
                row.update(entry=observation,label_status='pending_exit',due_ns=now+self.p['hold_ns']+self.p['exit_delay_ns'],
                    movement_consumed_bps=str(D(10000)*(mid-number(row['decision_mid']))/number(row['decision_mid'])))
            else:
                row.update(exit=observation,label_status='complete',label=float(D(10000)*(mid-number(row['entry']['midpoint']))/number(row['entry']['midpoint'])))
            for profile in row['profiles']:
                if profile['status']!=('pending_entry' if entry else 'pending_exit'):continue
                N=number(profile['target']);q=number(profile['quantity']);side=profile['direction'] if entry else -profile['direction']
                value,why=quote_value(event,market,q,side,N,entry=entry)
                if why:profile.update(failed_stage=profile['status'],status=why);continue
                if entry:profile.update(entry_value=str(value),entry_received_ns=now,status='pending_exit')
                else:
                    old=number(profile['entry_value']);gross=D(profile['direction'])*(value-old)
                    fees=(old+value)*fee_rate(market)
                    capital=N*number(self.p['annual_capital_rate'])*D(now-profile['entry_received_ns'])/(NS*self.p['year_seconds'])
                    net=gross-fees-capital
                    profile.update(status='complete',exit_value=str(value),exit_received_ns=now,gross_cash=str(gross),
                        fee_cash=str(fees),capital_cash=str(capital),net_cash=str(net),net_bps=str(net/old*10000),
                        stressed_cash={str(bp):str(net-old*D(bp)/10000) for bp in self.p['extra_cost_stress_bps']})
            if entry:keep.append(row)
        self.pending[key]=keep
    def process_group(self,group):
        if not group:return
        now=group[0]['received_ns']
        if any(e['received_ns']!=now for e in group) or self.last_group is not None and now<self.last_group:
            raise ValueError('receipt_group_order')
        self.fire(now)
        for event in group:self.process(event)
        self.fire(now,inclusive=True);self.last_group=now
    def result(self):
        expected=28*len(self.assets)*len(VENUES)
        if len(self.rows)!=expected:raise ValueError('calendar_denominator_differs')
        return dict(chunk=self.chunk,scheduled_anchors=expected,anchors=self.rows,feature_counts=dict(self.features.counts))

def fit_models(chunks):
    import numpy as np
    if tuple(x['chunk'] for x in chunks)!=FIT:raise ValueError('fit_chunk_identity')
    cells={}
    for asset in ASSETS:
        for venue in VENUES:
            selected=[r for c in chunks for r in c['anchors'] if r['asset']==asset and r['venue']==venue
                and r['feature_failure'] is None and r['label_status']=='complete']
            cell=dict(training_ids=[FIT.index(r['chunk'])*28+r['slot'] for r in selected],
                training_labels=len(selected),means=None,scales=None,models={})
            if len(selected)<PARAMS['minimum_training_labels']:
                cell['models']={name:dict(status='insufficient_training_labels') for name in ('baseline','augmented')}
                cells[asset+':'+venue]=cell;continue
            X=np.asarray([r['features']['values'] for r in selected],dtype=float)
            y=np.asarray([r['label'] for r in selected],dtype=float)
            if X.shape!=(len(selected),len(FEATURES)) or not np.isfinite(X).all() or not np.isfinite(y).all():
                raise ValueError('nonfinite_fit_matrix')
            means=X.mean(axis=0);scales=X.std(axis=0,ddof=0);constant=np.all(X==X[0],axis=0)
            cell['means']=means.tolist();cell['scales']=scales.tolist();cell['constant_columns']=np.flatnonzero(constant).tolist()
            for name,width in (('baseline',5),('augmented',6)):
                columns=[i for i in range(width) if not constant[i]]
                if any(scales[i]<=0 for i in columns):raise ValueError('invalid_nonconstant_scale')
                design=np.column_stack([np.ones(len(X)),(X[:,columns]-means[columns])/scales[columns]])
                coefficients,_,rank,singular=np.linalg.lstsq(design,y,rcond=PARAMS['ols_rcond'])
                condition=float(singular[0]/singular[-1]) if singular[-1]>0 else math.inf
                status='available'
                if rank!=design.shape[1]:status='rank_deficient'
                elif not math.isfinite(condition) or condition>PARAMS['maximum_design_condition_number']:status='condition_number_exceeded'
                result=dict(status=status,columns=columns,rank=int(rank),design_columns=design.shape[1],
                    condition=None if not math.isfinite(condition) else condition)
                if status=='available':
                    if not np.isfinite(coefficients).all():raise ValueError('nonfinite_fit_coefficient')
                    result['coefficients']=coefficients.tolist()
                cell['models'][name]=result
            cells[asset+':'+venue]=cell
    return dict(schema='single-venue-queue-ofi-model-v1',features=list(FEATURES),fit_chunks=list(FIT),
        training_id_encoding='fit_chunk_index*28+calendar_slot',ols_rcond=PARAMS['ols_rcond'],
        numpy_version=np.__version__,python_version=platform.python_version(),cells=cells)

def profile_for(row,target,direction):
    return next((r for r in row['profiles'] if r['target']==target and r['direction']==direction),None)
def policy_observation(row,model,target):
    policy=row['policies'].get(model+':'+target)
    if policy is None:return dict(admitted=False,status=row['label_status'],cash=D(0),stressed={str(bp):D(0) for bp in PARAMS['extra_cost_stress_bps']})
    if not policy['admitted']:return dict(admitted=False,status=policy['status'],cash=D(0),stressed={str(bp):D(0) for bp in PARAMS['extra_cost_stress_bps']})
    profile=profile_for(row,target,policy['direction'])
    if profile is None or profile['status']!='complete':
        return dict(admitted=True,status='missing_profile' if profile is None else profile['status'],cash=None,stressed=None)
    return dict(admitted=True,status='complete',cash=number(profile['net_cash']),stressed={k:number(v) for k,v in profile['stressed_cash'].items()},profile=profile)
def average(values):return None if not values else sum(values)/len(values)
def evaluation_summary(chunks,models):
    if tuple(c['chunk'] for c in chunks)!=EVALUATION:raise ValueError('evaluation_chunk_identity')
    rows=[]
    for asset in ASSETS:
        for venue in VENUES:
            cell=models['cells'][asset+':'+venue]
            for target in PARAMS['notionals']:
                by_chunk=[]
                for chunk in chunks:
                    original=[r for r in chunk['anchors'] if (r['asset'],r['venue'])==(asset,venue)]
                    if len(original)!=28:raise ValueError('summary_calendar_denominator')
                    paired=[]
                    for r in original:
                        if r['label_status']=='complete' and all(r['policies'].get(m+':'+target,{}).get('predicted_y') is not None for m in ('baseline','augmented')):
                            paired.append(r)
                    forecast={}
                    for model in ('baseline','augmented'):
                        errors=[r['policies'][model+':'+target]['predicted_y']-r['label'] for r in paired]
                        signed=[(1 if r['policies'][model+':'+target]['predicted_y']>0 else -1 if r['policies'][model+':'+target]['predicted_y']<0 else 0)*r['label'] for r in paired]
                        forecast[model]=dict(paired_labels=len(paired),mse=average([e*e for e in errors]),
                            mae=average([abs(e) for e in errors]),mean_signed_remaining_midpoint_bps=average(signed))
                    policies_summary={};observations={}
                    for model in ('baseline','augmented'):
                        obs=[policy_observation(r,model,target) for r in original];observations[model]=obs
                        completed=[x for x in obs if x['admitted'] and x['cash'] is not None]
                        unknown=any(x['cash'] is None for x in obs)
                        total=None if unknown else sum((x['cash'] for x in obs),D(0))
                        policies_summary[model]=dict(statuses=dict(Counter(x['status'] for x in obs)),
                            scheduled=len(obs),admitted=sum(x['admitted'] for x in obs),admitted_complete=len(completed),
                            admitted_unknown=sum(x['cash'] is None for x in obs),all_calendar_cash_sum=total,
                            all_calendar_cash_mean=None if total is None else total/len(obs),
                            complete_mean_net_cash=average([x['cash'] for x in completed]),
                            complete_cash={k:sum((number(x['profile'][k]) for x in completed),D(0)) for k in ('gross_cash','fee_cash','capital_cash','net_cash')},
                            complete_mean_net_bps=average([number(x['profile']['net_bps']) for x in completed]),
                            all_calendar_stressed_cash_sum={str(bp):None if unknown else sum((x['stressed'][str(bp)] for x in obs),D(0)) for bp in PARAMS['extra_cost_stress_bps']})
                    b,a=policies_summary['baseline'],policies_summary['augmented']
                    differences=[a0['cash']-b0['cash'] for a0,b0 in zip(observations['augmented'],observations['baseline']) if a0['cash'] is not None and b0['cash'] is not None]
                    gate=bool(all(cell['models'][m]['status']=='available' for m in ('baseline','augmented'))
                        and forecast['augmented']['mse'] is not None and forecast['augmented']['mse']<forecast['baseline']['mse']
                        and a['admitted_complete']>=3 and a['admitted_unknown']==0 and a['complete_mean_net_cash']>0
                        and a['all_calendar_cash_sum'] is not None and b['all_calendar_cash_sum'] is not None
                        and a['all_calendar_cash_sum']>b['all_calendar_cash_sum'])
                    by_chunk.append(dict(chunk=chunk['chunk'],feature_statuses=dict(Counter(r['feature_failure'] or 'usable' for r in original)),
                        label_statuses=dict(Counter(r['label_status'] for r in original)),forecast=forecast,policies=policies_summary,
                        paired_policy_known=len(differences),paired_known_cash_delta_sum=sum(differences,D(0)),
                        all_calendar_cash_delta=None if a['all_calendar_cash_sum'] is None or b['all_calendar_cash_sum'] is None else a['all_calendar_cash_sum']-b['all_calendar_cash_sum'],advance_gate=gate))
                pooled={}
                for model in ('baseline','augmented'):
                    members=[c['policies'][model] for c in by_chunk];unknown=sum(x['admitted_unknown'] for x in members)
                    fmembers=[c['forecast'][model] for c in by_chunk];labels=sum(x['paired_labels'] for x in fmembers)
                    completes=sum(x['admitted_complete'] for x in members)
                    cash={k:sum((x['complete_cash'][k] for x in members),D(0)) for k in ('gross_cash','fee_cash','capital_cash','net_cash')}
                    total=None if unknown else sum((x['all_calendar_cash_sum'] for x in members),D(0))
                    pooled[model]=dict(scheduled=84,admitted=sum(x['admitted'] for x in members),
                        admitted_complete=completes,admitted_unknown=unknown,all_calendar_cash_sum=total,
                        all_calendar_cash_mean=None if total is None else total/84,complete_cash=cash,
                        complete_mean_net_cash=None if not completes else cash['net_cash']/completes,
                        statuses=dict(sum((Counter(x['statuses']) for x in members),Counter())),
                        forecast=dict(paired_labels=labels,**{k:None if not labels else sum(x[k]*x['paired_labels'] for x in fmembers if x['paired_labels'])/labels for k in ('mse','mae','mean_signed_remaining_midpoint_bps')}),
                        all_calendar_stressed_cash_sum={str(bp):None if unknown else sum((x['all_calendar_stressed_cash_sum'][str(bp)] for x in members),D(0)) for bp in PARAMS['extra_cost_stress_bps']})
                rows.append(dict(asset=asset,venue=venue,target=target,collateral='USDC' if venue=='lighter' else 'USDG',
                    models={m:cell['models'][m]['status'] for m in ('baseline','augmented')},chunks=by_chunk,pooled=pooled,
                    decision='exploratory_followup_candidate' if all(c['advance_gate'] for c in by_chunk) else 'park_or_insufficient_coverage'))
    if len(rows)!=60:raise ValueError('policy_cell_denominator')
    return dict(schema='single-venue-queue-ofi-summary-v1',validation_claim=False,rows=rows,
        limitations='All inputs exploratory. Conditional displayed quote values are not fills, impact-adjusted executions or a portfolio. Independent cells and sizes cannot be summed. Chronological fitting does not create independent regime replication.')

def source_pins(pins):
    if not pins:raise ValueError('source_pins_missing')
    for pin in pins:
        relative=Path(pin['path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('unsafe_source_pin')
        path=ROOT/relative;rolling.regular(path)
        if digest(path)!=pin['sha256']:raise ValueError('frozen_source_pin_changed '+pin['path'])
def verify():
    plan=rolling.read_json(PLAN,CAPS['protocol'])
    if plan.get('status')!='frozen':raise ValueError('queue_protocol_not_frozen')
    if plan.get('schema')!='single-venue-queue-ofi-v1' or plan['parameters']!=PARAMS or plan['output_caps']!=CAPS:
        raise ValueError('frozen_queue_specification_differs')
    if plan['fit_chunks']!=list(FIT) or plan['evaluation_chunks']!=list(EVALUATION) or plan['features']['baseline']!=list(FEATURES[:5]):
        raise ValueError('frozen_feature_or_chunk_identity_differs')
    if plan['output_root']!='reports/single-venue-research/queue-ofi-v1' or plan['store_root']!='data/rolling/market-research-v1' or plan['pin_owner']!='inventory_context_v1':
        raise ValueError('fixed_paths_or_owner_differ')
    if plan['runtime_requirements']!={'python':'3.13.9','numpy':'2.5.3'} or platform.python_version()!='3.13.9':raise ValueError('frozen_python_runtime_differs')
    import numpy as np
    if np.__version__!='2.5.3':raise ValueError('frozen_numpy_runtime_differs')
    direct=[pin['path'] for pin in plan['source_pins']]
    required={'scripts/single_venue_queue_ofi.py','tests/test_single_venue_queue_ofi.py'}
    if len(set(direct))!=len(direct) or not required.issubset(direct):raise ValueError('unique_own_source_and_test_pins_required')
    source_pins(plan['source_pins'])
    validation_path=ROOT/plan['input_validation_plan']
    if plan['input_validation_plan']!='reports/experiment-storage/single-venue-inventory-context-ordinary-feed-fix-v1.json' or plan['input_validation_plan_sha256']!=VALIDATION_SHA or digest(validation_path)!=VALIDATION_SHA:
        raise ValueError('inventory_validation_plan_changed')
    validation=rolling.read_json(validation_path,16384)
    if len(validation['source_pins'])!=45:raise ValueError('transitive_pin_inventory_changed')
    source_pins(validation['source_pins'])
    reference=validation['method_reference']
    if reference['path']!='reports/experiment-storage/single-venue-inventory-context-v1.json' or reference['sha256']!=METHOD_SHA or digest(ROOT/reference['path'])!=METHOD_SHA:
        raise ValueError('original_inventory_method_changed')
    if digest(rolling.PLAN)!=validation['capture_parent_plan_sha256']:raise ValueError('capture_parent_plan_changed')
    return plan,validation
def stream_chunk(record,models=None):
    directory=Path(record['capture']);metadata=rolling.read_json(directory/'metadata/normalized.json',131072)['markets']
    study=Study(metadata,record['started_ns'],record['chunk'],models=models)
    group=[];last=None;terminal=None
    with adapter_configuration():
        for event in ordinary.iter_events(directory,expected_manifest_sha256=record['manifest_sha256'],
                expected_raw_sha256=record['raw_sha256'],max_raw_bytes=inventory.RAW_CAP,
                max_decoded_bytes=PARAMS['max_decoded_bytes_per_chunk'],max_records=PARAMS['max_records_per_chunk'],max_ids=PARAMS['max_ids_per_chunk']):
            now=event['received_ns']
            if last is not None and now!=last:study.process_group(group);group=[]
            if len(group)>=PARAMS['max_same_receipt_events']:raise ValueError('same_receipt_group_cap')
            group.append(event);last=now
            if event['type']=='end':terminal=event
        study.process_group(group)
    if terminal is None or terminal['truncated'] or terminal['reason']!='duration_limit':raise ValueError('unverified_complete_capture')
    result=study.result();result['adapter']={k:terminal[k] for k in ('decoded_bytes','archive_bytes','counts','metadata_sha256',
        'raw_gzip_sha256','manifest_sha256','max_receipt_gap_ns')}
    return result
def run():
    plan,validation=verify();plan_hash=digest(PLAN);out=ROOT/plan['output_root']
    out.mkdir(parents=True,exist_ok=False)
    publish(out/'started.json',dict(started_utc=utc(),plan_sha256=plan_hash,state='fit',no_retry=True),4096)
    store=rolling.Store(ROOT/plan['store_root'])
    def snapshot():
        with store.locked():return {str(batch):inventory.check_inputs(store,validation,batch) for batch in (1,2)}
    before=None;outputs={};model_hash=None
    def recheck():
        verify()
        if digest(PLAN)!=plan_hash or snapshot()!=before:raise ValueError('frozen_source_or_input_changed')
    def save(name,value,cap,compressed=False,decoded_cap=None):
        recheck();outputs[name]=publish(out/name,value,cap,compressed=compressed,decoded_cap=decoded_cap)
    def control(name,value):
        existing=sum((out/n).stat().st_size for n in ('started.json','model-sha.json','terminal.json') if (out/n).exists())
        if existing+len(encode(value))>CAPS['control']:raise ValueError('total_control_byte_cap')
        return publish(out/name,value,4096)
    try:
        before=snapshot()
        fit=[]
        for record in before['1']['inputs']:
            result=stream_chunk(record);fit.append(result)
            save(record['chunk']+'.json.gz',result,CAPS['gzip_per_chunk'],True)
        model=fit_models(fit);model.update(plan_sha256=plan_hash,created_utc=utc())
        save('model.json',model,CAPS['model']);model_hash=outputs['model.json']
        # Publish exact model and hash before decoding any evaluation raw records.
        recheck();outputs['model-sha.json']=control('model-sha.json',dict(model_sha256=model_hash,plan_sha256=plan_hash))
        model=rolling.read_json(out/'model.json',CAPS['model'])
        if digest(out/'model.json')!=model_hash:raise ValueError('published_model_changed')
        evaluation=[]
        for record in before['2']['inputs']:
            if digest(out/'model.json')!=model_hash:raise ValueError('published_model_changed')
            result=stream_chunk(record,models=model);evaluation.append(result)
            save(record['chunk']+'.json.gz',result,CAPS['gzip_per_chunk'],True)
        summary=evaluation_summary(evaluation,model);summary.update(plan_sha256=plan_hash,model_sha256=model_hash)
        save('summary.json.gz',summary,CAPS['summary'],True,2097152)
        save('provenance.json',dict(schema='single-venue-queue-ofi-provenance-v1',plan_sha256=plan_hash,
            model_sha256=model_hash,source_pins=plan['source_pins'],transitive_validation_plan_sha256=VALIDATION_SHA,
            inputs=before,outputs=dict(outputs),summary_encoding='gzip JSON; decoded cap 2097152 bytes'),CAPS['provenance'])
        recheck()
        control('terminal.json',dict(state='finished',success=True,ended_utc=utc(),model_sha256=model_hash,
            output_count=len(outputs),plan_sha256=plan_hash))
    except Exception as exc:
        control('terminal.json',dict(state='finished',success=False,ended_utc=utc(),plan_sha256=plan_hash,
            model_sha256=model_hash,error=type(exc).__name__+': '+str(exc)[:2000]))
        raise
def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('verify','run'):raise SystemExit('usage: single_venue_queue_ofi.py verify|run')
    globals()[sys.argv[1]]()
if __name__=='__main__':main()
