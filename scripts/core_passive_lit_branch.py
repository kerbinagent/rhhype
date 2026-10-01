"""Core maker / RH hedge, exact-state fixed-offset planner and conditional IOC rules."""
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal as D
import math
from scripts.core_passive_hedged_base import NS,floor_step
from scripts.core_passive_hedged_retirement import RetirementGuardPassiveExitBranch

class CorePassiveBranch(RetirementGuardPassiveExitBranch):
 capture_start_ns=None
 def __init__(self,config,metadata,*,exit_policy,audit_sink=None):
  assert config.policy=='adaptive' and exit_policy=='control10s' and config.hold_ns==10*NS
  assert config.maker_latency_ns in (100_000_000,400_000_000)
  super().__init__(replace(config,policy='fixed_best'),metadata,exit_policy=exit_policy,audit_sink=audit_sink)
  self.cfg=config
 @contextmanager
 def _ioc_rules(self):
  maker,hedge=self.maker,self.hedge
  self.maker=replace(maker,min_qty=maker.qty_step,min_notional=D(0))
  self.hedge=replace(hedge,min_qty=hedge.qty_step,min_notional=D(0))
  try:yield
  finally:self.maker,self.hedge=maker,hedge
 def _fill_hedge(self,intent,book):
  with self._ioc_rules():return super()._fill_hedge(intent,book)
 def _fill_exit(self,venue,book):
  with self._ioc_rules():return super()._fill_exit(venue,book)
 def _episode_executable_exit_mark(self,now_ns):
  with self._ioc_rules():return super()._episode_executable_exit_mark(now_ns)
 def summary(self):
  with self._ioc_rules():result=super().summary()
  result['ioc_minimum_exemption']='published_circuit_scenario_not_verified_deployed_API'
  return result
 def _on_diagnostic(self,ignored,now_ns):
  if set(self.books)!={'maker','hedge'}:return super()._on_diagnostic({'reason':'missing_book'},now_ns)
  maker,hedge=self.books['maker'],self.books['hedge']
  if not maker.bids or not hedge.bids:return super()._on_diagnostic({'reason':'missing_depth'},now_ns)
  if self.quote is not None:
   diag={'reason':'quote','price':str(self.quote.price),'quantity':str(self.quote.qty)}
  else:
   price=floor_step(maker.bids[0][0]*(1-D(10)/10000),self.maker.price_tick)
   a,b=self.maker.qty_step,self.hedge.qty_step
   places=max(-a.as_tuple().exponent,-b.as_tuple().exponent,0);scale=D(10)**places
   step=D(math.lcm(int(a*scale),int(b*scale)))/scale
   qty=floor_step(self.cfg.budget_usd/max(price,hedge.bids[0][0]),step)
   diag={'reason':'quote' if price>=maker.bids[-1][0] else 'book_depth_does_not_cover_better_queue','price':str(price),'quantity':str(qty)}
   assert self.capture_start_ns is not None
   if not 10*NS<=now_ns-self.capture_start_ns<480*NS:diag['reason']='outside_admission_window'
   elif self.episode_no>=100:diag['reason']='attempt_cap'
   elif now_ns//(3600*NS)!=(now_ns+120*NS)//(3600*NS):diag['reason']='funding_boundary_guard'
  return super()._on_diagnostic(diag,now_ns)
