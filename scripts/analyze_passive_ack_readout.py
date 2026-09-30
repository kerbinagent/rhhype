#!/usr/bin/env python3
"""Read only completed strict/corrected/base/+200 artifacts, never replay feeds."""
from __future__ import annotations

import argparse
from collections import Counter
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import analyze_rh_passive_exit as original
from scripts import analyze_passive_correction_comparison as comparison
from scripts import replay_passive_ack_exploratory as ack_wrapper

SCHEMA = 'rh-passive-ack-exploratory-readout-v1'
RUNS = ('strict', 'corrected', 'base', 'plus200')
MAX_INPUT_BYTES = 32_000_000
MAX_OUTPUT_BYTES = 32_000_000
MAX_REPORT_BYTES = 1_000_000
MAX_ALIGNMENT_ROWS = 6 * 128
MAX_ALIGNMENT_COHORTS = 6 * original.MAX_COHORTS * 4
DEFAULT_BASE = ROOT / 'data/derived/rh-passive-exit-v1-restart-ack-exploratory-base/analysis.json'
DEFAULT_PLUS200 = ROOT / 'data/derived/rh-passive-exit-v1-restart-ack-exploratory-plus200/analysis.json'
DEFAULT_OUT = ROOT / 'data/derived/rh-passive-exit-v1-restart-ack-readout'
HELPER_ARTIFACTS = ('scripts/analyze_passive_ack_readout.py',
                    'tests/test_analyze_passive_ack_readout.py',
                    'research/passive-ack-exploratory-readout.md')
LIMITATIONS = [
    'ACK known contributions and complete totals are conditional_known model economics, never validated private executions.',
    'Changes combine ACK clocks, coverage, anchor revisions, native-ID evidence and outer historical guards; attrition differences are not isolated latency effects.',
    'First halt categories and event counters describe observed model attrition; they do not causally identify why another run differs.',
    'Shared admission IDs alone do not establish equal fills: full-entry signature matches are reported separately.',
    'Unmatched later admissions and different halt/exposure times prevent causal comparisons of total net.',
    'Episode decision/flat intervals are observation intervals, not inventory exposure; branch aggregate inventory exposure cannot be allocated to cohorts from these summaries.',
    'Frozen-parent retained passive guards after a halt or incomplete retention require historical adjudication; their raw known contributions remain provisional.',
    'The 128 correlated branches and four runs are independent counterfactual ledgers and are never summed into a portfolio.',
]


def _reason_family(reason):
    if reason is None:
        return 'no_recorded_halt'
    if reason in ('eligible_flow_before_activation_book', 'eligible_flow_before_queue_snapshot',
                  'activation_book_timeout', 'passive_eligible_flow_before_activation_snapshot',
                  'passive_eligible_flow_before_queue_snapshot', 'passive_activation_book_timeout'):
        return 'strict_activation_window'
    if reason in ('trade_cancel_order_ambiguous', 'cancel_fill_same_source_time', 'cancel_confirmation_book_timeout',
                  'passive_trade_cancel_order_ambiguous', 'passive_cancel_fill_same_source_time', 'passive_cancel_confirmation_timeout'):
        return 'strict_cancel_window'
    if 'retired' in reason:
        return 'retirement_execution_evidence'
    if any(word in reason for word in ('coverage', 'stale', 'generation', 'clock', 'source')):
        return 'coverage_generation_clock'
    if reason.startswith('assumed_ack_anchor') or reason == 'assumed_post_only_reject_unresolved':
        return 'assumed_anchor_or_post_only'
    if 'trade_id' in reason or 'identity' in reason:
        return 'native_id_evidence'
    if 'cap' in reason:
        return 'model_or_retention_cap'
    if any(word in reason for word in ('lot', 'minimum', 'dust', 'depth', 'inventory', 'hedge', 'obligation')):
        return 'execution_rule_depth_or_obligation'
    return 'other_explicit_reason'


