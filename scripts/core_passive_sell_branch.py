"""Exploratory Core maker ask with RH buy hedge; fixed 10 bp offset."""
from decimal import Decimal as D, ROUND_CEILING
from scripts.core_passive_hedged_base import NS, floor_step, dec, venue_key
from scripts.core_passive_hedged_late_flow import GuardedMakerSellBranch
from scripts.core_passive_hedged_exit import PassiveExitBranch
from scripts.core_passive_lit_branch import CorePassiveBranch
from scripts.replay_core_passive_lit import common_step

class CorePassiveSellBranch(GuardedMakerSellBranch):
 capture_start_ns=None
 _ioc_rules=CorePassiveBranch._ioc_rules
 _deplete=staticmethod(PassiveExitBranch._deplete)
 def __init__(self,config,metadata,*,exit_policy='control10s',audit_sink=None):
  assert config.policy=='adaptive' and exit_policy=='control10s' and config.hold_ns==10*NS
  assert config.maker_latency_ns==100_000_000
  super().__init__(config,metadata,audit_sink=audit_sink)
  self.entry_hedge_qty=D(0)
 def _fresh_pair(self,now):
  return super()._fresh_pair(now) and all(b.bids and b.asks for b in self.books.values())
 def _fill_hedge(self,intent,book):
  before=self.hedge_pos
  with self._ioc_rules():super()._fill_hedge(intent,book)
  filled=self.hedge_pos-before
  if filled>0:self.entry_hedge_qty+=filled;self._deplete(book,'buy',filled)
 def _fill_exit(self,venue,book):
  before=self.maker_pos if venue=='maker' else self.hedge_pos
  with self._ioc_rules():super()._fill_exit(venue,book)
  after=self.maker_pos if venue=='maker' else self.hedge_pos
  if abs(before)>abs(after):self._deplete(book,'sell' if before>0 else 'buy',abs(before)-abs(after))
 def _episode_executable_exit_mark(self,now):
  with self._ioc_rules():return super()._episode_executable_exit_mark(now)
 def _on_diagnostic(self,ignored,now):
  if not self._fresh_pair(now):return super()._on_diagnostic({'reason':'stale_or_skewed_pair'},now)
  m,h=self.books['maker'],self.books['hedge']
  if self.quote is not None:diag={'reason':'quote','price':str(self.quote.price),'quantity':str(self.quote.qty)}
  else:
   tick=self.maker.price_tick
   price=(m.asks[0][0]*(1+D(10)/10000)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
   qty=floor_step(self.cfg.budget_usd/max(price,h.asks[0][0]),common_step(self.maker.qty_step,self.hedge.qty_step))
   diag={'reason':'quote' if price<=m.asks[-1][0] else 'book_depth_does_not_cover_better_queue','price':str(price),'quantity':str(qty)}
   assert self.capture_start_ns is not None
   if not 10*NS<=now-self.capture_start_ns<480*NS:diag['reason']='outside_admission_window'
   elif self.episode_no>=100:diag['reason']='attempt_cap'
   elif now//(3600*NS)!=(now+120*NS)//(3600*NS):diag['reason']='funding_boundary_guard'
  super()._on_diagnostic(diag,now)
 def _close_episode_if_flat(self,now):
  n=len(self.episodes);q=self.quote;mq=self._episode_maker_entries;hq=self._episode_hedge_entries;qty=self.entry_hedge_qty
  super()._close_episode_if_flat(now)
  if len(self.episodes)>n:
   e=self.episodes[-1];e.update(entry_quote_price=str(q.price),entry_quote_qty=str(q.qty),entry_maker_notional=str(mq),entry_hedge_notional=str(hq),entry_hedge_qty=str(qty),fee_only_net=None if e['funding_unknown'] else e['cash_known'],stressed_net=None if e['funding_unknown'] else str(D(e['cash_known'])-D(e['reserve_cost'])-D(e['capital_cost'])))
   self.entry_hedge_qty=D(0)
 def _late_retired_match(self,event):
  old=super()._late_retired_match(event)
  if old is not None:return old
  if event.get('type',event.get('kind'))!='trade' or venue_key(event.get('venue'))!='maker' or event.get('asset')!=self.cfg.asset or event.get('side')!='buy':return None
  try:receipt=int(event.get('received_ns',event.get('receipt_ns')));source=int(event['source_ns']);price=dec(event['price']);qty=dec(event['qty'])
  except (KeyError,TypeError,ValueError,ArithmeticError):return None
  if source<=0 or source>receipt or price<=0 or qty<=0:return None
  for old in reversed(self.retired_quotes):
   if receipt==old.retired_ns and old.activation_due_ns<=source<=old.cancel_due_ns and price>=old.price:return old
  return None
 def process(self,event,quote_diag=None):
  super().process(event,quote_diag)
  if self._late_retired_match(event) is not None:super().process(event,quote_diag)
 def summary(self):
  with self._ioc_rules():s=super().summary()
  s['direction']='Core-short/RH-long';s['ioc_minimum_exemption']='published_circuit_scenario_not_verified_deployed_API'
  return s
