import copy, json, runpy, types
from pathlib import Path
import subprocess
import sys
import unittest

SOURCE = Path(__file__).resolve().parents[1]/"scripts/peer_comet_usdc_reconcile_v1.py"
r = types.SimpleNamespace(**runpy.run_path(str(SOURCE)))
REJECTED = "rejected_closure"

def case(two=False, external=False):
 tokens = ["C", "WETH", "USDC"] if two else ["C", "USDC"]
 steps = []
 for i in range(len(tokens)-1):
  n = 100 if i == 0 else 8
  steps.append(dict(pool="p"+str(i), state_id="b"*64,
      token_in=tokens[i], token_out=tokens[i+1],
      requested=n, debited=n, received=n,
      output=8 if two and i == 0 else 110,
      full_fill=True, coverage_complete=True))
 opening = {t: 0 for t in tokens}
 closing = dict(opening)
 opening["USDC"], closing["USDC"] = (0, 7) if external else (100, 110)
 finance = dict.fromkeys("draw_received principal_due premium_due repayment_debited repayment_credited outstanding_principal outstanding_premium".split(), 0)
 finance["kind"] = "external" if external else "own"
 if external:
  finance.update(draw_received=100, principal_due=100, premium_due=3,
         repayment_debited=103, repayment_credited=103)
 return dict(schema="peer-comet-usdc-reconciliation-v1",
    route=dict(id="r", sha256="a"*64, state_id="b"*64,
      tokens=tokens, pools=[s["pool"] for s in steps],
      decimals=[18]*(len(tokens)-1)+[6]),
    model=dict(p=1, d=1, stock=1000, minimum=1, state_id="b"*64),
    buy=dict(requested=100, debited=100, received=100,
      nominal_collateral=100, actual_collateral=100), steps=steps,
    balances=dict(opening=opening, closing=closing),
    financing=finance,
    disposals={t: 0 for t in tokens}, other_costs_usdc=0)