def validate_ack(result, selection, strict, corrected, protocol, sources, paths):
    if result.get('schema') != ack_wrapper.SCHEMA:
        raise ValueError('separate exploratory ACK schema required')
    required = {'original_result_schema': original.RESULT_SCHEMA,
                'implementation_variant': ack_wrapper.VARIANT, 'study_classification': ack_wrapper.CLASSIFICATION,
                'original_frozen_v1_result': False, 'retirement_corrected_v1_result': False,
                'prospective_result': False, 'pre_holdout_freeze_claimed': False,
                'execution_assumed': True, 'private_ack_observed': False, 'actual_fills_observed': False,
                'guaranteed_profit_bound': False, 'native_trade_ids_stable_across_generations_assumed': True,
                'source_snapshots_are_not_prospective_freezes': True}
    if any(result.get(k) != v or isinstance(v, bool) and type(result.get(k)) is not bool
           for k, v in required.items()):
        raise ValueError('exploratory ACK classification/assumption mismatch')
    # Check the private staged coordinator format through its original gate;
    # the published schema above remains distinct and is never relabeled.
    ack_wrapper._validate_variant_result(dict(result, schema=original.RESULT_SCHEMA), selection)
    for branch in result['branches']:
        for row in (branch, *branch.get('episodes', [])):
            if any(type(row.get(field)) is not bool for field in
                   ('execution_assumed', 'private_ack_observed', 'native_trade_ids_stable_across_generations_assumed')):
                raise ValueError('ACK branch/episode assumptions require boolean labels')
    plan = ack_wrapper.scenario_plan(selection)
    if (result.get('ack_scenario') != plan or result.get('active_ack_execution_assumptions') != plan
            or result.get('runtime_factory_override') != {**ack_wrapper.RUNTIME_FACTORY,
                'scenario_selection': selection, 'scenario_id': plan['scenario_id']}
            or result.get('original_coordinator_assumptions') != strict['assumptions']
            or result.get('exploratory_disclosure') != ack_wrapper.DISCLOSURE
            or result.get('combined_model_changes') != [
                'deterministic maker/cancel ACK clocks', 'ordered obligation coverage checks',
                'preceding raw-book anchor and late revision checks',
                'native trade-ID stability, dedupe, cap and conflict evidence',
                'outer historical execution evidence checks after earlier halt']):
        raise ValueError('exact scenario/runtime/combined assumptions mismatch')
    active = {**strict['assumptions'], 'timing': 'deterministic assumed private ACK clocks; previous received raw anchor; public trade receipt notification model'}
    if result.get('assumptions') != active:
        raise ValueError('active ACK timing/economic assumptions mismatch')
    for field in ('capture', 'capture_manifest_sha256', 'raw_sha256', 'protocol_sha256',
                  'protocol_frozen_at', 'source_sha256', 'metadata_normalized_sha256',
                  'started_ns', 'cutoff_ns', 'ended_ns', 'entry_admission_end_ns', 'intended_end_ns',
                  'metadata', 'models'):
        if result.get(field) != strict[field]:
            raise ValueError(f'ACK/reference source or timeline mismatch: {field}')
    if (result.get('actual_dependency_sha256_before') != sources
            or result.get('actual_dependency_sha256_after') != sources
            or result.get('source_sha256_extra') != {name: sources[name] for name in ack_wrapper.EXTRA_SOURCES}):
        raise ValueError('ACK actual 21-source snapshot mismatch')
    stopped = result.get('stopped_capture_provenance') or {}
    for field in ('protocol_sha256', 'capture_manifest_sha256', 'raw_sha256', 'metadata_normalized_sha256',
                  'started_ns', 'cutoff_ns', 'ended_ns', 'entry_admission_end_ns', 'intended_end_ns'):
        if stopped.get(field) != strict[field]:
            raise ValueError('ACK stopped provenance mismatch')
    references = stopped.get('readout_references') or {}
    for name, result_path in (('strict', paths['strict']), ('corrected', paths['corrected'])):
        if (not isinstance(references.get(f'{name}_analysis'), str)
                or Path(references[f'{name}_analysis']).resolve() != result_path.resolve()
                or references.get(f'{name}_analysis_sha256') != original.digest(result_path)):
            raise ValueError('ACK completed readout reference hash/path mismatch')
    return plan


