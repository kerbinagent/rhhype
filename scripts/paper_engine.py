"""Deterministic event-driven paper execution; no exchange order endpoints."""
from __future__ import annotations

import copy
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_FLOOR
import math
import time
from collections import Counter, defaultdict, deque
from monitor import common_step, affordable_quantity, walk


@dataclass
class EngineConfig:
    notional: float = 1000.0
    capital_usd: float = 20000.0
    margin_fraction: float = 1.0
    max_positions: int = 10
    max_matched_notional: float = 10000.0
    holding_seconds: float = 300.0
    network_delay_ms: float = 100.0
    hl_processing_ms: float = 50.0
    aster_processing_ms: float = 50.0
    fill_timeout_seconds: float = 3.0
    max_book_age: float = 2.0
    max_skew: float = 1.0
    max_divergence_bps: float = 500.0
    entry_slippage_bps: float = 10.0
    extra_cost_bps: float = 5.0
    capital_rate: float = 0.05
    signal_interval: float = 0.1
    episode_gap_seconds: float = 5.0
    evidence_levels: int = 100
    metadata_max_age: float = 7200.0
    strategies: tuple = ('standard', 'plus', 'premium')
    latency_probes_ms: tuple = (100, 300, 500, 1000)


def key(m):
    return f"{m['venue']}:{m['market']}"


def scenario_fee(m, strategy):
    if m['venue'] in ('lighter', 'rh_lighter'):
        fee = {'standard': 0, 'plus': .5,
               'premium': 3.5 if m['venue']=='rh_lighter' else 2.8}[strategy]
        # Public market fee floor, not the discovery account's hypothetical tier.
        return max(fee, float(m.get('published_fee_floor_bps', 0)))
    return float(m['fee_bps'])


def taker_delay(m, strategy, config):
    if m['venue'] in ('lighter','rh_lighter'):
        venue_ms = (200 if m['venue']=='rh_lighter' else 140) if strategy=='premium' else 300
    elif m['venue']=='hyperliquid': venue_ms=config.hl_processing_ms
    else: venue_ms=config.aster_processing_ms
    return (config.network_delay_ms+venue_ms)/1000


def valid_book(b, now, config):
    if not b or not b.get('valid') or not b.get('bids') or not b.get('asks'): return False
    if not -0.1 <= now-b['received'] <= config.max_book_age: return False
    engine=b.get('engine_time')
    if engine is not None and not -2 <= now-engine <= config.max_book_age: return False
    return b['bids'][0][0]<b['asks'][0][0]


def available_fill(levels, desired, step, price_limit=None, buy=True):
    """IOC-style partial execution at displayed depth, rounded to venue lot size."""
    eligible=[]
    for p,q in levels:
        if price_limit is not None and ((buy and p>price_limit) or (not buy and p<price_limit)): break
        eligible.append((p,q))
    available=min(desired,sum(q for _,q in eligible))
    step=Decimal(str(step))
    qty=float((Decimal(str(available))/step).to_integral_value(rounding=ROUND_FLOOR)*step)
    if desired-qty < max(1e-10,desired*1e-10):qty=desired
    if qty<=0:return 0.0,0.0,levels
    value=walk(eligible,qty)
    if value is None:return 0.0,0.0,levels
    left=qty;remaining=[]
    for p,q in levels:
        taken=min(left,q);left-=taken
        if q-taken>1e-12:remaining.append((p,q-taken))
    return qty,value,remaining


