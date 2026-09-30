#!/usr/bin/env python3
"""Resource-only sentinel successor; default dry. Live stages require root authorization."""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rh_spread_regime_sentinel as frozen

NOTE = ROOT / 'research/rh-spread-regime-sentinel-compact-resource-method.md'
TESTS = ROOT / 'tests/test_rh_spread_regime_sentinel_compact.py'
MARKER = 'sentinel_compact_provenance_v1'
MAX_ARCHIVE_DECODED = 65_536
MAX_ALL_ARCHIVES_DECODED = 262_144
BASE_STORE = frozen.Store
BASE_DEPENDENCIES = frozen.dependencies
PINS = {
    str(ROOT / 'scripts/rh_spread_regime_sentinel.py'): 'd6a59773dd59caad7c20431ef62cafd2e1b6a69c5dc5826a7bbb1f48b902c7de',
    str(frozen.METHOD): 'cfd3bd8d50c9e5885e7af1de7e4edd5bcd9c5f71f0b97dea09832f10bb294f54',
    str(frozen.TESTS): '3ec64fe58fe6198cd9e9c362248a0c4bac748e68cdb2a271b50a0daeff1adcf0',
    str(frozen.DEPENDENCY): '71cf56d9bd91847011d30767be918130ea02cf38b2d125d1ece82cb4a09e9014',
    str(frozen.REFERENCE): frozen.REFERENCE_SHA,
}


def dependencies():
    return BASE_DEPENDENCIES() + [Path(__file__), TESTS, NOTE]


def archives():
    return {
        'source.py.gz': ROOT / 'scripts/rh_spread_regime_sentinel.py',
        'method.md.gz': frozen.METHOD,
        'tests.py.gz': frozen.TESTS,
        'wrapper.py.gz': Path(__file__),
        'wrapper-tests.py.gz': TESTS,
        'resource-method.md.gz': NOTE,
    }


def archive_inventory():
    result = {}
    total = 0
    for name, path in archives().items():
        raw = path.read_bytes()
        total += len(raw)
        if len(raw) > MAX_ARCHIVE_DECODED or total > MAX_ALL_ARCHIVES_DECODED:
            raise frozen.CapReached('archived_source_decoded_cap')
        packed = gzip.compress(raw, mtime=0)
        result[name] = {
            'input': str(path), 'decoded_bytes': len(raw), 'decoded_sha256': hashlib.sha256(raw).hexdigest(),
            'compressed_bytes': len(packed), 'compressed_sha256': hashlib.sha256(packed).hexdigest(),
        }
    return result


def verify_archives(path, versions):
    if versions.get('resource_wrapper') != MARKER:
        raise ValueError('requires_new_compact_marked_stage')
    if versions.get('overrides') != ['Store', 'dependencies']:
        raise ValueError('resource_override_identity')
    expected = archive_inventory()
    if versions.get('archived_sources') != expected:
        raise ValueError('archived_source_inventory_changed')
    if set(versions.get('input_hashes', {})) != {str(p) for p in dependencies()}:
        raise ValueError('requires_all_eight_dependencies')
    total = 0
    for name, record in expected.items():
        packed = (path / name).read_bytes()
        if len(packed) != record['compressed_bytes'] or hashlib.sha256(packed).hexdigest() != record['compressed_sha256']:
            raise ValueError('compressed_source_identity')
        with gzip.GzipFile(fileobj=io.BytesIO(packed), mode='rb') as stream:
            raw = stream.read(MAX_ARCHIVE_DECODED + 1)
        total += len(raw)
        if len(raw) > MAX_ARCHIVE_DECODED or total > MAX_ALL_ARCHIVES_DECODED:
            raise frozen.CapReached('archived_source_decoded_cap')
        if len(raw) != record['decoded_bytes'] or hashlib.sha256(raw).hexdigest() != record['decoded_sha256']:
            raise ValueError('decoded_source_identity')


class CompactStore(BASE_STORE):
    """Compress provenance copies only; delegate every write budget to the frozen Store."""

    def __init__(self, path):
        super().__init__(path)
        if (self.path / 'source-freeze.json').exists():
            verify_archives(self.path, json.loads((self.path / 'source-freeze.json').read_bytes()))

    def write(self, name, data, category, *, final=False):
        mapped = {'source.py': 'source.py.gz', 'method.md': 'method.md.gz', 'tests.py': 'tests.py.gz'}
        if name in mapped:
            expected = archives()[mapped[name]].read_bytes()
            if data != expected or category != 'control':
                raise ValueError('source_copy_identity')
            if len(data) > MAX_ARCHIVE_DECODED:
                raise frozen.CapReached('archived_source_decoded_cap')
            return super().write(mapped[name], gzip.compress(data, mtime=0), category, final=final)
        if name == 'source-freeze.json':
            data = dict(data)
            inventory = archive_inventory()
            for archive in ('wrapper.py.gz', 'wrapper-tests.py.gz', 'resource-method.md.gz'):
                super().write(archive, gzip.compress(archives()[archive].read_bytes(), mtime=0), 'control')
            data.update(resource_wrapper=MARKER, overrides=['Store', 'dependencies'], archived_sources=inventory)
        return super().write(name, data, category, final=final)


@contextmanager
def installed():
    """Expose the exact two overrides during delegation; restore even on failed stages."""
    if frozen.Store is not BASE_STORE or frozen.dependencies is not BASE_DEPENDENCIES:
        raise ValueError('unexpected_or_nested_runtime_override')
    if frozen.input_hashes() != PINS:
        raise ValueError('original_frozen_dependency_changed')
    frozen.Store, frozen.dependencies = CompactStore, dependencies
    snapshot = None
    error = None
    try:
        snapshot = frozen.input_hashes()
        frozen.verify_inputs(snapshot)
        yield frozen
    except BaseException as exc:
        error = exc
        raise
    finally:
        try:
            if snapshot is not None:
                try:
                    frozen.verify_inputs(snapshot)
                except BaseException as failure:
                    if error is None:
                        raise
                    error.add_note('postdelegation_dependency_verification_failed: ' + type(failure).__name__ + ':' + str(failure))
        finally:
            frozen.Store, frozen.dependencies = BASE_STORE, BASE_DEPENDENCIES


def main():
    with installed():
        frozen.main()


if __name__ == '__main__':
    main()
