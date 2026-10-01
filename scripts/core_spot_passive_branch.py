"""Core USDC spot-long/perp-short public-flow scenario; independent $600 portfolio per asset."""
from collections import deque
from dataclasses import replace
from decimal import Decimal as D
from statistics import median
from scripts.core_passive_hedged_retirement import RetirementGuardPassiveExitBranch
from scripts.core_passive_hedged_base import NS,Rules,floor_step
from scripts.replay_core_passive_lit import common_step

class SpotPassiveBranch(RetirementGuardPassiveExitBranch):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  self.source_venues={'maker':'lighter','hedge':'lighter'}
  self.references=deque(maxlen=125);self.last_sample=None;self.capture_start_ns=None
  self.metadata=args[1];self.min_available=D(600)
  assert self.cfg.budget_usd==100 and self.cfg.policy=='fixed_best'
  # Base tier fee override must agree with fresh spot metadata.
  assert self.maker==Rules.parse(self.metadata['maker'][self.cfg.asset])
 def _log(self,event,now_ns,**details):
  if event=='abstain':self._count('abstain:'+details.get('reason','unknown'));return
  if details.get('venue') in ('maker','hedge'):
   r=self.metadata[details['venue']][self.cfg.asset]
   details.update(source_market=r['market'],market_kind=r['market_kind'])
  context=getattr(self,'event_context',{})
  details.update(callback_market=context.get('source_market',context.get('market')),callback_kind=context.get('type'))
  return super()._log(event,now_ns,**details)
 def cash_state(self):
  principal=sum((q*p for q,p in self.open_lots['hedge']),D(0))
  cash=D(600)+self.cash_maker+self.cash_hedge-principal-self.capital_cost
  available=cash-principal
  return {'actual_cash_usdc':str(cash),'perp_margin_usdc':str(principal),'available_before_pending_orders_usdc':str(available),'spot_inventory':str(self.maker_pos),'perp_inventory':str(self.hedge_pos),'spot_principal_fully_funded':True}
 def _apply_fill(self,venue,side,qty,value,now_ns,maker=False):
  assert not (venue=='maker' and side=='sell' and qty>self.maker_pos)
  assert not (venue=='hedge' and side=='buy' and qty>-self.hedge_pos)
  super()._apply_fill(venue,side,qty,value,now_ns,maker)
  assert self.maker_pos>=0 and self.hedge_pos<=0
  state=self.cash_state();available=D(state['available_before_pending_orders_usdc'])
  assert available>=0
  self.min_available=min(self.min_available,available)
  self._log('cash_state',now_ns,**state)
 def _episode_executable_exit_mark(self,now):
  mark=super()._episode_executable_exit_mark(now)
  return None if mark is None else mark+self.reserve_cost-self._episode_start_reserve
 def model(self,now):
  if not self._fresh_pair(now):return {'reason':'stale_or_skewed_pair'}
  s,p=self.books['maker'],self.books['hedge'];basis=(p.mid()/s.mid()-1)*10000
  if self.last_sample is None or now-self.last_sample>=NS:
   self.references.append((now,basis));self.last_sample=now
  refs=[r for r in self.references if now-122*NS<=r[0]<=now-2*NS]
  if len(refs)<60 or refs[-1][0]-refs[0][0]<89*NS:return {'reason':'reference_warmup'}
  ref=D(median(v for _,v in refs));excursion=basis-ref
  if excursion<5:return {'reason':'under_5bp_excursion'}
  price=s.bids[0][0];step=common_step(self.maker.qty_step,self.hedge.qty_step)
  qty=floor_step(self.cfg.budget_usd/max(price,p.bids[0][0]),step)
  if qty<=0:return {'reason':'zero_quantity'}
  walks=[p.walk('sell',qty),s.walk('sell',qty),p.walk('buy',qty)]
  if any(q!=qty for q,v in walks):return {'reason':'insufficient_depth'}
  he,se,pe=[v for q,v in walks]
  entry=qty*price
  fees=entry*self.maker.maker_fee_bps/10000+se*self.maker.taker_fee_bps/10000+(he+pe)*self.hedge.taker_fee_bps/10000
  capital=(entry+he)*self.cfg.capital_rate*D(10)/D(365*86400)
  forecast=he-entry+se-pe+qty*((p.mid()-s.mid())-ref*s.mid()/10000)-fees-capital
  reason='quote' if forecast>=D('.01') else 'forecast_below_1bp'
  return {'reason':reason,'price':str(price),'quantity':str(qty),'basis_bps':str(basis),'reference_bps':str(ref),'excursion_bps':str(excursion),'reference_count':len(refs),'reference_rows':[[t,str(v)] for t,v in refs],'hedge_entry_value':str(he),'spot_exit_value':str(se),'perp_exit_value':str(pe),'fees':str(fees),'capital':str(capital),'forecast_cash_after_capital':str(forecast)}
 def _on_diagnostic(self,ignored,now):
  diag=self.model(now)
  if self.quote is None:
   if not 122*NS<=now-self.capture_start_ns<480*NS:diag={'reason':'outside_admission_window'}
   elif self.episode_no>=30:diag={'reason':'attempt_cap'}
   elif self.last_flat_ns is not None and now-self.last_flat_ns<30*NS:diag={'reason':'cooldown'}
   elif now//(3600*NS)!=(now+120*NS)//(3600*NS):diag={'reason':'funding_boundary_guard'}
   elif D(self.cash_state()['available_before_pending_orders_usdc'])<D(202):diag={'reason':'actual_cash_reservation'}
  old=self.quote
  super()._on_diagnostic(diag,now)
  if old is None and self.quote is not None:self._log('spot_admission',now,**diag,**self.cash_state())
 def process(self,event,quote_diag=None):
  self.event_context=event
  if event.get('type')=='invalidate':self.references.clear();self.last_sample=None
  super().process(event,quote_diag)
 def summary(self):
  out=super().summary();out.pop('cash_hedge_usdg',None)
  out.update(cash_hedge_usdc_synthetic=str(self.cash_hedge),cash_accounting_note='Spot cash is actual purchase/sale cash. Perp notional flows are synthetic until flat; actual_cash_usdc removes open-short proceeds. Full spot principal and 1x perp margin held in the same USDC portfolio.',portfolio_prefund_usdc=600,minimum_available_usdc=str(self.min_available),**self.cash_state())
  return out
