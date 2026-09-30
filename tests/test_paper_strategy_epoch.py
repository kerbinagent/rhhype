"""Current strategy attribution survives carryover, restart, and retention."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_paper_engine import book, pair
from paper_engine import EngineConfig, PaperEngine
from paper_exit_observer import ObservedPaperEngine
from paper_store import PaperStore
from paper_strategy_epoch import (strategy_identity, StrategyEpoch, STRATEGY_SOURCES,
                                  RETAIN_CLOSED_EPOCHS, MAX_PINNED_AND_ACTIVE_EPOCHS)
from paper_ui import tui_lines


def identity(version):
    return {'fingerprint': version * 64, 'execution_config': {}, 'source_sha256': {}}


def observed(state=None, version='a', now=1000):
    return ObservedPaperEngine([pair()], EngineConfig(strategies=('standard',), capital_rate=0),
                               state=state, now=now, strategy_identity=identity(version))


def pending(engine, ident, *, net=2, fees=0.5):
    position = {'id': ident, 'strategy': 'standard', 'pair_id': ident, 'asset': 'BTC',
                'status': 'AWAITING_FUNDING', 'created_at': 1000, 'closed_at': 1005,
                'opened_at': 1000, 'reserved': {'hyperliquid': 10, 'rh_lighter': 10},
                'price_net_before_funding': net, 'fees_usd': fees,
                'other_costs_usd': 0.2, 'capital_costs_usd': 0,
                'legs': [{'key': 'hyperliquid:BTC', 'venue': 'hyperliquid', 'side': 'long',
                          'market': 'BTC', 'quantity': 1, 'remaining': 0, 'entry_time': 1000},
                         {'key': 'rh_lighter:1', 'venue': 'rh_lighter', 'side': 'short',
                          'market': 1, 'quantity': 1, 'remaining': 0, 'entry_time': 1000}]}
    engine.positions[ident] = position
    engine._index_position(position)
    return position


def settle(engine, ident, estimated=False):
    engine.settle_funding(ident, {'complete': True, 'cashflow_usd': 0,
                                 'estimated': estimated, 'events': []}, 1010)


class EpochAccountingTests(unittest.TestCase):
    def test_position_is_tagged_before_initial_transition(self):
        engine = observed()
        engine.receive(book('hyperliquid', 'BTC', 1000, 99.99, 100))
        engine.receive(book('rh_lighter', 1, 1000, 102, 102.01))
        engine.tick(1000)
        position = next(iter(engine.positions.values()))
        self.assertEqual(position['paper_epoch_id'], engine.paper_epoch.active['epoch_id'])
        self.assertEqual(engine.transitions[-1]['paper_epoch_id'], position['paper_epoch_id'])

    def test_current_closed_totals_exact_estimated_and_no_duplicate(self):
        engine = observed()
        pending(engine, 'win', net=4, fees=0.6)
        pending(engine, 'loss', net=-1, fees=0.3)
        settle(engine, 'win')
        settle(engine, 'loss', estimated=True)
        settle(engine, 'win')
        row = engine.snapshot(1011)['paper_strategy_epoch']['strategies']['standard']
        self.assertEqual((row['closed_trades'], row['estimated_trades'], row['closed_wins']), (1, 1, 1))
        self.assertEqual((row['closed_pnl_exact'], row['closed_pnl_estimated'], row['closed_net_usd']), (4, -1, 3))
        self.assertAlmostEqual(row['fees_usd'], 0.9)
        self.assertEqual(row['other_costs_usd'], 0.4)

    def test_preinstrumentation_positions_never_become_current(self):
        base = PaperEngine([pair()], EngineConfig(strategies=('standard',)), now=1000)
        old = pending(base, 'legacy', net=99)
        base.ledgers['standard']['closed_pnl_exact'] = 500
        wallets = copy.deepcopy(base.ledgers['standard']['wallets'])
        engine = observed(copy.deepcopy(base.export_state()), now=1006)
        self.assertEqual(engine.positions['legacy']['paper_epoch_id'], 'legacy')
        before = engine.snapshot(1007)['paper_strategy_epoch']
        self.assertEqual(before['carryover']['pending_funding'], 1)
        self.assertEqual(engine.ledgers['standard']['wallets'], wallets)
        settle(engine, 'legacy')
        row = engine.snapshot(1011)['paper_strategy_epoch']['strategies']['standard']
        self.assertEqual(row['closed_trades'], 0)
        self.assertEqual(row['closed_net_usd'], 0)
        self.assertEqual(row['fees_usd'], 0)
        self.assertEqual(engine.ledgers['standard']['closed_pnl_exact'], 599)
        self.assertEqual(engine.paper_epoch.state['legacy_settled_after_cutover']['standard']['closed_net_usd'], 99)

    def test_version_change_pins_old_open_positions_and_excludes_later_settlement(self):
        old = observed()
        pending(old, 'old', net=20)
        old_epoch = old.paper_epoch.active['epoch_id']
        current = observed(copy.deepcopy(old.export_state()), version='b', now=1006)
        self.assertNotEqual(current.paper_epoch.active['epoch_id'], old_epoch)
        self.assertEqual(current.positions['old']['paper_epoch_id'], old_epoch)
        pending(current, 'new', net=3)
        settle(current, 'old')
        settle(current, 'new')
        row = current.snapshot(1011)['paper_strategy_epoch']['strategies']['standard']
        self.assertEqual((row['closed_trades'], row['closed_net_usd'], row['fees_usd']), (1, 3, 0.5))
        self.assertEqual(current.paper_epoch.require(old_epoch)['strategies']['standard']['closed_net_usd'], 20)
        self.assertEqual(current.ledgers['standard']['closed_pnl_exact'], 23)

    def test_runtime_reindex_never_retags_restored_origin(self):
        old = observed()
        pending(old, 'old')
        origin = old.paper_epoch.active['epoch_id']
        current = observed(copy.deepcopy(old.export_state()), version='b', now=1006)
        position = current.positions['old']
        current._index_position(position)
        self.assertEqual(position['paper_epoch_id'], origin)
        settle(current, 'old')
        self.assertEqual(current.paper_epoch.active['strategies'], {})
        self.assertEqual(current.paper_epoch.require(origin)['strategies']['standard']['closed_trades'], 1)

    def test_public_runtime_restore_keeps_old_origin_and_uses_current_version(self):
        old = observed()
        pending(old, 'old', net=20)
        origin = old.paper_epoch.active['epoch_id']
        current = observed(version='b', now=1006)
        current.restore(copy.deepcopy(old.export_state()))
        self.assertEqual(current.positions['old']['paper_epoch_id'], origin)
        self.assertEqual(current.paper_epoch.active['version'], 'b' * 12)
        settle(current, 'old')
        self.assertEqual(current.paper_epoch.active['strategies'], {})
        self.assertEqual(current.paper_epoch.require(origin)['strategies']['standard']['closed_net_usd'], 20)

    def test_cumulative_counters_exceed_5000_and_survive_state_restore(self):
        engine = observed()
        for index in range(5001):
            pending(engine, f'trade-{index}', net=2)
            settle(engine, f'trade-{index}')
            engine.drain()
        restored = observed(copy.deepcopy(engine.export_state()), now=2000)
        row = restored.snapshot(2000)['paper_strategy_epoch']['strategies']['standard']
        self.assertEqual((row['closed_trades'], row['closed_wins'], row['closed_net_usd']), (5001, 5001, 10002))
        self.assertEqual(row['fees_usd'], 2500.5)

    def test_restart_and_sliding_store_retention_preserve_current_totals(self):
        engine = observed()
        for index in range(6):
            pending(engine, str(index), net=2)
            settle(engine, str(index))
        original_epoch = copy.deepcopy(engine.paper_epoch.active)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'paper.sqlite3'
            store = PaperStore(path, {}, max_trades=1, window_seconds=1)
            store.checkpoint({'engine': engine.export_state()}, trades=engine.transitions)
            store.maintenance()
            self.assertEqual(store.snapshot()['retained_trades'], 0)
            saved = store.load_state()['engine']
            store.close()
            reopened = PaperStore(path, {}, max_trades=1, window_seconds=1)
            restored = observed(reopened.load_state()['engine'], now=2000)
            reopened.close()
        self.assertEqual(restored.paper_epoch.active['epoch_id'], original_epoch['epoch_id'])
        self.assertEqual(restored.paper_epoch.active['started_at'], 1000)
        row = restored.snapshot(2000)['paper_strategy_epoch']['strategies']['standard']
        self.assertEqual((row['closed_trades'], row['closed_net_usd']), (6, 12))

    def test_unresolved_funding_is_unknown_and_wallet_collateral_remains_full_state(self):
        engine = observed()
        p = pending(engine, 'unknown')
        engine.settle_funding('unknown', {'complete': False, 'cashflow_usd': None}, 1010)
        snap = engine.snapshot(1011)
        row = snap['paper_strategy_epoch']['strategies']['standard']
        self.assertEqual((row['closed_trades'], row['pending_funding']), (0, 1))
        full = snap['paper_strategy_epoch']['wallets_all_versions']['standard']
        self.assertEqual(full['wallets'], engine.ledgers['standard']['wallets'])
        self.assertEqual(full['available_collateral_by_venue']['hyperliquid'],
                         engine.cash_available('standard', 'hyperliquid', 1011))
        self.assertIn('unknown', engine.positions)

    def test_old_active_unrealized_is_excluded_and_quantity_remains_visible(self):
        base = PaperEngine([pair()], EngineConfig(strategies=('standard',)), now=1000)
        p = pending(base, 'old-active')
        p['status'] = 'OPEN'
        p['exit_due'] = 2000
        for leg in p['legs']:
            leg.update(remaining=1, fee_bps=0, entry_value=100, entry_vwap=100,
                       price_pnl=0, fees_usd=0, exit_fills=[], exit_time=None)
        engine = observed(copy.deepcopy(base.export_state()), now=1010)
        engine.receive(book('hyperliquid', 'BTC', 1010, 90, 91))
        engine.receive(book('rh_lighter', 1, 1010, 109, 110))
        snap = engine.snapshot(1010)['paper_strategy_epoch']
        self.assertEqual(snap['strategies']['standard']['open_liquidation_pnl'], 0)
        self.assertEqual(snap['carryover']['active_positions'], 1)
        self.assertEqual(snap['carryover']['remaining_quantity_by_market']['hyperliquid:BTC:long'], 1)


class EpochIdentityTests(unittest.TestCase):
    def test_source_and_execution_config_change_version_but_ui_edit_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            for name in STRATEGY_SOURCES:
                (root / name).write_text('strategy')
            monitor = root / 'scripts/monitor.py'
            monitor.write_text('def common_step(a, b): return a\n'
                               'def affordable_quantity(a, b): return b\n'
                               'def walk(a, b): return a\n')
            config = EngineConfig()
            first = strategy_identity(config, root=root)['fingerprint']
            (root / 'scripts/paper_ui.py').write_text('viewer edit')
            (root / 'scripts/paper_exit_observer.py').write_text('observer edit')
            self.assertEqual(strategy_identity(config, root=root)['fingerprint'], first)
            monitor.write_text(monitor.read_text() + '\ndef draw(): return "UI edit"\n')
            self.assertEqual(strategy_identity(config, root=root)['fingerprint'], first)
            original_monitor = monitor.read_text()
            monitor.write_text(original_monitor.replace('def walk(a, b): return a', 'def walk(a, b): return b'))
            self.assertNotEqual(strategy_identity(config, root=root)['fingerprint'], first)
            monitor.write_text(original_monitor)
            self.assertNotEqual(strategy_identity(replace(config, holding_seconds=10), root=root)['fingerprint'], first)
            self.assertNotEqual(strategy_identity(config, {'hl_fee_bps': 3}, root=root)['fingerprint'], first)
            (root / STRATEGY_SOURCES[0]).write_text('changed strategy')
            self.assertNotEqual(strategy_identity(config, root=root)['fingerprint'], first)

    def test_history_bounded_with_archived_totals_and_pinned_obligations(self):
        epoch = StrategyEpoch(None, identity('a'), 1000)
        pinned = epoch.active['epoch_id']
        position = {'paper_epoch_id': pinned}
        for index in range(25):
            epoch = StrategyEpoch(epoch.export([position]), {'fingerprint': str(index)},
                                  1001 + index, [position])
        self.assertIsNotNone(epoch.require(pinned))
        self.assertLessEqual(len(epoch.state['epochs']), RETAIN_CLOSED_EPOCHS + 2)
        self.assertGreater(epoch.state['archived_epoch_count'], 0)

    def test_pinned_overflow_fails_explicitly(self):
        epoch = StrategyEpoch(None, identity('a'), 1000)
        positions = []
        for index in range(MAX_PINNED_AND_ACTIVE_EPOCHS - 1):
            positions.append({'paper_epoch_id': epoch.active['epoch_id']})
            epoch = StrategyEpoch(epoch.export(positions), {'fingerprint': str(index)},
                                  1001 + index, positions)
        positions.append({'paper_epoch_id': epoch.active['epoch_id']})
        with self.assertRaisesRegex(ValueError, 'outstanding positions'):
            StrategyEpoch(epoch.export(positions), {'fingerprint': 'overflow'}, 2000, positions)


class EpochUiTests(unittest.TestCase):
    def test_latest_only_with_version_start_wallet_and_stress_labels(self):
        engine = observed()
        pending(engine, 'new', net=3)
        settle(engine, 'new')
        engine.ledgers['standard']['closed_pnl_exact'] += 987654
        snapshot = engine.snapshot(1011)
        snapshot.update(status='running', updated_at=1, feeds={'hyperliquid': {'status': 'stale'}},
                        cost_assumptions={'extra_cost_bps': 5})
        joined = '\n'.join(tui_lines(snapshot, 80, 30))
        self.assertIn('Version aaaaaaaaaaaa', joined)
        self.assertIn('since 1970-01-01 00:16Z', joined)
        self.assertIn('Current version only', joined)
        self.assertIn('Net incl.stress', joined)
        self.assertIn('Stress allowance 5 bp', joined)
        self.assertIn('Sum cash/free (all):', joined)
        self.assertIn('cash/free sums not pooled', joined)
        self.assertIn('Carryover, older versions', joined)
        self.assertIn('update ', joined)
        self.assertIn('HL stale', joined)
        self.assertNotIn('987', joined)
        self.assertIn('+3.00', joined)
        self.assertIn('+0.50', joined)

    def test_versioned_view_fits_terminals_and_sanitizes(self):
        engine = observed()
        snapshot = engine.snapshot(1011)
        snapshot['paper_strategy_epoch']['version'] = '\033[31m\n界'
        for width, height in ((120, 30), (80, 24), (50, 20), (30, 12), (1, 1)):
            lines = tui_lines(snapshot, width, height)
            self.assertLessEqual(len(lines), max(1, height - 1))
            self.assertTrue(all(len(line) <= max(1, width - 1) for line in lines))
            self.assertTrue(all(32 <= ord(c) < 127 for line in lines for c in line))

    def test_narrow_view_keeps_start_time_and_packed_footer_counts_original_signals(self):
        engine = observed()
        snapshot = engine.snapshot(1011)
        snapshot['top_signals'] = [{'asset': f'ASSET{i}', 'strategy': 'standard',
                                    'net_edge_usd': i} for i in range(6)]
        narrow = '\n'.join(tui_lines(snapshot, 50, 20))
        self.assertIn('Since 1970-01-01 00:16Z', narrow)
        # One strategy means nine fixed rows; this height fits one paired row
        # and the footer. Two rendered cells out of six original signals.
        packed = '\n'.join(tui_lines(snapshot, 80, 12))
        self.assertIn('Showing 2/6 signals', packed)

    def test_full_eight_strategies_and_ten_signals_fit_80_by_24(self):
        engine = observed()
        engine.enable_shadows(now=1000)
        # Include every fee tier, as in the production collector.
        template = copy.deepcopy(engine.ledgers['standard'])
        engine.ledgers.update(plus=copy.deepcopy(template), premium=copy.deepcopy(template))
        snapshot = engine.snapshot(1011)
        snapshot.update(status='running', updated_at=1, cost_assumptions={'extra_cost_bps': 5},
                        feeds={'hyperliquid': {'status': 'stale'}}, top_signals=[
                            {'asset': f'ASSET{i}', 'strategy': 'standard', 'net_edge_usd': i,
                             'net_edge_bps': i, 'timestamp': 1000} for i in range(10)])
        lines = tui_lines(snapshot, 80, 24)
        joined = '\n'.join(lines)
        self.assertEqual(len(lines), 23)
        self.assertTrue(all(len(line) <= 79 for line in lines))
        for name in ('Standard', 'Plus', 'Premium', 'Shadow base', 'Cooldown',
                     'Convergence', 'Conservative', 'Confirmed'):
            self.assertIn(name, joined)
        for index in range(10):
            self.assertIn(f'ASSET{index}', joined)
        self.assertIn('Carryover, older versions', joined)
        self.assertIn('Stress allowance 5 bp', joined)
        self.assertIn('HL stale', joined)
        self.assertIn('Conf ', joined)


if __name__ == '__main__':
    unittest.main()