def _snapshot(branch, group, is_ack):
    state = comparison._branch_snapshot(branch, group)
    if is_ack:
        incomplete = state['retention_incomplete']
        state['retirement_guard_status'] = ('retention_incomplete' if incomplete else 'outer_historical_guard_active_under_ACK_model')
        state['historical_adjudication_required'] = incomplete
        state['known_closed_contributions_provisional'] = incomplete
        for field in ('fee_only', 'after_reserve_capital'):
            state.pop(f'validated_known_closed_{field}_contribution_usd')
            state[f'conditional_known_closed_{field}_contribution_usd'] = (
                None if incomplete else state[f'known_closed_{field}_contribution_usd'])
        state['conditional_known_complete_portfolio_net_usd'] = (
            None if incomplete else state['complete_portfolio_net_usd'])
        state['net_semantics'] = 'conditional_known_assumed_execution_model'
    else:
        state['net_semantics'] = 'frozen_public_flow_model_with_historical_guard_validation_limit'
    state['first_halt_reason_family'] = _reason_family(state['unknown_reason'])
    state['first_halt_mentions_cap'] = 'cap' in (state['unknown_reason'] or '')
    state['exit_adverse_bps'] = branch.get('exit_adverse_bps')
    episode_reasons = Counter(e.get('execution_unknown_reason') or 'unspecified' for e in branch['episodes'] if e.get('execution_unknown'))
    state['episode_execution_unknown_reason_counts'] = dict(episode_reasons)
    counts = state['engine_counts']
    state['attrition_counters'] = {name: value for name, value in counts.items() if
                                  any(token in name for token in ('abstain', 'target', 'cap', 'assumed', 'activation', 'cancel', 'unknown', 'retired', 'hedge', 'fallback'))}
    state['known_no_flow_closed_episodes'] = sum(original._complete_net(e) is not None and
        comparison._decimal(e['maker_attributed'], 'maker attributed') == 0 for e in branch['episodes'])
    state['known_attributed_flow_closed_episodes'] = state['known_closed_episodes'] - state['known_no_flow_closed_episodes']
    return state


def _cohort_observation(ident, cohort, episode):
    return {'cohort_id': ident, 'decision_ns': cohort['decision_ns'],
            'episode_decided_ns': episode.get('decided_ns') if episode else None,
            'episode_flat_ns': episode.get('flat_ns') if episode else None,
            'first_full_hedge_ns': episode.get('first_full_hedge_ns') if episode else None,
            'episode_execution_unknown': bool(episode.get('execution_unknown')) if episode else None,
            'inventory_exposure_by_cohort': None}


