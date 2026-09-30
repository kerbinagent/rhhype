#!/usr/bin/env python3
"""Compare completed strict and separately frozen retirement-corrected artifacts.

Reads stopped artifact provenance and hashes raw bytes without decoding feeds.
No cross-history profit improvement or sum of counterfactual branches is scored.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import analyze_rh_passive_exit as original
from scripts import replay_passive_retirement_corrected as correction
from scripts.rh_maker_events import _archive_size

SCHEMA = 'rh-passive-retirement-comparison-v1'
MAX_INPUT_BYTES = 32_000_000
MAX_OUTPUT_BYTES = 32_000_000
MAX_REPORT_BYTES = 1_000_000
DEFAULT_STRICT = ROOT / 'data/derived/rh-passive-exit-v1-restart/analysis.json'
DEFAULT_CORRECTED = ROOT / 'data/derived/rh-passive-exit-v1-restart-corrected/analysis.json'
DEFAULT_OUT = ROOT / 'data/derived/rh-passive-exit-v1-restart-comparison'
LIMITATIONS = [
    'Each branch is an independent correlated counterfactual ledger; branches are never summed.',
    'Known closed episode contribution excludes unknown/unsettled episodes and is not total portfolio net.',
    'An execution-unknown episode stays unknown, including a previously claimed zero.',
    'Correction can halt a branch/group earlier and change later admissions and observation time.',
    'Side-by-side cash, fills, and net from unequal admission histories do not establish causal profit improvement.',
    'Common cohort IDs identify shared decisions; economic comparison also requires identical fully hedged entries.',
    'Public queue attribution is conditional; private fills, funding and executable conversion remain unobserved.',
    'A halted branch with retained passive quote guards needs historical adjudication because frozen passive late-flow checks can be bypassed after an earlier unknown.',
]


def _decimal(value, label):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'{label}: finite decimal required') from None
    if isinstance(value, bool) or not result.is_finite():
        raise ValueError(f'{label}: finite decimal required')
    return result


def _hash(value, label):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError(f'{label}: SHA-256 required')
    return value


def _key(row, policy=True):
    value = _decimal(row.get('budget_usd'), 'budget')
    if value != value.to_integral_value():
        raise ValueError('integral budget required')
    key = (row.get('tier'), row.get('asset'), int(value))
    return (*key, row.get('exit_policy')) if policy else key


def _identity(key):
    return dict(zip(('tier', 'asset', 'budget_usd', 'exit_policy'), key))


def _validate_provenance(strict, corrected, protocol_path, freeze_path):
    for result, schema in ((strict, original.RESULT_SCHEMA), (corrected, correction.RESULT_SCHEMA)):
        if (result.get('schema') != schema or result.get('status') != 'complete'
                or result.get('errors') != [] or result.get('event_source') != 'verified_capture'):
            raise ValueError('completed verified_capture result with correct schema required')
        terminal = result.get('terminal_event')
        if (not isinstance(terminal, dict) or terminal.get('type') != 'end'
                or terminal.get('truncated') is not False or terminal.get('raw_sha_verified') is not True):
            raise ValueError('verified nontruncated terminal event required')
        for field, terminal_field in (('raw_sha256', 'raw_gzip_sha256'),
                                       ('capture_manifest_sha256', 'manifest_sha256')):
            if _hash(result.get(field), field) != _hash(terminal.get(terminal_field), terminal_field):
                raise ValueError(f'capture terminal {field} mismatch')
    fields = ('capture', 'capture_manifest_sha256', 'raw_sha256', 'protocol_sha256',
              'protocol_frozen_at', 'source_sha256', 'metadata_normalized_sha256',
              'started_ns', 'cutoff_ns', 'entry_admission_end_ns', 'ended_ns', 'intended_end_ns',
              'assumptions', 'metadata', 'models')
    for field in fields:
        if field not in strict or strict[field] != corrected.get(field):
            raise ValueError(f'strict/corrected provenance or economic assumption mismatch: {field}')
    capture = Path(strict['capture'])
    protocol, manifest, start, cutoff, stop = original.verify_protocol(protocol_path, capture)
    freeze = correction.verify_correction(freeze_path, protocol_path, capture, cutoff_ns=cutoff)
    if (strict['source_sha256'] != protocol['source_sha256']
            or len(strict['source_sha256']) != 18
            or strict['protocol_sha256'] != original.digest(Path(protocol_path))
            or strict['protocol_frozen_at'] != protocol['frozen_at']
            or strict['metadata_normalized_sha256'] != protocol['metadata_normalized_sha256']):
        raise ValueError('original 18-source protocol provenance mismatch')
    if (strict['started_ns'], strict['cutoff_ns'], strict['ended_ns'],
            strict['entry_admission_end_ns'], strict['intended_end_ns']) != (
            start, cutoff, stop, start + 2920 * original.NS, start + 3000 * original.NS):
        raise ValueError('result timeline differs from stopped capture/protocol')
    if (manifest.get('end_reason') != 'duration_limit' or manifest.get('truncated')
            or stop != start + 3000 * original.NS):
        raise ValueError('complete stopped capture required')
    if strict['capture_manifest_sha256'] != original.digest(capture / 'manifest.json'):
        raise ValueError('actual capture manifest SHA-256 mismatch')
    _archive_size(capture, original.RAW_CAP)
    if (manifest.get('frames_sha256') != strict['raw_sha256']
            or original.digest(capture / 'frames.jsonl.gz') != strict['raw_sha256']):
        raise ValueError('actual capture raw SHA-256 mismatch')
    if (corrected.get('implementation_variant') != correction.VARIANT
            or corrected.get('original_result_schema') != original.RESULT_SCHEMA
            or corrected.get('original_frozen_v1_result') is not False
            or corrected.get('runtime_class_override') != correction.RUNTIME_OVERRIDE
            or corrected.get('source_sha256_extra') != freeze['source_sha256_extra']
            or len(corrected.get('source_sha256_extra', {})) != 2):
        raise ValueError('corrected 20-source variant provenance mismatch')
    declared = corrected.get('correction_freeze', {})
    expected = {'sha256': original.digest(Path(freeze_path)), 'frozen_at': freeze['frozen_at'],
                'conservative_holdout_lower_bound_ns': freeze['conservative_holdout_lower_bound_ns'],
                'actual_capture_started_ns': start, 'actual_holdout_cutoff_ns': cutoff,
                'frozen_after_capture_started': original._utc_ns(freeze['frozen_at']) >= start,
                'disclosure': freeze['timing_disclosure']}
    if any(declared.get(k) != v for k, v in expected.items()):
        raise ValueError('correction freeze provenance mismatch')
    if not isinstance(declared.get('path'), str) or Path(declared['path']).resolve() != Path(freeze_path).resolve():
        raise ValueError('correction freeze path mismatch')
    if strict.get('implementation_variant') or strict.get('source_sha256_extra'):
        raise ValueError('strict result mislabeled with corrected provenance')
    return {'capture': str(capture), 'raw_sha256': strict['raw_sha256'],
            'capture_manifest_sha256': strict['capture_manifest_sha256'],
            'protocol_sha256': strict['protocol_sha256'],
            'source_sha256': strict['source_sha256'],
            'source_sha256_extra': corrected['source_sha256_extra'],
            'correction_freeze': declared, 'started_ns': start, 'cutoff_ns': cutoff,
            'ended_ns': stop, 'raw_decoding_performed': False}


def _index(result, *, corrected):
    expected = set(itertools.product(original.TIERS, original.ASSETS, original.SIZES, original.POLICIES))
    branches = result.get('branches')
    if not isinstance(branches, list) or len(branches) != 128:
        raise ValueError('all 128 branch ledgers required')
    branch_map = {}
    for branch in branches:
        key = _key(branch)
        if key not in expected or key in branch_map:
            raise ValueError('branch universe or duplicate branch mismatch')
        if corrected and (branch.get('retirement_guard_revision') != 'entry-same-receipt-v1'
                          or branch.get('frozen_v1_result') is not False):
            raise ValueError('corrected branch identity mismatch')
        branch_map[key] = branch
    cohorts = result.get('cohorts')
    if not isinstance(cohorts, list) or len(cohorts) > original.MAX_COHORTS:
        raise ValueError('bounded cohorts required')
    cohort_map, groups = {}, {}
    for cohort in cohorts:
        key, ident = _key(cohort, False), cohort.get('cohort_id')
        if (not isinstance(ident, str) or not 0 < len(ident) <= 160
                or key not in {k[:3] for k in expected} or (*key, ident) in cohort_map
                or type(cohort.get('decision_ns')) is not int
                or not result['cutoff_ns'] <= cohort['decision_ns'] < result['entry_admission_end_ns']):
            raise ValueError('invalid cohort identity or decision time')
        admitted = cohort.get('admitted')
        if (not isinstance(admitted, dict) or set(admitted) != set(original.POLICIES)
                or any(type(v) is not bool for v in admitted.values()) or not any(admitted.values())):
            raise ValueError('cohort admission map malformed')
        cohort_map[(*key, ident)] = cohort
        groups.setdefault(key, {})[ident] = cohort
    episodes = {}
    for key, branch in branch_map.items():
        rows = branch.get('episodes')
        if not isinstance(rows, list) or len(rows) > 2000:
            raise ValueError('bounded episode rows required')
        numbers = set()
        for episode in rows:
            ident, number = episode.get('cohort_id'), episode.get('number')
            cohort = cohort_map.get((*key[:3], ident))
            if (cohort is None or not cohort['admitted'][key[3]] or (*key, ident) in episodes
                    or type(number) is not int or number <= 0 or number in numbers):
                raise ValueError('episode/cohort admission identity mismatch')
            numbers.add(number)
            for field in ('execution_unknown', 'funding_unknown'):
                if field in episode and type(episode[field]) is not bool:
                    raise ValueError('episode unknown flag must be boolean')
            episodes[(*key, ident)] = episode
    recomputed = original.score_cohorts(cohorts, branches, result.get('counts', {}))
    if result.get('cohort_score') != recomputed:
        raise ValueError('cohort score differs from actual episodes/admissions')
    return branch_map, groups, episodes


def _branch_snapshot(branch, cohort_group):
    known = funding_unknown = execution_unknown = 0
    fee_contribution = stressed_contribution = Decimal(0)
    for episode in branch['episodes']:
        funding_unknown += bool(episode.get('funding_unknown'))
        execution_unknown += bool(episode.get('execution_unknown'))
        net = original._complete_net(episode)
        if net is not None:
            known += 1
            fee_contribution += _decimal(episode['cash_known'], 'known episode cash')
            stressed_contribution += net
    policy = branch['exit_policy']
    admitted = sum(c['admitted'][policy] for c in cohort_group.values())
    outstanding = admitted - len(branch['episodes'])
    if outstanding < 0:
        raise ValueError('episode count exceeds admission count')
    positions = ('rh_position', 'hl_position', 'delta', 'gross_inventory')
    for field in positions:
        _decimal(branch.get(field), field)
    obligations = (branch.get('passive_quote_open') or branch.get('passive_buy_intents_open')
                   or branch.get('fallback_pending') or branch.get('cohort_id_active'))
    unresolved = (bool(branch.get('unknown_reason')) or bool(branch.get('funding_unknown'))
                  or execution_unknown > 0 or funding_unknown > 0 or outstanding > 0
                  or any(_decimal(branch[f], f) != 0 for f in ('rh_position', 'hl_position'))
                  or bool(obligations))
    complete = branch.get('complete_net')
    if unresolved and complete is not None:
        raise ValueError('unresolved portfolio cannot claim known complete_net')
    if complete is not None:
        cash = _decimal(branch['cash_known'], 'branch cash')
        net = cash - _decimal(branch['reserve_cost'], 'branch reserve') - _decimal(branch['capital_cost'], 'branch capital')
        if _decimal(complete, 'complete net') != net:
            raise ValueError('complete portfolio net identity mismatch')
    halt = branch.get('first_unknown_ns')
    if halt is not None and type(halt) is not int:
        raise ValueError('first halt time malformed')
    retired_passive_count = branch.get('retired_passive_quote_guard_count')
    if type(retired_passive_count) is not int or retired_passive_count < 0:
        raise ValueError('retired passive quote guard count required')
    for field in ('audit_truncated', 'truncated'):
        if field in branch and type(branch[field]) is not bool:
            raise ValueError('branch retention/truncation flag must be boolean')
    retention_incomplete = bool(branch.get('audit_truncated') or branch.get('truncated'))
    historical_adjudication = retention_incomplete or (
        retired_passive_count > 0 and (halt is not None or bool(branch.get('unknown_reason'))))
    guard_status = ('retention_incomplete' if retention_incomplete else
                    'historical_adjudication_required' if historical_adjudication else
                    'nonapplicable_no_retired_passive_guards' if retired_passive_count == 0 else
                    'no_recorded_halt')
    engine_counts = branch.get('counts')
    if (not isinstance(engine_counts, dict) or len(engine_counts) > 256
            or any(not isinstance(k, str) or len(k) > 160 or type(v) is not int or v < 0
                   for k, v in engine_counts.items())):
        raise ValueError('bounded engine counts required')
    return {'retained_candidate_cohorts': len(cohort_group), 'admitted_cohorts': admitted,
            'closed_episodes': len(branch['episodes']), 'known_closed_episodes': known,
            'closed_episodes_with_attributed_entry_flow': sum(
                _decimal(e['maker_attributed'], 'maker attributed') > 0 for e in branch['episodes']),
            'engine_counts': engine_counts,
            'unknown_closed_episodes': len(branch['episodes']) - known,
            'execution_unknown_episodes': execution_unknown, 'funding_unknown_episodes': funding_unknown,
            'admitted_without_closed_episode': outstanding,
            'known_closed_fee_only_contribution_usd': str(fee_contribution),
            'known_closed_after_reserve_capital_contribution_usd': str(stressed_contribution),
            'known_closed_contributions_are_raw_reported': True,
            'known_closed_contributions_provisional': historical_adjudication,
            'validated_known_closed_fee_only_contribution_usd': None if historical_adjudication else str(fee_contribution),
            'validated_known_closed_after_reserve_capital_contribution_usd': None if historical_adjudication else str(stressed_contribution),
            'retired_passive_quote_guard_count': retired_passive_count,
            'retention_incomplete': retention_incomplete,
            'retirement_guard_status': guard_status,
            'historical_adjudication_required': historical_adjudication,
            'complete_portfolio_net_usd': complete, 'complete_portfolio_net_known': complete is not None,
            'portfolio_unresolved': unresolved or complete is None,
            'first_halt_ns': halt, 'unknown_reason': branch.get('unknown_reason'),
            'first_quote_requested_ns': branch.get('first_quote_requested_ns'),
            'effective_quote_opportunity_seconds_before_unknown': branch.get('effective_quote_opportunity_seconds_before_unknown'),
            'group_book_quote_checks': branch.get('group_book_quote_checks'),
            'delta_exposure_base_seconds': str(_decimal(branch['delta_exposure_base_seconds'], 'delta exposure')),
            'gross_inventory_base_seconds': str(_decimal(branch['gross_inventory_base_seconds'], 'gross exposure')),
            **{field: branch[field] for field in positions}}


def _episode_state(episode):
    if episode is None:
        return None
    net = original._complete_net(episode)
    return {'number': episode['number'], 'execution_unknown': bool(episode.get('execution_unknown')),
            'execution_unknown_reason': episode.get('execution_unknown_reason'),
            'funding_unknown': bool(episode.get('funding_unknown')),
            'known_after_reserve_capital_contribution_usd': None if net is None else str(net),
            'cash_recorded_usd': episode.get('cash_known'),
            'late_retired_flow': episode.get('late_retired_flow'),
            'late_retired_passive_flow': episode.get('late_retired_passive_flow')}


def compare_results(strict, corrected):
    """Pure bounded comparison; production caller first verifies provenance."""
    old_branches, old_groups, old_episodes = _index(strict, corrected=False)
    new_branches, new_groups, new_episodes = _index(corrected, corrected=True)
    comparisons, execution_changes, group_comparisons = [], [], []
    for group in sorted({key[:3] for key in old_branches}):
        old, new = old_groups.get(group, {}), new_groups.get(group, {})
        common = sorted(old.keys() & new.keys(), key=lambda ident: old[ident]['decision_ns'])
        for ident in common:
            if old[ident]['decision_ns'] != new[ident]['decision_ns']:
                raise ValueError('common cohort decision time differs')
        def cohort_list(keys, source):
            return [{'cohort_id': ident, 'decision_ns': source[ident]['decision_ns'],
                     'admitted': source[ident]['admitted']}
                    for ident in sorted(keys, key=lambda value: source[value]['decision_ns'])]
        group_comparisons.append({**_identity(group), 'common_cohort_ids': common,
                                  'strict_only_cohorts': cohort_list(old.keys() - new.keys(), old),
                                  'corrected_only_cohorts': cohort_list(new.keys() - old.keys(), new),
                                  'common_admission_changes': [
                                      {'cohort_id': ident, 'decision_ns': old[ident]['decision_ns'],
                                       'strict_admitted': old[ident]['admitted'], 'corrected_admitted': new[ident]['admitted']}
                                      for ident in common if old[ident]['admitted'] != new[ident]['admitted']]})
    for key in sorted(old_branches):
        old_group, new_group = old_groups.get(key[:3], {}), new_groups.get(key[:3], {})
        old_admitted = {ident for ident, c in old_group.items() if c['admitted'][key[3]]}
        new_admitted = {ident for ident, c in new_group.items() if c['admitted'][key[3]]}
        common_admitted = sorted(old_admitted & new_admitted)
        old_state = _branch_snapshot(old_branches[key], old_group)
        new_state = _branch_snapshot(new_branches[key], new_group)
        common_closed = common_known_same_entry = 0
        for ident in common_admitted:
            old_ep, new_ep = old_episodes.get((*key, ident)), new_episodes.get((*key, ident))
            if old_ep is not None and new_ep is not None:
                common_closed += 1
                old_sig, new_sig = original._entry_signature(old_ep), original._entry_signature(new_ep)
                if (old_sig is not None and old_sig == new_sig
                        and original._complete_net(old_ep) is not None and original._complete_net(new_ep) is not None):
                    common_known_same_entry += 1
            old_unknown = bool(old_ep and old_ep.get('execution_unknown'))
            new_unknown = bool(new_ep and new_ep.get('execution_unknown'))
            if old_unknown != new_unknown or (old_ep and new_ep and
                    old_ep.get('execution_unknown_reason') != new_ep.get('execution_unknown_reason')):
                execution_changes.append({**_identity(key), 'cohort_id': ident,
                                          'strict': _episode_state(old_ep), 'corrected': _episode_state(new_ep)})
        comparisons.append({**_identity(key), 'strict': old_state, 'corrected': new_state,
                            'common_admitted_cohort_ids': common_admitted,
                            'strict_only_admitted_cohort_ids': sorted(old_admitted - new_admitted),
                            'corrected_only_admitted_cohort_ids': sorted(new_admitted - old_admitted),
                            'common_closed_episode_count': common_closed,
                            'common_known_full_same_entry_episode_count': common_known_same_entry,
                            'validated_common_known_full_same_entry_episode_count': (
                                None if old_state['historical_adjudication_required'] or new_state['historical_adjudication_required']
                                else common_known_same_entry),
                            'admission_histories_identical': old_admitted == new_admitted,
                            'effective_observation_time_identical': (
                                old_state['first_halt_ns'] == new_state['first_halt_ns'] and
                                old_state['effective_quote_opportunity_seconds_before_unknown'] ==
                                new_state['effective_quote_opportunity_seconds_before_unknown'])})
    primary = [row for row in comparisons if (row['tier'], row['asset'], row['budget_usd'], row['exit_policy'])
               in (('standard', 'XAG', 1000, 'control10s'), ('standard', 'XAG', 1000, 'passive_target10s'))]
    label = 'primary_standard_xag_1000_target10_vs_control10'
    primary_old_provisional = any(b['strict']['historical_adjudication_required'] for b in primary)
    primary_new_provisional = any(b['corrected']['historical_adjudication_required'] for b in primary)
    return {'schema': SCHEMA, 'branch_count': len(comparisons), 'branches': comparisons,
            'execution_unknown_changes': execution_changes, 'cohort_groups': group_comparisons,
            'primary_standard_xag_1000': {'branches': primary,
                                        'strict_raw_reported_within_replay_same_entry_contrast': strict['cohort_score'][label],
                                        'corrected_raw_reported_within_replay_same_entry_contrast': corrected['cohort_score'][label],
                                        'strict_historical_adjudication_required': primary_old_provisional,
                                        'corrected_historical_adjudication_required': primary_new_provisional,
                                        'strict_validated_within_replay_same_entry_contrast': (
                                            None if primary_old_provisional else strict['cohort_score'][label]),
                                        'corrected_validated_within_replay_same_entry_contrast': (
                                            None if primary_new_provisional else corrected['cohort_score'][label]),
                                        'cross_variant_profit_improvement': None},
            'limitations': LIMITATIONS, 'summed_branch_portfolio_net': None}


def _report(result):
    lines = ['# Strict and retirement-corrected passive-exit comparison', '',
             'Both artifacts passed stopped-capture provenance checks. Each row is an independent ledger.', '',
             'Raw reported closed contribution excludes episodes already marked unknown. '
             'Retained passive guards after a halt require historical adjudication; their validated contribution remains undefined.', '',
             '| Tier | Asset | Budget | Policy | Admissions strict/corrected | Closed strict/corrected | Execution unknown strict/corrected | Raw reported contribution strict/corrected | Validated contribution strict/corrected | Complete portfolio net strict/corrected | First halt ns strict/corrected | Retirement guard strict/corrected |',
             '|---|---|---:|---|---:|---:|---:|---:|---|---|---|---|']
    def value(v):
        return 'unknown' if v is None else str(v)
    for branch in result['branches']:
        old, new = branch['strict'], branch['corrected']
        pair = lambda field: f'{value(old[field])} / {value(new[field])}'
        lines.append(f"| {branch['tier']} | {branch['asset']} | {branch['budget_usd']} | {branch['exit_policy']} | "
                     f"{pair('admitted_cohorts')} | {pair('closed_episodes')} | {pair('execution_unknown_episodes')} | "
                     f"{pair('known_closed_after_reserve_capital_contribution_usd')} | "
                     f"{pair('validated_known_closed_after_reserve_capital_contribution_usd')} | "
                     f"{pair('complete_portfolio_net_usd')} | {pair('first_halt_ns')} | {pair('retirement_guard_status')} |")
    lines += ['', f"Actual execution-unknown classification changes on common admitted cohorts: {len(result['execution_unknown_changes'])}.", '',
              'The JSON identifies shared cohort IDs, changed admission maps, and later cohorts present in only one replay. '
              'It also provides separate Standard XAG $1,000 control10s and passive_target10s diagnostics. '
              'Differences in net across unequal admission histories or observation time do not establish causal profit improvement.', '',
              *[f'- {item}' for item in LIMITATIONS], '']
    return '\n'.join(lines)


def analyze(strict_path, corrected_path, protocol_path, freeze_path, out):
    strict_path, corrected_path, protocol_path, freeze_path, out = map(
        Path, (strict_path, corrected_path, protocol_path, freeze_path, out))
    # Both completed results must exist before opening any stopped source artifact.
    strict = original._bounded_json(strict_path, MAX_INPUT_BYTES)
    corrected = original._bounded_json(corrected_path, MAX_INPUT_BYTES)
    input_hashes = {'strict_analysis_sha256': original.digest(strict_path),
                    'corrected_analysis_sha256': original.digest(corrected_path)}
    provenance = _validate_provenance(strict, corrected, protocol_path, freeze_path)
    result = compare_results(strict, corrected)
    result.update({'status': 'complete', 'provenance': provenance, **input_hashes,
                   'strict_analysis': str(strict_path), 'corrected_analysis': str(corrected_path),
                   'comparison_source_sha256': original.digest(Path(__file__))})
    for name, path in (('strict_analysis_sha256', strict_path), ('corrected_analysis_sha256', corrected_path)):
        if original.digest(path) != input_hashes[name]:
            raise ValueError('input analysis changed during comparison')
    body = (json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    report = _report(result).encode()
    if len(body) > MAX_OUTPUT_BYTES or len(report) > MAX_REPORT_BYTES:
        raise ValueError('comparison output exceeds hard byte cap')
    if out.exists():
        raise ValueError('comparison output must be a new directory')
    out.mkdir(parents=True)
    (out / 'comparison.json').write_bytes(body)
    (out / 'REPORT.md').write_bytes(report)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict', type=Path, default=DEFAULT_STRICT)
    parser.add_argument('--corrected', type=Path, default=DEFAULT_CORRECTED)
    parser.add_argument('--protocol', type=Path, default=correction.DEFAULT_PROTOCOL)
    parser.add_argument('--correction-freeze', type=Path, default=correction.DEFAULT_FREEZE)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = analyze(args.strict, args.corrected, args.protocol, args.correction_freeze, args.out)
    print(json.dumps({'out': str(args.out), 'status': result['status'], 'branches': result['branch_count'],
                      'execution_unknown_changes': len(result['execution_unknown_changes'])}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
