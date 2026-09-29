#!/usr/bin/env python3
"""Read-only, bounded adjudication of late public flow after retired RH maker bids.

This is an independent ambiguity check on a stopped, frozen buy-side replay.
It does not infer an actual order, fill, revised P&L, or queue position.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.rh_maker_events import iter_events

FREEZE = ROOT / 'reports/rh-small-maker-v1/implementation-freeze.json'
WRAPPER = 'scripts/optimized_rh_maker_replay.py'
CACHED_VARIANT = 'postfreeze_book_parse_cache'
ORIGINAL_SOURCE_KEYS = frozenset((
    'scripts/analyze_rh_maker.py', 'scripts/rh_maker_config.py',
    'scripts/rh_maker_engine.py', 'scripts/rh_maker_model.py',
    'scripts/rh_maker_events.py', 'scripts/maker_book_archive.py',
    'scripts/paper_streams.py', 'scripts/maker_capture.py',
    'scripts/rh_maker_capture.py', 'reports/rh-small-maker-v1/method.md',
    'reports/rh-small-maker-v1/capture-freeze.json',
    'reports/rh-small-maker-v1/launch.json',
))
MAX_ANALYSIS = 32_000_000
MAX_AUDIT = 96_000_000
MAX_DECODED = 1_000_000_000
MAX_RECORDS = 2_000_000
MAX_LINE = 1_000_000
MAX_BRANCHES = 96
MAX_EPISODES_PER_BRANCH = 1024
MAX_TOMBSTONES = MAX_BRANCHES * MAX_EPISODES_PER_BRANCH
MAX_INTERVAL_NS = 10_000_000_000
MAX_FLAG_DETAILS = 4096
MAX_OUTPUT = 8_000_000


def sha256(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bounded_json(path: Path, cap: int) -> dict:
    if path.stat().st_size > cap:
        raise ValueError(f'oversized JSON: {path.name}')
    body = json.loads(path.read_bytes())
    if not isinstance(body, dict):
        raise ValueError(f'JSON object required: {path.name}')
    return body


def identity(row: dict) -> tuple[str, str, int, str]:
    return (str(row['tier']), str(row['asset']), int(row['budget_usd']), str(row['policy']))


def _positive(value, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f'invalid {name}') from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f'nonpositive or nonfinite {name}')
    return number


def verify_variant(analysis: dict, derived: Path, frozen_files: dict) -> dict:
    """Keep the frozen primary and post-freeze cache provenance distinct."""
    sources = analysis['source_sha256']
    variant = analysis.get('implementation_variant')
    provenance_path = derived / 'optimization_provenance.json'
    if variant is None:
        if provenance_path.exists() or WRAPPER in sources or analysis.get('optimization_cache') is not None:
            raise ValueError('original replay contains optimization markers')
        if set(sources) != ORIGINAL_SOURCE_KEYS:
            raise ValueError('original replay source inventory incomplete')
        if any(name not in frozen_files or digest != frozen_files[name]
               for name, digest in sources.items()):
            raise ValueError('original replay source differs from implementation freeze')
        return {'variant': 'original_frozen', 'post_freeze_optimization': False,
                'original_equivalence': 'original_reference',
                'optimization_provenance_sha256': None}
    if variant != CACHED_VARIANT:
        raise ValueError('unknown post-freeze replay variant')
    wrapper_hash = sha256(ROOT / WRAPPER)
    if sources.get(WRAPPER) != wrapper_hash or set(sources) != ORIGINAL_SOURCE_KEYS | {WRAPPER}:
        raise ValueError('cached replay wrapper/source inventory mismatch')
    if any(digest != frozen_files[name] for name, digest in sources.items() if name != WRAPPER):
        raise ValueError('cached replay changed a frozen original source')
    provenance = bounded_json(provenance_path, 16_384)
    if (provenance.get('schema') != 'rh-maker-replay-optimization-v1'
            or provenance.get('implementation_variant') != CACHED_VARIANT
            or provenance.get('post_freeze_optimization') is not True
            or provenance.get('optimization') != 'one_event_identity_immutable_Book_parse_cache'
            or provenance.get('original_replay') != 'scripts/analyze_rh_maker.py'
            or provenance.get('original_engine') != 'scripts/rh_maker_engine.py'):
        raise ValueError('cached replay optimization provenance identity mismatch')
    for name, claimed in (('capture_manifest_sha256', analysis['capture_manifest_sha256']),
                          ('raw_sha256', analysis['raw_sha256']),
                          ('analysis_sha256', sha256(derived / 'analysis.json')),
                          ('audit_sha256', analysis['audit_sha256'])):
        if provenance.get(name) != claimed:
            raise ValueError(f'cached replay optimization provenance mismatch: {name}')
    required = {WRAPPER, 'scripts/analyze_rh_maker.py', 'scripts/rh_maker_engine.py'}
    claimed_sources = provenance.get('source_sha256')
    if (not isinstance(claimed_sources, dict) or set(claimed_sources) != required
            or any(claimed_sources[name] != sources.get(name) for name in required)):
        raise ValueError('cached replay wrapper/original source hashes mismatch')
    cache = provenance.get('cache')
    if not isinstance(cache, dict) or cache != analysis.get('optimization_cache'):
        raise ValueError('cached replay counters differ from analysis')
    fields = ('parse_calls', 'cache_hits', 'cache_misses', 'validation_errors')
    if (any(type(cache.get(name)) is not int or cache[name] < 0 for name in fields)
            or cache['parse_calls'] != cache['cache_hits'] + cache['cache_misses'] + cache['validation_errors']):
        raise ValueError('cached replay counters malformed')
    return {'variant': CACHED_VARIANT, 'post_freeze_optimization': True,
            'original_equivalence': 'not_assessed_requires_full_original_cached_comparison',
            'optimization_provenance_sha256': sha256(provenance_path)}


def verify_inputs(capture: Path, derived: Path, freeze_path: Path = FREEZE) -> tuple[dict, dict, dict, dict]:
    analysis = bounded_json(derived / 'analysis.json', MAX_ANALYSIS)
    manifest = bounded_json(capture / 'manifest.json', 1_000_000)
    freeze = bounded_json(freeze_path, 1_000_000)
    if analysis.get('schema') != 'rh-maker-replay-v1' or analysis.get('event_source') != 'verified_capture':
        raise ValueError('original verified buy-side replay required')
    if manifest.get('schema') != 'rh-maker-public-capture-v1' or manifest.get('read_only') is not True:
        raise ValueError('stopped public RH maker capture required')
    if analysis.get('capture_manifest_sha256') != sha256(capture / 'manifest.json'):
        raise ValueError('capture manifest digest mismatch')
    if analysis.get('raw_sha256') != manifest.get('frames_sha256'):
        raise ValueError('replay/raw compressed hash mismatch')
    if (analysis.get('audit_sha256') != sha256(derived / 'audit.jsonl.gz') or
            analysis.get('audit_bytes') != (derived / 'audit.jsonl.gz').stat().st_size):
        raise ValueError('derived audit digest or byte count mismatch')
    if (derived / 'audit.jsonl.gz').stat().st_size > MAX_AUDIT:
        raise ValueError('audit gzip exceeds 96 MB bound')
    if sha256(capture / 'metadata/normalized.json') != manifest.get('metadata_normalized_sha256'):
        raise ValueError('captured metadata digest mismatch')
    files = freeze.get('files')
    sources = analysis.get('source_sha256')
    if not isinstance(files, dict) or len(files) != 23 or not isinstance(sources, dict) or not sources:
        raise ValueError('original 23-file implementation freeze inventory required')
    frozen_normalized = ROOT / 'reports/rh-small-maker-v1/metadata/normalized.json'
    normalized_claim = None
    for name, claimed in files.items():
        if not isinstance(name, str) or not isinstance(claimed, str) or len(claimed) != 64:
            raise ValueError('malformed implementation-freeze file inventory')
        path = Path(name)
        path = (path if path.is_absolute() else ROOT / path).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or sha256(path) != claimed:
            raise ValueError(f'implementation-freeze file changed: {name}')
        if path == frozen_normalized:
            normalized_claim = claimed
    if (normalized_claim is None or
            sha256(capture / 'metadata/normalized.json') != normalized_claim):
        raise ValueError('captured normalized metadata differs from frozen original')
    variant_info = verify_variant(analysis, derived, files)
    if analysis.get('status') not in ('complete', 'capture_incomplete'):
        raise ValueError('replay audit incomplete or failed')
    if len(analysis.get('branches', [])) != MAX_BRANCHES:
        raise ValueError('expected 96 original buy-side branches')
    return analysis, manifest, freeze, variant_info


def audit_rows(path: Path, expected_records: int):
    if type(expected_records) is not int or not 0 <= expected_records <= MAX_RECORDS:
        raise ValueError('audit record count out of bounds')
    decoded = count = 0
    with gzip.open(path, 'rb') as stream:
        while True:
            line = stream.readline(MAX_LINE + 1)
            if not line:
                break
            if len(line) > MAX_LINE or not line.endswith(b'\n'):
                raise ValueError('oversized or unterminated audit row')
            decoded += len(line)
            count += 1
            if decoded > MAX_DECODED or count > expected_records:
                raise ValueError('audit decoded limits exceeded')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('audit row must be object')
            yield row
    if count != expected_records:
        raise ValueError('audit record count mismatch')


def retired_quotes(analysis: dict, rows) -> tuple[dict[str, list[dict]], dict]:
    """Reconstruct only activated, flattened quotes with remaining quantity."""
    episodes = {}
    branch_reasons = {}
    for branch in analysis['branches']:
        key = identity(branch)
        if key in episodes or len(branch.get('episodes', [])) > MAX_EPISODES_PER_BRANCH:
            raise ValueError('duplicate branch or episode cap exceeded')
        index = {}
        for e in branch['episodes']:
            ek = (int(e['decided_ns']), int(e['flat_ns']))
            if ek in index:
                raise ValueError('duplicate episode interval')
            index[ek] = e
        episodes[key] = index
        branch_reasons[key] = branch.get('unknown_reason')
    if len(episodes) != MAX_BRANCHES:
        raise ValueError('branch identity count mismatch')
    current = {}
    tombstones = defaultdict(list)
    counts = Counter()
    matched_episodes = set()
    for row in rows:
        key = identity(row)
        if key not in episodes:
            raise ValueError('audit branch identity not in analysis')
        event, at = row['event'], int(row['ns'])
        if event == 'quote_requested':
            if key in current:
                raise ValueError('overlapping quote audit episodes')
            qty = _positive(row['qty'], 'quote quantity')
            current[key] = {'branch': key, 'decided_ns': at, 'activation_due_ns': int(row['due_ns']),
                            'price': _positive(row['price'], 'quote price'), 'qty': qty,
                            'remaining': qty, 'activated_ns': None, 'cancel_due_ns': None}
            counts['quote_requested'] += 1
        elif event == 'activated':
            q = current.get(key)
            if q is None or q['activated_ns'] is not None:
                raise ValueError('activation without unique quote')
            q['activated_ns'] = at
            counts['activated'] += 1
        elif event == 'cancel_requested':
            q = current.get(key)
            if q is None or q['cancel_due_ns'] is not None:
                raise ValueError('cancel without unique quote')
            q['cancel_due_ns'] = int(row['due_ns'])
        elif event == 'maker_increment':
            q = current.get(key)
            if q is None:
                raise ValueError('increment without quote')
            qty = _positive(row['qty'], 'maker increment')
            remaining = Decimal(str(row['remaining']))
            if not remaining.is_finite() or remaining < 0 or q['remaining'] - qty != remaining:
                raise ValueError('maker increment/remaining mismatch')
            q['remaining'] = remaining
        elif event == 'episode_flat':
            q = current.pop(key, None)
            if q is None:
                raise ValueError('flat episode without quote')
            e = episodes[key].get((q['decided_ns'], at))
            if e is None or q['qty'] - q['remaining'] != Decimal(str(e['maker_attributed'])):
                raise ValueError('audit/analysis episode mismatch')
            matched_episodes.add((key, q['decided_ns'], at))
            counts['episode_flat'] += 1
            if q['activated_ns'] is None or q['remaining'] <= 0:
                continue
            due = q['activation_due_ns']
            cancel_due = q['cancel_due_ns']
            if cancel_due is None or cancel_due < due or cancel_due - due > MAX_INTERVAL_NS:
                raise ValueError('retired activated quote lacks bounded cancel interval')
            q.update(flat_ns=at, episode_number=int(e['number']),
                     prior_unknown_reason=branch_reasons[key],
                     match_count=0, examples=[])
            tombstones[key[1]].append(q)
            counts['retired_with_remaining'] += 1
            if counts['retired_with_remaining'] > MAX_TOMBSTONES:
                raise ValueError('retired quote tombstone cap exceeded')
    expected_episodes = sum(len(b['episodes']) for b in analysis['branches'])
    if len(matched_episodes) != expected_episodes:
        raise ValueError('analysis episodes absent from audit stream')
    counts['analysis_episodes'] = expected_episodes
    for asset, entries in tombstones.items():
        entries.sort(key=lambda q: q['activation_due_ns'])
    return dict(tombstones), dict(counts)


def match_trades(tombstones: dict[str, list[dict]], events) -> tuple[dict, dict]:
    """Match later RH sell prints to retired quote source intervals only."""
    due_index = {asset: [q['activation_due_ns'] for q in entries]
                 for asset, entries in tombstones.items()}
    counts = Counter()
    terminal = None
    for event in events:
        typ = event.get('type')
        if typ == 'end':
            terminal = event
            break
        if typ != 'trade' or event.get('venue') != 'rh_lighter':
            continue
        counts['rh_trades_seen'] += 1
        if event.get('side') != 'sell':
            continue
        counts['rh_sell_trades_seen'] += 1
        asset = str(event.get('asset'))
        entries = tombstones.get(asset, [])
        if not entries:
            continue
        source, receipt = int(event['source_ns']), int(event['received_ns'])
        price, qty = _positive(event['price'], 'trade price'), _positive(event['qty'], 'trade qty')
        if source > receipt or event.get('clock_valid') is False:
            raise ValueError('invalid RH trade clock reached adjudicator')
        starts = due_index[asset]
        left = bisect_left(starts, source - MAX_INTERVAL_NS)
        right = bisect_right(starts, source)
        matched_event = False
        for q in entries[left:right]:
            if (receipt <= q['flat_ns'] or source > q['cancel_due_ns']
                    or price > q['price'] or q['remaining'] <= 0):
                continue
            q['match_count'] += 1
            counts['trade_quote_ambiguity_matches'] += 1
            matched_event = True
            if len(q['examples']) < 3:
                q['examples'].append({'trade_id': str(event['trade_id']),
                                      'source_ns': source, 'receipt_ns': receipt,
                                      'price': str(price), 'qty': str(qty)})
        if matched_event:
            counts['unique_trade_events_with_match'] += 1
    if terminal is None or not terminal.get('raw_sha_verified'):
        raise ValueError('raw capture replay has no verified terminal marker')
    return dict(counts), terminal


def result_document(analysis: dict, manifest: dict, freeze: dict, capture: Path,
                    derived: Path, tombstones: dict, lifecycle_counts: dict,
                    trade_counts: dict, terminal: dict, variant_info: dict) -> dict:
    if terminal['raw_gzip_sha256'] != analysis['raw_sha256']:
        raise ValueError('streamed raw digest differs from replay analysis')
    affected = [q for entries in tombstones.values() for q in entries if q['match_count']]
    affected.sort(key=lambda q: (q['branch'], q['flat_ns'], q['episode_number']))
    by_branch = Counter(str(q['branch']) for q in affected)
    cases = []
    for q in affected[:MAX_FLAG_DETAILS]:
        tier, asset, budget, policy = q['branch']
        cases.append({'tier': tier, 'asset': asset, 'budget_usd': budget,
                      'policy': policy, 'episode_number': q['episode_number'],
                      'decided_ns': q['decided_ns'], 'activated_ns': q['activated_ns'],
                      'activation_due_ns': q['activation_due_ns'],
                      'cancel_due_ns': q['cancel_due_ns'], 'flat_ns': q['flat_ns'],
                      'own_bid': str(q['price']), 'original_qty': str(q['qty']),
                      'remaining_qty_at_flat': str(q['remaining']),
                      'prior_branch_unknown_reason': q['prior_unknown_reason'],
                      'matching_trade_count': q['match_count'], 'examples': q['examples']})
    return {
        'schema': 'rh-retired-quote-flow-audit-v1',
        'classification': 'potential_late_flow_ambiguity_not_actual_fill',
        'status': 'flags_found' if affected else 'specific_check_passed_no_flags',
        'scope': 'original buy-side 96-branch public-flow replay only',
        'capture': str(capture), 'derived_replay': str(derived),
        'capture_manifest_sha256': sha256(capture / 'manifest.json'),
        'raw_gzip_sha256': terminal['raw_gzip_sha256'],
        'analysis_sha256': sha256(derived / 'analysis.json'),
        'audit_gzip_sha256': sha256(derived / 'audit.jsonl.gz'),
        'implementation_freeze_sha256': sha256(FREEZE),
        'adjudicator_source_sha256': sha256(Path(__file__)),
        'implementation_variant': variant_info['variant'],
        'post_freeze_optimization': variant_info['post_freeze_optimization'],
        'original_equivalence': variant_info['original_equivalence'],
        'optimization_provenance_sha256': variant_info['optimization_provenance_sha256'],
        'source_sha256': analysis['source_sha256'],
        'replay_status': analysis['status'], 'capture_end_reason': manifest.get('end_reason'),
        'capture_truncated': manifest.get('truncated'),
        'lifecycle_counts': lifecycle_counts, 'trade_counts': trade_counts,
        'affected_branch_count': len(by_branch), 'affected_episode_count': len(affected),
        'affected_branches': dict(sorted(by_branch.items())),
        'flag_details_truncated': len(affected) > MAX_FLAG_DETAILS,
        'flag_details_omitted': max(0, len(affected) - MAX_FLAG_DETAILS),
        'flagged_episodes': cases,
        'rule': ('receipt after episode_flat; source within activation_due..cancel_due '
                 'inclusive; RH sell aggressor price at/below retired own bid; '
                 'positive trade quantity and retired quote remaining quantity'),
        'interpretation': ('A same-price queue may absorb the print. This is unresolved '
                           'late public-flow evidence, not an observed or guaranteed maker fill; '
                           'no original replay classification or P&L is revised.'),
    }


def report_markdown(result: dict) -> str:
    lines = ['# Retired RH maker bid: late public-flow check', '',
             f"Result: **{result['status']}**. Affected branches: {result['affected_branch_count']}; "
             f"affected episodes: {result['affected_episode_count']}.", '',
             'The check compares the frozen audit lifecycle with later public RH sell trades.',
             'A matching print makes the old no-flow or partial-flow episode **ambiguous**.',
             'It does not prove our counterfactual order existed or filled: displayed',
             'same-price queue could have absorbed the trade. Original results are unchanged.', '',
             f"Replay status: `{result['replay_status']}`; capture end: "
             f"`{result['capture_end_reason']}`; truncated: `{result['capture_truncated']}`.", '',
             f"Replay implementation: `{result['implementation_variant']}`; "
             f"original equivalence: `{result['original_equivalence']}`.", '',
             f"Retired activated quotes with remaining quantity: "
             f"{result['lifecycle_counts'].get('retired_with_remaining', 0)}; "
             f"RH sell trades scanned: {result['trade_counts'].get('rh_sell_trades_seen', 0)}; "
             f"matching trade/quote pairs: {result['trade_counts'].get('trade_quote_ambiguity_matches', 0)}.", '']
    if result['affected_branches']:
        lines += ['| Branch `(tier, asset, budget, policy)` | Ambiguous episodes |', '|---|---:|']
        lines += [f'| `{key}` | {n} |' for key, n in result['affected_branches'].items()]
        lines.append('')
    if result['flag_details_truncated']:
        lines += [f"JSON detail lists the first {MAX_FLAG_DETAILS} affected episodes; "
                  f"{result['flag_details_omitted']} details omitted under the output cap.", '']
    lines += ['`validation.json` records each affected episode, up to three example trade IDs,',
              'and capture, replay, audit, raw, and frozen-source hashes. A zero-flag result',
              'passes only this specific delayed-print test.', '']
    return '\n'.join(lines)


def adjudicate(capture: Path, derived: Path, out: Path) -> dict:
    capture, derived, out = Path(capture), Path(derived), Path(out)
    if out.exists():
        raise ValueError('output directory must not exist')
    analysis, manifest, freeze, variant_info = verify_inputs(capture, derived)
    tombstones, lifecycle = retired_quotes(
        analysis, audit_rows(derived / 'audit.jsonl.gz', analysis['audit_records']))
    trades, terminal = match_trades(tombstones, iter_events(capture, max_raw_bytes=384_000_000))
    result = result_document(analysis, manifest, freeze, capture, derived,
                             tombstones, lifecycle, trades, terminal, variant_info)
    body = (json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    note = report_markdown(result).encode()
    if len(body) + len(note) > MAX_OUTPUT:
        raise ValueError('validation report exceeds 8 MB output bound')
    out.mkdir(parents=True)
    (out / 'validation.json').write_bytes(body)
    (out / 'RESULTS.md').write_bytes(note)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--derived', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = adjudicate(args.capture, args.derived, args.out)
    print(json.dumps({'out': str(args.out), 'status': result['status'],
                      'affected_branches': result['affected_branch_count'],
                      'affected_episodes': result['affected_episode_count']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
