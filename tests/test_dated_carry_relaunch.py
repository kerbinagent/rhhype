import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import dated_carry_collector as collector
from scripts import dated_carry_relaunch as relaunch


class RelaunchBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.enterContext(patch.object(collector, 'ROOT', root))
        self.retired = root / 'retired'
        self.fresh = root / 'fresh'
        (self.retired / 'source_control').mkdir(parents=True)
        (self.retired / 'terminal').mkdir()
        (root / 'external.py').write_bytes(b'v' * 1234)
        external = dict.fromkeys(collector.CAPS, 0)
        external['source_control'] = 1234
        freeze = collector.body({'external_bytes': external,
            'source_sha256': {'external.py': collector.digest(b'v' * 1234)},
            'metadata_sha256': {}})
        index = collector.body({'preserved': True})
        (self.retired / 'source_control/freeze.json').write_bytes(freeze)
        (self.retired / 'terminal/index.json').write_bytes(index)
        self.caps = dict(collector.CAPS)
        self.constants = copy.deepcopy(collector.CONSTANTS)
        self.store = collector.Store
        self.addCleanup(self.restore_collector)
        for name, value in {
            'RETIRED': self.retired, 'STUDY': self.fresh,
            'RETIRED_FREEZE_SHA': collector.digest(freeze),
            'RETIRED_INDEX_SHA': collector.digest(index),
        }.items():
            self.enterContext(patch.object(relaunch, name, value))

    def restore_collector(self):
        collector.CAPS.clear()
        collector.CAPS.update(self.caps)
        collector.CONSTANTS.clear()
        collector.CONSTANTS.update(self.constants)
        collector.CONSTANTS['caps'] = collector.CAPS
        collector.Store = self.store

    def test_combined_reservation_and_atomic_sample_peak_are_enforced(self):
        relaunch.install_budget()
        self.assertEqual(sum(collector.CAPS.values()) + relaunch.RETIRED_CAP, 16 << 20)
        store = collector.Store(self.fresh)
        (self.fresh / 'samples').mkdir(parents=True)
        old = self.fresh / 'samples/existing'
        with old.open('wb') as f:
            f.truncate((7 << 20) - 4)
        with self.assertRaises(collector.BudgetExceeded):
            store.write('samples', 'existing', b'12345678', replace=True)
        self.assertEqual(old.stat().st_size, (7 << 20) - 4)
        self.assertEqual(list((self.fresh / 'samples').iterdir()), [old])

    def test_retired_growth_blocks_next_fresh_write_without_deletion(self):
        relaunch.install_budget()
        store = collector.Store(self.fresh)
        store.write('terminal', 'first.json', b'{}')
        old = self.retired / 'samples'
        old.mkdir()
        with (old / 'preserved').open('wb') as f:
            f.truncate(1 << 20)
        with self.assertRaisesRegex(collector.BudgetExceeded, 'retired_run'):
            store.write('terminal', 'second.json', b'{}')
        self.assertFalse((self.fresh / 'terminal/second.json').exists())
        self.assertTrue((old / 'preserved').exists())

    def test_retired_index_cannot_be_replaced_or_reattested(self):
        relaunch.install_budget()
        store = collector.Store(self.fresh)
        (self.retired / 'terminal/index.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'last_index_changed'):
            store.write('terminal', 'claim.json', b'{}')
        self.assertFalse(self.fresh.exists())

    def test_retired_external_dependency_growth_is_not_unaccounted(self):
        relaunch.install_budget()
        store = collector.Store(self.fresh)
        (self.retired.parent / 'external.py').write_bytes(b'v' * 1235)
        with self.assertRaisesRegex(ValueError, 'source/metadata hash mismatch'):
            store.write('terminal', 'claim.json', b'{}')
        self.assertFalse(self.fresh.exists())

    def test_wrapper_rejects_retired_path(self):
        relaunch.install_budget()
        with self.assertRaisesRegex(ValueError, 'fresh_run_path'):
            collector.Store(self.retired)

    def test_budget_and_wrapper_pins_are_required(self):
        with self.assertRaisesRegex(ValueError, 'must_be_pinned'):
            relaunch.check_pins({'scripts/dated_carry_collector.py': 'fixture'})
        relaunch.check_pins(dict.fromkeys(relaunch.REQUIRED_PINS, 'fixture'))

    def test_original_entrypoint_cannot_match_new_frozen_constants(self):
        relaunch.install_budget()
        directory = self.fresh / 'source_control'
        directory.mkdir(parents=True)
        config_path = directory / 'config.json'
        config_path.write_bytes(b'{}')
        config_sha = collector.digest(b'{}')
        freeze_path = directory / 'freeze.json'
        config = {'source_sha256': {'external.py': collector.digest(b'v' * 1234)},
                  'metadata_sha256': {}}
        with patch.object(collector, 'load_config', return_value=config):
            collector.prepare(config_path, config_sha, self.fresh, freeze_path)
            freeze_sha = collector.digest(freeze_path.read_bytes())
            collector.verify_freeze(config_path, config_sha, self.fresh, freeze_path, freeze_sha)
            self.restore_collector()
            with self.assertRaisesRegex(ValueError, 'identity/runtime/pins mismatch'):
                collector.verify_freeze(config_path, config_sha, self.fresh, freeze_path, freeze_sha)


if __name__ == '__main__':
    unittest.main()
