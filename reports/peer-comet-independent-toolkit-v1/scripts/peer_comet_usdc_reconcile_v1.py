#!/usr/bin/env python3
import json
import sys

U = 2**256 - 1
M128 = 2**128 - 1
INPUT_CAP = 65536

class Failure(Exception):
  def __init__(self, reason, status="unknown"):
    self.reason, self.status = reason, status

def check(ok, reason, status="rejected_closure"):
  if not ok:
    raise Failure(reason, status)

def unknown(ok, reason):
  check(ok, reason, "unknown")

def get(obj, key):
  if type(obj) is not dict or key not in obj:
    raise Failure("missing:" + key)
  return obj[key]

def uint(x, key, maximum=U):
  if x is None:
    raise Failure("missing:" + key)
  if type(x) is not int or not 0 <= x <= maximum:
    raise Failure("integer:" + key)
  return x

def nums(obj, keys):
  return [uint(get(obj, k), k) for k in keys.split()]

def text(x):
  return type(x) is str and 0 < len(x) <= 64

def digest(x):
  return text(x) and len(x) == 64 and all(c in "0123456789abcdef" for c in x)

def quantity_caps(p, d, stock, minimum=1):
  p, d = uint(p, "p", U * U), uint(d, "d", U * U)
  m, k = min(uint(stock, "stock"), M128), uint(minimum, "minimum")
  unknown(p > 0 and d > 0, "quote_zero")
  unknown(k > 0, "minimum_zero")
  lo, hi = (k*d+p-1)//p, min(U//p, ((m+1)*d-1)//p)
  return {"minimum": lo, "maximum": hi, "stock_cap": m, "positive_domain_empty": lo > hi}

def cash(record):
  steps = get(record, "steps")
  unknown(type(steps) is list and 1 <= len(steps) <= 2 and
     get(steps[-1], "token_out") == "USDC", "cash_unit")
  draw, repay = nums(get(record, "financing"), "draw_received repayment_debited")
  return (nums(steps[-1], "output")[0] - nums(get(record, "buy"), "debited")[0]
      + draw - repay - nums(record, "other_costs_usdc")[0]
      - nums(get(record, "disposals"), "USDC")[0])

