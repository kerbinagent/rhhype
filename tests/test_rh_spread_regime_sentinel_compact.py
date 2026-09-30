"""Offline resource fixtures: actual admission path, no public requests or quotes."""
import asyncio
from contextlib import contextmanager
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import rh_spread_regime_sentinel_compact as compact

m = compact.frozen
FIXTURE = m.ROOT / 'reports/rh-spread-regime-sentinel/20260930T0755Z'
EXPECTED_METADATA = {
    'rh_order_book_details': '8c2903763eabfac8fe7877453e18573152d51885aead4b1175c5556ce1137974',
    'hl_meta_native': 'f613bc079a469463cce7c83b7071d09e6285c05392d6f8623197f8138362e97b',
    'hl_meta_xyz': '245ccab2d2c8843ef10d3f62711ec6d52b433b38ad853a8f8492ac3f7ee571aa',
}


def control_bytes(path):
    entries = json.loads((path / 'storage.json').read_bytes())
    return sum(v['bytes'] for v in entries.values() if v['category'] == 'control') + (path / 'storage.json').stat().st_size


def rows(path):
    return list(csv.DictReader(io.StringIO(gzip.decompress((path / 'observations.csv.gz').read_bytes()).decode())))


class FakeClock:
    def __init__(self, requests):
        first = next(iter(requests.values()))
        self.now = first['started_ns']
        self.mono = first['completed_mono_ns'] - (first['completed_ns'] - self.now)
        self.deadlines = []

    def completed(self, request):
        self.now, self.mono = request['completed_ns'], request['completed_mono_ns']

    async def wait(self, deadline, stop):
        if stop.is_set():
            return False
        if deadline < self.mono:
            raise AssertionError('fixed schedule moved backwards')
        self.now += deadline - self.mono
        self.mono = deadline
        self.deadlines.append(deadline)
        # Let the real receiver create/close its fake socket before sampling.
        for _ in range(3):
            await asyncio.sleep(0)
        return not stop.is_set()


class FakeNetwork:
    def __init__(self, clock, requests, metadata):
        self.clock, self.requests, self.metadata = clock, requests, metadata
        self.http = []
        self.sockets = []
        self.subscriptions = []
        self.path = None

    def session(self, timeout):
        network = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def request(self, method, url, **kwargs):
                if timeout != 20 or len(network.http) >= 3:
                    raise AssertionError('unexpected HTTP attempt')
                name = tuple(m.REQUESTS)[len(network.http)]
                expected_method, expected_url, expected_body = m.REQUESTS[name]
                if (method, url, kwargs) != (expected_method, expected_url, {'json': expected_body, 'allow_redirects': False}):
                    raise AssertionError('HTTP route or redirect policy changed')
                network.http.append(name)

                class Content:
                    async def iter_chunked(self, size):
                        raw = network.metadata[name]
                        for k in range(0, len(raw), size):
                            yield raw[k:k + size]
                        network.clock.completed(network.requests[name])

                class Response:
                    status = 200
                    content = Content()

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        return False

                return Response()

            def ws_connect(self, url, **kwargs):
                if timeout != 10 or network.sockets:
                    raise AssertionError('unexpected websocket attempt')
                if url != m.WS or kwargs != {'max_msg_size': 32768, 'autoping': False}:
                    raise AssertionError('websocket route or protocol policy changed')
                admitted = control_bytes(network.path)
                if admitted > 80000:
                    raise AssertionError('actual control admission exceeded')
                network.sockets.append(admitted)

                class Socket:
                    close_code = 1000

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        return False

                    async def send_json(self, payload):
                        if payload.get('type') != 'subscribe':
                            raise AssertionError('unexpected outbound fake message')
                        network.subscriptions.append(payload)

                    def __aiter__(self):
                        return self

                    async def __anext__(self):
                        # Closed socket is a technical stop; run must still reach endpoint.
                        raise StopAsyncIteration

                    async def close(self):
                        pass

                return Socket()

        return Session()


