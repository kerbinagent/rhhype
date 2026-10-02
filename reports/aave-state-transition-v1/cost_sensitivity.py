"""Post-hoc cost break-even arithmetic, not a new execution or profit study."""
from decimal import Decimal,getcontext
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
getcontext().prec=50


def load(path,digest):
    raw=(ROOT/path).read_bytes()
    assert len(raw)<16384 and hashlib.sha256(raw).hexdigest()==digest
    return json.loads(raw)


def main():
    r=load('reports/aave-ordered-replay-v1/reconciliation.json','02386ed90d4768f25b082d4e6aa5e2f9a24518a6937360e02ce3fe737105b7a1')
    p=load('reports/aave-ordered-replay-v1/run-v1/projection.json','87831afaea4ba6804a049e669771ba1bcc501307664b4cd33b7e5014f719d826')
    gross=int(r['gross_unwrapped_wei']);bid=int(r['direct_fee_recipient_payment_wei'])
    gas_fee=int(r['target_gas_fee_wei']);remainder=int(r['conditional_native_remainder_wei'])
    gas_units=int(p['comparisons'][1]['gas_used'])
    assert gross-bid-gas_fee==remainder>0 and gas_fee%gas_units==0
    gas_price=gas_fee//gas_units
    ceil=lambda n,d:(n+d-1)//d
    stresses=[('extra_cost_equal_to_1bp_of_gross_unwrap',ceil(gross,10000)),
              ('extra_cost_equal_to_5bp_of_gross_unwrap',ceil(gross*5,10000)),
              ('gas_fee_10_percent_higher_same_gas_units',ceil(gas_fee,10)),
              ('gas_price_1_gwei_higher_same_gas_units',gas_units*10**9)]
    d=Decimal
    result=dict(schema='aave-conditional-cost-sensitivity-v1',post_hoc=True,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        gross_unwrap_wei=str(gross),direct_bid_wei=str(bid),target_gas_units=gas_units,
        target_effective_gas_price_wei=str(gas_price),target_gas_fee_wei=str(gas_fee),
        baseline_conditional_remainder_wei=str(remainder),
        baseline_conditional_remainder_eth=str(d(remainder)/10**18),
        remainder_basis_points_of_gross_unwrap=str(d(remainder)*10000/gross),
        max_extra_gas_price_wei_for_nonnegative_remainder=str(remainder//gas_units),
        max_extra_gas_units_at_recorded_price=str(remainder//gas_price),
        max_total_direct_bid_wei_for_nonnegative_remainder=str(gross-gas_fee),
        additional_gas_fee_percent_at_exact_zero=str(d(remainder)*100/gas_fee),
        stresses=[dict(scenario=name,additional_cost_wei=str(cost),conditional_remainder_wei=str(remainder-cost)) for name,cost in stresses],
        all_other_inputs_held_fixed=True,stresses_are_scenarios_not_measured_costs=True,
        amount_is_gross_unwrap_not_total_trade_notional=True,group_control_verified=False,
        token_balances_verified=False,private_costs_known=False,inclusion_verified_for_our_executor=False,
        realized_profit=False,repeatable_profit=False,
        implication='This copied historical execution has a narrow conditional cost allowance; lower bid or optimized gas cannot be assumed obtainable. No broader liquidation-family rejection.')
    assert all(int(x['conditional_remainder_wei'])<0 for x in result['stresses'])
    print(json.dumps(result,sort_keys=True,separators=(',',':')))


if __name__=='__main__':main()
