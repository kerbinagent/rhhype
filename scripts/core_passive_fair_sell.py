"""Past closing-basis maker ask floor; exploratory, cash-only profit target."""
from collections import deque
from decimal import Decimal as D, ROUND_CEILING
from statistics import median
from scripts.core_maker_cash_exit import CashSellBranch
from scripts.core_passive_hedged_late_flow import GuardedMakerSellBranch
from scripts.core_passive_hedged_base import NS,floor_step
from scripts.replay_core_passive_lit import common_step
class FairSellBranch(CashSellBranch):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs);self.references=deque();self.last_sample=None
 def model(self,now):
  if not self._fresh_pair(now):return {'reason':'stale_or_skewed_pair'}
  m,h=self.books['maker'],self.books['hedge'];step=common_step(self.maker.qty_step,self.hedge.qty_step)
  qref=floor_step(self.cfg.budget_usd/max(m.asks[0][0],h.bids[0][0]),step)
  if qref<=0:return {'reason':'zero_reference_quantity'}
  mf,mv=m.walk('buy',qref);hf,hv=h.walk('sell',qref)
  if mf==hf==qref and (self.last_sample is None or now-self.last_sample>=NS):
   self.references.append((now,(hv-mv)/qref/m.mid()*10000));self.last_sample=now
  while self.references and self.references[0][0]<now-120*NS:self.references.popleft()
  refs=[r for r in self.references if r[0]<=now-2*NS]
  if len(refs)<90 or refs[-1][0]-refs[0][0]<89*NS:return {'reason':'reference_warmup'}
  center=D(median([r[1] for r in refs]));closing=center*m.mid()/10000
  qty=floor_step(self.cfg.budget_usd/max(m.asks[0][0],h.asks[0][0]),step)
  for iteration in range(16):
   if qty<=0:return {'reason':'zero_quantity'}
   hf,hv=h.walk('buy',qty)
   if hf!=qty:return {'reason':'hedge_depth'}
   unit=max(m.asks[0][0],hv/qty)
   fee_unit=unit*(self.maker.maker_fee_bps+self.maker.taker_fee_bps+2*self.hedge.taker_fee_bps)/10000
   capital_unit=2*unit*self.cfg.capital_rate*D(10)/D(365*86400)
   tick=self.maker.price_tick
   price=(max(m.asks[0][0],hv/qty-closing+unit*D('.0006')+fee_unit+capital_unit)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
   smaller=min(qty,floor_step(self.cfg.budget_usd/max(price,hv/qty),step))
   if smaller==qty:break
   qty=smaller
  else:return {'reason':'quantity_iteration_cap'}
  return {'reason':'quote' if price<=m.asks[-1][0] else 'book_depth_does_not_cover_better_queue','price':str(price),'quantity':str(qty),'median_close_bps':str(center),'reference_rows':[[t,str(v)] for t,v in refs],'hedge_entry_value':str(hv),'maker_mid':str(m.mid()),'fee_unit':str(fee_unit),'capital_unit':str(capital_unit),'quantity_iterations':iteration+1,'forecast_cash':str(qty*(price-hv/qty+closing-fee_unit-capital_unit))}
 def _on_diagnostic(self,ignored,now):
  diag=self.model(now)
  if self.quote is not None:
   if diag.get('reason')=='quote' and self.quote.price>=D(diag['price']):diag={**diag,'price':str(self.quote.price),'quantity':str(self.quote.qty)}
  else:
   if not 10*NS<=now-self.capture_start_ns<480*NS:diag={**diag,'reason':'outside_admission_window'}
   elif self.episode_no>=100:diag={**diag,'reason':'attempt_cap'}
   elif now//(3600*NS)!=(now+120*NS)//(3600*NS):diag={**diag,'reason':'funding_boundary_guard'}
  previous=self.quote;GuardedMakerSellBranch._on_diagnostic(self,diag,now)
  if previous is None and self.quote is not None:self._log('fair_value_admission',now,**diag)
