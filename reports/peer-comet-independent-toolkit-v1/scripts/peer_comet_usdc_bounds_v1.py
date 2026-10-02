"""Offline native-unit MODEL: supplied state is not authority.
Candidate V3 v1.0.0 arithmetic; no runtime, settlement or profit certification.
"""
import json
import sys
import time
from fractions import Fraction

U256 = (1 << 256) - 1
U128 = (1 << 128) - 1
I256 = (1 << 255) - 1
Q96 = 1 << 96
Q192 = 1 << 192
F = 1000000
MIN_TICK, MAX_TICK = -887272, 887272
MIN_SQRT = 4295128739
MAX_SQRT = 1461446703485210103287273052203988822378723970342
MAX_STEPS, MAX_QUOTES, MAX_INTERVALS, MAX_MS = 256, 256, 4096, 2000
FLAGS = dict(authority_verified=False, source_equivalence_proven=False,
      economic_state_verified=False, cash_closed_execution_proven=False,
      inclusion_proven=False, profitability_proven=False)
_RATIOS = tuple(int(x, 16) for x in (
  'fffcb933bd6fad37aa2d162d1a594001', 'fff97272373d413259a46990580e213a',
  'fff2e50f5f656932ef12357cf3c7fdcc', 'ffe5caca7e10e4e61c3624eaa0941cd0',
  'ffcb9843d60f6159c9db58835c926644', 'ff973b41fa98c081472e6896dfb254c0',
  'ff2ea16466c96a3843ec78b326b52861', 'fe5dee046a99a2a811c461f1969c3053',
  'fcbe86c7900a88aedcffc83b479aa3a4', 'f987a7253ac413176f2b074cf7815e54',
  'f3392b0822b70005940c7a398e4b70f3', 'e7159475a2c29b7443b29c7fa6e889d9',
  'd097f3bdfd2022b8845ad8f792aa5825', 'a9f746462d870fdf8a65dc1f90e061e5',
  '70d869a156d2a1b890bb3df62baf32f7', '31be135f97d08fd981231505542fcfa6',
  '9aa508b5b7a84e1c677de54f3e99bc9', '5d6af8dedb81196699c329225ee604',
  '2216e584f5fa1ea926041bedfe98', '48a170391f7dc42444e8fa2'))

class ModelError(ValueError):
  pass

class CoverageError(ModelError):
  pass

def integer(x, lo=0, hi=U256):
  if type(x) is not int or not lo <= x <= hi:
    raise ModelError('integer/type/width')
  return x

def ceildiv(a, b):
  if a < 0 or b <= 0:
    raise ModelError('division')
  return (a + b - 1) // b

def muldiv(a, b, d, up=False):
  integer(a); integer(b); integer(d, 1)
  n = a * b
  z = ceildiv(n, d) if up else n // d
  return integer(z)

def comet_caps(p, d, stock, uint_max=U256, minimum=1):
  integer(p, 1, U256 * U256); integer(d, 1, U256 * U256)
  integer(stock); integer(uint_max, 1); integer(minimum, 1)
  m = min(stock, U128)
  qa = uint_max // p
  qi = ((m + 1) * d - 1) // p
  low, high = ceildiv(minimum * d, p), min(qa, qi)
  return dict(q_min=low, q_cap=high, q_arithmetic=qa, q_inventory=qi,
        output_cap=m, minimum_collateral=minimum, empty=low > high, **FLAGS)

def checked_quote(q, p, d, stock=U128, uint_max=U256):
  integer(q, 1, uint_max)
  caps = comet_caps(p, d, stock, uint_max)
  if p * q > uint_max:
    raise ModelError('Comet checked multiplication')
  c = p * q // d
  if c > caps['output_cap']:
    raise ModelError('inventory/uint128 output')
  return c

def name(x):
  if type(x) is not str or not 1 <= len(x) <= 64 or not x.isascii():
    raise ModelError('asset/pool identity')
  return x.lower()

def pool_rate(pool, input_asset):
  a, b = name(pool['token0']), name(pool['token1'])
  if a == b:
    raise ModelError('identical assets')
  s = integer(pool['sqrt_price'], MIN_SQRT, MAX_SQRT - 1)
  fee = integer(pool['fee'], 0, F - 1)
  incoming = name(input_asset)
  if incoming == a:
    rho, outgoing = Fraction(s * s, Q192), b
  elif incoming == b:
    rho, outgoing = Fraction(Q192, s * s), a
  else:
    raise ModelError('route input asset')
  return rho * Fraction(F - fee, F), rho, outgoing

