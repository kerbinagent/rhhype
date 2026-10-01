"""Entry5bp excursion; active quote retains original-price forecast>=.01 without excursion gate."""
from decimal import Decimal as D
from statistics import median
from scripts.core_spot_passive_inside_branch import InsideSpotBranch
from scripts.core_passive_hedged_base import NS,floor_step
from scripts.replay_core_passive_lit import common_step

class CashRetentionSpotBranch(InsideSpotBranch):
 def model(self,now):
  if not self._fresh_pair(now):return {'reason':'stale_or_skewed_pair'}
  s,p=self.books['maker'],self.books['hedge'];basis=(p.mid()/s.mid()-1)*10000
  if self.last_sample is None or now-self.last_sample>=NS:
   self.references.append((now,basis));self.last_sample=now
  refs=[r for r in self.references if now-122*NS<=r[0]<=now-2*NS]
  if len(refs)<60 or refs[-1][0]-refs[0][0]<89*NS:return {'reason':'reference_warmup'}
  ref=D(median(v for _,v in refs));excursion=basis-ref
  if self.quote is None and excursion<5:return {'reason':'under_5bp_excursion'}
  price=self.quote.price if self.quote else s.bids[0][0]+self.maker.price_tick
  if price>=s.asks[0][0]:return {'reason':'post_only_cross'}
  step=common_step(self.maker.qty_step,self.hedge.qty_step)
  qty=self.quote.qty if self.quote else floor_step(self.cfg.budget_usd/max(price,p.bids[0][0]),step)
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
