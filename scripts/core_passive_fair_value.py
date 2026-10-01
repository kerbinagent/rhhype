"""Exploratory past-only closing-basis quote cap; inherited public-flow lifecycle."""
from collections import deque
from decimal import Decimal as D
from statistics import median
from scripts.core_passive_lit_branch import CorePassiveBranch
from scripts.core_passive_hedged_retirement import RetirementGuardPassiveExitBranch
from scripts.core_passive_hedged_base import NS, floor_step
from scripts.replay_core_passive_lit import common_step

class FairValueBranch(CorePassiveBranch):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs)
  self.references=deque();self.last_sample=None;self.last_model=None
 def model(self,now):
  if set(self.books)!={'maker','hedge'} or not self._fresh_pair(now):return {'reason':'stale_or_skewed_pair'}
  m,h=self.books['maker'],self.books['hedge'];step=common_step(self.maker.qty_step,self.hedge.qty_step)
  qref=floor_step(self.cfg.budget_usd/max(m.bids[0][0],h.asks[0][0]),step)
  if qref<=0:return {'reason':'zero_reference_quantity'}
  mf,mv=m.walk('sell',qref);hf,hv=h.walk('buy',qref)
  if mf==hf==qref and (self.last_sample is None or now-self.last_sample>=NS):
   self.references.append((now,(mv-hv)/qref/m.mid()*10000));self.last_sample=now
  while self.references and self.references[0][0]<now-120*NS:self.references.popleft()
  refs=[r for r in self.references if r[0]<=now-2*NS]
  if len(refs)<90 or refs[-1][0]-refs[0][0]<89*NS:return {'reason':'reference_warmup'}
  qty=floor_step(self.cfg.budget_usd/max(m.bids[0][0],h.bids[0][0]),step)
  if qty<=0:return {'reason':'zero_quantity'}
  hf,hv=h.walk('sell',qty)
  if hf!=qty:return {'reason':'hedge_depth'}
  center=D(median([r[1] for r in refs]));closing=center*m.mid()/10000
  unit=max(m.bids[0][0],hv/qty)
  # Bound four venue fees conservatively at the larger current entry unit.
  fee_unit=unit*(self.maker.maker_fee_bps+self.maker.taker_fee_bps+2*self.hedge.taker_fee_bps)/10000
  capital_unit=2*unit*self.cfg.capital_rate*D(10)/D(365*86400)
  price=floor_step(min(m.bids[0][0],hv/qty+closing-unit*D(6)/10000-fee_unit-capital_unit),self.maker.price_tick)
  reason='quote'
  if price<=0 or price<m.bids[-1][0]:reason='book_depth_does_not_cover_better_queue'
  return {'reason':reason,'price':str(price),'quantity':str(qty),'median_close_bps':str(center),'reference_count':len(refs),'reference_first_ns':refs[0][0],'reference_last_ns':refs[-1][0],'reference_rows':[[t,str(v)] for t,v in refs],'hedge_entry_value':str(hv),'maker_mid':str(m.mid()),'fee_unit':str(fee_unit),'capital_unit':str(capital_unit),'forecast_cash':str(qty*(hv/qty-price+closing-fee_unit-capital_unit))}
 def _on_diagnostic(self,ignored,now_ns):
  diag=self.model(now_ns);self.last_model=diag
  if self.quote is not None:
   if diag.get('reason')=='quote' and self.quote.price<=D(diag['price']):diag={**diag,'price':str(self.quote.price),'quantity':str(self.quote.qty)}
  else:
   if not 10*NS<=now_ns-self.capture_start_ns<480*NS:diag={**diag,'reason':'outside_admission_window'}
   elif self.episode_no>=100:diag={**diag,'reason':'attempt_cap'}
   elif now_ns//(3600*NS)!=(now_ns+120*NS)//(3600*NS):diag={**diag,'reason':'funding_boundary_guard'}
  previous=self.quote
  RetirementGuardPassiveExitBranch._on_diagnostic(self,diag,now_ns)
  if previous is None and self.quote is not None:self._log('fair_value_admission',now_ns,**diag)