def validate_route(pools, collateral, base='USDC'):
  if type(pools) is not list or not 1 <= len(pools) <= 2:
    raise ModelError('one/two pools only')
  if any(type(pool) is not dict for pool in pools):
    raise ModelError('pool dictionary')
  ids = [name(p['pool_id']) for p in pools]
  if len(set(ids)) != len(ids):
    raise ModelError('shared pool requires state mutation; refused')
  asset = name(collateral)
  for pool in pools:
    _, _, asset = pool_rate(pool, asset)
  if asset != name(base):
    raise ModelError('route must end in base native units')

def fee_bound(c, pool, input_asset):
  integer(c, 0, U256 * U256)
  _, rho, _ = pool_rate(pool, input_asset)
  net = c * (F - pool['fee']) // F
  return rho.numerator * net // rho.denominator

def route_bound(c, pools, collateral, base='USDC'):
  validate_route(pools, collateral, base)
  asset = name(collateral)
  for pool in pools:
    c = fee_bound(c, pool, asset)
    _, _, asset = pool_rate(pool, asset)
  return c

def coefficient(p, d, pools, collateral, base='USDC'):
  comet_caps(p, d, 0)
  validate_route(pools, collateral, base)
  result, asset = Fraction(p, d), name(collateral)
  for pool in pools:
    k, _, asset = pool_rate(pool, asset)
    result *= k
  return result

def sqrt_at_tick(tick):
  integer(tick, MIN_TICK, MAX_TICK)
  absolute = abs(tick)
  ratio = 1 << 128
  for i, constant in enumerate(_RATIOS):
    if absolute & (1 << i):
      ratio = ratio * constant >> 128
  if tick > 0:
    ratio = U256 // ratio
  return (ratio >> 32) + bool(ratio & ((1 << 32) - 1))

def tick_at_sqrt(s):
  integer(s, MIN_SQRT, MAX_SQRT - 1)
  lo, hi = MIN_TICK, MAX_TICK
  while lo < hi:
    mid = (lo + hi + 1) // 2
    if sqrt_at_tick(mid) <= s:
      lo = mid
    else:
      hi = mid - 1
  return lo