class PaperEngine:
    """Three independent portfolios; one position per undirected pair/strategy."""
    def __init__(self, pairs, config=None, state=None, now=None):
        self.config=config or EngineConfig()
        self.pairs={self.pair_id(p):p for p in pairs}
        self.books={};self.dirty=set();self.last_evaluation={}
        self.stats=Counter();self.transitions=[];self.signals=[];self.evidence=[]
        self.positions={};self.finished=[];self.sequence=0
        self.episodes={};self.episode_history=deque(maxlen=2000)
        self.probes={};self.probe_stats=defaultdict(lambda:Counter())
        self.probe_stats_by_strategy=defaultdict(lambda:Counter())
        self.episode_sequence=0
        self.top_signals={}
        self.last_processed=now or time.time()
        venues=sorted({m['venue'] for p in pairs for m in (p['hl'],p['other'])}) or ['hyperliquid','rh_lighter','lighter','aster']
        self.ledgers={s:{'initial_capital':self.config.capital_usd,
            'wallets':{v:self.config.capital_usd/len(venues) for v in venues},
            'closed_pnl_exact':0.0,'closed_pnl_estimated':0.0,'closed_trades':0,
            'estimated_trades':0,'aborted_trades':0,'fees_usd':0.0,'funding_usd':0.0,
            'other_costs_usd':0.0,'capital_costs_usd':0.0,'entry_attempts':0} for s in self.config.strategies}
        for ledger in self.ledgers.values():
            for quality in ('exact','estimated'):
                ledger.update({f'closed_profit_sum_{quality}':0.0,
                               f'closed_loss_sum_{quality}':0.0,
                               f'closed_wins_{quality}':0,
                               f'closed_losses_{quality}':0})
        self.market_pairs=defaultdict(set)
        self._index_pairs()
        if state:self.restore(state)

    @staticmethod
    def pair_id(pair):
        return f"{pair['asset']}|{key(pair['hl'])}|{key(pair['other'])}"

    def _index_pairs(self):
        self.market_pairs.clear()
        self.market_meta={}
        for ident,p in self.pairs.items():
            for m in (p['hl'],p['other']):
                self.market_pairs[key(m)].add(ident)
                self.market_meta[key(m)]=m

    def update_pairs(self,pairs):
        previous=set(self.pairs)
        self.pairs={self.pair_id(p):p for p in pairs};self._index_pairs()
        removed=previous-set(self.pairs)
        if removed:
            now=time.time()
            for ident in removed:self._censor_pair(ident,now)
            for pid,p in list(self.probes.items()):
                if p['pair_id'] in removed:self._finish_probe(pid,'missing','pair_removed')
        keep=set(self.market_pairs)|{leg['key'] for p in self.positions.values() for leg in p['legs']}
        self.books={k:v for k,v in self.books.items() if k in keep}
        self.last_evaluation={k:v for k,v in self.last_evaluation.items() if k in self.pairs}
        self.dirty.intersection_update(self.pairs);self.dirty.update(self.pairs)

    def _reserved(self,strategy,venue):
        return sum(p['reserved'].get(venue,0) for p in self.positions.values() if p['strategy']==strategy)

    def _unrealized_for_venue(self,strategy,venue,now):
        total=0
        for p in self.positions.values():
            if p['strategy']!=strategy:continue
            for leg in p['legs']:
                if leg['venue']!=venue or leg['remaining']<=0:continue
                b=self.books.get(leg['key'])
                if not valid_book(b,now,self.config):return None
                val=walk(b['bids'] if leg['side']=='long' else b['asks'],leg['remaining'])
                if val is None:return None
                total+=(val-leg['entry_vwap']*leg['remaining'])*(1 if leg['side']=='long' else -1)
        return total

    def cash_available(self,strategy,venue,now):
        ledger=self.ledgers[strategy]
        unrealized=self._unrealized_for_venue(strategy,venue,now)
        if unrealized is None:return None
        funding_reserve=0.0
        boundary=int(now//3600)*3600
        for p in self.positions.values():
            if p['strategy']!=strategy or not any(l['venue']==venue for l in p['legs']):continue
            crossed=any(l['entry_time'] is not None and l['entry_time']<boundary for l in p['legs'])
            if not crossed:continue
            funding=p.get('funding') if p['status']=='AWAITING_FUNDING' else p.get('open_funding')
            if (not funding or not funding.get('complete') or
                    (p['status']!='AWAITING_FUNDING' and funding.get('covered_until',0)<boundary)):
                return None
            events=funding.get('events',[])
            if abs(sum(e.get('cashflow_usd',0) for e in events)-funding['cashflow_usd'])>1e-7:return None
            funding_reserve+=sum(min(0,float(e['cashflow_usd'])) for e in events if e.get('venue')==venue)
        return ledger['wallets'].get(venue,0)-self._reserved(strategy,venue)+min(0,unrealized)+funding_reserve

    def _cancel_entry(self,p,now,reason):
        for leg in p['legs']:
            intent=leg.get('intent')
            if intent and intent['kind']=='entry':
                leg['intent']=None
                leg['entry_result']=reason
        self._transition(p,now)

    def receive(self,book):
        """Called for every feed event: delayed orders see the first eligible new book."""
        now=book['received'];k=f"{book['venue']}:{book['market']}"
        old=self.books.get(k)
        if old and book.get('valid') and old.get('valid') and now<old['received']:
            self.stats['out_of_order_receipts']+=1;return
        if (old and book.get('valid') and old.get('valid')
                and book.get('engine_time') is not None and old.get('engine_time') is not None
                and book['engine_time']<old['engine_time']):
            self.stats['out_of_order_engine_times']+=1;return
        self.books[k]=book;self.dirty.update(self.market_pairs.get(k,()))
        self.stats['book_events']+=1
        if not valid_book(book,now,self.config):
            self.stats['invalid_books']+=1
            self._probe_invalidate(k,'invalid_book')
            for p in list(self.positions.values()):
                for leg in p['legs']:
                    if leg['key']!=k:continue
                    intent=leg.get('intent')
                    if intent and intent['kind']=='entry':
                        self._cancel_entry(p,now,'book_invalidated')
                        break
                    if intent and intent['kind']=='exit':leg['intent']=None
            return
        # Each fee scenario is an independent counterfactual; within one scenario
        # reserve displayed liquidity across simultaneous hypothetical orders.
        remaining={s:{'bids':list(book['bids']),'asks':list(book['asks'])} for s in self.config.strategies}
        for p in list(self.positions.values()):
            if p['status']=='AWAITING_FUNDING':continue
            for leg in p['legs']:
                intent=leg.get('intent')
                if not intent and p['status']=='EXITING' and leg['key']==k and leg['remaining']>0:
                    self._exit_intent(p,leg,now)
                    continue
                if not intent or leg['key']!=k:continue
                if book.get('generation')!=intent.get('generation'):
                    self.stats['intent_generation_changed']+=1
                    if intent['kind']=='entry':
                        self._cancel_entry(p,now,'generation_changed')
                        break
                    leg['intent']=None
                    self._exit_intent(p,leg,now)
                    continue
                if now<intent['due'] or now>intent['expires']:continue
                if book.get('engine_time') is not None and book['engine_time']<intent['due']:
                    self.stats['pre_delay_source_books']+=1;continue
                self._fill(p,leg,intent,book,remaining[p['strategy']],now)
            self._transition(p,now)
        self._probe_update(k,now)

    def _fill(self,p,leg,intent,book,liquidity,now):
        entry=intent['kind']=='entry';buy=(leg['side']=='long') if entry else (leg['side']=='short')
        side='asks' if buy else 'bids'
        available_before=liquidity[side][:self.config.evidence_levels]
        limit=intent.get('price_limit') if entry else None
        q,value,remaining=available_fill(liquidity[side],intent['quantity'],leg['step'],limit,buy)
        if entry and (value<leg['min_notional'] or q<leg['min_qty']):q=value=0
        if entry and value>self.config.notional+1e-8:q=value=0
        current_meta=self.market_meta.get(leg['key'])
        fill_fee_bps=scenario_fee(current_meta,p['strategy']) if current_meta else leg['fee_bps']
        fee=value*fill_fee_bps/10000
        ledger=self.ledgers[p['strategy']]
        if q>0:
            liquidity[side]=remaining
            ledger['wallets'][leg['venue']]-=fee;ledger['fees_usd']+=fee
            leg['fees_usd']+=fee
            if entry:
                leg.update(quantity=q,remaining=q,entry_value=value,entry_vwap=value/q,entry_time=now,entry_fee=fee)
                leg['entry_fee_bps']=fill_fee_bps
                leg['entry_result']='filled' if q>=intent['quantity']-1e-9 else 'partial'
            else:
                pnl=(value-leg['entry_vwap']*q)*(1 if leg['side']=='long' else -1)
                ledger['wallets'][leg['venue']]+=pnl
                leg['price_pnl']+=pnl;leg['exit_value']+=value;leg['exit_fee']+=fee
                leg['remaining']=max(0,leg['remaining']-q)
                leg['exit_fills'].append({'timestamp':now,'quantity':q,'value':value,'fee':fee,
                                          'fee_bps':fill_fee_bps})
                if len(leg['exit_fills'])>256:
                    leg['exit_fills'].pop(0);p['funding_history_truncated']=True
                if leg['remaining']<=1e-9:leg['exit_time']=now
            self.stats['fills']+=1
            self.evidence.append((f"{p['id']}:{leg['venue']}:{intent['kind']}:{now}",
                {'position_id':p['id'],'leg':leg['key'],'intent':intent,'fill_quantity':q,'fill_value':value,
                 'fill_fee_bps':fill_fee_bps,'available_side_before_fill':available_before,
                 'book':self._book_evidence(book)},'fill',now))
        elif entry:leg['entry_result']='rejected'
        self.stats['partial_fills']+=int(0<q<intent['quantity']-1e-9)
        self.stats['unfilled_intents']+=int(q==0)
        leg['intent']=None
        if not entry and leg['remaining']>1e-9:self._exit_intent(p,leg,now)

    def _book_evidence(self,b):
        return {k:b.get(k) for k in ('venue','market','received','engine_time','sequence','generation','valid')} | {
            'bids':b.get('bids',[])[:self.config.evidence_levels], 'asks':b.get('asks',[])[:self.config.evidence_levels]}

    def _exit_intent(self,p,leg,now):
        b=self.books.get(leg['key'],{})
        delay=taker_delay(leg,p['strategy'],self.config)
        leg['intent']={'kind':'exit','quantity':leg['remaining'],'created':now,'due':now+delay,
                       'expires':now+delay+self.config.fill_timeout_seconds,'generation':b.get('generation')}

    def _transition(self,p,now):
        if p['status']=='ENTRY_PENDING' and all(leg.get('entry_result') for leg in p['legs']):
            quantities=[leg['quantity'] for leg in p['legs']]
            if all(leg['entry_result']=='filled' for leg in p['legs']) and abs(quantities[0]-quantities[1])<1e-9:
                p['status']='OPEN';p['opened_at']=now;p['exit_due']=now+self.config.holding_seconds
                self.stats['positions_opened']+=1
            elif any(quantities):
                p['status']='EXITING';p['exit_reason']='entry_failure';p['opened_at']=now
                self.stats['hedge_failures']+=1
                for leg in p['legs']:
                    if leg['remaining']>0:self._exit_intent(p,leg,now)
            else:
                p['status']='ABORTED';p['closed_at']=now
                self.ledgers[p['strategy']]['aborted_trades']+=1
                self.transitions.append(copy.deepcopy(p));self.positions.pop(p['id'],None)
                return
        if p['status']=='EXITING' and all(leg['remaining']<=1e-9 for leg in p['legs']):
            p['status']='AWAITING_FUNDING';p['closed_at']=now
            p['price_pnl']=sum(leg['price_pnl'] for leg in p['legs'])
            p['fees_usd']=sum(leg['fees_usd'] for leg in p['legs'])
            p['other_costs_usd']=self.config.extra_cost_bps/10000*max(leg['entry_value'] for leg in p['legs'])
            elapsed=sum((leg.get('exit_time',now)-leg['entry_time'])*leg['entry_value']*self.config.margin_fraction for leg in p['legs'] if leg['entry_time'] is not None)
            p['capital_costs_usd']=elapsed*self.config.capital_rate/(365*86400)
            charge=p['other_costs_usd']+p['capital_costs_usd']
            venue=p['legs'][0]['venue'];self.ledgers[p['strategy']]['wallets'][venue]-=charge
            self.ledgers[p['strategy']]['other_costs_usd']+=p['other_costs_usd']
            self.ledgers[p['strategy']]['capital_costs_usd']+=p['capital_costs_usd']
            p['price_net_before_funding']=p['price_pnl']-p['fees_usd']-charge
            p['funding']={'complete':False,'cashflow_usd':None,'missing':['pending settlement lookup']}
            self.transitions.append(copy.deepcopy(p))

    def tick(self,now):
        self.last_processed=now
        for p in list(self.positions.values()):
            if p['status']=='OPEN' and now>=p['exit_due']:
                p['status']='EXITING';p['exit_reason']='holding_period'
                for leg in p['legs']:self._exit_intent(p,leg,now)
            for leg in p['legs']:
                intent=leg.get('intent')
                if intent and now>intent['expires']:
                    self.stats['intent_timeouts']+=1;leg['intent']=None
                    if intent['kind']=='entry':leg['entry_result']='timeout'
                    elif leg['remaining']>0:self._exit_intent(p,leg,now)
            self._transition(p,now)
        dirty=list(self.dirty)
        for ident in dirty:
            if now-self.last_evaluation.get(ident,0)<self.config.signal_interval:continue
            self.dirty.discard(ident);self.last_evaluation[ident]=now
            p=self.pairs.get(ident)
            if not p:continue
            if now-p.get('metadata_timestamp',now)>self.config.metadata_max_age:
                self.stats['stale_metadata']+=1;self._censor_pair(ident,now);continue
            a,b=self.books.get(key(p['hl'])),self.books.get(key(p['other']))
            if not (valid_book(a,now,self.config) and valid_book(b,now,self.config)):
                self._censor_pair(ident,now);continue
            if abs(a['received']-b['received'])>self.config.max_skew:
                self.stats['skew_rejections']+=1;self._censor_pair(ident,now);continue
            am=(a['bids'][0][0]+a['asks'][0][0])/2;bm=(b['bids'][0][0]+b['asks'][0][0])/2
            if abs(bm/am-1)>self.config.max_divergence_bps/10000:
                self.stats['unit_or_price_divergence']+=1;self._censor_pair(ident,now);continue
            for strategy in self.config.strategies:
                candidates=[]
                for buy,sell,bb,sb in ((p['hl'],p['other'],a,b),(p['other'],p['hl'],b,a)):
                    signal=self._signal(p,buy,sell,bb,sb,strategy,now)
                    route=f"{strategy}|{p['asset']}|{key(buy)}|{key(sell)}"
                    self._track_signal(signal,ident,now,route)
                    if signal is not None:candidates.append(signal)
                for signal in sorted(candidates,key=lambda s:s['net_edge_usd'],reverse=True):
                    if signal['net_edge_usd']>0:
                        self._maybe_enter(p,ident,signal,strategy,now)
                        break
        # No events must not let an episode appear continuously executable.
        for route,e in list(self.episodes.items()):
            if now-e['last']>self.config.episode_gap_seconds:self._finish_episode(route,now,'data_gap')
        for pid,probe in list(self.probes.items()):
            if now>probe['due']+self.config.max_book_age:
                self._finish_probe(pid,'missing','timeout')

    def _signal(self,p,buy,sell,bb,sb,strategy,now,quantity=None):
        if quantity is None:
            budget=self.config.notional/(1+self.config.entry_slippage_bps/10000)
            affordable=affordable_quantity(bb['asks'],budget)
            if affordable is None:return None
            qmax=min(affordable,budget/sb['bids'][0][0])
            step=common_step(buy['step'],sell['step'])
            quantity=float((Decimal(str(qmax))/step).to_integral_value(rounding=ROUND_FLOOR)*step)
        if quantity<=0:return None
        cost=walk(bb['asks'],quantity);proceeds=walk(sb['bids'],quantity)
        if cost is None or proceeds is None:return None
        if any(quantity<m['min_qty'] or quantity>m.get('max_qty',math.inf) for m in (buy,sell)):return None
        if cost<buy['min_notional'] or proceeds<sell['min_notional']:return None
        bf,sf=scenario_fee(buy,strategy),scenario_fee(sell,strategy)
        fees=(cost*bf+proceeds*sf)/10000
        reserve=self.config.extra_cost_bps/10000*max(cost,proceeds)
        capital=(cost+proceeds)*self.config.margin_fraction*self.config.capital_rate*self.config.holding_seconds/(365*86400)
        net=proceeds-cost-2*fees-reserve-capital
        route=f"{p['asset']}|{key(buy)}|{key(sell)}"
        return {'route':route,'pair_id':self.pair_id(p),'asset':p['asset'],'strategy':strategy,
                'buy':key(buy),'sell':key(sell),'quantity':quantity,'buy_value':cost,'sell_value':proceeds,
                'buy_fee_bps':bf,'sell_fee_bps':sf,'net_edge_usd':net,'net_edge_bps':net/cost*10000,
                'opening_edge_usd':proceeds-cost-fees,'timestamp':now,'skew_ms':abs(bb['received']-sb['received'])*1000,
                'notional':self.config.notional,'lifetime_is_sampled':True}

    def _track_signal(self,s,ident,now,route=None):
        # A missing walk (depth, lot, or minimum failure) is observed loss of
        # executability, not a positive episode continuing for five seconds.
        if route is None and s is not None:route=s['strategy']+'|'+s['route']
        episode=self.episodes.get(route)
        if s is None or s['net_edge_usd']<=0:
            if episode:self._finish_episode(route,now,
                                            'observed_unexecutable' if s is None else 'observed_nonpositive')
            return
        if episode is None:
            self.episode_sequence+=1
            episode_id=f"{int(now*1e6)}:{self.episode_sequence}"
            episode={'id':episode_id,'first':now,'last':now,'samples':1,
                     'peak':s['net_edge_usd'],'asset':s['asset'],'strategy':s['strategy'],
                     'pair_id':ident,'route':s['route'],'sampled_only':True}
            self.episodes[route]=episode
            self.evidence.append((f"{episode_id}:start",{
                'signal':copy.deepcopy(s),'episode_id':episode_id,
                'books':[self._book_evidence(self.books[k]) for k in (s['buy'],s['sell'])]},
                'signal_episode_start',now))
            for delay in self.config.latency_probes_ms:
                probe_key=f"{episode_id}|{delay}"
                self.probes[probe_key]={'signal':copy.deepcopy(s),'due':now+delay/1000,
                                        'delay_ms':delay,'strategy':s['strategy'],
                                        'pair_id':ident,'episode_id':episode_id,'after':{},
                                        'generations':{k:self.books[k].get('generation') for k in (s['buy'],s['sell'])}}
                self.probe_stats[str(delay)]['triggered']+=1
                self.probe_stats_by_strategy[s['strategy']][str(delay)+':triggered']+=1
            # Never retain an unbounded number of pending probe snapshots.
            while len(self.probes)>4096:
                self._finish_probe(next(iter(self.probes)),'missing','probe_overflow')
        else:
            episode.update(last=now,samples=episode['samples']+1,
                           peak=max(episode['peak'],s['net_edge_usd']))
        previous=self.top_signals.get(route)
        if previous is None or s['net_edge_usd']>previous['net_edge_usd']:
            self.top_signals[route]=copy.deepcopy(s)
            best=sorted(self.top_signals,key=lambda k:self.top_signals[k]['net_edge_usd'],reverse=True)[:30]
            self.top_signals={k:self.top_signals[k] for k in best}
            self.signals.append(copy.deepcopy(s))
            self.evidence.append((route,{'signal':s,'books':[self._book_evidence(self.books[k]) for k in (s['buy'],s['sell'])]},'best_signal',now))

    def _finish_episode(self,route,now,reason):
        e=self.episodes.pop(route)
        observed_end=reason in ('observed_nonpositive','observed_unexecutable')
        lower=max(0,e['last']-e['first'])
        e.update(end=now,observed_span_seconds=lower,
                 lifetime_lower_seconds=lower,
                 lifetime_upper_seconds=max(0,now-e['first']) if observed_end else None,
                 end_reason=reason,right_censored=not observed_end)
        self.episode_history.append(e)
        self.evidence.append((f"{e['id']}:end",{'episode':copy.deepcopy(e),
                              'timing':{'first_positive':e['first'],
                                        'last_positive':e['last'],
                                        'first_observed_end':now if observed_end else None,
                                        'lifetime_lower_seconds':lower,
                                        'lifetime_upper_seconds':e['lifetime_upper_seconds'],
                                        'right_censored':e['right_censored']}},
                              'signal_episode_end',now))

    def censor_all(self,reason='shutdown',now=None):
        """Close sampled lifetimes without claiming a negative observation."""
        now=now if now is not None else time.time()
        for route in list(self.episodes):self._finish_episode(route,now,reason)
        for pid in list(self.probes):self._finish_probe(pid,'missing',reason)

    def _censor_pair(self,ident,now):
        for route,e in list(self.episodes.items()):
            if e['pair_id']==ident:self._finish_episode(route,now,'invalid_or_stale_book')

    def _finish_probe(self,pid,outcome,reason,actual_delay_ms=None):
        p=self.probes.pop(pid,None)
        if p is None:return
        delay=str(p['delay_ms']);strategy=p['strategy']
        self.probe_stats[delay][outcome]+=1
        self.probe_stats_by_strategy[strategy][f'{delay}:{outcome}']+=1
        if outcome=='missing':
            self.probe_stats[delay][f'missing_{reason}']+=1
            self.probe_stats_by_strategy[strategy][f'{delay}:missing_{reason}']+=1
        if actual_delay_ms is not None:
            self.probe_stats[delay]['actual_delay_ms_sum']+=actual_delay_ms
            self.probe_stats_by_strategy[strategy][f'{delay}:actual_delay_ms_sum']+=actual_delay_ms
            for stats,prefix in ((self.probe_stats[delay],''),
                                 (self.probe_stats_by_strategy[strategy],f'{delay}:')):
                lo,hi=prefix+'actual_delay_ms_min',prefix+'actual_delay_ms_max'
                stats[lo]=min(stats.get(lo,actual_delay_ms),actual_delay_ms)
                stats[hi]=max(stats.get(hi,actual_delay_ms),actual_delay_ms)
        self.evidence.append((f"{p['episode_id']}:probe:{delay}",{
            'episode_id':p['episode_id'],'strategy':strategy,
            'configured_delay_ms':p['delay_ms'],'actual_delay_ms':actual_delay_ms,
            'outcome':outcome,'reason':reason},'signal_latency_probe',time.time()))

    def _probe_invalidate(self,k,reason):
        for pid,p in list(self.probes.items()):
            if k in (p['signal']['buy'],p['signal']['sell']):
                self._finish_probe(pid,'missing',reason)

    def _probe_update(self,k,now):
        for pid,p in list(self.probes.items()):
            s=p['signal']
            if k not in (s['buy'],s['sell']) or now<p['due']:continue
            if self.books[k].get('engine_time') is not None and self.books[k]['engine_time']<p['due']:continue
            if self.books[k].get('generation')!=p['generations'][k]:
                self._finish_probe(pid,'missing','generation_changed');continue
            p['after'].setdefault(k,copy.deepcopy(self.books[k]))
            if len(p['after'])<2:continue
            a,b=p['after'][s['buy']],p['after'][s['sell']]
            if abs(a['received']-b['received'])>self.config.max_skew or not all(valid_book(x,now,self.config) for x in (a,b)):
                self._finish_probe(pid,'missing','stale_or_skewed')
            else:
                pair=self.pairs.get(p['pair_id'])
                if pair:
                    ms={key(pair['hl']):pair['hl'],key(pair['other']):pair['other']}
                    later=self._signal(pair,ms[s['buy']],ms[s['sell']],a,b,s['strategy'],now,s['quantity'])
                    actual=max(a['received'],b['received'])*1000-s['timestamp']*1000
                    self._finish_probe(pid,'observed','valid_books',actual)
                    if later is not None and later['net_edge_usd']>0:
                        delay=str(p['delay_ms'])
                        self.probe_stats[delay]['survived']+=1
                        self.probe_stats_by_strategy[s['strategy']][f'{delay}:survived']+=1
                else:
                    self._finish_probe(pid,'missing','pair_removed')

    def _maybe_enter(self,pair,ident,s,strategy,now):
        if any(p['strategy']==strategy and p['pair_id']==ident for p in self.positions.values()):return
        active=[p for p in self.positions.values() if p['strategy']==strategy]
        if len(active)>=self.config.max_positions or (len(active)+1)*self.config.notional>self.config.max_matched_notional:
            self.stats['portfolio_limit_rejections']+=1;return
        ms={key(pair['hl']):pair['hl'],key(pair['other']):pair['other']}
        reserved={}
        for m in ms.values():
            amount=self.config.notional*self.config.margin_fraction+self.config.notional*(scenario_fee(m,strategy)*2+self.config.extra_cost_bps)/10000
            reserved[m['venue']]=reserved.get(m['venue'],0)+amount
        available={v:self.cash_available(strategy,v,now) for v in reserved}
        if any(available[v] is None or available[v]<amount for v,amount in reserved.items()):
            self.stats['capital_rejections']+=1;return
        self.sequence+=1;ident_trade=f"{int(now*1e6)}-{self.sequence}-{strategy}"
        p={'id':ident_trade,'pair_id':ident,'asset':pair['asset'],'strategy':strategy,'status':'ENTRY_PENDING',
           'created_at':now,'opened_at':None,'closed_at':None,'signal':s,'reserved':reserved,'legs':[]}
        for direction,mk,value in (('long',s['buy'],s['buy_value']),('short',s['sell'],s['sell_value'])):
            m=ms[mk];b=self.books[mk];delay=taker_delay(m,strategy,self.config)
            q=s['quantity'];expected=value/q
            leg={'venue':m['venue'],'market':m['market'],'key':mk,'side':direction,
                 'step':m['step'],'min_qty':m['min_qty'],'min_notional':m['min_notional'],
                 'fee_bps':scenario_fee(m,strategy),'quantity':0.0,'remaining':0.0,'entry_value':0.0,
                 'entry_vwap':0.0,'entry_time':None,'exit_time':None,'entry_result':None,
                 'entry_fee':0.0,'exit_fee':0.0,'fees_usd':0.0,'price_pnl':0.0,'exit_value':0.0,'exit_fills':[]}
            leg['intent']={'kind':'entry','quantity':q,'created':now,'due':now+delay,
                'expires':now+delay+self.config.fill_timeout_seconds,'generation':b.get('generation'),
                'price_limit':expected*(1+(1 if direction=='long' else -1)*self.config.entry_slippage_bps/10000)}
            p['legs'].append(leg)
        self.positions[p['id']]=p;self.ledgers[strategy]['entry_attempts']+=1
        self.transitions.append(copy.deepcopy(p))

    def funding_due(self):
        return [copy.deepcopy(p) for p in self.positions.values() if p['status']=='AWAITING_FUNDING']

    def settle_funding(self,position_id,result,now):
        p=self.positions.get(position_id)
        if p is None or p['status']!='AWAITING_FUNDING':return
        p['funding']=copy.deepcopy(result)
        if not result.get('complete') or result.get('cashflow_usd') is None:
            self.stats['funding_incomplete_checks']+=1;return
        cash=float(result['cashflow_usd'])
        if not math.isfinite(cash):raise ValueError('Non-finite funding cash')
        p['funding_usd']=cash;p['net_pnl_usd']=p['price_net_before_funding']+cash
        p['status']='CLOSED_ESTIMATED' if result.get('estimated') else 'CLOSED'
        p['settled_at']=now
        ledger=self.ledgers[p['strategy']]
        # Event detail can assign cash across wallets; total-only fallback is
        # conservatively assigned to the HL wallet and explicitly recorded.
        allocated=defaultdict(float)
        for event in result.get('events',[]):
            if event.get('venue') in ledger['wallets'] and event.get('cashflow_usd') is not None:
                allocated[event['venue']]+=float(event['cashflow_usd'])
        if abs(sum(allocated.values())-cash)>1e-7:
            allocated=defaultdict(float,{p['legs'][0]['venue']:cash});p['funding_allocation_estimated']=True
        for venue,amount in allocated.items():ledger['wallets'][venue]+=amount
        ledger['funding_usd']+=cash
        if result.get('estimated'):
            ledger['closed_pnl_estimated']+=p['net_pnl_usd'];ledger['estimated_trades']+=1
            quality='estimated'
        else:
            ledger['closed_pnl_exact']+=p['net_pnl_usd'];ledger['closed_trades']+=1
            quality='exact'
        if p['net_pnl_usd']>0:
            ledger[f'closed_profit_sum_{quality}']+=p['net_pnl_usd']
            ledger[f'closed_wins_{quality}']+=1
        elif p['net_pnl_usd']<0:
            ledger[f'closed_loss_sum_{quality}']+=p['net_pnl_usd']
            ledger[f'closed_losses_{quality}']+=1
        self.transitions.append(copy.deepcopy(p));self.finished.append(copy.deepcopy(p))
        self.positions.pop(position_id)

    def liquidation(self,p,now):
        if p['status']=='AWAITING_FUNDING':return None
        total=sum(leg['price_pnl']-leg['fees_usd'] for leg in p['legs'])
        for leg in p['legs']:
            q=leg['remaining']
            if q<=0:continue
            b=self.books.get(leg['key'])
            if not valid_book(b,now,self.config):return None
            value=walk(b['bids'] if leg['side']=='long' else b['asks'],q)
            if value is None:return None
            current_meta=self.market_meta.get(leg['key'])
            fee_bps=scenario_fee(current_meta,p['strategy']) if current_meta else leg['fee_bps']
            total+=(value-leg['entry_vwap']*q)*(1 if leg['side']=='long' else -1)-value*fee_bps/10000
        base=max(leg['entry_value'] for leg in p['legs'])
        total-=base*self.config.extra_cost_bps/10000
        elapsed=sum(max(0,now-leg['entry_time'])*leg['entry_value']*self.config.margin_fraction for leg in p['legs'] if leg['entry_time'] is not None)
        total-=elapsed*self.config.capital_rate/(365*86400)
        crossed=any(leg['entry_time'] is not None and int(leg['entry_time']//3600)<int(now//3600) for leg in p['legs'])
        funding=p.get('open_funding')
        if crossed:
            if not funding or not funding.get('complete') or funding.get('covered_until',0)<int(now//3600)*3600:return None
            total+=funding['cashflow_usd']
        return total

    def snapshot(self,now):
        strategies={}
        pos=[]
        for strategy,ledger in self.ledgers.items():
            current=[p for p in self.positions.values() if p['strategy']==strategy]
            marks=[self.liquidation(p,now) for p in current if p['status']!='AWAITING_FUNDING']
            strategies[strategy]={**ledger,'capital_usd':ledger['initial_capital'],
                'open_positions':sum(any(leg['remaining']>0 for leg in p['legs']) for p in current),
                'pending_entries':sum(p['status']=='ENTRY_PENDING' for p in current),
                'pending_exits':sum(p['status']=='EXITING' for p in current),
                'pending_funding':sum(p['status']=='AWAITING_FUNDING' for p in current),
                'incomplete_trades':sum(p['status']=='AWAITING_FUNDING' for p in current),
                'reserved_usd':sum(sum(p['reserved'].values()) for p in current),
                'open_liquidation_pnl':sum(marks) if all(x is not None for x in marks) else None,
                'open_mark_excludes_unsettled_funding':False,'wallet_cash_usd':sum(ledger['wallets'].values()),
                'closed_winning_sum_usd':ledger['closed_profit_sum_exact']+ledger['closed_profit_sum_estimated'],
                'closed_losing_sum_usd':ledger['closed_loss_sum_exact']+ledger['closed_loss_sum_estimated'],
                'closed_wins':ledger['closed_wins_exact']+ledger['closed_wins_estimated'],
                'closed_losses':ledger['closed_losses_exact']+ledger['closed_losses_estimated']}
        for p in self.positions.values():
            pos.append({'id':p['id'],'asset':p['asset'],'strategy':p['strategy'],'status':p['status'],
                        'age_seconds':now-p['created_at'],'liquidation_pnl':self.liquidation(p,now),
                        'unhedged':abs(p['legs'][0]['remaining']-p['legs'][1]['remaining'])>1e-9,
                        'funding':p.get('funding')})
        spans=[max(0,e['last']-e['first']) for e in self.episode_history]
        brackets={'<0.1s':0,'0.1-0.5s':0,'0.5-1s':0,'1-5s':0,'>=5s':0}
        for span in spans:
            label=('<0.1s' if span<.1 else '0.1-0.5s' if span<.5 else
                   '0.5-1s' if span<1 else '1-5s' if span<5 else '>=5s')
            brackets[label]+=1
        by_strategy={}
        for strategy,counter in self.probe_stats_by_strategy.items():
            per_delay=defaultdict(dict)
            for name,value in counter.items():
                delay,metric=name.split(':',1)
                per_delay[delay][metric]=value
            by_strategy[strategy]=dict(per_delay)
        return {'strategies':strategies,'positions':pos,'stats':dict(self.stats),
                'top_signals':sorted(self.top_signals.values(),key=lambda s:s['net_edge_usd'],reverse=True)[:10],
                'latency':{delay:dict(v) for delay,v in self.probe_stats.items()},
                'latency_by_strategy':by_strategy,
                'episode_summary':{'finished':len(self.episode_history),
                                   'active':len(self.episodes),
                                   'right_censored':sum(e['right_censored'] for e in self.episode_history),
                                   'observed_end':sum(not e['right_censored'] for e in self.episode_history),
                                   'observed_positive_span_min_seconds':min(spans) if spans else None,
                                   'observed_positive_span_max_seconds':max(spans) if spans else None,
                                   'observed_positive_span_brackets':brackets,
                                   'span_interpretation':'sampled lower bound; censored upper bound unknown'},
                'active_episodes':list(self.episodes.values())[:300],
                'recent_episodes':list(self.episode_history)[-20:]}

    def export_state(self):
        return {'version':1,'config':asdict(self.config),'sequence':self.sequence,'ledgers':self.ledgers,
                'positions':self.positions,'stats':dict(self.stats),'top_signals':self.top_signals,
                'probe_stats':{k:dict(v) for k,v in self.probe_stats.items()},
                'probe_stats_by_strategy':{k:dict(v) for k,v in self.probe_stats_by_strategy.items()},
                'episode_history':list(self.episode_history),'active_episodes':self.episodes,
                'episode_sequence':self.episode_sequence,
                'pending_probes':[{k:p[k] for k in ('delay_ms','strategy','episode_id')}
                                  for p in self.probes.values()]}

    def restore(self,state):
        self.sequence=state['sequence'];self.ledgers=state['ledgers'];self.positions=state['positions']
        for ledger in self.ledgers.values():
            for quality in ('exact','estimated'):
                for name,default in (('profit_sum',0.0),('loss_sum',0.0),('wins',0),('losses',0)):
                    ledger.setdefault(f'closed_{name}_{quality}',default)
        self.stats=Counter(state.get('stats',{}));self.top_signals=state.get('top_signals',{})
        self.probe_stats=defaultdict(lambda:Counter(),{k:Counter(v) for k,v in state.get('probe_stats',{}).items()})
        self.probe_stats_by_strategy=defaultdict(lambda:Counter(),{
            k:Counter(v) for k,v in state.get('probe_stats_by_strategy',{}).items()})
        self.episode_history=deque(state.get('episode_history',[]),maxlen=2000)
        self.episode_sequence=int(state.get('episode_sequence',0))
        self.episodes=state.get('active_episodes',{}).copy()
        for route,e in list(self.episodes.items()):
            self._finish_episode(route,e['last'],'restart')
        for i,p in enumerate(state.get('pending_probes',[])):
            pid=f"restart:{i}"
            self.probes[pid]={**p,'signal':{'buy':'','sell':''}}
            self._finish_probe(pid,'missing','restart')
        # Never fill against a pre-restart cache. Entry intents expire safely;
        # exits are reissued on a valid new generation in tick after timeout.
        for p in self.positions.values():
            for leg in p['legs']:
                if leg.get('intent'):leg['intent']['generation']='restart-invalidated'

    def drain(self):
        transitions,self.transitions=self.transitions,[]
        signals,self.signals=self.signals,[]
        evidence,self.evidence=self.evidence,[]
        finished,self.finished=self.finished,[]
        return transitions,signals,evidence,finished
