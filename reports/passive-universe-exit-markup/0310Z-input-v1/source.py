#!/usr/bin/env python3
"""Offline exact RH grid exit distance needed for the frozen static margin hurdle."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'reports/passive-universe-screen/20260930T0310Z'
METHOD = ROOT / 'research/passive-universe-exit-markup-method.md'
SIZES = [100, 250, 500, 1000]
TARGET = Fraction(1, 10)
STRESS = Fraction(5, 10000)
CAP = 2_000_000


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def f(value):
    d = Decimal(str(value))
    if not d.is_finite():
        raise ValueError('nonfinite_input')
    return Fraction(d)


def decimal(value):
    # Reporting only: all price inequality/ceiling decisions remain rational.
    with localcontext() as ctx:
        ctx.prec = max(50, len(str(abs(value.numerator))) + len(str(value.denominator)) + 5)
        return format(Decimal(value.numerator) / Decimal(value.denominator), 'f')


def ceiling(value):
    return -(-value.numerator // value.denominator)


def derive(quote, score, market):
    row = {'asset':quote['asset'], 'round':quote['round'], 'budget':score['budget'],
           'original_valid':score['valid'], 'pricing_supported':False}
    if not score['valid']:
        return row | {'original_exclusion_reason':score['reason']}
    try:
        q,b,a,S,B = map(f, (score['quantity'],score['rh_bid'],score['rh_ask'],
                            score['hl_sell_notional'],score['hl_buy_notional']))
        tick,r,h = f(market['rh_price_tick']),f(market['rh_maker_fee_bps'])/10000,f(market['hl_taker_fee_bps'])/10000
        if min(q,b,a,tick) <= 0 or a <= b or r >= 1 or h < 0:
            raise ValueError('invalid_price_grid_or_fee_slope')
        if (a/tick).denominator != 1 or (b/tick).denominator != 1:
            raise ValueError('original_rh_prices_off_frozen_grid')
        opening,stress = q*b, max(q*b,S)*STRESS
        original_fees = (q*b+q*a)*r+(S+B)*h
        if original_fees != f(score['modeled_fill_fees']) or stress != f(score['stress_allowance']):
            raise ValueError('original_fee_or_stress_not_exactly_supported')
        def margin(x):
            return q*x*(1-r)-q*b*(1+r)+S-B-h*(S+B)-TARGET-stress
        original = margin(a)
        if original != f(score['after_target_stress']):
            raise ValueError('original_stressed_margin_not_exactly_supported')
        raw = (opening*(1+r)+B-S+h*(S+B)+TARGET+stress)/(q*(1-r))
        rounded = max(a,ceiling(raw/tick)*tick)
        if margin(rounded)<0:
            raise ValueError('grid_ceiling_failed_margin')
        if rounded>a and margin(rounded-tick)>=0:
            raise ValueError('required_exit_not_minimal_grid_price')
        if q*rounded>f(market['rh_max_quote']) or q*rounded<f(market['rh_min_notional']):
            raise ValueError('required_exit_notional_violates_frozen_bound')
        delta=rounded-a
        ticks=delta/tick
        if ticks.denominator!=1:
            raise ValueError('noninteger_markup_ticks')
        return row | {'pricing_supported':True,'quantity':decimal(q),'rh_bid':decimal(b),
                      'original_rh_ask':decimal(a),'rh_price_tick':decimal(tick),
                      'raw_required_price_rational':str(raw.numerator)+'/'+str(raw.denominator),
                      'raw_required_price_decimal_display':decimal(raw),
                      'required_exit_price':decimal(rounded),'markup_price':decimal(delta),
                      'markup_ticks':int(ticks),'markup_bps_above_ask':decimal(delta/a*10000),
                      'original_modeled_fill_fees':decimal(original_fees),
                      'repriced_rh_exit_fee':decimal(q*rounded*r),
                      'repriced_total_modeled_fill_fees':decimal((q*b+q*rounded)*r+(S+B)*h),
                      'original_stress':decimal(stress),'original_stressed_margin':decimal(original),
                      'rounded_exit_margin_after_target_stress':decimal(margin(rounded)),
                      'previous_tick_margin_after_target_stress':decimal(margin(rounded-tick))}
    except (KeyError,ValueError,ArithmeticError,TypeError) as exc:
        return row | {'pricing_limitation':str(exc)}


def stats(rows):
    if not rows:
        return {'median_markup_bps':None,'maximum_markup_bps':None,
                'median_markup_ticks':None,'maximum_markup_ticks':None}
    bps=[Decimal(r['markup_bps_above_ask']) for r in rows]
    ticks=[r['markup_ticks'] for r in rows]
    return {'median_markup_bps':str(statistics.median(bps)),'maximum_markup_bps':str(max(bps)),
            'median_markup_ticks':str(statistics.median(ticks)),'maximum_markup_ticks':max(ticks)}


def summarize(rows,universe):
    by=defaultdict(list)
    for r in rows: by[(r['asset'],r['budget'])].append(r)
    coverage={p['asset']:sum(r['original_valid'] for r in by[(p['asset'],1000)]) for p in universe['selected']}
    assets=[]
    for p in universe['selected']:
        for size in SIZES:
            original=by[(p['asset'],size)];supported=[r for r in original if r['pricing_supported']]
            assets.append({'asset':p['asset'],'budget':size,'original_valid_rounds':sum(r['original_valid'] for r in original),
                           'supported_rounds':len(supported),'eligible_original_1000_coverage':coverage[p['asset']]>=3,
                           'valid_1000_rounds':coverage[p['asset']],**stats(supported)})
    sizes=[]
    for size in SIZES:
        allrows=[r for r in rows if r['budget']==size];supported=[r for r in allrows if r['pricing_supported']]
        sizes.append({'budget':size,'total_observations':len(allrows),
                      'original_valid_observations':sum(r['original_valid'] for r in allrows),
                      'original_exclusions':sum(not r['original_valid'] for r in allrows),
                      'pricing_supported_observations':len(supported),
                      'unsupported_original_valid':sum(r['original_valid'] and not r['pricing_supported'] for r in allrows),
                      **stats(supported)})
    return {'interpretation':'necessary_static_quote_distance_not_fill_or_future_profit_prediction',
            'total_observations':len(rows),'original_valid_observations':sum(r['original_valid'] for r in rows),
            'original_exclusion_reasons':dict(Counter(r['original_exclusion_reason'] for r in rows if not r['original_valid'])),
            'pricing_limitations':dict(Counter(r['pricing_limitation'] for r in rows if r['original_valid'] and not r['pricing_supported'])),
            'by_size':sizes,'asset_size_distances':assets,'eligible_assets_original_1000':sum(n>=3 for n in coverage.values()),
            'candidate_nominations':[], 'nomination_reason':'quote_distance_alone_cannot_establish_execution_odds_or_expected_return'}


def run(source,out):
    paths=[source/n for n in ('quotes.jsonl','universe.json','summary.json','manifest.json','freeze.json')]
    paths += [METHOD,Path(__file__),ROOT/'tests/test_passive_universe_exit_markup.py']
    hashes={str(p.resolve()):sha(p) for p in paths}
    freeze=json.loads((source/'freeze.json').read_bytes())
    for name,expected in freeze['hashes'].items():
        if sha(source/name)!=expected:raise ValueError('frozen_input_changed_'+name)
    if (source/'quotes.jsonl').stat().st_size>16_000_000:raise ValueError('input_cap')
    universe=json.loads((source/'universe.json').read_bytes());markets={p['asset']:p for p in universe['selected']}
    quotes=[json.loads(l) for l in (source/'quotes.jsonl').read_bytes().splitlines()]
    manifest=json.loads((source/'manifest.json').read_bytes());original=json.loads((source/'summary.json').read_bytes())
    if manifest['status']!='completed' or manifest['rounds_completed']!=5:raise ValueError('requires_complete_screen')
    rows=[derive(q,s,markets[q['asset']]) for q in quotes for s in q['scores']]
    expected={(a,n,b) for a in markets for n in range(5) for b in SIZES}
    if len(rows)!=len(expected) or {(r['asset'],r['round'],r['budget']) for r in rows}!=expected:raise ValueError('original_denominator_mismatch')
    summary=summarize(rows,universe)
    if (summary['total_observations']!=original['total_size_observations']
            or summary['original_valid_observations']!=original['valid_size_observations']
            or summary['original_exclusion_reasons']!=original['missing_size_observations']):raise ValueError('original_validity_changed')
    coverage={r['asset']:r['valid_1000_rounds'] for r in original['coverage']}
    if any(r['valid_1000_rounds']!=coverage[r['asset']] for r in summary['asset_size_distances']):raise ValueError('original_coverage_changed')
    outputs={'observations.jsonl':b''.join((json.dumps(r,separators=(',',':'))+'\n').encode() for r in rows),
             'summary.json':(json.dumps(summary,indent=2)+'\n').encode(),'source.py':Path(__file__).read_bytes(),
             'method.md':METHOD.read_bytes(),'tests.py':(ROOT/'tests/test_passive_universe_exit_markup.py').read_bytes()}
    if sum(map(len,outputs.values()))>CAP-100_000:raise ValueError('derived_cap')
    out.mkdir(parents=True,exist_ok=False)
    for name,raw in outputs.items():(out/name).write_bytes(raw)
    if any(sha(Path(p))!=h for p,h in hashes.items()):raise ValueError('read_input_changed')
    (out/'manifest.json').write_text(json.dumps({'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'input_hashes':hashes,'input_hashes_unchanged':True,'original_frozen_inputs_verified':True,
        'output_hashes':{n:sha(out/n) for n in outputs},'network_calls':0,'derived_file_cap_bytes':CAP},indent=2)+'\n')
    print(json.dumps({'out':str(out),'sizes':summary['by_size'],'limitations':summary['pricing_limitations']}))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,default=INPUT)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args();run(args.input,args.out)


if __name__=='__main__':main()