class Tests(unittest.TestCase):
 def result(self, record, status="coherent_record", gain=None):
  out = r.reconcile(record)
  self.assertEqual(out["status"], status, out)
  if gain is not None:
   self.assertEqual(out["pre_gas_usdc_gain"], gain)
  for k in ("authority_verified", "source_equivalence_verified",
    "execution_established", "economic_claim", "hashes_authenticated"):
   self.assertIs(out[k], False)
  return out

 def test_cash(self):
  x = case()
  self.result(x, gain=10)
  x["other_costs_usdc"] = 2
  x["balances"]["closing"]["USDC"] = 108
  self.result(x, gain=8)
  x = case(); x["balances"].update(opening={"C":0,"USDC":0}, closing={"C":0,"USDC":10})
  self.assertEqual(self.result(x, REJECTED, 10)["reasons"], ["unfunded_buy"])

 def test_loan(self):
  x = case(external=True)
  self.result(x, gain=7)
  x["financing"].update(draw_received=120, principal_due=120,
       repayment_debited=123, repayment_credited=123)
  self.result(x, gain=7)

 def test_receipt(self):
  x = case()
  x["buy"].update(received=99, nominal_collateral=99, actual_collateral=99)
  x["steps"][0].update(requested=99, debited=99, received=99, output=99)
  x["balances"]["closing"]["USDC"] = 99
  out = self.result(x, gain=-1)
  self.assertEqual(out["quantity"], 99)
  x["buy"]["nominal_collateral"] = 100
  self.result(x, REJECTED, -1)

 def test_caps(self):
  self.assertEqual(r.quantity_caps(2, 3, 1), dict(minimum=2, maximum=2, stock_cap=1, positive_domain_empty=False))
  c = r.quantity_caps(1, r.U+1, 1)
  self.assertTrue(c["positive_domain_empty"])
  self.assertEqual(c["minimum"], r.U+1)
  with self.assertRaises(r.Failure): r.quantity_caps(1, 1, 1, 0)
  self.assertEqual(r.quantity_caps(r.U, r.U, 2)["maximum"], 1)
  self.assertEqual(r.quantity_caps(1, 1, r.U)["stock_cap"], 2**128-1)
  x = case()
  x["model"].update(p=r.U, d=r.U)
  self.result(x, "unknown")
  x = case()
  x["model"]["stock"] = 99
  self.result(x, REJECTED)

 def test_partial(self):
  x = case()
  x["steps"][0].update(debited=99, received=99)
  x["balances"]["closing"]["C"] = 1
  out = self.result(x, REJECTED, 10)
  self.assertEqual(out["reasons"], ["partial_fill"])

 def test_inventory(self):
  x = case()
  x["balances"]["opening"]["C"] = 1
  x["steps"][0].update(requested=101, debited=101, received=101)
  self.result(x, REJECTED)

 def test_disposal(self):
  x = case()
  x["disposals"]["C"] = 1
  x["steps"][0].update(requested=99, debited=99, received=99)
  self.result(x, gain=10)
  x["disposals"]["USDC"] = 5
  x["balances"]["closing"]["USDC"] = 105
  self.result(x, gain=5)
  x["balances"]["closing"]["USDC"] = 106
  self.result(x, REJECTED, 5)

 def test_absent(self):
  y = case(); del y["other_costs_usdc"]
  self.assertIsNone(self.result(y, "unknown")["pre_gas_usdc_gain"])
  x = case()
  x["steps"][0]["output"] = 0
  x["balances"]["closing"]["USDC"] = 0
  self.result(x, gain=-100)
  for missing in (None, "absent"):
   y = copy.deepcopy(x)
   if missing is None:
    y["steps"][0]["output"] = None
   else:
    del y["steps"][0]["output"]
   self.assertIsNone(self.result(y, "unknown")["pre_gas_usdc_gain"])

 def test_numbers(self):
  for bad in (True, 1.0, "100", -1, r.U+1):
   x = case(); x["buy"]["received"] = bad
   self.result(x, "unknown")
  x = case(); x["steps"][0]["received"] = 101
  self.result(x, REJECTED)
  x = case(); x["steps"][0]["received"] = 99
  self.assertEqual(self.result(x, REJECTED, 10)["reasons"], ["callback_funding"])
  x = case(); x["buy"]["debited"] = 99
  self.result(x, "unknown")

 def test_debt(self):
  for key, value in (("outstanding_principal", 1), ("outstanding_premium", 1),
      ("repayment_credited", 102)):
   x = case(external=True); x["financing"][key] = value
   self.result(x, REJECTED, 7)
  x = case(); x["financing"]["draw_received"] = 1
  self.result(x, REJECTED)

 def test_two_hop(self):
  x = case(two=True)
  self.result(x, gain=10)
  x["steps"][0]["output"] = 0
  x["steps"][1].update(requested=0, debited=0, received=0)
  self.result(x, REJECTED)
  x["steps"][1]["output"] = x["balances"]["closing"]["USDC"] = 0
  self.result(x, REJECTED, -100)
  x = case(two=True); x["route"]["pools"][1] = "p0"
  self.result(x, "unknown")

 def test_identity(self):
  for area, key, value in (("step", "pool", "changed"), ("step", "state_id", "c"*64),
        ("step", "coverage_complete", False), ("step", "full_fill", 1),
        ("route", "sha256", "bad"), ("route", "decimals", [18, 18])):
   x = case(); (x["steps"][0] if area == "step" else x[area])[key] = value
   self.result(x, "unknown")
  x = case(); x.update(authority_verified=True, economic_claim=True)
  self.result(x, gain=10)

 def test_cli(self):
  payload = json.dumps(case()).encode()
  for body, code in ((payload, 0), (payload+b" "*(65536-len(payload)), 0),
      (b" "*65537, 1), (b'{"x":1,"x":2}', 1), (b'{"x":1e999}', 1)):
   proc = subprocess.run([sys.executable, "-B", str(SOURCE)], input=body,
        capture_output=True, timeout=3)
   self.assertEqual(proc.returncode, code, proc.stderr)
   out = json.loads(proc.stdout)
   self.assertIs(out["economic_claim"], False)