def compare_readouts(results):
    indices = {name: comparison._index(result, corrected=name == 'corrected') for name, result in results.items()}
    rows, alignments = [], []
    retained_alignment_cohorts = 0
    primary = []
    for key in sorted(indices['strict'][0]):
        states = {name: _snapshot(index[0][key], index[1].get(key[:3], {}), name in ('base', 'plus200'))
                  for name, index in indices.items()}
        row = {**comparison._identity(key), 'runs': states}
        rows.append(row)
        if key in (('standard', 'XAG', 1000, 'control10s'), ('standard', 'XAG', 1000, 'passive_target10s')):
            primary.append(row)
        for left, right in itertools.combinations(RUNS, 2):
            li, ri = indices[left], indices[right]
            lg, rg = li[1].get(key[:3], {}), ri[1].get(key[:3], {})
            la = {ident for ident, c in lg.items() if c['admitted'][key[3]]}
            ra = {ident for ident, c in rg.items() if c['admitted'][key[3]]}
            common = sorted(la & ra)
            full_matches, known_matches = [], []
            for ident in common:
                if lg[ident]['decision_ns'] != rg[ident]['decision_ns']:
                    raise ValueError('shared admitted cohort decision mismatch')
                le, re = li[2].get((*key, ident)), ri[2].get((*key, ident))
                ls = original._entry_signature(le) if le else None
                rs = original._entry_signature(re) if re else None
                if ls is not None and ls == rs:
                    full_matches.append(ident)
                    if original._complete_net(le) is not None and original._complete_net(re) is not None:
                        known_matches.append(ident)
            def unmatched(ids, group, episode_index):
                return [_cohort_observation(ident, group[ident], episode_index.get((*key, ident)))
                        for ident in sorted(ids, key=lambda ident: group[ident]['decision_ns'])]
            retained_alignment_cohorts += len(common) + len(la - ra) + len(ra - la)
            if retained_alignment_cohorts > MAX_ALIGNMENT_COHORTS:
                raise ValueError('alignment cohort retention bound exceeded')
            withheld = states[left]['historical_adjudication_required'] or states[right]['historical_adjudication_required']
            alignments.append({**comparison._identity(key), 'left': left, 'right': right,
                'common_admitted_cohort_ids': common, 'common_full_entry_match_cohort_ids': full_matches,
                'common_reported_known_full_entry_match_cohort_ids': known_matches,
                'trusted_under_each_model_common_known_full_entry_match_count': None if withheld else len(known_matches),
                'left_only_admissions': unmatched(la - ra, lg, li[2]),
                'right_only_admissions': unmatched(ra - la, rg, ri[2]),
                'admission_histories_identical': la == ra,
                'common_inventory_exposure': None, 'unmatched_inventory_exposure': None,
                'exposure_allocation_available': False, 'causal_profit_improvement': None})
    if len(alignments) != MAX_ALIGNMENT_ROWS:
        raise ValueError('six alignments for all 128 branches required')
    return {'schema': SCHEMA, 'status': 'complete', 'branches': rows, 'branch_count': len(rows),
            'pairwise_alignments': alignments, 'alignment_rows': len(alignments),
            'alignment_cohorts_retained': retained_alignment_cohorts,
            'primary_standard_xag_1000': primary, 'causal_profit_improvement': None,
            'combined_branch_portfolio_net': None, 'limitations': LIMITATIONS}


def _report(result):
    lines = ['# Exploratory ACK readout', '',
             'Four independent model readouts. ACK known nets are conditional on assumed execution.', '',
             '| Tier | Asset | Budget | Exit | Run | Admitted | Known closed | Unknown closed | Known no flow | Known flow | Complete net | First halt family | Target abstain counter |',
             '|---|---|---:|---|---|---:|---:|---:|---:|---:|---|---|---:|']
    for row in result['branches']:
        for name in RUNS:
            state = row['runs'][name]
            net = state['complete_portfolio_net_usd']
            lines.append(f"| {row['tier']} | {row['asset']} | {row['budget_usd']} | {row['exit_policy']} | {name} | "
                f"{state['admitted_cohorts']} | {state['known_closed_episodes']} | {state['unknown_closed_episodes']} | "
                f"{state['known_no_flow_closed_episodes']} | {state['known_attributed_flow_closed_episodes']} | "
                f"{net if net is not None else 'unknown'} | {state['first_halt_reason_family']} | "
                f"{state['engine_counts'].get('passive_target_abstain', 0)} |")
    lines += ['', 'Raw first-halt reasons, target/abstain/cap/ACK counters, conditional contributions, '
              'branch quote/delta/gross exposure, six cohort alignments, and primary Standard XAG $1,000 rows are in readout.json.', '',
              *[f'- {limitation}' for limitation in LIMITATIONS], '']
    return '\n'.join(lines)


