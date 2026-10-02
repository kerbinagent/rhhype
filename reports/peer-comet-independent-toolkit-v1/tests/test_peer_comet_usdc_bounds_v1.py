"""Finite synthetic model checks; no deployed data, compiler or network."""
import bisect
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from scripts import peer_comet_usdc_bounds_v1 as m
def bnd(word, bitmap, tick, initialized=False, delta=0):
  return dict(word=word, bitmap=bitmap, tick=tick, sqrt_price=m.sqrt_at_tick(tick),
        initialized=initialized, liquidity_net=delta)
def pool(zfo=True, s=None, liquidity=10**12, fee=3000, limit=None):
  s = s or (m.Q96 + 3 * m.Q96 // 5000 if zfo else m.Q96)
  tick = m.tick_at_sqrt(s)
  if zfo:
    steps = [bnd(0, 1, 0, True)]
    steps += [bnd(-i, 0, -15360 * i) for i in range(1, 8)]
  else:
    steps = [bnd(0, 2, 60, True), bnd(0, 2, 15300)]
    steps += [bnd(i, 0, (256 * (i + 1) - 1) * 60) for i in range(1, 6)]
  return dict(pool_id='p0', token0='COLL' if zfo else 'USDC',
        token1='USDC' if zfo else 'COLL', sqrt_price=s, tick=tick,
        liquidity=liquidity, fee=fee, tick_spacing=60,
        price_limit=limit or m.sqrt_at_tick(-100000 if zfo else 100000),
        zero_for_one=zfo, steps=steps)
def quote(p, amount, **kw):
  return m.quote_exact_input(p, p['steps'], amount, **kw)
TC=unittest.TestCase
class BoundsTests(TC):
  eq=TC.assertEqual
  true=TC.assertTrue
  false=TC.assertFalse
  none=TC.assertIsNone
  gt=TC.assertGreater
  le=TC.assertLessEqual
  lt=TC.assertLess
  raises=TC.assertRaises
  is_=TC.assertIs
  def test_3300_caps(self):
    count = 0
    for p in range(1, 16):
      for d in range(1, 21):
        values = [p * q // d for q in range(101) if p * q <= 100]
        for stock in range(11):
          k=1+stock%3; positive=bisect.bisect_left(values,k)
          want = bisect.bisect_right(values, stock) - 1
          caps = m.comet_caps(p, d, stock, 100, k)
          self.eq(caps['q_cap'], want)
          self.eq(caps['empty'], positive > want)
          if not caps['empty']:
            self.eq(caps['q_min'], positive)
            self.eq(m.checked_quote(want, p, d, stock, 100), values[want])
          count += 1
    self.eq(count, 3300)
  def test_caps(self):
    with self.raises(m.ModelError): m.comet_caps(1,1,10,minimum=0)
    self.true(m.comet_caps(101, 1, 10, 100)['empty'])
    self.true(m.comet_caps(1, 101, 10, 100)['empty'])
    self.eq(m.comet_caps(1, 1, m.U256)['output_cap'], m.U128)
    self.eq(m.checked_quote(100, 1, 200, 10, 100), 0)
    with self.raises(m.ModelError):
      m.checked_quote(101, 1, 1, 10, 100)
    self.eq(m.comet_caps(2, 1, 10)['q_cap'], 5)
    self.eq(m.checked_quote(10, 1, 1, 10), 10)
  def test_fullmath(self):
    self.eq(m.muldiv(m.U256, m.U256, m.U256), m.U256)
    for args in [(1, 1, 0), (m.U256, m.U256, 1),
          (m.U256 - 1, m.U256 - 1, m.U256 - 2, True)]:
      with self.raises(m.ModelError):
        m.muldiv(*args)
    for x in [True, 1.0, -1, m.U256 + 1]:
      with self.raises(m.ModelError):
        m.integer(x)
  def test_ticks(self):
    self.eq(m.sqrt_at_tick(m.MIN_TICK), m.MIN_SQRT)
    self.eq(m.sqrt_at_tick(m.MAX_TICK), m.MAX_SQRT)
    self.eq(m.sqrt_at_tick(0), m.Q96)
    p=pool(False,s=m.MIN_SQRT,liquidity=m.U128,limit=m.MIN_SQRT+1)
    p['steps']=[bnd(-58,0,-875580)]
    r=quote(p,1); m.pool_rate(p,'COLL')
    self.eq((r['status'],r['sqrt_price'],r['output']),('complete_input',m.MIN_SQRT,0))
    for tick in [-887271, -30720, -1, 0, 1, 15300, 887271]:
      self.eq(m.tick_at_sqrt(m.sqrt_at_tick(tick)), tick)
  def test_rounding(self):
    p = pool()
    row = quote(p, 1000)
    self.eq(row['status'], 'complete_input')
    self.eq((row['net_input'], row['fee'], row['output']), (997, 3, 998))
    self.eq(m.fee_bound(1000, p, 'COLL'), 998)
    naive = (1000 * p['sqrt_price']**2 // m.Q192) * 997000 // m.F
    self.eq(naive, 997)
    self.gt(row['output'], naive)
    for flag in m.FLAGS:
      self.is_(row[flag], False)
  def test_net(self):
    p = pool(False, liquidity=2*m.Q96)
    row = quote(p, 1000)
    self.eq(row['status'], 'complete_input')
    self.eq((row['net_input'], row['fee']), (996, 4))
    self.lt(row['net_input'], 1000 * 997000 // m.F)
  def test_sides(self):
    for zfo in [True, False]:
      p = pool(zfo)
      outs = [quote(p, c)['output'] for c in range(1, 65)]
      self.eq(outs, sorted(outs))
      for c, output in enumerate(outs, 1):
        self.le(output, m.fee_bound(c, p, 'COLL'))
    row = quote(pool(False), 1000)
    self.eq(row['output'], 996)
  def test_fallback(self):
    s, liquidity = m.MAX_SQRT - 1, m.U128
    n = liquidity << 96
    cut = (m.U256 - n) // s
    fast = m.next_from_input(s, liquidity, cut, True)
    fallback = m.next_from_input(s, liquidity, cut + 1, True)
    self.eq(fallback, (n + n//s + cut) // (n//s + cut + 1))
    self.le(fallback, fast)
    with self.raises(m.ModelError):
      m.next_from_input(s, liquidity, m.U256, True)
  def test_missing_steps(self):
    p = pool()
    p['complete_coverage'] = True
    row = m.quote_exact_input(p, [], 1000)
    self.eq(row['status'], 'unknown_coverage')
    self.none(row['output'])
    for field, value in [('word', 1), ('tick', 60), ('sqrt_price', m.Q96+1),
              ('initialized', False)]:
      bad = copy.deepcopy(p['steps'])
      bad[0][field] = value
      r = m.quote_exact_input(p, bad, 1000)
      self.eq(r['status'], 'unknown_coverage')
      self.none(r['output'])
  def test_skipped_word(self):
    p = pool(liquidity=20, fee=0, s=142*m.Q96//100)
    self.eq(quote(p, 100)['status'], 'complete_input')
    skipped = [p['steps'][0], p['steps'][2]]
    row = m.quote_exact_input(p, skipped, 100)
    self.eq(row['status'], 'unknown_coverage')
    self.none(row['output'])
  def test_zero_L(self):
    p = pool(False, liquidity=0)
    p['steps'][0]['liquidity_net'] = 10**12
    self.eq(quote(p, 100)['steps'], 2)
    self.eq(quote(p, 100)['status'], 'complete_input')
    row = quote(p, 100, max_steps=1)
    self.eq(row['status'], 'unknown_work')
    self.none(row['output'])
    p['steps'][0]['liquidity_net'] = -1
    self.eq(quote(p, 100)['status'], 'unknown_arithmetic')
  def test_limits(self):
    p = pool(liquidity=20, fee=0, limit=m.Q96)
    row = quote(p, 1000)
    self.eq(row['status'], 'partial_price_limit')
    self.gt(row['remaining_input'], 0)
    self.is_(row['cash_closed'], False)
    for amount in [0, -1, m.I256+1]:
      self.none(quote(pool(), amount)['output'])
    p['price_limit'] = p['sqrt_price']
    self.none(quote(p, 1)['output'])
    bad = pool(); bad['tick'] = -1
    self.none(quote(bad, 1)['output'])
    self.none(quote(pool(), 1, deadline_ns=0)['output'])
  def test_fee_growth(self):
    with self.raises(m.ModelError):
      m.muldiv(m.I256, 1 << 128, 1)
    p = pool(); p['fee_protocol'] = 3
    self.eq(quote(p, 1)['status'], 'unknown_arithmetic')
  def test_two_pools(self):
    a, b = pool(), pool(False)
    a['token1'] = 'MID'
    b.update(pool_id='p1', token1='MID')
    value = m.route_bound(1000, [a,b], 'COLL')
    self.eq(value, m.fee_bound(m.fee_bound(1000,a,'COLL'),b,'MID'))
    row = m.route_quote(1000,[a,b],'COLL')
    self.eq(row['status'], 'complete_input')
    self.le(row['output'], value)
    b['pool_id'] = 'P0'
    with self.raises(m.ModelError):
      m.route_bound(1000,[a,b],'COLL')
    b['pool_id'] = 'p1'; b['token0'] = 'OTHER'
    with self.raises(m.ModelError):
      m.route_bound(1000,[a,b],'COLL')
    with self.raises(m.ModelError):
      m.route_bound(1000,[a,b,a],'COLL')
  def test_nonmonotone_gain(self):
    cfg = dict(p=1,d=1,stock=100,collateral_asset='COLL')
    p = pool(False)
    r = m.search(cfg,[p])
    self.eq(r['status'], 'mathematical_rejection')
    self.eq(r['pruned_quantities'], 100)
    self.eq(r['quotes'], 0)
    p = pool(s=142*m.Q96//100,liquidity=20,fee=0)
    self.gt(quote(p,2)['output']-2, 0)
    self.lt(quote(p,100)['output']-100, 0)
    r = m.search(cfg,[p])
    self.eq(r['status'], 'conditional_positive_model_candidate')
    self.gt(r['candidate']['quoted_model_gain'], 0)
    self.gt(r['unresolved_quantities'], 0)
    self.false(r['full_domain_rejected'])
    self.eq(r['pruned_quantities']+r['unresolved_quantities']+1,100)
  def test_unknown_work(self):
    cfg = dict(p=1,d=1,stock=100,collateral_asset='COLL')
    p = pool(s=142*m.Q96//100,liquidity=20,fee=0); p['steps']=[]
    r = m.search(cfg,[p],dict(quotes=1))
    self.eq(r['status'],'unresolved_model_domain')
    self.gt(r['unresolved_quantities'],0)
    self.eq(r['pruned_quantities']+r['unresolved_quantities'],100)
    self.le(r['quotes'],1)
    for limits in [dict(intervals=1),dict(pending=1)]:
      r=m.search(cfg,[p],limits)
      self.gt(r['unresolved_count'],0)
    with patch.object(m.time,'monotonic_ns',side_effect=[0,2000001,2000001]):
      r=m.search(cfg,[p],dict(elapsed_ms=1))
      self.eq(r['unresolved_quantities'],100)
    with self.raises(m.ModelError):
      m.search(cfg,[p],dict(quotes=257))
  def test_partial(self):
    p=pool(s=142*m.Q96//100,liquidity=20,fee=0,limit=m.Q96)
    row=m.route_quote(100,[p],'COLL')
    self.eq(row['status'],'partial_price_limit')
    self.false(row['modeled_all_inputs_consumed'])
    cfg=dict(p=100,d=1,stock=100,collateral_asset='COLL')
    r=m.search(cfg,[p])
    self.none(r['candidate'])
    self.eq(r['status'],'unresolved_model_domain')
  def test_cli(self):
    script=Path(m.__file__)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    run=lambda raw:subprocess.run([sys.executable,'-B',str(script)],input=raw,
                  capture_output=True,env=env,timeout=5)
    row=run(json.dumps(dict(operation='caps',p=1,d=1,stock=10)).encode())
    self.eq(row.returncode,0)
    r=json.loads(row.stdout)
    self.eq(r['q_cap'],10)
    self.false(r['authority_verified'])
    for raw in [b' '*65537,b'{"operation":"caps","p":1,"p":2}',
          b'{"operation":"caps","p":1.2}',b'NaN']:
      r=run(raw)
      self.eq(r.returncode,2)
      self.lt(len(r.stdout),1024)
    with self.raises(m.ModelError):
      m.bounded_tree(1<<513)
    with self.raises(m.ModelError):
      m.bounded_tree([0]*4097)
if __name__=='__main__':
  unittest.main()
