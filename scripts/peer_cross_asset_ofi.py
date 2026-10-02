#!/usr/bin/env python3
"""Frozen, bounded cross-asset observed-frame OFI evaluator of shared tables.

No capture decoder, collector, study, numpy import or table read runs at import.
All economics are conditional displayed-quote observations, never realized fills.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal as D
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
SHARED_PATH = 'scripts/single_venue_queue_ofi.py'
SHARED_PROTOCOL_PATH = 'reports/experiment-storage/single-venue-queue-ofi-v1.json'
PRODUCER_PATH = 'scripts/single_venue_queue_ofi_publication_fix.py'
PRODUCER_PROTOCOL_PATH = 'reports/experiment-storage/single-venue-queue-ofi-publication-fix-v1.json'
INPUT_VALIDATION_PATH = 'reports/experiment-storage/single-venue-inventory-context-ordinary-feed-fix-v1.json'
INPUT_INVENTORY_PATH = 'research/peer-shared-ofi-v1/input-inventory.json'
INPUT_INVENTORY_SHA = '4d64aa71acd4b5299c5c9ed60c6a48b37f37d1d5553c47f80357422965177b54'
SHARED_SHA = 'b549671eede741992df7d47dddb9247278b308f2775facb515c66de15014ff96'
RUNTIME = {'python': '3.13.9', 'numpy': '2.5.3'}
_spec = importlib.util.spec_from_file_location('_peer_frozen_queue_ofi', ROOT / SHARED_PATH)
shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shared)

TARGETS = ('ETH', 'SOL', 'HYPE', 'XRP', 'SUI', 'NEAR', 'ZEC', 'VVV', 'LIT')
ASSETS = ('BTC',) + TARGETS
VENUES = ('lighter', 'rh_lighter')
COLLATERAL = {'lighter': 'USDC', 'rh_lighter': 'USDG'}
FIT = ('chunk-000001', 'chunk-000002', 'chunk-000003')
APPLICATION = ('chunk-000007', 'chunk-000008', 'chunk-000009')
CHUNKS = FIT + APPLICATION
CELLS = tuple(asset + ':' + venue for asset in TARGETS for venue in VENUES)
WIDTHS = {'M0': 6, 'M1': 11, 'M2': 12}
FEATURES = tuple('target:' + name for name in shared.FEATURES) + tuple(
    'BTC:' + name for name in shared.FEATURES)
PARAMS = dict(training_chunks=list(FIT), application_chunks=list(APPLICATION),
    assets=list(ASSETS), venues=list(VENUES), targets=list(TARGETS), leader='BTC',
    calendar_start_second=30, calendar_step_seconds=20, calendar_stop_second=570,
    rows_per_table=560, slots_per_chunk=28, training_rows_min=65,
    training_rows_per_chunk_min=20, application_common_slots_min=21,
    economic_admitted_slots_min=3, notionals=['100', '1000', '10000'],
    funding_excluded_at_decision=True, shared_parameters=dict(shared.PARAMS))
NUMERICS = dict(dtype='float64', population_sd=True, ols_rcond=1e-10,
    maximum_design_condition_number=100000000, constant_columns='unavailable',
    feature_identity_tolerance=1e-12)
CAPS = dict(protocol_bytes=65536, table_gzip_bytes=524288,
    table_total_gzip_bytes=3145728, table_decoded_bytes=16777216,
    preflight_bytes=131072, model_bytes=262144, result_decoded_bytes=8388608,
    result_gzip_bytes=1048576, readout_bytes=32768, runtime_seconds=300)
REQUIRED_SOURCES = {'scripts/peer_cross_asset_ofi.py', 'tests/test_peer_cross_asset_ofi.py',
                    SHARED_PATH, SHARED_PROTOCOL_PATH, PRODUCER_PATH, PRODUCER_PROTOCOL_PATH,
                    INPUT_VALIDATION_PATH}


def encode(value):
    return shared.encode(value)


def digest(path):
    return shared.digest(path)


def _finite(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('nonfinite_or_boolean_number')
    result = float(shared.number(value))
    if not math.isfinite(result):
        raise ValueError('nonfinite_or_boolean_number')
    return result


def _integer(value):
    if type(value) is not int:
        raise ValueError('integer_clock_or_slot_required')
    return value


def validate_tables(chunks):
    """Inspect identities/calendar only; do not access labels, costs or profiles."""
    if tuple(chunk['chunk'] for chunk in chunks) != CHUNKS:
        raise ValueError('six_exact_ordered_chunk_identities_required')
    index = {}
    for chunk in chunks:
        name = chunk['chunk']; rows = chunk['anchors']
        if chunk.get('scheduled_anchors') != 560 or len(rows) != 560:
            raise ValueError('560_original_calendar_rows_required')
        keyed = {}; origin = None
        for row in rows:
            asset, venue, slot = row['asset'], row['venue'], _integer(row['slot'])
            when = _integer(row['decision_ns'])
            if (row['chunk'] != name or asset not in ASSETS or venue not in VENUES
                    or not 0 <= slot < 28 or when < 0):
                raise ValueError('calendar_row_identity_differs')
            key = (asset, venue, slot)
            if key in keyed:
                raise ValueError('duplicate_calendar_row')
            anchor_origin = when - slot * 20 * shared.NS
            if origin is None: origin = anchor_origin
            if anchor_origin != origin:
                raise ValueError('common_receipt_calendar_differs')
            keyed[key] = row
        if len(keyed) != 560:
            raise ValueError('full_asset_venue_calendar_required')
        index[name] = keyed
    return index


def _market_feature(row):
    """Use only producer-certified causal features and decision-time fields."""
    if row['feature_failure'] is not None:
        return None, str(row['feature_failure'])
    feature = row['features']
    try:
        when = _integer(row['decision_ns']); left = when - shared.PARAMS['lookback_ns']
        if not isinstance(feature, dict) or len(feature['values']) != 6:
            raise ValueError('feature_vector_width')
        values = [_finite(x) for x in feature['values']]
        depth = shared.number(feature['depth_start']); flow = shared.number(feature['ofi'])
        unchanged = shared.number(feature['unchanged_price_ofi'])
        changing = shared.number(feature['price_changing_ofi'])
        if depth <= 0 or unchanged + changing != flow:
            raise ValueError('ofi_components_or_depth_differ')
        for flag in ('zero_flow', 'zero_ofi', 'all_prices_unchanged'):
            if type(feature[flag]) is not bool:
                raise ValueError('feature_flag_not_boolean')
        tolerance = NUMERICS['feature_identity_tolerance']
        if (feature['zero_ofi'] != (flow == 0)
                or not math.isclose(values[5], float(flow / depth), rel_tol=tolerance, abs_tol=tolerance)
                or (feature['all_prices_unchanged'] and (changing != 0 or not math.isclose(
                    values[5], values[3] - values[2], rel_tol=tolerance, abs_tol=tolerance)))):
            raise ValueError('ofi_identity_differs')
        if not isinstance(feature['generation'], str) or not feature['generation']:
            raise ValueError('own_market_generation_absent')
        if 'generation' in row and row['generation'] != feature['generation']:
            raise ValueError('own_market_generation_differs')
        for label, boundary in (('start', left), ('end', when)):
            received = _integer(feature[label + '_received_ns'])
            source = _integer(feature[label + '_source_ns'])
            if (source > received or received < 0 or source < 0
                    or not 0 <= boundary - received <= shared.PARAMS['book_age_ns']
                    or not 0 <= boundary - source <= shared.PARAMS['book_age_ns']):
                raise ValueError('noncausal_or_stale_boundary_clock')
        return values, None
    except (KeyError, TypeError, ValueError, ArithmeticError, OverflowError) as exc:
        return None, 'invalid_causal_feature:' + str(exc)[:100]


def feature_vector(target_row, btc_row):
    if (target_row['chunk'] != btc_row['chunk'] or target_row['venue'] != btc_row['venue']
            or target_row['slot'] != btc_row['slot'] or target_row['decision_ns'] != btc_row['decision_ns']
            or target_row['asset'] not in TARGETS or btc_row['asset'] != 'BTC'):
        return None, 'leader_target_calendar_identity_differs'
    if shared.funding_crosses(target_row['decision_ns'], shared.PARAMS):
        return None, 'decision_funding_excluded'
    own, why = _market_feature(target_row)
    if why: return None, 'target:' + why
    leader, why = _market_feature(btc_row)
    if why: return None, 'BTC:' + why
    # Generations are market-local identities, never cross-market equal counters.
    return own + leader[:5] + leader[5:], None


def _features(index):
    joined = {}; failures = {}; transcript = []
    for name in CHUNKS:
        joined[name] = {}; failures[name] = {}
        for cell in CELLS:
            asset, venue = cell.split(':'); joined[name][cell] = {}; failures[name][cell] = {}
            for slot in range(28):
                own = index[name][asset, venue, slot]; btc = index[name]['BTC', venue, slot]
                xs, why = feature_vector(own, btc)
                if why: failures[name][cell][slot] = why
                else: joined[name][cell][slot] = xs
                # Fingerprint causal provenance too; no outcome-field access.
                transcript.append([name, cell, slot, own['decision_ns'], xs, why,
                                   own['features'], btc['features'], own['feature_failure'], btc['feature_failure']])
    return joined, failures, hashlib.sha256(encode(transcript)).hexdigest()


def _design(X, width, y=None):
    import numpy as np
    X = np.asarray(X, dtype=np.float64)
    result = dict(status='available', columns=list(range(width)), design_columns=width + 1,
                  rank=None, condition=None, constant_columns=[])
    if X.ndim != 2 or X.shape[1] != 12 or not np.isfinite(X).all():
        raise ValueError('finite_12_column_matrix_required')
    if not len(X):
        result['status'] = 'no_rows'; return result, None, None
    means = X.mean(axis=0); scales = X.std(axis=0, ddof=0)
    if not np.isfinite(means).all() or not np.isfinite(scales).all():
        raise ValueError('nonfinite_standardization')
    constants = np.flatnonzero(np.all(X[:, :width] == X[0, :width], axis=0)).tolist()
    result['constant_columns'] = constants
    if constants or any(scales[i] <= 0 for i in range(width)):
        result['status'] = 'constant_columns'; return result, means.tolist(), scales.tolist()
    design = np.column_stack([np.ones(len(X)), (X[:, :width] - means[:width]) / scales[:width]])
    dependent = np.zeros(len(X)) if y is None else np.asarray(y, dtype=np.float64)
    if dependent.shape != (len(X),) or not np.isfinite(dependent).all() or not np.isfinite(design).all():
        raise ValueError('nonfinite_fit_design_or_label')
    coefficients, _, rank, singular = np.linalg.lstsq(design, dependent, rcond=NUMERICS['ols_rcond'])
    condition = float(singular[0] / singular[-1]) if singular[-1] > 0 else math.inf
    result.update(rank=int(rank), condition=condition if math.isfinite(condition) else None)
    if rank != width + 1: result['status'] = 'rank_deficient'
    elif not math.isfinite(condition) or condition > NUMERICS['maximum_design_condition_number']:
        result['status'] = 'condition_number_exceeded'
    elif y is not None:
        if not np.isfinite(coefficients).all(): raise ValueError('nonfinite_fit_coefficients')
        result['coefficients'] = coefficients.tolist()
    return result, means.tolist(), scales.tolist()


def _counts_pass(counts):
    return sum(counts.values()) >= 65 and all(counts.get(name, 0) >= 20 for name in FIT)


def feature_preflight(chunks):
    index = validate_tables(chunks); joined, failures, fingerprint = _features(index)
    cells = {}
    for cell in CELLS:
        counts = {name: len(joined[name][cell]) for name in FIT}
        xs = [row for name in FIT for row in joined[name][cell].values()]
        designs = {model: _design(xs, width)[0] for model, width in WIDTHS.items()} if xs else {
            model: dict(status='no_rows') for model in WIDTHS}
        status = ('passed' if _counts_pass(counts) and all(r['status'] == 'available' for r in designs.values())
                  else 'insufficient_feature_support')
        cells[cell] = dict(status=status, counts=counts, models=designs,
            failures={name: dict(Counter(failures[name][cell].values())) for name in FIT})
    mask = {}; mask_failures = {}
    for name in APPLICATION:
        mask[name] = [slot for slot in range(28) if all(slot in joined[name][cell] for cell in CELLS)]
        mask_failures[name] = {str(slot): {cell: failures[name][cell][slot] for cell in CELLS
                                         if slot in failures[name][cell]}
                               for slot in range(28) if slot not in mask[name]}
    counts = {name: len(slots) for name, slots in mask.items()}
    passed = all(row['status'] == 'passed' for row in cells.values()) and all(n >= 21 for n in counts.values())
    return dict(status='passed' if passed else 'insufficient_feature_support', cells=cells,
        application_mask=mask, application_counts=counts, mask_failures=mask_failures,
        feature_sha256=fingerprint, mask_sha256=hashlib.sha256(encode(mask)).hexdigest(),
        scheduled_training_rows_per_cell=84, scheduled_application_slots_per_chunk=28,
        fixed_cells=18, interpretation='Feature-only coverage/rank; no outcome fields used.')


def _stage_features(chunks, preflight):
    index = validate_tables(chunks); joined, _, fingerprint = _features(index)
    if fingerprint != preflight['feature_sha256'] or hashlib.sha256(encode(preflight['application_mask'])).hexdigest() != preflight['mask_sha256']:
        raise ValueError('causal_features_or_immutable_mask_changed')
    return index, joined


def fit_models(chunks, preflight):
    if preflight['status'] != 'passed': raise ValueError('feature_preflight_must_pass_first')
    import numpy as np
    index, joined = _stage_features(chunks, preflight); cells = {}
    for cell in CELLS:
        asset, venue = cell.split(':'); xs = []; ys = []; ids = []; counts = dict.fromkeys(FIT, 0); failures = Counter()
        for name in FIT:
            for slot, features in joined[name][cell].items():
                row = index[name][asset, venue, slot]
                if row['label_status'] != 'complete' or row['label'] is None:
                    failures[str(row['label_status'])] += 1; continue
                try: y = _finite(row['label'])
                except (ValueError, TypeError, ArithmeticError, OverflowError):
                    failures['nonfinite_training_label'] += 1; continue
                xs.append(features); ys.append(y); ids.append([name, slot]); counts[name] += 1
        record = dict(training_ids=ids, training_counts=counts, training_labels=len(ys),
                      label_failures=dict(failures), means=None, scales=None, variance=None, models={})
        for model, width in WIDTHS.items():
            if not _counts_pass(counts): record['models'][model] = dict(status='insufficient_training_labels'); continue
            result, means, scales = _design(xs, width, ys)
            record['means'] = means; record['scales'] = scales; record['models'][model] = result
        variance = float(np.var(np.asarray(ys, dtype=np.float64), ddof=0)) if ys else None
        record['variance'] = variance if variance is not None and math.isfinite(variance) else None
        record['status'] = ('available' if _counts_pass(counts) and record['variance'] is not None
                            and variance > 0 and all(r['status'] == 'available' for r in record['models'].values())
                            else 'insufficient_training_support')
        if variance is not None and (not math.isfinite(variance) or variance <= 0):
            record['label_variance_failure'] = 'zero_or_nonfinite_training_label_variance'
        cells[cell] = record
    return dict(status='available' if all(r['status'] == 'available' for r in cells.values())
                else 'insufficient_training_support', cells=cells, features=list(FEATURES),
        feature_sha256=preflight['feature_sha256'], mask_sha256=preflight['mask_sha256'],
        application_mask={name: list(slots) for name, slots in preflight['application_mask'].items()},
        numerical_contract=NUMERICS, numpy_version=np.__version__, python_version=platform.python_version())


def predict(cell, xs, model):
    return shared.predict(cell, xs, model)


def policies(cell, xs, row):
    """Exact shared admission policy; funding is a known decision abstention."""
    if shared.funding_crosses(row['decision_ns'], shared.PARAMS):
        return {model + ':' + size: dict(predicted_y=None, direction=None, admitted=False,
                    status='decision_funding_excluded', score_cash=None)
                for model in ('M1', 'M2') for size in PARAMS['notionals']}
    adapted = dict(cell, models={'baseline': cell['models']['M1'], 'augmented': cell['models']['M2']})
    costs = row['decision_costs']
    if set(costs) != set(PARAMS['notionals']): raise ValueError('decision_cost_size_contract_differs')
    raw = shared.policies(adapted, xs, costs)
    return {key.replace('baseline:', 'M1:').replace('augmented:', 'M2:'): value for key, value in raw.items()}


def policy_observation(row, policy, size):
    """An absent admitted outcome is unknown; a known abstention contributes 0."""
    if type(policy.get('admitted')) is not bool: raise ValueError('policy_admission_not_boolean')
    if not policy['admitted']:
        return dict(admitted=False, status=policy['status'], cash=D(0),
                    stressed={str(bp): D(0) for bp in shared.PARAMS['extra_cost_stress_bps']})
    if policy.get('direction') not in (1, -1): raise ValueError('admitted_direction_invalid')
    matching = [p for p in row['profiles'] if p['target'] == size and p['direction'] == policy['direction']]
    if len(matching) > 1: raise ValueError('duplicate_size_direction_profile')
    if not matching or matching[0]['status'] != 'complete':
        return dict(admitted=True, status='missing_profile' if not matching else matching[0]['status'], cash=None, stressed=None)
    observation = shared.policy_observation(dict(row, policies={'peer:' + size: policy}), 'peer', size)
    profile = observation['profile']
    gross, fee, capital, net, entry = (shared.number(profile[k]) for k in
        ('gross_cash', 'fee_cash', 'capital_cash', 'net_cash', 'entry_value'))
    if (fee < 0 or capital < 0 or entry <= 0 or net != gross - fee - capital
            or set(observation['stressed']) != {'1', '2', '5'}
            or any(value != net - entry * D(bp) / 10000 for bp, value in observation['stressed'].items())):
        raise ValueError('quoted_profile_accounting_differs')
    return observation


def _mean(values):
    return sum(values) / len(values) if values else None


def _loo(values):
    return {name: None if any(values[other] is None for other in APPLICATION if other != name)
            else _mean([values[other] for other in APPLICATION if other != name]) for name in APPLICATION}


def evaluate(chunks, preflight, models):
    if models['status'] != 'available' or preflight['status'] != 'passed':
        raise ValueError('all_18_frozen_models_required')
    if models['feature_sha256'] != preflight['feature_sha256'] or models['mask_sha256'] != preflight['mask_sha256'] or models['application_mask'] != preflight['application_mask']:
        raise ValueError('frozen_model_mask_differs')
    index, joined = _stage_features(chunks, preflight)
    audit = []; forecast_blocks = []; economic_rows = []
    for name in APPLICATION:
        slots = preflight['application_mask'][name]; forecast_cells = {}; observations = {}
        for cell in CELLS:
            asset, venue = cell.split(':'); fitted = models['cells'][cell]
            errors = {model: [] for model in WIDTHS}; missing_labels = Counter()
            observations[cell] = {model + ':' + size: [] for model in ('M1', 'M2') for size in PARAMS['notionals']}
            for slot in slots:
                row = index[name][asset, venue, slot]; xs = joined[name][cell][slot]
                forecasts = {model: predict(fitted, xs, model) for model in WIDTHS}
                if row['label_status'] == 'complete' and row['label'] is not None:
                    try: label = _finite(row['label'])
                    except (ValueError, TypeError, ArithmeticError, OverflowError): label = None
                    if label is None: missing_labels['nonfinite_application_label'] += 1
                else:
                    label = None; missing_labels[str(row['label_status'])] += 1
                if label is not None:
                    squared = {model: (label - forecast) ** 2 / fitted['variance'] for model, forecast in forecasts.items()}
                    if not all(math.isfinite(value) for value in squared.values()):
                        raise ValueError('nonfinite_application_squared_error')
                    for model, value in squared.items(): errors[model].append(value)
                selected = policies(fitted, xs, row); policy_audit = {}
                for model in ('M1', 'M2'):
                    for size in PARAMS['notionals']:
                        key = model + ':' + size; policy = selected[key]
                        observation = policy_observation(row, policy, size)
                        observations[cell][key].append(dict(slot=slot, policy=policy, observation=observation))
                        policy_audit[key] = dict(policy, observation_status=observation['status'],
                            conditional_net_cash=observation['cash'], stressed_cash=observation['stressed'])
                audit.append(dict(chunk=name, cell=cell, slot=slot, decision_ns=row['decision_ns'],
                    input_row_reference=[name, asset, venue, slot], forecasts=forecasts,
                    label=label, label_status=row['label_status'], policies=policy_audit))
            conditional = {model: _mean(values) for model, values in errors.items()}
            complete = not missing_labels and len(errors['M2']) == len(slots)
            forecast_cells[cell] = dict(mask_rows=len(slots), complete_labels=len(errors['M2']),
                missing_labels=dict(missing_labels), conditional_available_normalized_mse=conditional,
                normalized_mse=conditional if complete else dict.fromkeys(WIDTHS),
                primary_available=complete)
        all_labels = all(c['primary_available'] for c in forecast_cells.values())
        mse = {model: _mean([c['normalized_mse'][model] for c in forecast_cells.values()]) if all_labels else None for model in WIDTHS}
        improvement = mse['M1'] - mse['M2'] if all_labels else None
        forecast_blocks.append(dict(chunk=name, mask_rows=len(slots), cells=forecast_cells,
            primary_available=all_labels, normalized_mse=mse, M2_vs_M1_improvement=improvement,
            M1_vs_M0_descriptive_improvement=None if not all_labels else mse['M0'] - mse['M1']))
        for venue in VENUES:
            for size in PARAMS['notionals']:
                per_cell = {}; admitted_slots = set()
                for asset in TARGETS:
                    cell = asset + ':' + venue; record = {}
                    for model in ('M1', 'M2'):
                        obs = observations[cell][model + ':' + size]
                        known = [r['observation']['cash'] for r in obs if r['observation']['cash'] is not None]
                        unknown = len(obs) - len(known)
                        admitted = sum(r['observation']['admitted'] for r in obs)
                        complete = sum(r['observation']['admitted'] and r['observation']['cash'] is not None for r in obs)
                        if model == 'M2': admitted_slots.update(r['slot'] for r in obs if r['observation']['admitted'])
                        cash = None if unknown else _mean(known)
                        calendar_cash = None if unknown else sum(known, D(0)) / 28
                        stress = {str(bp): None if unknown else _mean([r['observation']['stressed'][str(bp)] for r in obs])
                                  for bp in shared.PARAMS['extra_cost_stress_bps']}
                        record[model] = dict(mask_rows=len(slots), admitted=admitted, admitted_complete=complete,
                            admitted_unknown=unknown, original_calendar_rows=28,
                            known_no_action_on_mask=len(obs) - admitted, known_no_action_off_mask=28 - len(slots),
                            known_no_action=28 - admitted,
                            statuses=dict(Counter(r['observation']['status'] for r in obs)
                                          + Counter({'off_mask_decision_abstention': 28 - len(slots)})),
                            all_mask_mean_conditional_net_cash=cash, all_mask_mean_stressed_cash=stress,
                            all_calendar_mean_conditional_net_cash=calendar_cash,
                            all_calendar_mean_stressed_cash={bp: None if value is None else value * len(slots) / 28
                                                            for bp, value in stress.items()})
                    per_cell[cell] = record
                available = all(r[m]['admitted_unknown'] == 0 for r in per_cell.values() for m in ('M1', 'M2'))
                mean = {model: _mean([r[model]['all_mask_mean_conditional_net_cash'] for r in per_cell.values()]) if available else None for model in ('M1', 'M2')}
                delta = mean['M2'] - mean['M1'] if available else None
                calendar_mean = {model: _mean([r[model]['all_calendar_mean_conditional_net_cash'] for r in per_cell.values()]) if available else None for model in ('M1', 'M2')}
                calendar_delta = calendar_mean['M2'] - calendar_mean['M1'] if available else None
                economic_rows.append(dict(chunk=name, venue=venue, collateral=COLLATERAL[venue], native_notional=size,
                    fixed_targets=9, mask_rows=len(slots), cells=per_cell, primary_available=available,
                    distinct_M2_admitted_slots=len(admitted_slots), all_mask_equal_target_mean_conditional_net_cash=mean,
                    M2_minus_M1_mean_conditional_net_cash=delta,
                    original_calendar_rows=28, all_calendar_equal_target_mean_conditional_net_cash=calendar_mean,
                    all_calendar_M2_minus_M1_mean_conditional_net_cash=calendar_delta,
                    support_pass=available and len(admitted_slots) >= 3,
                    positive_cash_pass=available and len(admitted_slots) >= 3 and calendar_mean['M2'] > 0 and calendar_delta > 0))
    loss = {r['chunk']: r['M2_vs_M1_improvement'] for r in forecast_blocks}
    forecast_pass = all(value is not None and value > 0 for value in loss.values())
    economic_pass = all(row['positive_cash_pass'] for row in economic_rows)
    missing = any(not row['primary_available'] for row in forecast_blocks + economic_rows)
    classification = ('supports_later_untouched_replication_proposal' if forecast_pass and economic_pass
                      else 'inconclusive_missing_application_evidence' if missing else 'park_this_linear_version')
    economic_aggregates = []
    for venue in VENUES:
        for size in PARAMS['notionals']:
            rows = [r for r in economic_rows if r['venue'] == venue and r['native_notional'] == size]
            cash = {r['chunk']: r['all_calendar_equal_target_mean_conditional_net_cash']['M2'] for r in rows}
            delta = {r['chunk']: r['all_calendar_M2_minus_M1_mean_conditional_net_cash'] for r in rows}
            economic_aggregates.append(dict(venue=venue, collateral=COLLATERAL[venue], native_notional=size,
                equal_chunk_M2_conditional_net_cash=None if any(v is None for v in cash.values()) else _mean(list(cash.values())),
                equal_chunk_M2_minus_M1=None if any(v is None for v in delta.values()) else _mean(list(delta.values())),
                denominator='28 original calendar anchors including known off-mask abstentions; nine equal targets',
                descriptive_leave_one_chunk_out_M2_cash=_loo(cash), descriptive_leave_one_chunk_out_delta=_loo(delta)))
    return dict(classification=classification, forecast=dict(chunks=forecast_blocks, passes=forecast_pass,
        equal_chunk_M2_vs_M1_improvement=None if any(v is None for v in loss.values()) else _mean(list(loss.values())),
        descriptive_leave_one_chunk_out_improvement=_loo(loss)),
        economics=dict(rows=economic_rows, aggregates=economic_aggregates, passes=economic_pass),
        audit_rows=audit, application_mask=preflight['application_mask'], mask_sha256=preflight['mask_sha256'],
        validation_claim=False, strategy_promotion=False, realized_fill_claim=False)


def analyze(chunks):
    preflight = feature_preflight(chunks)
    result = dict(preflight=preflight, models=None, evaluation=None, classification=preflight['status'])
    if preflight['status'] != 'passed': return result
    models = fit_models(chunks, preflight); result['models'] = models
    if models['status'] != 'available': result['classification'] = models['status']; return result
    result['evaluation'] = evaluate(chunks, preflight, models)
    result['classification'] = result['evaluation']['classification']
    return result


def safe_relative(path):
    relative = Path(path)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('workspace_relative_path_required')
    full = ROOT / relative
    if full.is_symlink() or not full.is_file() or not full.resolve().is_relative_to(ROOT):
        raise ValueError('regular_workspace_file_required')
    return full


def read_json(path, cap):
    if Path(path).stat().st_size > cap: raise ValueError('json_byte_cap')
    return json.loads(Path(path).read_bytes(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite_json_constant')))


def verify_inventory_metadata(inventory, tables, *, workspace=None):
    """Pure identity/role/time checks; producer metadata contains no selection."""
    records = inventory.get('tables', [])
    if (inventory.get('schema') != 'peer-shared-ofi-input-inventory-v1'
            or inventory.get('table_gzip_cap_bytes') != CAPS['table_gzip_bytes']
            or inventory.get('table_decoded_cap_bytes') != CAPS['table_decoded_bytes']
            or inventory.get('rows_per_table') != 560 or inventory.get('rows_per_cell') != 28
            or tuple(r['chunk'] for r in records) != CHUNKS or tables != records
            or len({r['path'] for r in records}) != 6):
        raise ValueError('fixed_input_inventory_contract_differs')
    if workspace is not None and str(Path(workspace).resolve()) != inventory.get('execution_workspace'):
        raise ValueError('production_execution_workspace_differs')
    previous_end = None; total = 0
    for record in records:
        start = _integer(record['started_ns']); end = _integer(record['ended_ns'])
        size = _integer(record['bytes'])
        if (record['role'] != ('fit' if record['chunk'] in FIT else 'application')
                or start < 0 or end <= start or (previous_end is not None and start <= previous_end)
                or not 0 < size <= CAPS['table_gzip_bytes']):
            raise ValueError('input_role_span_or_byte_bound_differs')
        previous_end = end; total += size
    if total != inventory.get('total_table_bytes') or total > CAPS['table_total_gzip_bytes']:
        raise ValueError('inventory_total_table_bytes_differs')
    for key, path in (('producer_protocol', PRODUCER_PROTOCOL_PATH), ('producer_source', PRODUCER_PATH),
                      ('scientific_parent_protocol', SHARED_PROTOCOL_PATH), ('scientific_source', SHARED_PATH)):
        if inventory[key]['path'] != path:
            raise ValueError('inventory_producer_identity_differs')
    return records


def validate_table_clock(table, record):
    if table['chunk'] != record['chunk']:
        raise ValueError('decoded_table_chunk_differs')
    for row in table['anchors']:
        expected = record['started_ns'] + (30 + 20 * _integer(row['slot'])) * shared.NS
        if _integer(row['decision_ns']) != expected or expected > record['ended_ns']:
            raise ValueError('table_anchor_clock_not_bound_to_input_span')


def _verify_record(record):
    path = safe_relative(record['path'])
    if type(record['bytes']) is not int or path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
        raise ValueError('pinned_record_bytes_or_sha256_differs:' + record['path'])
    return path


def verify_plan(path, expected_sha):
    path = Path(path)
    if not isinstance(expected_sha, str) or len(expected_sha) != 64 or digest(path) != expected_sha:
        raise ValueError('external_frozen_protocol_sha256_differs')
    plan = read_json(path, CAPS['protocol_bytes'])
    if (plan.get('schema') != 'peer-cross-asset-ofi-v1' or plan.get('status') != 'frozen-before-features'
            or plan.get('parameters') != PARAMS or plan.get('numerical_contract') != NUMERICS or plan.get('caps') != CAPS):
        raise ValueError('frozen_protocol_or_contract_differs')
    import numpy as np
    if (plan.get('runtime_requirements') != RUNTIME
            or dict(python=platform.python_version(), numpy=np.__version__) != RUNTIME):
        raise ValueError('pinned_runtime_differs')
    contract = plan['shared_contract']
    if (contract['source_path'] != SHARED_PATH or contract['protocol_path'] != SHARED_PROTOCOL_PATH
            or contract['source_sha256'] != SHARED_SHA or digest(safe_relative(SHARED_PATH)) != SHARED_SHA):
        raise ValueError('frozen_shared_scientific_source_differs')
    shared_plan_path = safe_relative(contract['protocol_path'])
    if digest(shared_plan_path) != contract['protocol_sha256']: raise ValueError('shared_protocol_sha256_differs')
    original = read_json(shared_plan_path, CAPS['protocol_bytes'])
    if (original.get('schema') != 'single-venue-queue-ofi-v1' or original.get('status') != 'frozen'
            or original.get('parameters') != shared.PARAMS or original.get('fit_chunks') != list(FIT)
            or original.get('evaluation_chunks') != list(APPLICATION)
            or original.get('input_validation_plan') != INPUT_VALIDATION_PATH
            or original.get('input_validation_plan_sha256') != shared.VALIDATION_SHA):
        raise ValueError('frozen_shared_protocol_design_differs')
    inventory_pin = plan['input_inventory']
    if (inventory_pin['path'] != INPUT_INVENTORY_PATH or inventory_pin['sha256'] != INPUT_INVENTORY_SHA
            or inventory_pin['bytes'] != 4197):
        raise ValueError('fixed_input_inventory_pin_differs')
    inventory = read_json(_verify_record(inventory_pin), CAPS['protocol_bytes'])
    tables = plan.get('tables', [])
    verify_inventory_metadata(inventory, tables, workspace=ROOT)
    for key in ('producer_protocol', 'producer_source', 'scientific_parent_protocol', 'scientific_source', 'provenance'):
        _verify_record(inventory[key])
    if (contract['protocol_sha256'] != inventory['scientific_parent_protocol']['sha256']
            or contract['source_sha256'] != inventory['scientific_source']['sha256']):
        raise ValueError('shared_contract_not_bound_to_producer_inventory')
    producer = read_json(safe_relative(PRODUCER_PROTOCOL_PATH), CAPS['protocol_bytes'])
    if (producer.get('schema') != 'single-venue-queue-ofi-publication-fix-v1' or producer.get('status') != 'frozen'
            or producer.get('parent_plan') != SHARED_PROTOCOL_PATH
            or producer.get('parent_plan_sha256') != contract['protocol_sha256']):
        raise ValueError('publication_wrapper_parent_identity_differs')
    validation_path = safe_relative(INPUT_VALIDATION_PATH)
    if digest(validation_path) != shared.VALIDATION_SHA:
        raise ValueError('transitive_input_validation_protocol_differs')
    validation = read_json(validation_path, CAPS['protocol_bytes'])
    transitive = validation['source_pins']
    if len(transitive) != 45 or len({pin['path'] for pin in transitive}) != 45:
        raise ValueError('full45_transitive_source_chain_required')
    pins = plan.get('source_pins', []); paths = [pin['path'] for pin in pins]
    if not pins or len(paths) != len(set(paths)) or not REQUIRED_SOURCES <= set(paths):
        raise ValueError('unique_required_source_pins_absent')
    pinned = {pin['path']: pin['sha256'] for pin in pins}
    required = transitive + original['source_pins'] + producer['source_pins'] + [
        dict(path=INPUT_VALIDATION_PATH, sha256=shared.VALIDATION_SHA),
        *[inventory[key] for key in ('producer_protocol', 'producer_source', 'scientific_parent_protocol', 'scientific_source')]]
    if any(pinned.get(pin['path']) != pin['sha256'] for pin in required):
        raise ValueError('scientific_or_producer_dependency_pin_omitted_or_changed')
    for pin in pins:
        if digest(safe_relative(pin['path'])) != pin['sha256']: raise ValueError('source_pin_differs:' + pin['path'])
    if tuple(t['chunk'] for t in tables) != CHUNKS or len({t['path'] for t in tables}) != 6:
        raise ValueError('six_unique_pinned_tables_required')
    total = 0
    for record in tables:
        file = safe_relative(record['path']); size = file.stat().st_size
        if (type(record['bytes']) is not int or not 0 < size == record['bytes'] <= CAPS['table_gzip_bytes']
                or digest(file) != record['sha256']):
            raise ValueError('shared_table_bytes_or_sha256_differs')
        total += size
    if total > CAPS['table_total_gzip_bytes']: raise ValueError('incoming_table_total_byte_cap')
    return plan


def load_tables(plan):
    chunks = []
    inventory_pin = plan['input_inventory']
    inventory = read_json(_verify_record(inventory_pin), CAPS['protocol_bytes'])
    verify_inventory_metadata(inventory, plan['tables'], workspace=ROOT)
    for record in plan['tables']:
        path = safe_relative(record['path'])
        if digest(path) != record['sha256']: raise ValueError('table_changed_before_decode')
        with gzip.open(path, 'rb') as stream: body = stream.read(CAPS['table_decoded_bytes'] + 1)
        if len(body) > CAPS['table_decoded_bytes']: raise ValueError('decoded_table_byte_cap')
        table = json.loads(body, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite_json_constant')))
        validate_table_clock(table, record)
        chunks.append(table)
    validate_tables(chunks)
    return chunks


def publish_exclusive(path, body, cap):
    path = Path(path)
    if len(body) > cap: raise ValueError('output_byte_cap')
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def render_readout(result):
    lines = ['Cross-asset observed-frame OFI: conditional exploratory diagnostic.',
        'Classification: ' + result['classification'],
        '18 fixed cells; three dependent application chunks. USDC/USDG and size alternatives stay separate.',
        'Conditional quoted cash is not realized fills or an executable simultaneous portfolio.',
        'Preflight: ' + result['preflight']['status'],
        'Feature-only application mask counts: ' + json.dumps(result['preflight']['application_counts'], sort_keys=True)]
    for cell, record in result['preflight']['cells'].items():
        lines.append(cell + ' feature support: ' + json.dumps(dict(counts=record['counts'],
            status=record['status'], ranks={m: r.get('rank') for m, r in record['models'].items()},
            models={m: r['status'] for m, r in record['models'].items()}), sort_keys=True))
    if result['models']:
        lines.append('Training-label fit: ' + result['models']['status'])
        for cell, record in result['models']['cells'].items():
            lines.append(cell + ' fit: ' + json.dumps(dict(counts=record['training_counts'], status=record['status'],
                models={m: r['status'] for m, r in record['models'].items()}, variance=record['variance']), sort_keys=True))
    if result['evaluation']:
        evaluation = result['evaluation']
        for row in evaluation['forecast']['chunks']:
            lines.append(row['chunk'] + ' forecast: ' + json.dumps(dict(primary_available=row['primary_available'],
                mask_rows=row['mask_rows'], normalized_mse=row['normalized_mse'], improvement=row['M2_vs_M1_improvement']), sort_keys=True))
        for row in evaluation['economics']['rows']:
            totals = {model: {key: sum(c[model][key] for c in row['cells'].values())
                for key in ('admitted', 'admitted_complete', 'admitted_unknown', 'known_no_action')} for model in ('M1', 'M2')}
            lines.append(row['chunk'] + ' ' + row['venue'] + '/' + row['collateral'] + ' size ' + row['native_notional'] + ': ' +
                encode(dict(available=row['primary_available'], distinct_M2_admitted_slots=row['distinct_M2_admitted_slots'],
                    original_calendar_rows=28, mask_rows=row['mask_rows'],
                    mean_cash=row['all_calendar_equal_target_mean_conditional_net_cash'],
                    delta=row['all_calendar_M2_minus_M1_mean_conditional_net_cash'], counts=totals)).decode())
    lines.append('Full failures, immutable masks, coefficients, per-cell forecasts and admitted profile statuses are in the JSON outputs.')
    return ('\n'.join(lines) + '\n').encode()


def run(plan_path, expected_sha, output_root):
    started = time.monotonic(); plan = verify_plan(plan_path, expected_sha)
    model_sha = None
    out = Path(output_root)
    if not out.resolve().is_relative_to(ROOT): raise ValueError('output_root_must_be_in_workspace')
    out.mkdir(parents=True, exist_ok=False)
    def recheck():
        if time.monotonic() - started > CAPS['runtime_seconds']: raise TimeoutError('runtime_cap')
        verify_plan(plan_path, expected_sha)
        if model_sha is not None and digest(out / 'model.json') != model_sha:
            raise ValueError('published_model_changed')
    def save(name, body, cap):
        recheck(); publish_exclusive(out / name, body, cap)
    recheck(); chunks = load_tables(plan)
    preflight = feature_preflight(chunks)
    save('preflight.json', encode(preflight), CAPS['preflight_bytes'])
    result = dict(schema='peer-cross-asset-ofi-result-v1', protocol_sha256=expected_sha,
        source_pins=plan['source_pins'], shared_contract=plan['shared_contract'], input_tables=plan['tables'],
        input_inventory=plan['input_inventory'],
        preflight=preflight, models=None, evaluation=None, classification=preflight['status'],
        validation_claim=False, strategy_promotion=False, realized_fill_claim=False)
    if preflight['status'] == 'passed':
        recheck(); models = fit_models(chunks, preflight)
        model_body = encode(models); save('model.json', model_body, CAPS['model_bytes'])
        model_sha = hashlib.sha256(model_body).hexdigest()
        result.update(models=models, model_sha256=model_sha, classification=models['status'])
        if models['status'] == 'available':
            recheck()
            if digest(out / 'model.json') != model_sha: raise ValueError('published_model_changed')
            result['evaluation'] = evaluate(chunks, preflight, models)
            result['classification'] = result['evaluation']['classification']
    body = encode(result)
    if len(body) > CAPS['result_decoded_bytes']: raise ValueError('decoded_result_byte_cap')
    packed = gzip.compress(body, mtime=0); readout = render_readout(result)
    if len(packed) > CAPS['result_gzip_bytes'] or len(readout) > CAPS['readout_bytes']: raise ValueError('derived_output_byte_cap')
    if result.get('model_sha256') and digest(out / 'model.json') != result['model_sha256']:
        raise ValueError('published_model_changed_before_result_publication')
    save('result.json.gz', packed, CAPS['result_gzip_bytes']); save('readout.txt', readout, CAPS['readout_bytes'])
    return dict(classification=result['classification'], protocol_sha256=expected_sha,
        result_gzip_bytes=len(packed), readout_bytes=len(readout))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--expected-plan-sha256', required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.plan, args.expected_plan_sha256, args.output_root), sort_keys=True))


if __name__ == '__main__':
    main()
