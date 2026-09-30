import json
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from scripts import dated_carry_analysis as analysis
from scripts import dated_carry_collector as collector
from scripts import dated_carry_endpoint as endpoint


class EndpointTests(unittest.TestCase):
    def test_wall_clock_jump_cannot_release_early_analysis(self):
        config = {'t0_utc': '2026-09-30T13:00:00+00:00'}
        t0 = collector.timestamp(config['t0_utc'])
        mapping = {'utc_ns': t0-1000, 'monotonic_ns': 1000, 't0_utc_ns': t0, 't0_monotonic_ns': 2000}
        identity = {'host': 'test', 'boot_id': 'fixture'}
        launch = {'mapping': dict(mapping, **identity)}
        end = t0 + collector.DURATION_NS
        with self.assertRaisesRegex(ValueError, 'monotonic_endpoint'):
            endpoint.launch_endpoint_check(config, launch, end, 3000, identity)
        with self.assertRaisesRegex(ValueError, 'identity_changed'):
            endpoint.launch_endpoint_check(config, launch, end, 2000+collector.DURATION_NS, {})
        self.assertEqual(endpoint.launch_endpoint_check(config, launch, end,
                          2000+collector.DURATION_NS, identity), end)

    def test_real_collector_launch_schema_reaches_endpoint(self):
        from tests.test_dated_carry_collector import Clock, config_for
        with tempfile.TemporaryDirectory() as directory:
            store = collector.Store(Path(directory))
            async def scenario():
                stop = asyncio.Event()
                clock = Clock(stop)
                config = config_for(clock)
                stop.set()
                async def no_fetch(*args):
                    raise AssertionError('no network')
                await collector.collect(config, store, clock=clock, fetch=no_fetch, stop=stop)
                return config
            config = asyncio.run(scenario())
            launch = json.loads((store.path / 'terminal/launch.json').read_bytes())
            mapping = launch['mapping']
            endpoint.launch_endpoint_check(config, launch,
                mapping['t0_utc_ns']+collector.DURATION_NS,
                mapping['t0_monotonic_ns']+collector.DURATION_NS, collector.clock_identity())

    def test_metadata_age_cannot_be_revived_by_wall_clock(self):
        config = {'metadata_receipts': [{'role': role, 'utc_ns': 100, 'monotonic_ns': 200}
                                        for role in ('spot', 'future')]}
        endpoint.metadata_age_check(config, 101, 201)
        for wall, mono in ((99, 201), (101, 120_000_000_201)):
            with self.assertRaisesRegex(ValueError, 'age_exceeded'):
                endpoint.metadata_age_check(config, wall, mono)

    def test_no_early_economic_readout(self):
        config = {'t0_utc': '2026-09-30T13:00:00+00:00'}
        end = collector.timestamp(config['t0_utc']) + collector.DURATION_NS
        with self.assertRaisesRegex(ValueError, 'not_reached'):
            endpoint.endpoint_check(config, end-1)
        self.assertEqual(endpoint.endpoint_check(config, end), end)

    def test_interrupted_roster_keeps_all_rows_and_rejects_duplicate(self):
        config = {'t0_utc': '2026-09-30T13:00:00+00:00'}
        with tempfile.TemporaryDirectory() as directory:
            store = collector.Store(Path(directory))
            index = store.index(config, 'interrupted')
            rows = endpoint.final_rows(config, store, index)
            self.assertEqual(len(rows), 3456)
            self.assertEqual(analysis.summarize(rows)['groups']['1000']['invalid'], 864)
            index['slots'][-1] = index['slots'][0]
            with self.assertRaisesRegex(ValueError, 'unique_roster'):
                endpoint.final_rows(config, store, index)

    def test_changed_stored_sample_rejected(self):
        config = {'t0_utc': '2026-09-30T13:00:00+00:00'}
        with tempfile.TemporaryDirectory() as directory:
            store = collector.Store(Path(directory))
            record = {'slot': 0, 'planned_utc_ns': collector.timestamp(config['t0_utc']),
                      'status': 'arrival_invalid'}
            store.sample(0, record)
            index = store.index(config, 'interrupted')
            sample = store.path / index['slots'][0]['file']
            sample.write_bytes(sample.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'hash/bytes'):
                endpoint.final_rows(config, store, index)

    def test_dead_collector_recovery_does_not_replace_prior_hash(self):
        config = {'t0_utc': '2026-09-30T13:00:00+00:00'}
        t0 = collector.timestamp(config['t0_utc'])
        identity = {'host': 'test', 'boot_id': 'fixture'}
        with tempfile.TemporaryDirectory() as directory:
            store = collector.Store(Path(directory))
            record = {'slot': 0, 'planned_utc_ns': t0, 'status': 'arrival_invalid'}
            store.sample(0, record)
            store.write('terminal', 'launch.json', collector.body({'clock_identity': identity,
                'mapping': {'utc_ns': t0-1000, 'monotonic_ns': 1000,
                            't0_utc_ns': t0, 't0_monotonic_ns': 2000, **identity}}))
            index = store.index(config, 'running')
            index_data = (store.path / 'terminal/index.json').read_bytes()
            sample = store.path / index['slots'][0]['file']
            sample.write_bytes(sample.read_bytes() + b'changed')
            args = SimpleNamespace(config=None, config_sha256='fixture', study_dir=store.path,
                                   freeze=None, freeze_sha256='fixture')
            with patch.object(collector, 'verify_freeze', return_value=(config, store)), \
                 patch.object(collector, 'clock_identity', return_value=identity), \
                 patch.object(endpoint.time, 'time_ns', return_value=t0+collector.DURATION_NS), \
                 patch.object(endpoint.time, 'monotonic_ns', return_value=2000+collector.DURATION_NS):
                with self.assertRaisesRegex(ValueError, 'hash/bytes'):
                    endpoint.finalize(args)
            self.assertEqual((store.path / 'terminal/index.json').read_bytes(), index_data)
            self.assertFalse((store.path / 'derived/summary.json').exists())


if __name__ == '__main__':
    unittest.main()
