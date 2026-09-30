"""Future-model algebra only; no market/account data or frozen-study inputs.

BTC fee debits are assumed nonnegative and no greater than the stated caps.
The caps must cover the whole order, including all fill rounding.
They are assumptions here, not authenticated exchange/account maxima.
"""
from fractions import Fraction
import json


def exact(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Fraction)):
        raise ValueError('use exact decimal strings, integers or Fractions')
    return Fraction(value)


def envelope(q, step, entry_rate, exit_rate, entry_additive, exit_additive):
    q, step, fe, fx, de, dx = map(exact, (
        q, step, entry_rate, exit_rate, entry_additive, exit_additive))
    if q <= 0 or step <= 0 or not 0 <= fe < 1 or min(fx, de, dx) < 0:
        raise ValueError('invalid quantity, grid or fee caps')
    if (q / step).denominator != 1:
        raise ValueError('gross exit quantity must satisfy spot grid')
    needed_steps = (q * (1 + fx) + de + dx) / (1 - fe) / step
    g = -(-needed_steps.numerator // needed_steps.denominator) * step
    entry_cap, exit_cap = fe * g + de, fx * q + dx
    cases = []
    for entry_currency in ('BTC', 'quote'):
        for exit_currency in ('BTC', 'quote'):
            entry_debit = entry_cap if entry_currency == 'BTC' else Fraction(0)
            exit_debit = exit_cap if exit_currency == 'BTC' else Fraction(0)
            lower = g - entry_debit - q - exit_debit
            assert lower >= 0
            cases.append({'entry_fee_currency': entry_currency,
                          'exit_fee_currency': exit_currency,
                          'residual_btc_lower_bound': str(lower),
                          'residual_btc_upper_bound': str(g - q)})
    return {'gross_spot_buy_btc': str(g), 'gross_spot_sell_btc': str(q),
            'entry_btc_fee_cap': str(entry_cap), 'exit_btc_fee_cap': str(exit_cap),
            'cases': cases}


def synthetic_example():
    inputs = {'q': '0.01', 'step': '0.00000001', 'entry_rate': '0.0005',
              'exit_rate': '0.0005', 'entry_additive': '0.00000001',
              'exit_additive': '0.00000001'}
    return {'schema': 'spot-fee-inventory-envelope-synthetic-v1',
            'synthetic': True, 'inputs': inputs, 'result': envelope(**inputs),
            'formula': 'g=ceil_step((q*(1+exit_rate)+entry_additive+exit_additive)/(1-entry_rate))',
            'limitations': [
                'Rate and additive caps are assumptions over each whole order, not venue guarantees.',
                'Additive allowances must cover all fill rounding; the example is not a fee-precision claim.',
                'Successful gross acquisition is assumed; depth, budget, future grid and order limits remain external gates.',
                'Quote fees require separately funded cash and their own caps.',
                'Residual BTC can remain exposed or untradeable dust; this does not prove an exact hedge or closed P&L.',
                'Represent BTC fees in inventory quantities; do not subtract their USD value again from the same cashflows.',
                'No quote data, account data or frozen carry-study inputs are read.'],
            'all_in_headroom': None, 'closed_pnl': None}


if __name__ == '__main__':
    print(json.dumps(synthetic_example(), indent=2, sort_keys=True))
