#!/usr/bin/env python3
"""Post-freeze replay wrapper: cache one immutable parsed book per input event.

The original analyzer and frozen engine are imported without editing them.
The classmethod patch is scoped to one replay call and restored on exit.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import analyze_rh_maker
from scripts.rh_maker_engine import Book


@dataclass(frozen=True, slots=True)
class ImmutableBook:
    """Book's read-only interface with immutable levels and fields."""

    venue: str
    received_ns: int
    source_ns: int
    generation: Any
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    def walk(self, side: str, qty: Decimal,
             limit: Decimal | None = None) -> tuple[Decimal, Decimal]:
        return Book.walk(self, side, qty, limit)

    def mid(self) -> Decimal:
        return Book.mid(self)


@contextmanager
def cached_book_parse():
    """Cache only the current event; caller resets at every stream yield."""
    descriptor = Book.__dict__['parse']
    original = Book.parse
    stats = {'parse_calls': 0, 'cache_hits': 0, 'cache_misses': 0,
             'validation_errors': 0}
    previous_event = None
    previous_book = None

    def next_event():
        nonlocal previous_event, previous_book
        previous_event = previous_book = None

    def cached(cls, event: Mapping[str, Any]):
        nonlocal previous_event, previous_book
        stats['parse_calls'] += 1
        if event is previous_event:
            stats['cache_hits'] += 1
            return previous_book
        # Release the prior full-depth event before parsing another one.
        previous_event = previous_book = None
        try:
            parsed = original(event)
        except (ValueError, KeyError, TypeError):
            stats['validation_errors'] += 1
            raise
        frozen = ImmutableBook(parsed.venue, parsed.received_ns, parsed.source_ns,
                               parsed.generation, tuple(parsed.bids), tuple(parsed.asks))
        previous_event, previous_book = event, frozen
        stats['cache_misses'] += 1
        return frozen

    Book.parse = classmethod(cached)
    try:
        yield stats, next_event
    finally:
        Book.parse = descriptor


def _sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replay_optimized(capture, out, tiers=('standard', 'premium'), *, events=None):
    """Run the original analyzer under a scoped, one-event immutable parse cache."""
    out = Path(out)
    with cached_book_parse() as (stats, next_event):
        if events is None:
            # The verified archive adapter returns a fresh normalized dict for
            # every yield. Explicit boundaries also guard future adapters.
            original_iter_events = analyze_rh_maker.iter_events

            def bounded_events(*args, **kwargs):
                for event in original_iter_events(*args, **kwargs):
                    next_event()
                    yield event

            analyze_rh_maker.iter_events = bounded_events
            try:
                result = analyze_rh_maker.replay(capture, out, tiers)
            finally:
                analyze_rh_maker.iter_events = original_iter_events
        else:
            def bounded_injected_events():
                for event in events:
                    next_event()
                    yield event

            result = analyze_rh_maker.replay(capture, out, tiers,
                                             events=bounded_injected_events())
    variant = 'postfreeze_book_parse_cache'
    wrapper_name = 'scripts/optimized_rh_maker_replay.py'
    wrapper_hash = _sha256(ROOT / wrapper_name)
    # Make the analysis itself unambiguously a post-freeze implementation
    # variant. The original analyzer's financial rows and audit stream remain
    # byte-for-byte intact; only this provenance metadata/report label differs.
    result['implementation_variant'] = variant
    result['optimization_cache'] = dict(stats)
    result['source_sha256'][wrapper_name] = wrapper_hash
    report = (f'**Implementation variant: {variant}.** Post-freeze parse-cache '
              'optimization; compare with the unchanged primary replay.\n\n'
              + analyze_rh_maker.markdown(result)).encode()
    if len(report) > 1_000_000:
        raise ValueError('Variant report exceeds bounded reserve')
    analyze_rh_maker.write_json(out / 'analysis.json', result,
                                analyze_rh_maker.SUMMARY_CAP - len(report) - 16_384)
    (out / 'REPORT.md').write_bytes(report)
    provenance = {
        'schema': 'rh-maker-replay-optimization-v1',
        'implementation_variant': variant,
        'optimization': 'one_event_identity_immutable_Book_parse_cache',
        'original_replay': 'scripts/analyze_rh_maker.py',
        'original_engine': 'scripts/rh_maker_engine.py',
        'post_freeze_optimization': True,
        'cache': stats,
        'capture_manifest_sha256': result['capture_manifest_sha256'],
        'raw_sha256': result['raw_sha256'],
        'analysis_sha256': _sha256(out / 'analysis.json'),
        'audit_sha256': result['audit_sha256'],
        'source_sha256': {name: _sha256(ROOT / name) for name in (
            wrapper_name, 'scripts/analyze_rh_maker.py',
            'scripts/rh_maker_engine.py')},
        'written_unix_seconds': time.time(),
        'note': 'Financial and audit outputs are produced by the frozen original analyzer.'}
    body = json.dumps(provenance, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    if len(body) > 16_384:
        raise ValueError('Optimization provenance exceeds bound')
    (out / 'optimization_provenance.json').write_bytes(body)
    return result, provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tiers', nargs='+', choices=('standard', 'premium'),
                        default=['standard', 'premium'])
    args = parser.parse_args(argv)
    if len(set(args.tiers)) != len(args.tiers):
        parser.error('tiers must be unique')
    result, provenance = replay_optimized(args.capture, args.out, tuple(args.tiers))
    print(json.dumps({'out': str(args.out), 'status': result['status'],
                      'branches': len(result['branches']), 'cache': provenance['cache'],
                      'errors': result['errors']}))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
