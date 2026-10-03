"""Conditional initial-spot upper bounds; positive bounds are unresolved."""
import time
from fractions import Fraction

class Budget:
 def __init__(self,points=1400000,seconds=15,clock=time.monotonic):
  if type(points) is not int or not 1<=points<=1400000: raise ValueError('point cap')
  if type(seconds) is not int or not 1<=seconds<=15: raise ValueError('time cap')
  self.limit=points; self.points=0; self.clock=clock; self.deadline=clock()+seconds
 def allowed(self): return self.points<self.limit and self.clock()<self.deadline

def maximum(model,p,d,stock,pools,asset,base,budget):
 model.validate_route(pools,asset,base)
 caps=model.comet_caps(p,d,stock)
 lo,hi=caps['q_min'],caps['q_cap']
 out=dict(status='empty_model_domain',upper_gain=None,upper_argmax_q=None,
  q_min=lo,q_cap=hi,evaluated_points=0,domain_covered=caps['empty'],
  requires_principal_debit_ge_q=True,dependency_invariance_proven=False,**model.FLAGS)
 if caps['empty']: return out
 rates=[]; cur=asset; coefficient=Fraction(p,d)
 for pool in pools:
  k,rho,cur=model.pool_rate(pool,cur)
  coefficient*=k; rates.append((rho.numerator,rho.denominator,1000000-pool['fee']))
 def payout(q):
  c=p*q//d
  for n,dn,f in rates: c=(c*f//1000000)*n//dn
  return c
 delta=coefficient-1
 linear=(hi if delta>=0 else lo)*delta.numerator//delta.denominator
 upper=min(linear,payout(hi)-lo)
 out['upper_gain']=upper
 if upper<=0:
  out.update(status='conditional_nonpositive_upper',domain_covered=True)
  return out
 best=None; arg=None
 for q in range(lo,hi+1):
  if not budget.allowed():
   out['status']='unknown_work'
   return out
  gain=payout(q)-q; budget.points+=1; out['evaluated_points']+=1
  if best is None or gain>best: best,arg=gain,q
 out.update(status='conditional_nonpositive_upper' if best<=0 else 'positive_upper_unresolved',
  upper_gain=best,upper_argmax_q=arg,domain_covered=True)
 return out