def reconcile(record):
  out = {k: False for k in ("authority_verified", "source_equivalence_verified",
              "execution_established", "economic_claim", "hashes_authenticated")}
  out.update(status="unknown", reasons=[], pre_gas_usdc_gain=None, quantity=None,
       caps=None, assumptions={})
  try:
    out["pre_gas_usdc_gain"] = cash(record)
  except Failure:
    pass
  try:
    unknown(out["pre_gas_usdc_gain"] is not None, "cash_unavailable")
    unknown(get(record, "schema") == "peer-comet-usdc-reconciliation-v1", "schema")
    route, model = get(record, "route"), get(record, "model")
    tokens, pools, dec = (get(route, k) for k in ("tokens", "pools", "decimals"))
    unknown(type(tokens) is list and len(tokens) in (2, 3) and all(map(text, tokens)) and
       len(set(tokens)) == len(tokens) and tokens[-1] == "USDC" and
       (len(tokens) == 2 or tokens[1] == "WETH"), "route_tokens")
    unknown(type(pools) is list and len(pools) == len(tokens)-1 and all(map(text, pools)), "route_pools")
    unknown(len(set(pools)) == len(pools), "shared_pool_unsupported")
    unknown(type(dec) is list and len(dec) == len(tokens) and
       all(type(x) is int and 0 <= x <= 36 for x in dec) and dec[-1] == 6 and
       (len(tokens) == 2 or dec[1] == 18), "route_units")
    unknown(text(get(route, "id")) and digest(get(route, "sha256")) and
       digest(get(route, "state_id")), "route_identity")
    unknown(get(model, "state_id") == route["state_id"], "changed_state")
    p, d = get(model, "p"), get(model, "d")
    out["caps"] = cap = quantity_caps(p, d, get(model, "stock"), get(model, "minimum"))
    req, debit, q, nominal, bought = nums(get(record, "buy"),
      "requested debited received nominal_collateral actual_collateral")
    out["assumptions"] = {"debit_ge_receipt": debit >= q,
               "state_is_caller_claim": True}
    unknown(debit >= q and req >= q, "principal_rebate")
    unknown(p*q <= U, "quote_overflow")
    out["quantity"] = p*q//d
    check(cap["minimum"] <= q <= cap["maximum"], "quote_cap")
    check(nominal == out["quantity"], "nominal_quantity")
    unknown(bought <= nominal, "collateral_rebate")
    balance = get(record, "balances")
    maps = [get(balance, "opening"), get(balance, "closing"), get(record, "disposals")]
    unknown(all(type(x) is dict and set(x) == set(tokens) for x in maps), "asset_coverage")
    start, end, disposed = ({t: nums(x, t)[0] for t in tokens} for x in maps)
    finance = get(record, "financing")
    kind = get(finance, "kind")
    draw, principal, premium, repay, paid, owed_p, owed_f = nums(finance,
      "draw_received principal_due premium_due repayment_debited repayment_credited outstanding_principal outstanding_premium")
    unknown(kind in ("own", "external"), "financing_kind")
    if kind == "own":
      check(not any((draw, principal, premium, repay, paid, owed_p, owed_f)), "own_financing")
    else:
      check(principal >= draw and repay >= paid, "financing_quantity")
      check(owed_p == owed_f == 0, "loan_outstanding")
      check(paid == principal+premium, "loan_repayment")
    # Fixed buy-first route; sale-callback financing is a different model.
    check(start["USDC"]+draw >= debit, "unfunded_buy")
    steps = get(record, "steps")
    unknown(type(steps) is list and len(steps) == len(pools), "step_coverage")
    credits, debits = ({t: 0 for t in tokens} for _ in range(2))
    credits[tokens[0]] = available = bought
    for i, step in enumerate(steps):
      unknown(all(get(step, k) == v for k, v in
         zip(("pool", "token_in", "token_out"), (pools[i], tokens[i], tokens[i+1]))), "route_changed")
      unknown(get(step, "state_id") == route["state_id"], "changed_state")
      unknown(get(step, "coverage_complete") is True, "swap_coverage")
      ask, spent, received, output = nums(step, "requested debited received output")
      check(ask > 0, "zero_swap_input")
      check(received > 0 or output == 0, "unfunded_output")
      available -= disposed[tokens[i]]
      check(available >= 0 and ask == available, "stage_input")
      check(spent <= ask and received <= spent, "stage_gross_net")
      unknown(type(get(step, "full_fill")) is bool, "full_fill_type")
      check(step["full_fill"] and spent == ask, "partial_fill")
      # requested is V3 exact-input amountSpecified; require full callback funding.
      check(received == ask, "callback_funding")
      debits[tokens[i]] += spent
      credits[tokens[i+1]] += output
      available = output
    for t in tokens[:-1]:
      check(start[t]+credits[t] == debits[t]+disposed[t]+end[t], "asset_ledger:"+t)
      check(start[t] == 0, "opening_inventory:"+t)
      check(end[t] == 0, "residual:"+t)
    check(end["USDC"]-start["USDC"] == out["pre_gas_usdc_gain"], "usdc_cash_identity")
    out["status"] = "coherent_record"
  except Failure as exc:
    out["status"], out["reasons"] = exc.status, [exc.reason]
  return out

def decode(data):
  def pairs(items):
    obj = {}
    for k, v in items:
      if k in obj:
        raise ValueError("duplicate key")
      obj[k] = v
    return obj
  def bad_number(_):
    raise ValueError("noninteger JSON number")
  return json.loads(data, object_pairs_hook=pairs, parse_float=bad_number, parse_constant=bad_number)

def main():
  data = sys.stdin.buffer.read(INPUT_CAP+1)
  try:
    if len(data) > INPUT_CAP:
      raise ValueError("input cap")
    result = reconcile(decode(data))
  except (ValueError, UnicodeError, RecursionError):
    result = reconcile({})
    result["reasons"] = ["invalid_or_oversized_json"]
  print(json.dumps(result, sort_keys=True, separators=(",", ":")))
  return int(result["status"] != "coherent_record")

if __name__ == "__main__":
  raise SystemExit(main())
