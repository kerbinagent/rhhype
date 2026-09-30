#!/usr/bin/env python3
"""Prepare or explicitly replay one exploratory post-capture ACK model.

Dry by default. No private ACK, actual execution, prospective protocol, trading
request, or causal profit improvement is established by this sensitivity.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import analyze_rh_passive_exit as original
from scripts import rh_passive_exit_engine as engine
from scripts import rh_passive_ack_scenarios as ack
from scripts.rh_maker_events import _archive_size

SCHEMA = 'rh-passive-exit-replay-ack-exploratory-postcapture-v1'
CLASSIFICATION = 'EXPLORATORY POST-CAPTURE MODEL'
VARIANT = 'assumed-ack-exploratory-postcapture-v1'
EXTRA_SOURCES = ('scripts/rh_passive_retirement_guard.py',
                 'scripts/rh_passive_ack_scenarios.py',
                 'scripts/replay_passive_ack_exploratory.py')
ACTUAL_DEPENDENCIES = (*original.REQUIRED_SOURCES, *EXTRA_SOURCES)
MAX_SOURCE_BYTES = 2_000_000
MAX_SOURCE_TOTAL_BYTES = 16_000_000
MAX_REPORT_BYTES = 1_000_000
SCENARIOS = {'base': ack.BASE_SCENARIO, 'plus200': ack.LONGER_LATENCY_SCENARIO}
ORIGINAL_CLASS = engine.PassiveExitBranch
LOADED_ACK_SHA256 = original.digest(ROOT / 'scripts/rh_passive_ack_scenarios.py')
DEFAULT_PROTOCOL = ROOT / 'reports/rh-passive-exit-v1-restart/protocol.json'
DEFAULT_CAPTURE = ROOT / 'data/raw/rh-passive-exit-v1/20260930T0252Z'
DEFAULT_STRICT = ROOT / 'data/derived/rh-passive-exit-v1-restart/analysis.json'
DEFAULT_CORRECTED = ROOT / 'data/derived/rh-passive-exit-v1-restart-corrected/analysis.json'
CORRECTED_SCHEMA = 'rh-passive-exit-replay-retirement-corrected-v1'
CORRECTED_EXTRA = ('scripts/rh_passive_retirement_guard.py',
                   'scripts/replay_passive_retirement_corrected.py')
RUNTIME_FACTORY = {
    'module_binding': 'scripts.rh_passive_exit_engine.PassiveExitBranch',
    'original_class': 'scripts.rh_passive_exit_engine.PassiveExitBranch',
    'actual_class': 'scripts.rh_passive_ack_scenarios.AssumedAckPassiveExitBranch',
    'factory': 'scripts.replay_passive_ack_exploratory.scenario_branch_binding',
    'mechanism': 'temporary scenario-bound factory during original coordinator; restored in finally',
}
DISCLOSURE = (
    'EXPLORATORY POST-CAPTURE MODEL: one explicitly selected deterministic ACK sensitivity. '
    'The model is prepared after capture launch and is not an original prospective v1 result '
    'or the separately frozen retirement-corrected result. Code snapshots attest the implementation '
    'used for this diagnostic; they are not a pre-holdout freeze or authorization. Native trade IDs '
    'are assumed stable across transport generations. Private ACK clocks, actual fills, queue '
    'position and private notification timing are unobserved. Completed economics are conditional '
    'scenario results, never a guaranteed/executable profit bound or causal improvement over strict v1.'
    ' Changes combine deterministic clocks with ordered coverage checks, raw-anchor revision checks, '
    'native-ID evidence, and outer historical execution guards that still operate after an unrelated halt.'
)


def _scenario(selection):
    if selection not in SCENARIOS:
        raise ValueError('one explicit scenario base or plus200 required')
    return SCENARIOS[selection]


def scenario_plan(selection):
    scenario = _scenario(selection)
    delays = {}
    for tier in original.TIERS:
        config = original.Config('BTC', 1000, 'fixed_best', tier=tier)
        delays[tier] = {
            'maker_latency_ns': config.maker_latency_ns + scenario.additional_maker_latency_ns,
            'cancel_latency_ns': config.cancel_latency_ns + scenario.additional_cancel_latency_ns,
            'inherited_rh_taker_latency_ns': config.rh_taker_latency_ns,
            'inherited_hl_ioc_latency_ns': config.hl_ioc_latency_ns,
        }
    return {'selection': selection, **asdict(scenario), 'effective_delays_by_tier': delays,
            'execution_assumed': True, 'private_ack_observed': False, 'actual_fills_observed': False,
            'native_trade_ids_stable_across_generations_assumed': True,
            'activation_clock': 'request receipt + assumed maker latency; preceding raw RH anchor only',
            'cancel_clock': 'cancel request + assumed cancel latency; cancel source-time ties unknown',
            'processing_clock': 'timer effective time and processed public receipt remain separate',
            'notification_clock': 'public trade receipt starts inherited hedge/contingent-buy latency',
            'assumptions': list(ack.ASSUMPTIONS)}


def source_snapshot(protocol):
    if set(protocol.get('source_sha256', {})) != set(original.REQUIRED_SOURCES):
        raise ValueError('original 18-source inventory required')
    hashes, total = {}, 0
    for name in ACTUAL_DEPENDENCIES:
        path = original._source_path(name)
        size = path.stat().st_size
        total += size
        if size > MAX_SOURCE_BYTES or total > MAX_SOURCE_TOTAL_BYTES:
            raise ValueError('implementation source read cap exceeded')
        hashes[name] = original.digest(path)
        if name in protocol['source_sha256'] and hashes[name] != protocol['source_sha256'][name]:
            raise ValueError(f'original source hash mismatch: {name}')
    if hashes['scripts/rh_passive_ack_scenarios.py'] != LOADED_ACK_SHA256:
        raise ValueError('ACK source changed since import; start a fresh isolated process')
    return hashes


def _readout_references(strict_path, corrected_path, capture, protocol, manifest_hash, raw_hash):
    # Completion gates precede raw hash/read/replay in the production path.
    strict = original._bounded_json(strict_path, original.SUMMARY_CAP)
    corrected = original._bounded_json(corrected_path, original.SUMMARY_CAP)
    for result, schema in ((strict, original.RESULT_SCHEMA), (corrected, CORRECTED_SCHEMA)):
        if (result.get('schema') != schema or result.get('status') != 'complete'
                or result.get('errors') != [] or result.get('event_source') != 'verified_capture'
                or not isinstance(result.get('capture'), str)
                or Path(result['capture']).resolve() != capture.resolve()
                or result.get('capture_manifest_sha256') != manifest_hash
                or result.get('raw_sha256') != raw_hash
                or result.get('source_sha256') != protocol['source_sha256']
                or result.get('metadata_normalized_sha256') != protocol['metadata_normalized_sha256']):
            raise ValueError('completed strict/corrected readout reference provenance mismatch')
        terminal = result.get('terminal_event') or {}
        if (terminal.get('type') != 'end' or terminal.get('truncated') is not False
                or terminal.get('raw_sha_verified') is not True
                or terminal.get('raw_gzip_sha256') != raw_hash
                or terminal.get('manifest_sha256') != manifest_hash):
            raise ValueError('reference terminal hash/coverage mismatch')
    if strict.get('protocol_sha256') != corrected.get('protocol_sha256'):
        raise ValueError('reference protocol hash mismatch')
    if (corrected.get('implementation_variant') != 'entry-same-receipt-retirement-corrected-v1'
            or corrected.get('original_frozen_v1_result') is not False
            or corrected.get('original_result_schema') != original.RESULT_SCHEMA):
        raise ValueError('retirement-corrected reference variant required')
    extra = corrected.get('source_sha256_extra')
    if not isinstance(extra, dict) or set(extra) != set(CORRECTED_EXTRA):
        raise ValueError('reference frozen 20-source inventory required')
    for name in CORRECTED_EXTRA:
        if original.digest(original._source_path(name)) != extra[name]:
            raise ValueError('reference correction source hash mismatch')
    for field in ('started_ns', 'cutoff_ns', 'ended_ns', 'entry_admission_end_ns', 'intended_end_ns',
                  'assumptions', 'metadata', 'models'):
        if field not in strict or strict[field] != corrected.get(field):
            raise ValueError(f'reference timeline/economic assumptions mismatch: {field}')
    return {'strict_analysis': str(strict_path), 'strict_analysis_sha256': original.digest(Path(strict_path)),
            'corrected_analysis': str(corrected_path), 'corrected_analysis_sha256': original.digest(Path(corrected_path)),
            'readouts_are_references_not_ack_authorization': True}, strict


def verify_inputs(capture, protocol_path, strict_path, corrected_path):
    # A missing completed readout refuses before touching the capture.
    for path in (strict_path, corrected_path):
        readout = original._bounded_json(path, original.SUMMARY_CAP)
        if readout.get('status') != 'complete' or readout.get('event_source') != 'verified_capture' or readout.get('errors') != []:
            raise ValueError('completed verified strict/corrected readouts required before capture access')
    protocol, manifest, start, cutoff, stop = original.verify_protocol(protocol_path, capture)
    intended_end = start + 3000 * original.NS
    if (manifest.get('end_reason') != 'duration_limit' or manifest.get('truncated')
            or stop != intended_end):
        raise ValueError('completed duration-limit capture required')
    manifest_hash = original.digest(capture / 'manifest.json')
    raw_hash = manifest.get('frames_sha256')
    if (not isinstance(raw_hash, str) or len(raw_hash) != 64
            or any(c not in '0123456789abcdef' for c in raw_hash)):
        raise ValueError('stopped capture raw SHA-256 required')
    references, strict = _readout_references(strict_path, corrected_path, capture, protocol, manifest_hash, raw_hash)
    protocol_hash = original.digest(protocol_path)
    if strict['protocol_sha256'] != protocol_hash:
        raise ValueError('actual original protocol SHA-256 mismatch')
    expected_times = {'started_ns': start, 'cutoff_ns': cutoff, 'ended_ns': stop,
                      'entry_admission_end_ns': start + 2920 * original.NS, 'intended_end_ns': intended_end}
    if any(strict.get(k) != v for k, v in expected_times.items()):
        raise ValueError('readout timeline differs from stopped capture')
    archive_bytes = _archive_size(capture, original.RAW_CAP)
    if original.digest(capture / 'frames.jsonl.gz') != raw_hash:
        raise ValueError('actual stopped capture raw SHA-256 mismatch')
    return protocol, {'protocol_sha256': protocol_hash, 'capture_manifest_sha256': manifest_hash,
                      'raw_sha256': raw_hash, 'metadata_normalized_sha256': protocol['metadata_normalized_sha256'],
                      'archive_bytes': archive_bytes, 'readout_references': references, **expected_times}


@contextmanager
def scenario_branch_binding(selection):
    """Process-global factory binding; run one scenario per isolated process."""
    scenario = _scenario(selection)
    if engine.PassiveExitBranch is not ORIGINAL_CLASS:
        raise RuntimeError('passive branch factory already overridden')
    def scenario_factory(config, metadata, **kwargs):
        return ack.AssumedAckPassiveExitBranch(config, metadata, scenario=scenario, **kwargs)
    engine.PassiveExitBranch = scenario_factory
    try:
        yield
    finally:
        engine.PassiveExitBranch = ORIGINAL_CLASS


def _check_output(out, capture, protocol_path, strict_path, corrected_path):
    target = out.resolve()
    protected = (capture.resolve(), protocol_path.parent.resolve(), strict_path.parent.resolve(), corrected_path.parent.resolve())
    if any(target == path or target.is_relative_to(path) or path.is_relative_to(target) for path in protected):
        raise ValueError('exploratory output overlaps source or original strict/corrected artifacts')
    if out.exists() or out.is_symlink():
        raise ValueError('exploratory output must be a new directory')


def _validate_variant_result(result, selection):
    scenario = _scenario(selection)
    if (result.get('status') != 'complete' or result.get('errors') != []
            or result.get('schema') != original.RESULT_SCHEMA
            or result.get('event_source') != 'verified_capture'):
        raise ValueError('complete exploratory coordinator replay required for publication')
    terminal = result.get('terminal_event') or {}
    if (terminal.get('type') != 'end' or terminal.get('truncated') is not False
            or terminal.get('raw_sha_verified') is not True
            or terminal.get('raw_gzip_sha256') != result.get('raw_sha256')
            or terminal.get('manifest_sha256') != result.get('capture_manifest_sha256')):
        raise ValueError('exploratory verified terminal hash/coverage required')
    expected = set(itertools.product(original.TIERS, original.ASSETS, original.SIZES, original.POLICIES))
    branches = result.get('branches')
    if not isinstance(branches, list) or len(branches) != 128:
        raise ValueError('all 128 independent scenario branches required')
    seen = set()
    plan = scenario_plan(selection)
    for branch in branches:
        key = (branch.get('tier'), branch.get('asset'), int(branch.get('budget_usd')), branch.get('exit_policy'))
        if key not in expected or key in seen:
            raise ValueError('scenario branch universe mismatch')
        seen.add(key)
        labels = {'scenario_id': scenario.scenario_id, 'execution_assumed': True,
                  'private_ack_observed': False, 'native_trade_ids_stable_across_generations_assumed': True,
                  'assumed_maker_latency_ns': plan['effective_delays_by_tier'][key[0]]['maker_latency_ns'],
                  'assumed_cancel_latency_ns': plan['effective_delays_by_tier'][key[0]]['cancel_latency_ns']}
        if (branch.get('schema') != 'rh-passive-assumed-ack-scenario-v1'
                or branch.get('actual_fills_observed') is not False
                or branch.get('guaranteed_profit_bound') is not False
                or any(branch.get(k) != v for k, v in labels.items())):
            raise ValueError('actual scenario factory/ACK branch labels mismatch')
        for episode in branch.get('episodes', []):
            if any(episode.get(k) != v for k, v in labels.items()):
                raise ValueError('episode ACK scenario labels mismatch')
    return plan


def exploratory_report(result):
    body = original._report(result)
    body = '# EXPLORATORY POST-CAPTURE ACK model replay' + body[body.index('\n'):]
    disclosure = '\n\n' + DISCLOSURE + '\n\n'
    plan = result['ack_scenario']
    delays = '; '.join(f"{tier}: maker {clock['maker_latency_ns']} ns, cancel {clock['cancel_latency_ns']} ns"
                       for tier, clock in plan['effective_delays_by_tier'].items())
    disclosure += (f"Selected scenario: `{plan['selection']}` (`{plan['scenario_id']}`). {delays}. "
                   'Every branch remains independent; correlated branch nets are never summed. '
                   'Changed fills or admission histories are sensitivity diagnostics. '
                   'Unknown execution, funding, or obligations retain unknown net.\n\n')
    return body.replace('\n', disclosure, 1)


def replay_exploratory(capture, out, protocol_path, *, selection, strict_path=DEFAULT_STRICT,
                       corrected_path=DEFAULT_CORRECTED, events=None):
    capture, out, protocol_path, strict_path, corrected_path = map(
        Path, (capture, out, protocol_path, strict_path, corrected_path))
    _scenario(selection)
    if events is not None:
        raise ValueError('injected events cannot publish an exploratory capture result')
    _check_output(out, capture, protocol_path, strict_path, corrected_path)
    protocol, provenance = verify_inputs(capture, protocol_path, strict_path, corrected_path)
    sources_before = source_snapshot(protocol)
    snapshot_time = datetime.now(timezone.utc).isoformat()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.ack-exploratory-', dir=out.parent) as scratch:
        staged = Path(scratch) / 'result'
        with scenario_branch_binding(selection):
            result = original.replay(capture, staged, protocol_path)
        plan = _validate_variant_result(result, selection)
        _, provenance_after = verify_inputs(capture, protocol_path, strict_path, corrected_path)
        sources_after = source_snapshot(protocol)
        if sources_before != sources_after or provenance != provenance_after:
            raise ValueError('sources or stopped provenance changed during exploratory replay')
        for field in ('protocol_sha256', 'capture_manifest_sha256', 'raw_sha256', 'metadata_normalized_sha256',
                      'started_ns', 'cutoff_ns', 'ended_ns', 'entry_admission_end_ns', 'intended_end_ns'):
            if result.get(field) != provenance[field]:
                raise ValueError(f'exploratory result source/timeline mismatch: {field}')
        if (result.get('source_sha256') != protocol['source_sha256']
                or result.get('protocol_frozen_at') != protocol['frozen_at']):
            raise ValueError('exploratory original source inventory mismatch')
        inherited_assumptions = result.get('assumptions')
        if not isinstance(inherited_assumptions, dict):
            raise ValueError('inherited coordinator economic assumptions required')
        active_assumptions = {**inherited_assumptions,
                              'timing': 'deterministic assumed private ACK clocks; previous received raw anchor; public trade receipt notification model'}
        result.update({
            'schema': SCHEMA, 'original_result_schema': original.RESULT_SCHEMA,
            'implementation_variant': VARIANT, 'study_classification': CLASSIFICATION,
            'original_frozen_v1_result': False, 'retirement_corrected_v1_result': False,
            'prospective_result': False, 'pre_holdout_freeze_claimed': False,
            'runtime_factory_override': {**RUNTIME_FACTORY, 'scenario_selection': selection,
                                         'scenario_id': plan['scenario_id']},
            'ack_scenario': plan, 'execution_assumed': True, 'private_ack_observed': False,
            'original_coordinator_assumptions': inherited_assumptions,
            'assumptions': active_assumptions,
            'active_ack_execution_assumptions': plan,
            'combined_model_changes': ['deterministic maker/cancel ACK clocks',
                                       'ordered obligation coverage checks',
                                       'preceding raw-book anchor and late revision checks',
                                       'native trade-ID stability, dedupe, cap and conflict evidence',
                                       'outer historical execution evidence checks after earlier halt'],
            'actual_fills_observed': False, 'guaranteed_profit_bound': False,
            'native_trade_ids_stable_across_generations_assumed': True,
            'source_sha256_extra': {name: sources_before[name] for name in EXTRA_SOURCES},
            'actual_dependency_sha256_before': sources_before,
            'actual_dependency_sha256_after': sources_after,
            'source_snapshot_before_replay_utc': snapshot_time,
            'source_snapshots_are_not_prospective_freezes': True,
            'stopped_capture_provenance': provenance,
            'exploratory_disclosure': DISCLOSURE,
            'summed_branch_portfolio_net': None, 'causal_profit_improvement': None,
        })
        report = exploratory_report(result).encode()
        if len(report) > MAX_REPORT_BYTES:
            raise ValueError('exploratory report byte cap exceeded')
        original._write_json(staged / 'analysis.json', result, original.SUMMARY_CAP - len(report))
        (staged / 'REPORT.md').write_bytes(report)
        _check_output(out, capture, protocol_path, strict_path, corrected_path)
        staged.rename(out)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--scenario', choices=tuple(SCENARIOS))
    parser.add_argument('--capture', type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument('--protocol', type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument('--strict-analysis', type=Path, default=DEFAULT_STRICT)
    parser.add_argument('--corrected-analysis', type=Path, default=DEFAULT_CORRECTED)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    if not args.replay:
        selections = [args.scenario] if args.scenario else list(SCENARIOS)
        print(json.dumps({'dry_plan': True, 'study_classification': CLASSIFICATION,
                          'prospective_result': False, 'capture_read': False,
                          'scenarios': [scenario_plan(s) for s in selections],
                          'runtime_factory_override': RUNTIME_FACTORY,
                          'required_before_replay': 'completed same-capture strict and corrected readout references; explicit one scenario and new output',
                          'actual_dependencies_to_hash': list(ACTUAL_DEPENDENCIES),
                          'disclosure': DISCLOSURE}, indent=2))
        return 0
    if args.scenario is None or args.out is None:
        parser.error('--replay requires one --scenario and explicit --out')
    result = replay_exploratory(args.capture, args.out, args.protocol, selection=args.scenario,
                               strict_path=args.strict_analysis, corrected_path=args.corrected_analysis)
    print(json.dumps({'out': str(args.out), 'status': result['status'], 'schema': result['schema'],
                      'study_classification': CLASSIFICATION, 'scenario': args.scenario}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