def amount0(a, b, liq, up):
  integer(a, 1, (1 << 160) - 1); integer(b, 1, (1 << 160) - 1)
  integer(liq, 0, U128)
  a, b = min(a, b), max(a, b)
  t = muldiv(liq << 96, b - a, b, up)
  return integer(ceildiv(t, a) if up else t // a)

def amount1(a, b, liq, up):
  integer(a, 1, (1 << 160) - 1); integer(b, 1, (1 << 160) - 1)
  integer(liq, 0, U128)
  return muldiv(liq, abs(b - a), Q96, up)

def next_from_input(s, liq, amount, zfo):
  integer(s, 1, (1 << 160) - 1); integer(liq, 1, U128)
  integer(amount)
  if amount == 0:
    return s
  if zfo:
    n = liq << 96
    product = amount * s
    if product <= U256 and n + product <= U256:
      return integer(muldiv(n, s, n + product, True), 1, (1 << 160) - 1)
    denominator = integer(n // s + amount, 1)
    return integer(ceildiv(n, denominator), 1, (1 << 160) - 1)
  delta = muldiv(amount, Q96, liq)
  return integer(s + delta, 1, (1 << 160) - 1)

def swap_step(s, target, liq, left, fee, zfo):
  integer(left, 1, I256); integer(fee, 0, F - 1)
  integer(liq, 0, U128)
  if type(zfo) is not bool or (zfo and target > s) or (
      not zfo and target < s):
    raise ModelError('step direction')
  delta_in = amount0 if zfo else amount1
  delta_out = amount1 if zfo else amount0
  need = delta_in(s, target, liq, True)
  budget = muldiv(left, F - fee, F)
  nxt = target if budget >= need else next_from_input(s, liq, budget, zfo)
  net = need if nxt == target else delta_in(s, nxt, liq, True)
  out = delta_out(s, nxt, liq, False)
  charge = muldiv(net, fee, F - fee, True) if nxt == target else left - net
  integer(charge)
  if net > budget or net + charge > left:
    raise ModelError('step exceeds gross/net budget')
  return dict(sqrt_price=nxt, net_input=net, output=out, fee=charge,
        consumed=net + charge)

def next_bitmap_tick(tick, spacing, zfo, word, bitmap):
  compressed = tick // spacing
  lookup = compressed if zfo else compressed + 1
  expected_word, bit = lookup >> 8, lookup & 255
  integer(word, -(1 << 15), (1 << 15) - 1); integer(bitmap)
  if word != expected_word:
    raise CoverageError('bitmap word coverage')
  if zfo:
    masked = bitmap & ((1 << (bit + 1)) - 1)
    nxt = compressed - bit + (masked.bit_length() - 1 if masked else 0)
  else:
    masked = bitmap & (U256 ^ ((1 << bit) - 1))
    first = (masked & -masked).bit_length() - 1 if masked else 255
    nxt = lookup + first - bit
  raw_tick = nxt * spacing
  return max(MIN_TICK, min(MAX_TICK, raw_tick)), bool(masked)

def quote_exact_input(state, steps, amount, max_steps=MAX_STEPS, deadline_ns=None):
  """Step keys: word, bitmap, tick, sqrt_price, initialized, liquidity_net."""
  result = dict(status='unknown_arithmetic', output=None, remaining_input=None,
         steps=0, coverage_authority_verified=False, **FLAGS)
  try:
    if type(state) is not dict:
      raise ModelError('state dictionary')
    integer(amount, 1, I256); integer(max_steps, 1, MAX_STEPS)
    if type(steps) is not list or len(steps) > 4096:
      raise ModelError('supplied step cap/type')
    s = integer(state['sqrt_price'], MIN_SQRT, MAX_SQRT - 1)
    tick = integer(state['tick'], MIN_TICK, MAX_TICK - 1)
    if not sqrt_at_tick(tick) <= s <= sqrt_at_tick(tick + 1):
      raise ModelError('stored tick/price mismatch')
    liq = integer(state['liquidity'], 0, U128)
    fee = integer(state['fee'], 0, F - 1)
    # Missing fee_protocol is a default-zero model premise, not observed state.
    protocol = integer(state.get('fee_protocol', 0), 0, 10)
    if protocol not in (0, 4, 5, 6, 7, 8, 9, 10):
      raise ModelError('protocol fee nibble')
    spacing = integer(state['tick_spacing'], 1, 16383)
    direction = state['zero_for_one']
    if type(direction) is not bool:
      raise ModelError('direction bool')
    limit = integer(state['price_limit'], MIN_SQRT + 1, MAX_SQRT - 1)
    if not (limit < s if direction else limit > s):
      raise ModelError('price limit direction')
    left, output, net, fees = amount, 0, 0, 0
    words = {}
    for index in range(max_steps):
      if deadline_ns is not None and time.monotonic_ns() >= deadline_ns:
        result.update(status='unknown_work', reason='elapsed cap')
        break
      if index >= len(steps):
        result.update(status='unknown_coverage', reason='missing protocol step')
        break
      row = steps[index]
      if type(row) is not dict:
        raise ModelError('step dictionary')
      word, bitmap = row['word'], row['bitmap']
      nxt_tick, init = next_bitmap_tick(tick, spacing, direction, word, bitmap)
      if word in words and words[word] != bitmap:
        result.update(status='unknown_coverage', reason='inconsistent static bitmap')
        break
      words[word] = bitmap
      integer(row['tick'], MIN_TICK, MAX_TICK)
      integer(row['sqrt_price'], MIN_SQRT, MAX_SQRT)
      if (type(row['initialized']) is not bool or row['initialized'] != init
          or row['tick'] != nxt_tick or row['sqrt_price'] != sqrt_at_tick(nxt_tick)):
        result.update(status='unknown_coverage', reason='non-protocol/missing boundary')
        break
      delta = integer(row['liquidity_net'], -(1 << 127) + 1, (1 << 127) - 1)
      if not init and delta != 0:
        raise ModelError('uninitialized liquidity transition')
      boundary = row['sqrt_price']
      target = max(limit, boundary) if direction else min(limit, boundary)
      old_s, old_tick = s, tick
      step = swap_step(s, target, liq, left, fee, direction)
      s = step['sqrt_price']
      left -= step['consumed']
      integer(step['output'], 0, I256)
      output = integer(output + step['output'], 0, 1 << 255)
      net = integer(net + step['net_input'])
      fees = integer(fees + step['fee'])
      growth_fee = step['fee'] - (step['fee'] // protocol if protocol else 0)
      if liq:
        muldiv(growth_fee, 1 << 128, liq)
      result['steps'] = index + 1
      if s == boundary:
        if init:
          liq = integer(liq + (-delta if direction else delta), 0, U128)
        tick = nxt_tick - 1 if direction else nxt_tick
      elif s != old_s:
        tick = tick_at_sqrt(s)
      if left == 0 or s == limit:
        result.update(status='complete_input' if left == 0 else 'partial_price_limit',
               output=output, remaining_input=left, consumed=amount - left,
               net_input=net, fee=fees, sqrt_price=s, tick=tick, liquidity=liq,
               cash_closed=False)
        break
      if s == old_s and tick == old_tick and step['consumed'] == 0:
        raise ModelError('no traversal progress')
    else:
      result.update(status='unknown_work', reason='step cap')
  except (ModelError, KeyError, TypeError, OverflowError) as exc:
    result.update(status='unknown_coverage' if isinstance(exc, CoverageError)
           else 'unknown_arithmetic', reason=str(exc)[:96], output=None)
  return result

def route_quote(c, pools, collateral, base='USDC', max_steps=MAX_STEPS, deadline_ns=None):
  validate_route(pools, collateral, base)
  asset, profiles, closed = name(collateral), [], True
  for pool in pools:
    _, _, outgoing = pool_rate(pool, asset)
    state = dict(pool, zero_for_one=asset == name(pool['token0']))
    if c == 0:
      return dict(status='unknown_arithmetic', output=None, profiles=profiles,
            reason='zero-input swap is not execution', **FLAGS)
    profile = quote_exact_input(state, pool['steps'], c, max_steps, deadline_ns)
    profiles.append(profile)
    if profile['output'] is None:
      return dict(status=profile['status'], output=None, profiles=profiles, **FLAGS)
    closed &= profile['status'] == 'complete_input'
    c, asset = profile['output'], outgoing
  return dict(status='complete_input' if closed else 'partial_price_limit', output=c,
        profiles=profiles, modeled_all_inputs_consumed=closed,
        cash_closed=False, **FLAGS)

def search(config, pools, limits=None):
  """Fixed K, debit=q, claimed cost floor; partial H is not a closed route."""
  started = time.monotonic_ns()
  if type(config) is not dict or (limits is not None and type(limits) is not dict):
    raise ModelError('configuration dictionary')
  lim = dict(steps=MAX_STEPS, quotes=MAX_QUOTES, intervals=MAX_INTERVALS,
       pending=MAX_INTERVALS, elapsed_ms=MAX_MS)
  if limits:
    for key, value in limits.items():
      if key not in lim:
        raise ModelError('unknown limit')
      lim[key] = integer(value, 1, lim[key])
  p, d, stock = config['p'], config['d'], config['stock']
  collateral, base = config['collateral_asset'], config.get('base_asset', 'USDC')
  cost = integer(config.get('cost_lower', 0))
  validate_route(pools, collateral, base)
  caps = comet_caps(p, d, stock, minimum=config.get('minimum', 1))
  low, high = caps['q_min'], caps['q_cap']
  k = coefficient(p, d, pools, collateral, base)
  result = dict(status='empty_model_domain' if caps['empty'] else 'unresolved_model_domain',
         caps=caps, domain=[low, high], coefficient=[k.numerator, k.denominator],
         cost_lower_claim=cost, debit_assumption='q; actual funding not verified',
         quotes=0, processed_intervals=0, pruned_intervals=0, pruned_quantities=0,
         unresolved_intervals=[], unresolved_count=0, unresolved_quantities=0,
         candidate=None, **FLAGS)
  if caps['empty']:
    return result
  pending, unresolved, cache = [(low, high)], [], {}
  deadline = started + lim['elapsed_ms'] * 1000000

  def expired():
    return time.monotonic_ns() - started >= lim['elapsed_ms'] * 1000000

  def evaluate(q):
    if q in cache:
      return cache[q]
    if expired() or result['quotes'] + len(pools) > lim['quotes']:
      return dict(status='unknown_work', output=None)
    c = checked_quote(q, p, d, stock)
    row = route_quote(c, pools, collateral, base, lim['steps'], deadline)
    result['quotes'] += len(row['profiles'])
    cache[q] = row
    return row

  while pending:
    if expired() or result['processed_intervals'] >= lim['intervals']:
      unresolved.extend((a, b, 'search work cap') for a, b in pending)
      pending.clear()
      break
    l, u = pending.pop()
    result['processed_intervals'] += 1
    delta = k - 1
    linear = (u if delta >= 0 else l) * delta.numerator // delta.denominator
    analytical = min(linear, route_bound(p * u // d, pools, collateral, base) - l)
    if analytical <= cost:
      result['pruned_intervals'] += 1
      result['pruned_quantities'] += u - l + 1
      continue
    endpoint = evaluate(u)
    if endpoint['output'] is not None and endpoint['output'] - l <= cost:
      result['pruned_intervals'] += 1
      result['pruned_quantities'] += u - l + 1
      continue
    if (endpoint['status'] == 'complete_input' and endpoint['output'] is not None
        and endpoint['output'] - u > cost):
      result['candidate'] = dict(q=u, collateral=p * u // d,
                   output=endpoint['output'], quoted_model_gain=endpoint['output'] - u,
                   profile=endpoint)
      result['status'] = 'conditional_positive_model_candidate'
      if l < u:
        unresolved.append((l, u - 1, 'not searched after candidate'))
      unresolved.extend((a, b, 'not searched after candidate') for a, b in pending)
      pending.clear()
      break
    if l == u:
      unresolved.append((l, u, endpoint['status']))
    elif len(pending) + len(unresolved) + 2 > lim['pending']:
      unresolved.append((l, u, 'pending cap'))
    elif endpoint['status'] == 'unknown_work':
      unresolved.append((l, u, 'quote/time cap'))
    else:
      middle = (l + u) // 2
      pending.extend(((middle + 1, u), (l, middle)))
  result['unresolved_count'] = len(unresolved)
  result['unresolved_quantities'] = sum(b - a + 1 for a, b, _ in unresolved)
  result['unresolved_intervals'] = [list(row) for row in unresolved]
  if not unresolved and result['candidate'] is None:
    result['status'] = 'mathematical_rejection'
  result['full_domain_rejected'] = result['status'] == 'mathematical_rejection'
  result['elapsed_ms'] = (time.monotonic_ns() - started) // 1000000
  return result

def bounded_tree(value, depth=0, count=None):
  count = [0] if count is None else count
  count[0] += 1
  if depth > 16 or count[0] > 8192:
    raise ModelError('JSON tree cap')
  kind = type(value)
  if kind in (dict, list):
    if len(value) > 4096:
      raise ModelError('JSON collection cap')
    if kind is dict:
      if any(type(key) is not str or len(key) > 128 for key in value):
        raise ModelError('JSON key')
    for item in value.values() if kind is dict else value:
      bounded_tree(item, depth + 1, count)
  elif kind is int and value.bit_length() > 512:
    raise ModelError('JSON integer cap')
  elif kind is str and len(value) > 512:
    raise ModelError('JSON string cap')
  elif kind not in (int, str, bool, type(None)):
    raise ModelError('JSON integer-only numbers')

def unique_object(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise ModelError('duplicate JSON key')
    result[key] = value
  return result

def run(request):
  bounded_tree(request)
  op = request['operation']
  if op == 'caps':
    return comet_caps(request['p'], request['d'], request['stock'], minimum=request.get('minimum', 1))
  if op == 'quote':
    return quote_exact_input(request['state'], request['steps'], request['amount'])
  if op == 'bounds':
    cfg, pools = request['config'], request['pools']
    caps = comet_caps(cfg['p'], cfg['d'], cfg['stock'], minimum=cfg.get('minimum', 1))
    k = coefficient(cfg['p'], cfg['d'], pools, cfg['collateral_asset'], cfg.get('base_asset', 'USDC'))
    return dict(caps=caps, coefficient=[k.numerator, k.denominator],
          payout_upper=route_bound(request['collateral_amount'], pools,
                      cfg['collateral_asset'], cfg.get('base_asset', 'USDC')),
          all_size_pre_cost_rejection=k <= 1, **FLAGS)
  if op == 'search':
    return search(request['config'], request['pools'], request.get('limits'))
  raise ModelError('operation')

def main():
  try:
    if len(sys.argv) != 1:
      raise ModelError('JSON stdin only')
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
      raise ModelError('input byte cap')
    request = json.loads(raw, object_pairs_hook=unique_object,
              parse_float=lambda _: (_ for _ in ()).throw(ModelError('float forbidden')),
              parse_constant=lambda _: (_ for _ in ()).throw(ModelError('nonfinite forbidden')))
    result = run(request)
    encoded = json.dumps(result, separators=(',', ':'), ensure_ascii=True).encode()
    if len(encoded) + 1 > 65536 and 'unresolved_intervals' in result:
      result['unresolved_intervals'] = result['unresolved_intervals'][:32]
      result['unresolved_intervals_truncated'] = True
      encoded = json.dumps(result, separators=(',', ':')).encode()
    if len(encoded) + 1 > 65536:
      raise ModelError('output byte cap')
    sys.stdout.buffer.write(encoded + b'\n')
    return 0
  except (ValueError, KeyError, TypeError, OverflowError, RecursionError) as exc:
    print(json.dumps(dict(status='invalid_model_input', reason=str(exc)[:96], **FLAGS),
            separators=(',', ':')))
    return 2

if __name__ == '__main__':
  raise SystemExit(main())