def analyze(paths, protocol_path, freeze_path, out):
    paths = {name: Path(paths[name]) for name in RUNS}
    protocol_path, freeze_path, out = map(Path, (protocol_path, freeze_path, out))
    # All four completed artifact gates precede opening stopped source inputs.
    results = {name: original._bounded_json(path, MAX_INPUT_BYTES) for name, path in paths.items()}
    if any(r.get('status') != 'complete' or r.get('errors') != [] or r.get('event_source') != 'verified_capture' for r in results.values()):
        raise ValueError('all four completed verified_capture readouts required')
    input_hashes = {name: original.digest(path) for name, path in paths.items()}
    provenance = comparison._validate_provenance(results['strict'], results['corrected'], protocol_path, freeze_path)
    protocol = original._bounded_json(protocol_path)
    sources = ack_wrapper.source_snapshot(protocol)
    plans = {selection: validate_ack(results[selection], selection, results['strict'], results['corrected'],
                                     protocol, sources, paths) for selection in ('base', 'plus200')}
    helper_hashes = {name: original.digest(ROOT / name) for name in HELPER_ARTIFACTS}
    helper_hashes['scripts/analyze_passive_correction_comparison.py'] = original.digest(ROOT / 'scripts/analyze_passive_correction_comparison.py')
    result = compare_readouts(results)
    result.update(provenance=provenance, ack_scenarios=plans, input_analysis_sha256=input_hashes,
                  input_analysis_paths={name: str(path) for name, path in paths.items()},
                  actual_ack_dependency_sha256=sources, helper_artifact_sha256=helper_hashes,
                  inherited_economic_assumptions=results['strict']['assumptions'],
                  active_ack_assumptions={name: results[name]['assumptions'] for name in ('base', 'plus200')},
                  combined_model_changes=results['base']['combined_model_changes'])
    if (ack_wrapper.source_snapshot(protocol) != sources
            or any(original.digest(path) != input_hashes[name] for name, path in paths.items())
            or any(original.digest(ROOT / name) != digest for name, digest in helper_hashes.items())):
        raise ValueError('readout inputs/dependencies changed during comparison')
    body = (json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    report = _report(result).encode()
    if len(body) > MAX_OUTPUT_BYTES or len(report) > MAX_REPORT_BYTES:
        raise ValueError('ACK readout output byte cap exceeded')
    protected = [p.parent.resolve() for p in paths.values()] + [protocol_path.parent.resolve(), Path(provenance['capture']).resolve()]
    target = out.resolve()
    if out.exists() or out.is_symlink() or any(target == p or target.is_relative_to(p) or p.is_relative_to(target) for p in protected):
        raise ValueError('new readout output must not overlap inputs or existing paths')
    out.mkdir(parents=True)
    (out / 'readout.json').write_bytes(body)
    (out / 'REPORT.md').write_bytes(report)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strict', type=Path, default=ack_wrapper.DEFAULT_STRICT)
    parser.add_argument('--corrected', type=Path, default=ack_wrapper.DEFAULT_CORRECTED)
    parser.add_argument('--base', type=Path, default=DEFAULT_BASE)
    parser.add_argument('--plus200', type=Path, default=DEFAULT_PLUS200)
    parser.add_argument('--protocol', type=Path, default=ack_wrapper.DEFAULT_PROTOCOL)
    parser.add_argument('--correction-freeze', type=Path, default=ROOT / 'reports/rh-passive-exit-v1-restart/retirement-correction-freeze.json')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    result = analyze({name: getattr(args, name) for name in RUNS}, args.protocol, args.correction_freeze, args.out)
    print(json.dumps({'out': str(args.out), 'status': result['status'], 'branches': result['branch_count'],
                      'alignments': result['alignment_rows']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
