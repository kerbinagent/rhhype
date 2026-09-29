"""Explicit public-market constraints and paper assumptions for RH maker replay."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ASSETS = ('BTC', 'ETH', 'NVDA', 'XAG')
SIZES = (100, 250, 500, 1000)
POLICIES = ('adaptive', 'persistence', 'fixed_best')
MAX_METADATA_BYTES = 5_000_000


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise ValueError(f'metadata too large: {path.name}')
    return json.loads(path.read_bytes())


def policy_metadata(directory, tier='standard'):
    """Keep observed constraints separate from declared fees and timing assumptions.

    Account-specific rates, fills, and reduce-only dust exceptions are not
    observable here. None is silently obtained from a private endpoint.
    """
    if tier not in ('standard', 'premium'):
        raise ValueError('only frozen Standard and Premium scenarios supported')
    directory = Path(directory)
    n = read_json(directory / 'normalized.json')
    plan_path = directory / 'market_plan.json'
    plan = read_json(plan_path)
    if hashlib.sha256(plan_path.read_bytes()).hexdigest() != n['market_plan_sha256']:
        raise ValueError('market plan digest differs from normalized metadata')
    for name, request in n['raw_requests'].items():
        p = directory / f'{name}.json'
        if p.stat().st_size > MAX_METADATA_BYTES:
            raise ValueError('raw metadata too large')
        raw = p.read_bytes()
        if request['status'] != 200 or len(raw) != request['raw_bytes'] or hashlib.sha256(raw).hexdigest() != request['sha256']:
            raise ValueError(f'raw metadata integrity failure: {name}')
    for name in ('hl_meta_native', 'hl_meta_xyz'):
        if read_json(directory / f'{name}.json').get('collateralToken') != 0:
            raise ValueError('changed HL collateral requires a new study')
    by_asset = {}
    for asset in ASSETS:
        rh = deepcopy(n['markets']['rh_lighter'][asset])
        hl = deepcopy(n['markets']['hyperliquid'][asset])
        route = [r for r in plan['pairs'] if r['asset'] == asset and r['other']['venue'] == 'rh_lighter']
        if len(route) != 1:
            raise ValueError(f'nonunique frozen route: {asset}')
        route = route[0]
        for observed, frozen, collateral in ((rh, route['other'], 'USDG'), (hl, route['hl'], 'USDC')):
            if str(observed['market']) != str(frozen['market']) or frozen['collateral'] != collateral:
                raise ValueError(f'route identity mismatch: {asset}')
            if Decimal(observed['size_step']) != Decimal(str(frozen['step'])):
                raise ValueError(f'quantity lattice changed: {asset}')
            observed['qty_step'] = observed['size_step']
            observed['collateral'] = collateral
        if Decimal(rh['maker_fee_bps']) != 0 or Decimal(rh['taker_fee_bps']) != 0:
            raise ValueError('RH public fee baseline changed; freeze a new policy')
        if Decimal(rh['contract_multiplier']) != 1:
            raise ValueError('RH contract multiplier changed')
        expected_hl_fee = Decimal('4.5') if asset in ('BTC', 'ETH') else Decimal('0.9')
        if Decimal(str(route['hl']['fee_bps'])) != expected_hl_fee:
            raise ValueError('HL discovery fee differs from frozen public formula')
        if asset in ('NVDA', 'XAG') and (hl.get('growth_mode') != 'enabled' or Decimal(str(hl.get('deployer_fee_scale'))) != 1):
            raise ValueError('HIP-3 growth/fee-scale conditions changed')
        hl.update(price_tick_semantics='hl_perp', min_qty=hl['size_step'],
                  maker_fee_bps='1.5' if asset in ('BTC', 'ETH') else '0.3',
                  taker_fee_bps=str(expected_hl_fee))
        # $500k is the lowest published HL market-order ceiling. It is a
        # conservative study cap, not an inferred per-account limit.
        hl['max_quote'] = '500000'
        rh.update(maker_fee_bps='0' if tier == 'standard' else '1.2',
                  taker_fee_bps='0' if tier == 'standard' else '3.5')
        by_asset[asset] = {'rh': rh, 'hl': hl}
    return by_asset


ASSUMPTIONS = {
    'sizes_usd': list(SIZES), 'primary_size_usd': 1000,
    'initial_wallet_per_venue': '2 * branch budget; separate USDG and USDC wallets',
    'fee_tier': 'public base rates, no user volume/staking/referral/builder adjustments',
    'hl_native_taker_bps': 4.5, 'hl_selected_xyz_taker_bps': 0.9,
    'hl_fee_source': 'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees',
    'hl_minimum_source': 'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/error-responses',
    'hl_price_rule_source': 'https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size',
    'hl_contract_source': 'https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications',
    'rh_tier_source': 'https://apidocs.rh.lighter.xyz/docs/account-types',
    'combined_usd_net': 'conditional on USDG=USDC=USD parity; conversion and transfer not modeled',
    'timing': 'public-book timing proxies; source clocks are not calibrated private execution clocks',
    'reserve_bps': 5, 'capital_rate_annual': 0.05,
    'funding': 'hour-crossing exposure unresolved without sourced settlement cash',
    'private_fills': 'not observed; every maker fill is a counterfactual public-flow scenario',
    'dust': 'below-minimum hedge or exit remains unresolved; reduce-only exceptions not assumed',
    'promotion': '20-minute holdout is descriptive feasibility only; no production promotion',
}