@contextmanager
def environment():
    requests = json.loads((FIXTURE / 'requests.json').read_bytes())
    metadata = {name: (FIXTURE / (name + '.json')).read_bytes() for name in m.REQUESTS}
    for name, raw in metadata.items():
        if hashlib.sha256(raw).hexdigest() != EXPECTED_METADATA[name]:
            raise AssertionError('failed-stage fixture metadata changed')
    before = {str(p): m.sha(p) for p in FIXTURE.iterdir() if p.is_file()}
    clock = FakeClock(requests)
    network = FakeNetwork(clock, requests, metadata)
    with TemporaryDirectory(prefix='sentinel-offline-resource-') as t:
        path = Path(t)
        network.path = path

        def temporary_path(candidate, new=False):
            if Path(candidate) != path:
                raise AssertionError('fixture escaped temporary directory')
            if new and any(path.iterdir()):
                raise AssertionError('fixture attempted stage retry')
            return path

        with patch.object(m, 'stage_path', side_effect=temporary_path), \
             patch.object(m, 'client_session', side_effect=network.session), \
             patch.object(m, 'utc', side_effect=lambda: clock.now), \
             patch.object(m.time, 'monotonic_ns', side_effect=lambda: clock.mono), \
             patch.object(m, 'wait_deadline', side_effect=clock.wait), \
             patch('sys.stdout', new_callable=io.StringIO):
            yield path, clock, network
    if before != {str(p): m.sha(p) for p in FIXTURE.iterdir() if p.is_file()}:
        raise AssertionError('immutable failed stage changed')


