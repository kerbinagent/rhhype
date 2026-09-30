#!/usr/bin/env python3
"""Prospective, stopped-capture RH passive-exit public-flow replay.

Every branch is an independent counterfactual ledger. No private maker fill,
real order, collateral conversion, or production policy is inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.maker_capture import BoundedGzip, SizeCapReached
from scripts.rh_maker_config import ASSETS, SIZES, ASSUMPTIONS, policy_metadata
from scripts.rh_maker_engine import Config
from scripts.rh_maker_events import iter_events, _epoch_ns
from scripts.rh_maker_model import RhMakerModel
from scripts.rh_maker_sell_model import RhMakerSellModel

NS = 1_000_000_000
SCHEMA = 'rh-passive-exit-protocol-v1'
RESULT_SCHEMA = 'rh-passive-exit-replay-v1'
POLICIES = ('control10s', 'passive_best10s', 'passive_target10s', 'passive_target60s')
TIERS = ('standard', 'premium')
RAW_CAP = 384_000_000
AUDIT_CAP = 96_000_000
SUMMARY_CAP = 32_000_000
MAX_COHORTS = 20_000
METHOD = 'research/rh-passive-exit-method.md'
REQUIRED_SOURCES = (
    'scripts/analyze_rh_passive_exit.py',
    'scripts/rh_passive_exit_engine.py',
    'scripts/rh_passive_exit_cache.py',
    'scripts/rh_maker_engine.py',
    'scripts/rh_maker_sell_engine.py',
    'scripts/rh_maker_late_flow_guard.py',
    'scripts/rh_maker_model.py',
    'scripts/rh_maker_sell_model.py',
    'scripts/rh_maker_config.py',
    'scripts/rh_maker_events.py',
    'scripts/rh_maker_capture.py',
    'scripts/maker_book_archive.py',
    'scripts/maker_capture.py',
    'scripts/paper_streams.py',
    'scripts/analyze_maker_equity.py',
    'scripts/analyze_maker_capture.py',
    'scripts/analyze_maker_roundtrip.py',
    METHOD,
)


def digest(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _bounded_json(path: Path, cap: int = 1_000_000) -> dict:
    path = Path(path)
    if path.stat().st_size > cap:
        raise ValueError(f'oversized JSON: {path.name}')
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError('JSON object required')
    return value


def _utc_ns(value: str) -> int:
    if not isinstance(value, str):
        raise ValueError('UTC timestamp text required')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError('UTC timestamp with offset required')
    return _epoch_ns(value)


def _source_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError(f'invalid protocol source: {relative}')
    return path


def build_protocol(frozen_at: str, metadata_dir: Path) -> dict:
    """Create reviewable hashes; the caller writes the object before capture."""
    _utc_ns(frozen_at)
    return {'schema': SCHEMA, 'frozen_at': frozen_at,
            'source_sha256': {name: digest(_source_path(name)) for name in REQUIRED_SOURCES},
            'metadata_normalized_sha256': digest(Path(metadata_dir) / 'normalized.json'),
            'timeline_seconds': {'calibration': 1800, 'holdout': 1200,
                                 'entry_admission': 1120, 'washout': 80},
            'policies': list(POLICIES), 'tiers': list(TIERS),
            'assets': list(ASSETS), 'budgets_usd': list(SIZES),
            'primary': {'tier': 'standard', 'asset': 'XAG', 'budget_usd': 1000,
                        'treatment': 'passive_target10s', 'control': 'control10s'}}


def verify_protocol(protocol_path: Path, capture: Path) -> tuple[dict, dict, int, int, int]:
    protocol = _bounded_json(protocol_path)
    if protocol.get('schema') != SCHEMA or protocol.get('source_sha256') is None:
        raise ValueError('frozen passive-exit protocol required')
    frozen_ns = _utc_ns(protocol.get('frozen_at'))
    expected = protocol['source_sha256']
    if not isinstance(expected, dict) or set(expected) != set(REQUIRED_SOURCES):
        raise ValueError('incomplete source hash inventory')
    for name, claimed in expected.items():
        if not isinstance(claimed, str) or len(claimed) != 64 or digest(_source_path(name)) != claimed:
            raise ValueError(f'source hash mismatch: {name}')
    if protocol.get('timeline_seconds') != {'calibration': 1800, 'holdout': 1200,
                                            'entry_admission': 1120, 'washout': 80}:
        raise ValueError('timeline differs from protocol')
    if (protocol.get('policies'), protocol.get('tiers'), protocol.get('assets'),
            protocol.get('budgets_usd')) != (list(POLICIES), list(TIERS), list(ASSETS), list(SIZES)):
        raise ValueError('universe differs from protocol')
    if protocol.get('primary') != {'tier': 'standard', 'asset': 'XAG',
                                   'budget_usd': 1000,
                                   'treatment': 'passive_target10s',
                                   'control': 'control10s'}:
        raise ValueError('primary contrast differs from protocol')
    manifest = _bounded_json(Path(capture) / 'manifest.json')
    if manifest.get('schema') != 'rh-maker-public-capture-v1' or manifest.get('read_only') is not True:
        raise ValueError('stopped read-only maker capture required')
    if (manifest.get('configured_seconds'), manifest.get('calibration_seconds'),
            manifest.get('holdout_seconds')) != (3000, 1800, 1200):
        raise ValueError('capture timeline changed')
    budget = manifest.get('configured_total_bytes')
    if type(budget) is not int or not 0 < budget <= RAW_CAP:
        raise ValueError('capture raw byte cap changed')
    start, end = _utc_ns(manifest['started_utc']), _utc_ns(manifest['ended_utc'])
    if start < frozen_ns or end < start or end > start + 3001 * NS:
        raise ValueError('capture outside frozen timeline')
    meta_hash = digest(Path(capture) / 'metadata/normalized.json')
    if (meta_hash != protocol.get('metadata_normalized_sha256')
            or meta_hash != manifest.get('metadata_normalized_sha256')):
        raise ValueError('market metadata hash mismatch')
    return protocol, manifest, start, start + 1800 * NS, min(end, start + 3000 * NS)


def _decimal(value, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'invalid {label}') from None
    if not result.is_finite():
        raise ValueError(f'nonfinite {label}')
    return result


def _entry_signature(episode: dict) -> tuple[str, ...] | None:
    """Only compare episodes with a known, fully matched identical entry."""
    fields = ('entry_quote_price', 'entry_maker_qty', 'entry_rh_notional',
              'entry_hl_qty', 'entry_hl_notional', 'entry_rh_fee',
              'entry_hl_fee', 'first_full_hedge_ns')
    if any(episode.get(name) is None for name in fields):
        return None
    values = tuple(_decimal(episode[name], name) for name in fields[:-1])
    if any(value <= 0 for value in values[:5]) or any(value < 0 for value in values[5:]):
        return None
    price, maker_qty, rh_notional, hl_qty, _, _, _ = values
    if maker_qty != hl_qty or abs(rh_notional - maker_qty * price) > Decimal('0.00000001'):
        return None
    first = _decimal(episode[fields[-1]], fields[-1])
    if first <= 0 or first != first.to_integral_value():
        return None
    return tuple(str(value.normalize()) for value in values) + (str(int(first)),)


def _complete_net(episode: dict) -> Decimal | None:
    if episode.get('funding_unknown') or episode.get('execution_unknown'):
        return None
    cash = _decimal(episode['cash_known'], 'episode cash')
    if episode.get('fee_only_net') is not None and abs(cash - _decimal(episode['fee_only_net'], 'fee-only net')) > Decimal('0.000001'):
        raise ValueError('episode fee-only identity mismatch')
    reserve = _decimal(episode['reserve_cost'], 'episode reserve')
    capital = _decimal(episode['capital_cost'], 'episode capital')
    if reserve < 0 or capital < 0:
        raise ValueError('negative reserve or capital')
    net = cash - reserve - capital
    if episode.get('stressed_net') is not None and abs(net - _decimal(episode['stressed_net'], 'stressed net')) > Decimal('0.000001'):
        raise ValueError('episode net identity mismatch')
    return net


def _funding_entry_blocked(now_ns: int) -> bool:
    # UTC hourly funding is a conservative scheduling proxy, not funding cash.
    offset = now_ns % (3600 * NS)
    return offset >= (3600 - 80) * NS or offset < 2 * NS


def _group_flat(branches: list) -> bool:
    return all(b.quote is None and b.rh_pos == 0 and b.hl_pos == 0
               and not b.hedges and not b.exits and not b.unknown_reason
               and b.passive_ask is None and not b.passive_buys
               and b.fallback_requested_ns is None
               for b in branches)


def score_cohorts(cohorts: list[dict], branches: list[dict], opportunity_counts: dict) -> dict:
    """Pair only identical known full entries; preserve all candidate denominators."""
    if len(cohorts) > MAX_COHORTS:
        raise ValueError('cohort retention cap')
    episodes: dict[tuple, dict] = {}
    branch_totals = {}
    all_closed = defaultdict(lambda: {'episodes': 0, 'known': 0, 'unknown': 0,
                                       'known_with_flow': 0,
                                       'known_without_full_hedge': 0,
                                       'fee_only_usd': Decimal(0),
                                       'after_reserve_capital_usd': Decimal(0)})
    for branch in branches:
        key = (branch['tier'], branch['asset'], int(branch['budget_usd']), branch['exit_policy'])
        branch_totals[key] = branch.get('complete_net')
        all_closed[key]  # Show all independent ledgers, including zero-episode branches.
        for episode in branch['episodes']:
            cohort_id = episode.get('cohort_id')
            if cohort_id is None:
                raise ValueError('completed episode lacks cohort_id')
            epkey = (*key, cohort_id)
            if epkey in episodes:
                raise ValueError('duplicate cohort episode')
            episodes[epkey] = episode
            state = all_closed[key]
            state['episodes'] += 1
            net = _complete_net(episode)
            if net is None:
                state['unknown'] += 1
            else:
                state['known'] += 1
                if _decimal(episode['maker_attributed'], 'maker attributed') > 0:
                    state['known_with_flow'] += 1
                    if episode.get('first_full_hedge_ns') is None:
                        state['known_without_full_hedge'] += 1
                state['fee_only_usd'] += _decimal(episode['cash_known'], 'episode cash')
                state['after_reserve_capital_usd'] += net
    outcomes = Counter()
    paired = defaultdict(list)
    primary_diffs = []
    seen_cohort_keys = set()
    for cohort in cohorts:
        key = (cohort['tier'], cohort['asset'], int(cohort['budget_usd']))
        identifier = cohort['cohort_id']
        if not isinstance(identifier, str) or not identifier:
            raise ValueError('invalid cohort_id')
        if (*key, identifier) in seen_cohort_keys:
            raise ValueError('duplicate cohort row')
        seen_cohort_keys.add((*key, identifier))
        per = {}
        for policy in POLICIES:
            admitted = bool(cohort['admitted'].get(policy))
            episode = episodes.get((*key, policy, identifier))
            if episode is not None and not admitted:
                raise ValueError('episode for unadmitted branch')
            if not admitted:
                outcomes[f'{policy}:abstained'] += 1
                continue
            if episode is None:
                outcomes[f'{policy}:unsettled_or_unknown'] += 1
                continue
            net = _complete_net(episode)
            if net is None:
                outcomes[f'{policy}:funding_or_execution_unknown'] += 1
                continue
            sig = _entry_signature(episode)
            if sig is None:
                outcomes[f'{policy}:no_full_matched_entry'] += 1
                continue
            outcomes[f'{policy}:known_complete_matched_entry'] += 1
            per[policy] = (net, sig)
        for treatment, control in (('passive_target10s', 'control10s'),
                                   ('passive_best10s', 'control10s'),
                                   ('passive_target60s', 'passive_target10s')):
            label = f'{treatment}_vs_{control}'
            if treatment not in per or control not in per:
                outcomes[f'{label}:not_paired'] += 1
                continue
            if per[treatment][1] != per[control][1]:
                outcomes[f'{label}:entry_mismatch'] += 1
                continue
            diff = per[treatment][0] - per[control][0]
            paired[(key, label)].append(diff)
            outcomes[f'{label}:paired_complete'] += 1
            if key == ('standard', 'XAG', 1000) and label == 'passive_target10s_vs_control10s':
                primary_diffs.append(diff)
    if any((tier, asset, size, identifier) not in seen_cohort_keys
           for tier, asset, size, _, identifier in episodes):
        raise ValueError('episode omitted from cohort export')
    def stat(values):
        if not values:
            return {'n': 0, 'mean_usd': None, 'median_usd': None,
                    'positive': 0, 'sum_usd': None}
        ordered = sorted(values)
        middle = len(ordered) // 2
        median = ordered[middle] if len(ordered) % 2 else (ordered[middle-1]+ordered[middle])/2
        return {'n': len(values), 'mean_usd': str(sum(values) / len(values)),
                'median_usd': str(median), 'positive': sum(v > 0 for v in values),
                'sum_usd': str(sum(values))}
    return {'retained_cohorts': len(cohorts), 'opportunity_counts': dict(opportunity_counts),
            'cohort_status_counts': dict(outcomes),
            'all_admitted_closed_by_branch': [
                {'tier': key[0], 'asset': key[1], 'budget_usd': key[2],
                 'exit_policy': key[3], 'episodes': state['episodes'],
                 'known': state['known'], 'unknown': state['unknown'],
                 'known_with_flow': state['known_with_flow'],
                 'known_without_full_hedge': state['known_without_full_hedge'],
                 'known_closed_fee_only_contribution_usd': str(state['fee_only_usd']),
                 'known_closed_after_reserve_capital_contribution_usd': str(state['after_reserve_capital_usd']),
                 'total_branch_result_usd': branch_totals[key]}
                for key, state in sorted(all_closed.items())],
            'primary_standard_xag_1000_target10_vs_control10': stat(primary_diffs),
            'paired_by_group': [dict(tier=key[0][0], asset=key[0][1], budget_usd=key[0][2],
                                     contrast=key[1], **stat(values))
                                for key, values in sorted(paired.items())],
            'limitations': ['Only same-entry known-complete episodes enter paired cash comparisons.',
                            'Unsettled, funding-unknown, and execution-unknown paths have unknown net.',
                            'Public flow is conditional queue attribution, not private fills.',
                            'Counterfactual portfolios share events and must not be summed.']}


def _write_json(path: Path, value: dict, cap: int) -> None:
    body = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(body) > cap:
        raise ValueError('derived JSON byte cap exceeded')
    path.write_bytes(body)


def _report(result: dict) -> str:
    score = result['cohort_score']
    primary = score['primary_standard_xag_1000_target10_vs_control10']
    return '\n'.join([
        '# RH passive-exit public-flow replay', '',
        f"Status: **{result['status']}**; {len(result['branches'])} independent branches.",
        f"Original fixed-best opportunities: {score['opportunity_counts'].get('fixed_best_quote_checks', 0)} book-event checks; "
        f"retained admitted cohorts: {score['retained_cohorts']}.",
        f"Primary Standard XAG/$1,000 same-entry complete pairs: {primary['n']}; "
        f"mean treatment minus control: {primary['mean_usd']} USD conditional on parity.", '',
        'The primary contrast is descriptive and excludes no-flow, unsettled,',
        'funding-unknown, and mismatched-entry cohorts from paired cash. Their',
        'counts remain in analysis.json. Neither public trade-through nor a',
        'displayed book establishes a private fill or executable conversion.',
        'The final 80 seconds of the 20-minute holdout admit no new entries.',
        'Unknown terminal inventory is not assigned a zero result.', ''
    ])


def replay(capture: Path, out: Path, protocol_path: Path, *, events=None) -> dict:
    """Replay one verified future capture; explicit events are test injection."""
    # Import the new policy and cache only when replay is requested. This lets
    # the pure protocol/scoring tests run while a separate agent edits the engine.
    from scripts.rh_passive_exit_engine import PassiveExitBranch
    from scripts.rh_passive_exit_cache import cached_event_parses

    capture, out = Path(capture), Path(out)
    protocol, manifest, start, cutoff, stop = verify_protocol(protocol_path, capture)
    if out.exists():
        raise ValueError('output must be a new directory')
    out.mkdir(parents=True)
    audit = BoundedGzip(out / 'audit.jsonl.gz', AUDIT_CAP, reserve=1024)
    metadata = {tier: policy_metadata(capture / 'metadata', tier) for tier in TIERS}
    buy_models = {tier: RhMakerModel(metadata[tier], start) for tier in TIERS}
    sell_models = {tier: RhMakerSellModel(metadata[tier], start) for tier in TIERS}
    groups = {}
    cohorts = []
    counts, errors = Counter(), []
    group_counts = defaultdict(Counter)
    first_unknown, first_quote_request = {}, {}
    terminal = None
    status = 'complete'
    intended_end = start + 3000 * NS
    admit_end = start + 2920 * NS
    started_wall = time.monotonic()
    def make_groups():
        for tier in TIERS:
            fit = sell_models[tier].fit
            if fit is None:
                raise ValueError('sell adverse model did not freeze')
            for asset in ASSETS:
                for budget in SIZES:
                    route = fit['routes'][f'{asset}|{budget}']
                    adverse = route['adverse_p75_bps'] if route['flow_ready'] else None
                    branches = {}
                    for policy in POLICIES:
                        cfg = Config(asset, Decimal(budget), 'fixed_best', tier=tier,
                                     hold_ns=(60 if policy == 'passive_target60s' else 10) * NS)
                        identity = {'tier': tier, 'asset': asset, 'budget_usd': budget,
                                    'exit_policy': policy}
                        def sink(row, ident=identity):
                            audit.write(dict(row, **ident))
                            ident_key = (ident['tier'], ident['asset'], ident['budget_usd'], ident['exit_policy'])
                            if row.get('event') == 'unknown':
                                first_unknown.setdefault(ident_key, int(row['ns']))
                            elif row.get('event') == 'quote_requested':
                                first_quote_request.setdefault(ident_key, int(row['ns']))
                        branches[policy] = PassiveExitBranch(cfg, metadata[tier][asset],
                                        exit_policy=policy, exit_adverse_bps=adverse,
                                        audit_sink=sink)
                    groups[(tier, asset, budget)] = (branches, adverse)

    try:
        stream = iter_events(capture, max_raw_bytes=RAW_CAP) if events is None else events
        with cached_event_parses() as (cache_stats, next_event):
            for event in stream:
                next_event()
                kind = event.get('type', event.get('kind'))
                now = int(event.get('received_ns', event.get('receipt_ns', stop)))
                if kind == 'end':
                    terminal = event
                    break
                if now > intended_end:
                    continue
                counts[f'event:{kind}'] += 1
                for model in buy_models.values():
                    model.consume(event)
                for model in sell_models.values():
                    model.consume(event)
                if now < cutoff:
                    continue
                if not groups:
                    make_groups()
                asset = event.get('asset')
                target_groups = [(key, value) for key, value in groups.items()
                                 if asset is None or key[1] == asset]
                for (tier, group_asset, budget), (branches, adverse) in target_groups:
                    diag = None
                    if kind == 'book' and event.get('valid', True):
                        diag = buy_models[tier].quote(group_asset, budget, 'fixed_best', now_ns=now)
                    if diag is not None and diag.get('reason') == 'quote':
                        counts['fixed_best_quote_checks'] += 1
                        group_counts[(tier, group_asset, budget)]['fixed_best_quote_checks'] += 1
                        if now >= admit_end:
                            counts['washout_blocked'] += 1
                            group_counts[(tier, group_asset, budget)]['washout_blocked'] += 1
                            diag = None
                        elif _funding_entry_blocked(now):
                            counts['funding_window_blocked'] += 1
                            group_counts[(tier, group_asset, budget)]['funding_window_blocked'] += 1
                            diag = None
                        elif not _group_flat(list(branches.values())):
                            counts['group_busy'] += 1
                            group_counts[(tier, group_asset, budget)]['group_busy'] += 1
                            diag = None
                        elif len(cohorts) >= MAX_COHORTS:
                            raise ValueError('cohort retention cap reached')
                        else:
                            counts['group_admission_attempts'] += 1
                            group_counts[(tier, group_asset, budget)]['group_admission_attempts'] += 1
                            cohort_id = f'{group_asset}:{budget}:{tier}:{now}'
                            if any(c['cohort_id'] == cohort_id for c in cohorts[-32:]):
                                raise ValueError('duplicate cohort decision timestamp')
                            admitted = {}
                            for policy, branch in branches.items():
                                allowed = policy not in ('passive_target10s', 'passive_target60s') or adverse is not None
                                branch.process(event, quote_diag=diag if allowed else None)
                                admitted[policy] = bool(branch.quote is not None and branch.quote.decided_ns == now)
                                if not allowed:
                                    counts['target_model_unready'] += 1
                            if any(admitted.values()):
                                cohorts.append({'cohort_id': cohort_id, 'tier': tier,
                                                'asset': group_asset, 'budget_usd': budget,
                                                'decision_ns': now, 'admitted': admitted})
                            else:
                                counts['group_all_branches_abstained'] += 1
                                group_counts[(tier, group_asset, budget)]['group_all_branches_abstained'] += 1
                            continue
                    for branch in branches.values():
                        branch.process(event, quote_diag=None)
            cache_summary = dict(cache_stats)
        if terminal is None:
            status = 'missing_terminal_event'
        elif terminal.get('truncated') or manifest.get('end_reason') != 'duration_limit' or stop < intended_end:
            status = 'capture_incomplete'
        for branches, _ in groups.values():
            for branch in branches.values():
                branch.tick(stop)
                branch.process({'type': 'end', 'received_ns': stop,
                                'truncated': status != 'complete'})
    except (ValueError, KeyError, TypeError, ArithmeticError, OSError, SizeCapReached) as exc:
        status = 'audit_size_cap' if isinstance(exc, SizeCapReached) else 'replay_error'
        errors.append(f'{type(exc).__name__}: {str(exc)[:500]}')
        cache_summary = locals().get('cache_summary', {})
        for branches, _ in groups.values():
            for branch in branches.values():
                branch.truncated = True
                if branch.unknown_reason is None:
                    branch.unknown_reason = status
    finally:
        audit.close()
    summaries = []
    for branches, _ in groups.values():
        for policy, branch in branches.items():
            row = branch.summary()
            row['exit_policy'] = policy
            bkey = (branch.cfg.tier, branch.cfg.asset, int(branch.cfg.budget_usd), policy)
            row['first_unknown_ns'] = first_unknown.get(bkey)
            row['first_quote_requested_ns'] = first_quote_request.get(bkey)
            row['effective_quote_opportunity_seconds_before_unknown'] = (
                0 if bkey not in first_quote_request else
                max(0, (min(first_unknown.get(bkey, stop), stop) - first_quote_request[bkey]) / NS))
            row['group_book_quote_checks'] = group_counts[(branch.cfg.tier,
                                                            branch.cfg.asset,
                                                            int(branch.cfg.budget_usd))]['fixed_best_quote_checks']
            row.pop('audit', None)
            summaries.append(row)
    score = score_cohorts(cohorts, summaries, counts)
    result = {'schema': RESULT_SCHEMA, 'status': status, 'errors': errors,
              'event_source': 'verified_capture' if events is None else 'injected_test_events',
              'capture': str(capture), 'capture_manifest_sha256': digest(capture / 'manifest.json'),
              'raw_sha256': manifest.get('frames_sha256'),
              'protocol_sha256': digest(Path(protocol_path)),
              'protocol_frozen_at': protocol['frozen_at'],
              'source_sha256': protocol['source_sha256'],
              'metadata_normalized_sha256': protocol['metadata_normalized_sha256'],
              'started_ns': start, 'cutoff_ns': cutoff, 'entry_admission_end_ns': admit_end,
              'ended_ns': stop, 'intended_end_ns': intended_end,
              'counts': dict(counts), 'terminal_event': terminal,
              'models': {'entry_fixed_best': {tier: model.snapshot() for tier, model in buy_models.items()},
                         'exit_adverse': {tier: model.snapshot() for tier, model in sell_models.items()}},
              'branches': summaries, 'cohorts': cohorts, 'cohort_score': score,
              'assumptions': ASSUMPTIONS, 'metadata': metadata,
              'cache': cache_summary, 'audit_bytes': audit.bytes_written,
              'audit_records': audit.records,
              'audit_sha256': digest(out / 'audit.jsonl.gz'),
              'replay_wall_seconds': time.monotonic() - started_wall}
    report = _report(result).encode()
    if len(report) > 1_000_000:
        raise ValueError('report byte cap')
    _write_json(out / 'analysis.json', result, SUMMARY_CAP - len(report))
    (out / 'REPORT.md').write_bytes(report)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    freeze = sub.add_parser('freeze', help='write source-hashed protocol before capture')
    freeze.add_argument('--metadata-dir', type=Path, required=True)
    freeze.add_argument('--frozen-at', required=True, help='UTC ISO8601 timestamp')
    freeze.add_argument('--out', type=Path, required=True)
    run = sub.add_parser('replay', help='replay a stopped capture')
    run.add_argument('--capture', type=Path, required=True)
    run.add_argument('--out', type=Path, required=True)
    run.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'freeze':
        if args.out.exists():
            raise ValueError('protocol output already exists')
        protocol = build_protocol(args.frozen_at, args.metadata_dir)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        _write_json(args.out, protocol, 1_000_000)
        print(json.dumps({'protocol': str(args.out), 'schema': SCHEMA}))
        return 0
    result = replay(args.capture, args.out, args.protocol)
    print(json.dumps({'out': str(args.out), 'status': result['status'],
                      'branches': len(result['branches']), 'errors': result['errors']}))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
