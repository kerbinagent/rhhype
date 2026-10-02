"""Post-run event reconciliation; consumes retained evidence, makes no RPCs."""
from collections import Counter
from decimal import Decimal, localcontext
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ordered', ROOT/'scripts/aave_ordered_replay_v1.py')
o = importlib.util.module_from_spec(spec)
spec.loader.exec_module(o)
PLAN_SHA = 'a07214cb94cacb76a340e01f4025206b2d1af70a28da89aeb72921974ede843c'
RAW_SHA = 'e71b33fb3d824b73688312cf949ff57812a626200f722046d2186712fddbc93e'
WETH = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'


def main():
    o.verify(PLAN_SHA)
    result, pin, _ = o.replay(ROOT/o.OUT/'responses.frames')
    if pin['sha256'] != RAW_SHA:
        raise o.Refusal('post_run_input_identity')
    baseline = o.load_baseline()
    flow = result['target_flows']
    selected = set(flow['selected_addresses'])
    net = {k: int(v) for k, v in flow['conditional_group_event_net_raw'].items() if k != o.ETH}
    deposit = o.c.keccak_hex('Deposit(address,uint256)')
    withdrawal = o.c.keccak_hex('Withdrawal(address,uint256)')
    conversions, expected_native = [], Counter()
    for row in baseline['target_receipt']['logs']:
        if row['address'] != WETH or row['topics'][0] not in (deposit, withdrawal):
            continue
        if len(row['topics']) != 2:
            raise o.Refusal('weth_conversion_topics')
        account = o.c.address_word(row['topics'][1])
        amount = int(o.h.hexdata(row['data'], 32), 16)
        withdrawing = row['topics'][0] == withdrawal
        if account in selected:
            net[WETH] = net.get(WETH, 0) + (-amount if withdrawing else amount)
            expected_native[(WETH, account) if withdrawing else (account, WETH)] += amount
        conversions.append(dict(kind='Withdrawal' if withdrawing else 'Deposit',
                                account=account, amount_raw=str(amount), log_index=o.h.quantity(row['logIndex'])))
    observed_native = Counter()
    fee_recipient = baseline['block']['miner']
    recipient_payment = 0
    for row in flow['transfers']:
        if row['asset'] != o.ETH:
            continue
        key = row['sender'], row['recipient']
        amount = int(row['amount_raw'])
        if (key[0] == WETH and key[1] in selected) or (key[1] == WETH and key[0] in selected):
            observed_native[key] += amount
        if key[0] in selected and key[1] == fee_recipient:
            recipient_payment += amount
    if expected_native != observed_native:
        raise o.Refusal('weth_event_native_mismatch')
    gross = sum(v for (sender, recipient), v in expected_native.items() if sender == WETH)
    gas = int(flow['target_transaction_gas_fee_wei'])
    remainder = int(flow['conditional_group_native_after_target_gas_wei'])
    if gross - recipient_payment - gas != remainder:
        raise o.Refusal('selected_case_native_reconciliation')
    records, _, _ = o.decode_frames(ROOT/o.OUT/'responses.frames')
    prefix = next(o.decode(r['body'])['result'] for r in records if r['begin']['name'] == 'prefix_receipt')
    answer_topic = o.c.keccak_hex('AnswerUpdated(int256,uint256,uint256)')
    answers = []
    for row in prefix['logs']:
        if row['topics'][0] != answer_topic:
            continue
        if len(row['topics']) != 3:
            raise o.Refusal('answer_updated_shape')
        answer = int(o.h.hexdata(row['topics'][1], 32), 16)
        if answer >= 2**255:
            answer -= 2**256
        answers.append(dict(emitter=row['address'], answer_signed_raw=str(answer),
            round_id_raw=str(int(o.h.hexdata(row['topics'][2], 32), 16)),
            updated_at_raw=str(int(o.h.hexdata(row['data'], 32), 16))))
    with localcontext() as ctx:
        ctx.prec = 60
        percent = str(Decimal(recipient_payment) * 100 / Decimal(gross))
    analysis = dict(schema='aave-ordered-post-run-reconciliation-v1', post_hoc=True,
        plan_sha256=PLAN_SHA, raw=pin, source_sha256=o.sha(Path(__file__).read_bytes()),
        actual_weth_deposit_withdrawal_events=conversions,
        weth_conversions_match_simulated_native=True,
        conditional_group_token_event_net_after_weth_conversions={k: str(v) for k, v in sorted(net.items())},
        gross_unwrapped_wei=str(gross), fee_recipient=fee_recipient,
        direct_fee_recipient_payment_wei=str(recipient_payment), target_gas_fee_wei=str(gas),
        conditional_native_remainder_wei=str(remainder), direct_payment_percent_of_unwrap=percent,
        prefix_answer_updated_events=answers,
        interpretation='WETH Transfer-only incoming amount is fully offset by its real Withdrawal event. Native amounts come from a provider simulation matching both receipts. Remainder assumes sender and executor share economic control; no state balance proof, private-cost proof, causal attribution, or prospective profitability.',
        token_balances_verified=False, grouping_control_verified=False, causal_trigger_identified=False,
        economics=False, closed_cash=False,
        reference='https://github.com/gnosis/canonical-weth/blob/master/contracts/WETH9.sol')
    o.publish(Path(__file__).parent, 'reconciliation.json', analysis)
    print(o.encode(analysis).decode())


if __name__ == '__main__':
    main()