class CompactSentinelTests(unittest.TestCase):
    def test_actual_compact_run_admission_endpoint_and_all_caps(self):
        old = (m.Store, m.dependencies)
        with environment() as (path, clock, network), compact.installed():
            before = m.input_hashes()
            self.assertEqual(len(before), 8)
            asyncio.run(m.prepare(path))
            m.freeze(path)
            asyncio.run(m.run(path))
            self.assertEqual(network.http, list(m.REQUESTS))
            self.assertEqual(len(network.sockets), 1)
            self.assertLessEqual(network.sockets[0], 80000)
            self.assertEqual(network.subscriptions, [{'type': 'subscribe', 'channel': 'ticker/' + r['reference']['rh_market']}
                                                      for r in json.loads((path / 'eligibility.json').read_bytes())])
            self.assertEqual(len(network.subscriptions), 21)
            schedule = json.loads((path / 'schedule.json').read_bytes())
            self.assertEqual(set(schedule), {'run_activation_utc_ns', 'run_activation_mono_ns', 't0_utc_ns', 't0_mono_ns',
                                            'endpoint_utc_ns', 'endpoint_mono_ns', 'slot_count', 'interval_ns', 'max_dispatch_lateness_ns'})
            self.assertEqual(clock.deadlines, [schedule['t0_mono_ns'] + k * 60 * m.NS for k in range(20)] + [schedule['endpoint_mono_ns']])
            samples = [json.loads(line) for line in gzip.decompress((path / 'samples.jsonl.gz').read_bytes()).splitlines()]
            self.assertEqual(len(samples), 420)
            self.assertEqual({(s['k'], s['asset']) for s in samples}, {(k, a) for k in range(20) for a in m.ASSETS})
            result = rows(path)
            self.assertEqual(len(result), 1680)
            self.assertEqual({(int(r['k']), r['asset'], int(r['budget'])) for r in result}, {(k, a, b) for k in range(20) for a in m.ASSETS for b in m.BUDGETS})
            self.assertFalse(any(r['optimistic_budget'] for r in result))
            manifest = json.loads((path / 'manifest.json').read_bytes())
            self.assertEqual(manifest['status'], 'incomplete')
            self.assertTrue(manifest['economic_endpoint_reached'])
            self.assertEqual(manifest['input_hashes'], before)
            self.assertEqual(m.input_hashes(), before)
            self.assertEqual(json.loads((path / 'root-freeze.json').read_bytes())['inputs'], before)
            self.assertEqual(json.loads((path / 'source-freeze.json').read_bytes())['resource_wrapper'], compact.MARKER)
            m.Store(path).verify()
            self.assertLessEqual(control_bytes(path), 90000)
            self.assertLessEqual(sum(p.stat().st_size for p in path.iterdir()), 500000)
            self.assertFalse(any((path / name).exists() for name in ('source.py', 'method.md', 'tests.py')))
            self.assertEqual(m.BUDGETS, (100, 250, 500, 1000))
            self.assertEqual(m.LIMITS, {'control': 90000, 'metadata': 280000, 'samples': 80000, 'derived': 40000, 'logs': 10000})
        self.assertEqual((m.Store, m.dependencies), old)

    def test_uncompressed_real_run_reproduces_zero_ws_admission_failure(self):
        with environment() as (path, clock, network):
            asyncio.run(m.prepare(path))
            m.freeze(path)
            asyncio.run(m.run(path))
            self.assertEqual(network.sockets, [])
            self.assertEqual(network.http, list(m.REQUESTS))
            self.assertTrue((path / 'schedule.json').exists())
            self.assertGreater(control_bytes(path), 80000)
            self.assertLessEqual(control_bytes(path), 90000)
            failure = json.loads((path / 'failure.json').read_bytes())
            self.assertEqual(failure['reason'], 'pre_ws_control_finalization_reserve')
            self.assertFalse(failure['economics_evaluated'])
            self.assertEqual(len(rows(path)), 1680)
            self.assertFalse((path / 'samples.jsonl.gz').exists())

    def test_old_marked_gate_and_override_restoration(self):
        old = (m.Store, m.dependencies)
        with self.assertRaisesRegex(ValueError, 'requires_new_compact_marked_stage'):
            with compact.installed():
                m.Store(FIXTURE)
        self.assertEqual((m.Store, m.dependencies), old)
        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            with compact.installed():
                raise RuntimeError('synthetic')
        self.assertEqual((m.Store, m.dependencies), old)

    def test_archive_corruption_rejected_even_if_storage_index_rehashed(self):
        with environment() as (path, clock, network), compact.installed():
            asyncio.run(m.prepare(path))
            original = (path / 'wrapper.py.gz').read_bytes()
            altered = gzip.compress(b'wrong decoded archive', mtime=0)
            (path / 'wrapper.py.gz').write_bytes(altered)
            index = json.loads((path / 'storage.json').read_bytes())
            index['wrapper.py.gz'].update(bytes=len(altered), sha256=hashlib.sha256(altered).hexdigest())
            (path / 'storage.json').write_bytes(m.encoded(index))
            with self.assertRaisesRegex(ValueError, 'compressed_source_identity'):
                m.Store(path)
            self.assertNotEqual(altered, original)
            self.assertEqual(len(network.http), 3)
            self.assertFalse(network.sockets)

    def test_archive_decode_bound(self):
        with TemporaryDirectory() as t:
            path = Path(t)
            big = b'x' * (compact.MAX_ARCHIVE_DECODED + 1)
            packed = gzip.compress(big, mtime=0)
            (path / 'oversize.gz').write_bytes(packed)
            inventory = {'oversize.gz': {'compressed_bytes': len(packed), 'compressed_sha256': hashlib.sha256(packed).hexdigest(),
                                         'decoded_bytes': len(big), 'decoded_sha256': hashlib.sha256(big).hexdigest()}}
            versions = {'resource_wrapper': compact.MARKER, 'overrides': ['Store', 'dependencies'], 'archived_sources': inventory,
                        'input_hashes': {str(p): m.sha(p) for p in compact.dependencies()}}
            with patch.object(compact, 'archive_inventory', return_value=inventory):
                with self.assertRaisesRegex(m.CapReached, 'archived_source_decoded_cap'):
                    compact.verify_archives(path, versions)

    def test_same_eight_hashes_rechecked_and_exception_preserved(self):
        old = (m.Store, m.dependencies)
        with TemporaryDirectory() as t:
            note = Path(t) / 'resource-note.md'
            with patch.object(compact, 'NOTE', note):
                note.write_text('initial')
                with self.assertRaisesRegex(ValueError, 'source_or_reference_changed'):
                    with compact.installed():
                        self.assertEqual(len(m.input_hashes()), 8)
                        note.write_text('changed')
                self.assertEqual((m.Store, m.dependencies), old)
                note.write_text('initial')
                with self.assertRaisesRegex(RuntimeError, 'delegated failure') as result:
                    with compact.installed():
                        note.write_text('changed')
                        raise RuntimeError('delegated failure')
                self.assertTrue(any('postdelegation_dependency_verification_failed' in n for n in result.exception.__notes__))
                self.assertEqual((m.Store, m.dependencies), old)


if __name__ == '__main__':
    unittest.main()
