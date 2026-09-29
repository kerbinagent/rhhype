#!/usr/bin/env python3
"""Bounded offline equivalence check for original and cached RH maker replays.

The frozen provenance auditor validates each replay against one stopped capture
and the original implementation freeze. This comparison then checks every
scientific and financial result field plus every ordered audit row.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_rh_retired_quote_flow import (
    CACHED_VARIANT, ORIGINAL_SOURCE_KEYS, WRAPPER, audit_rows, verify_inputs,
)

SCHEMA = 'rh-maker-replay-comparison-v1'
MAX_OUTPUT = 1_000_000
MAX_RAW_BYTES = 384_000_000
MAX_MISMATCHES = 32
IGNORED_TOP_LEVEL = frozenset(('replay_wall_seconds', 'implementation_variant',
                               'optimization_cache', 'source_sha256'))


def _sha256(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _strict_comparable(analysis: dict) -> dict:
    """Remove only measured runtime and authorized wrapper provenance fields."""
    return {key: value for key, value in analysis.items()
            if key not in IGNORED_TOP_LEVEL}


def _differences(left, right, path='$', found=None):
    if found is None:
        found = []
    if len(found) >= MAX_MISMATCHES:
        return found
    if type(left) is not type(right):
        found.append(f'{path}: type {type(left).__name__} != {type(right).__name__}')
    elif isinstance(left, dict):
        lk, rk = set(left), set(right)
        for key in sorted(lk ^ rk):
            found.append(f'{path}.{key}: key only in {"original" if key in lk else "cached"}')
            if len(found) >= MAX_MISMATCHES:
                return found
        for key in sorted(lk & rk):
            _differences(left[key], right[key], f'{path}.{key}', found)
            if len(found) >= MAX_MISMATCHES:
                return found
    elif isinstance(left, list):
        if len(left) != len(right):
            found.append(f'{path}: list length {len(left)} != {len(right)}')
        for index, (a, b) in enumerate(zip(left, right)):
            _differences(a, b, f'{path}[{index}]', found)
            if len(found) >= MAX_MISMATCHES:
                return found
    elif left != right:
        found.append(f'{path}: value differs')
    return found


def _audit_differences(original: Path, cached: Path,
                       original_records: int, cached_records: int) -> tuple[list[str], int]:
    sentinel = object()
    differences, matched = [], 0
    left = audit_rows(original / 'audit.jsonl.gz', original_records)
    right = audit_rows(cached / 'audit.jsonl.gz', cached_records)
    # Decode both to EOF, even when an early row differs, so each bounded
    # stream's record count, line limit, and gzip integrity are validated.
    for index, (a, b) in enumerate(itertools.zip_longest(left, right, fillvalue=sentinel)):
        if a is sentinel or b is sentinel:
            if len(differences) < MAX_MISMATCHES:
                differences.append(f'audit[{index}]: ordered stream length differs')
        elif a != b:
            if len(differences) < MAX_MISMATCHES:
                differences.append(f'audit[{index}]: row differs')
        else:
            matched += 1
    return differences, matched


def compare_loaded(original_analysis: dict, cached_analysis: dict,
                   original: Path, cached: Path,
                   original_variant: dict, cached_variant: dict) -> dict:
    """Compare prevalidated analyses and bounded audit streams exactly."""
    if original_variant.get('variant') != 'original_frozen':
        raise ValueError('original directory is not the frozen original replay')
    if cached_variant.get('variant') != CACHED_VARIANT:
        raise ValueError('cached directory lacks explicit optimization provenance')
    provenance_hash = cached_variant.get('optimization_provenance_sha256')
    if not isinstance(provenance_hash, str) or len(provenance_hash) != 64:
        raise ValueError('cached optimization provenance digest missing')
    if original_analysis.get('status') != 'complete' or cached_analysis.get('status') != 'complete':
        raise ValueError('both replay outputs must be complete')
    if original_analysis.get('implementation_variant') is not None:
        raise ValueError('original analysis unexpectedly has wrapper label')
    if cached_analysis.get('implementation_variant') != CACHED_VARIANT:
        raise ValueError('cached analysis variant label missing')
    left_sources = original_analysis.get('source_sha256')
    right_sources = cached_analysis.get('source_sha256')
    if (not isinstance(left_sources, dict) or not isinstance(right_sources, dict)
            or set(left_sources) != ORIGINAL_SOURCE_KEYS
            or set(right_sources) != ORIGINAL_SOURCE_KEYS | {WRAPPER}
            or {name: right_sources[name] for name in ORIGINAL_SOURCE_KEYS} != left_sources):
        raise ValueError('original input/frozen source hashes differ across replays')
    for key in ('capture_manifest_sha256', 'raw_sha256'):
        if original_analysis.get(key) != cached_analysis.get(key):
            raise ValueError(f'input identity differs: {key}')
    original_count = original_analysis.get('audit_records')
    cached_count = cached_analysis.get('audit_records')
    if type(original_count) is not int or type(cached_count) is not int:
        raise ValueError('audit record count must be integer')
    audit_diffs, matched = _audit_differences(Path(original), Path(cached),
                                              original_count, cached_count)
    result_diffs = _differences(_strict_comparable(original_analysis),
                                _strict_comparable(cached_analysis))
    if original_count != cached_count:
        result_diffs.insert(0, 'audit_records: count differs')
    hash_equal = original_analysis.get('audit_sha256') == cached_analysis.get('audit_sha256')
    hash_diffs = [] if hash_equal else ['audit compressed SHA-256 differs']
    mismatches = (result_diffs + audit_diffs + hash_diffs)[:MAX_MISMATCHES]
    return {
        'schema': SCHEMA,
        'equivalent': not mismatches,
        'scope': ('Complete original frozen versus explicitly labeled post-freeze cache; '
                  'all analysis fields except replay_wall_seconds and authorized wrapper '
                  'label/cache/source-addition; full ordered audit JSON rows and exact '
                  'compressed audit SHA-256. No new replay or financial inference.'),
        'original_variant': original_variant['variant'],
        'cached_variant': cached_variant['variant'],
        'optimization_provenance_sha256': provenance_hash,
        'capture_manifest_sha256': original_analysis['capture_manifest_sha256'],
        'raw_sha256': original_analysis['raw_sha256'],
        'original_source_sha256': left_sources,
        'cached_wrapper_sha256': right_sources[WRAPPER],
        'original_audit_sha256': original_analysis['audit_sha256'],
        'cached_audit_sha256': cached_analysis['audit_sha256'],
        'audit_byte_identical': hash_equal,
        'audit_records_original': original_count,
        'audit_records_cached': cached_count,
        'ordered_audit_rows_equal': not audit_diffs,
        'ordered_audit_rows_matched': matched,
        'models_exact': original_analysis.get('models') == cached_analysis.get('models'),
        'branches_exact': original_analysis.get('branches') == cached_analysis.get('branches'),
        'counts_exact': original_analysis.get('counts') == cached_analysis.get('counts'),
        'errors_exact': original_analysis.get('errors') == cached_analysis.get('errors'),
        'mismatches': mismatches,
        'mismatch_list_capped_at': MAX_MISMATCHES,
    }


def compare(capture: Path, original: Path, cached: Path, out: Path) -> dict:
    """Gate inputs with the independent provenance auditor, then compare."""
    capture, original, cached, out = map(Path, (capture, original, cached, out))
    if out.exists():
        raise ValueError('comparison output must be a new directory')
    left, _, _, left_variant = verify_inputs(capture, original)
    right, _, _, right_variant = verify_inputs(capture, cached)
    frames = capture / 'frames.jsonl.gz'
    raw_bytes = frames.stat().st_size
    if not 0 < raw_bytes <= MAX_RAW_BYTES or frames.is_symlink():
        raise ValueError('capture raw gzip exceeds 384 MB bound or is invalid')
    raw_hash = _sha256(frames)
    if raw_hash != left.get('raw_sha256') or raw_hash != right.get('raw_sha256'):
        raise ValueError('capture raw gzip SHA-256 differs from replay claims')
    result = compare_loaded(left, right, original, cached, left_variant, right_variant)
    result.update(capture=str(capture), original=str(original), cached=str(cached),
                  capture_frames_bytes=raw_bytes, capture_frames_sha256=raw_hash,
                  original_analysis_sha256=_sha256(original / 'analysis.json'),
                  cached_analysis_sha256=_sha256(cached / 'analysis.json'),
                  comparator_source_sha256=_sha256(Path(__file__).resolve()))
    body = (json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    lines = [f"# RH maker replay comparison: {'equivalent' if result['equivalent'] else 'different'}", '',
             result['scope'], '',
             f"Ordered audit rows matched: {result['ordered_audit_rows_matched']} / {result['audit_records_original']}.",
             f"Compressed audit identical: {result['audit_byte_identical']}.",
             f"Models / branches / counts / errors exact: {result['models_exact']} / "
             f"{result['branches_exact']} / {result['counts_exact']} / {result['errors_exact']}."]
    if result['mismatches']:
        lines += ['', 'First bounded differences:', '']
        lines += [f'- {item}' for item in result['mismatches']]
    lines.append('')
    report = ('\n'.join(lines) + '\n').encode()
    if len(body) + len(report) > MAX_OUTPUT:
        raise ValueError('comparison output exceeds 1 MB bound')
    out.mkdir(parents=True)
    (out / 'comparison.json').write_bytes(body)
    (out / 'REPORT.md').write_bytes(report)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--cached', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare(args.capture, args.original, args.cached, args.out)
    print(json.dumps({'out': str(args.out), 'equivalent': result['equivalent'],
                      'audit_rows': result['ordered_audit_rows_matched'],
                      'mismatches': result['mismatches']}))
    return 0 if result['equivalent'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
