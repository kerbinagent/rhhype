"""Persistent attribution of paper outcomes to the strategy that admitted them.

This bookkeeping never modifies execution ledgers, wallets, or capital limits.
"""
from __future__ import annotations

import copy
import ast
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
# Deliberately exclude monitor orchestration, observer instrumentation and UI.
STRATEGY_SOURCES = ('scripts/paper_engine.py', 'scripts/paper_strategies.py',
                    'scripts/paper_funding.py')
EXECUTION_HELPERS = ('common_step', 'affordable_quantity', 'walk')
RETAIN_CLOSED_EPOCHS = 16
MAX_PINNED_AND_ACTIVE_EPOCHS = 64
FIELDS = ('closed_trades', 'estimated_trades', 'closed_wins', 'closed_losses',
          'closed_pnl_exact', 'closed_pnl_estimated', 'closed_net_usd', 'fees_usd',
          'funding_usd', 'other_costs_usd', 'capital_costs_usd',
          'closed_winning_sum_usd', 'closed_losing_sum_usd')


def strategy_identity(config, selection=None, *, root=ROOT):
    """Execution configuration and explicit strategy sources define a version."""
    config = asdict(config) if hasattr(config, '__dataclass_fields__') else config
    identity = {'execution_config': config, 'selection': selection or {},
                'source_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                  for name in STRATEGY_SOURCES}}
    monitor_source = (root / 'scripts/monitor.py').read_text()
    helpers = {node.name: node for node in ast.parse(monitor_source).body
               if isinstance(node, ast.FunctionDef) and node.name in EXECUTION_HELPERS}
    if set(helpers) != set(EXECUTION_HELPERS):
        raise ValueError('strategy execution helper inventory incomplete')
    identity['execution_helper_sha256'] = {
        name: hashlib.sha256(ast.get_source_segment(monitor_source, helpers[name]).encode()).hexdigest()
        for name in EXECUTION_HELPERS}
    body = json.dumps(identity, sort_keys=True, separators=(',', ':'), allow_nan=False)
    identity['fingerprint'] = hashlib.sha256(body.encode()).hexdigest()
    return identity


def _zero():
    return {name: 0 for name in FIELDS}


class StrategyEpoch:
    def __init__(self, saved, identity, now, positions=(), ledgers=None):
        self.state = copy.deepcopy(saved) if saved else {
            'schema': 'paper-strategy-epochs-v1', 'epochs': [],
            'archived_epoch_count': 0, 'archived_totals': {},
            'legacy_settled_after_cutover': {},
            # Keep the old lifetime accounting as evidence of the cutover.
            'legacy_ledger_at_cutover': {
                tier: {key: value for key, value in row.items()
                       if key != 'wallets'} for tier, row in (ledgers or {}).items()}}
        if self.state.get('schema') != 'paper-strategy-epochs-v1':
            raise ValueError('unknown paper strategy epoch schema')
        self.identity = copy.deepcopy(identity)
        epochs = self.state['epochs']
        active = next((e for e in epochs if e['epoch_id'] == self.state.get('active_epoch_id')), None)
        if saved and active is None:
            raise ValueError('saved active strategy epoch is unavailable')
        if active is None or active['fingerprint'] != identity['fingerprint']:
            if active:
                active['ended_at'] = now
            active = {'epoch_id': uuid.uuid4().hex, 'version': identity['fingerprint'][:12],
                      'fingerprint': identity['fingerprint'], 'started_at': now,
                      'started_utc': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                      'identity': copy.deepcopy(identity), 'strategies': {}}
            epochs.append(active)
            self.state['active_epoch_id'] = active['epoch_id']
        self.prune(positions)

    @property
    def active(self):
        return self.require(self.state['active_epoch_id'])

    def require(self, epoch_id):
        if epoch_id == 'legacy':
            return None
        for epoch in self.state['epochs']:
            if epoch['epoch_id'] == epoch_id:
                return epoch
        raise ValueError('position references an unavailable strategy epoch')

    def tag_new(self, position):
        position['paper_epoch_id'] = self.active['epoch_id']
        position['paper_strategy_version'] = self.active['version']

    def tag_restored(self, position):
        if 'paper_epoch_id' not in position:
            position['paper_epoch_id'] = 'legacy'
            position['paper_strategy_version'] = 'legacy/unversioned'
        self.require(position['paper_epoch_id'])

    def closed(self, position):
        epoch = self.require(position['paper_epoch_id'])
        strategies = (epoch['strategies'] if epoch is not None else
                      self.state['legacy_settled_after_cutover'])
        row = strategies.setdefault(position['strategy'], _zero())
        estimated = position['status'] == 'CLOSED_ESTIMATED'
        net = position['net_pnl_usd']
        row['estimated_trades' if estimated else 'closed_trades'] += 1
        row['closed_pnl_estimated' if estimated else 'closed_pnl_exact'] += net
        row['closed_net_usd'] += net
        for field in ('fees_usd', 'funding_usd', 'other_costs_usd', 'capital_costs_usd'):
            row[field] += position[field]
        if net > 0:
            row['closed_wins'] += 1
            row['closed_winning_sum_usd'] += net
        elif net < 0:
            row['closed_losses'] += 1
            row['closed_losing_sum_usd'] += net

    def prune(self, positions):
        pinned = {p.get('paper_epoch_id', 'legacy') for p in positions}
        completed = [e for e in self.state['epochs']
                     if e['epoch_id'] != self.state['active_epoch_id'] and e['epoch_id'] not in pinned]
        for epoch in completed[:-RETAIN_CLOSED_EPOCHS]:
            for tier, values in epoch['strategies'].items():
                totals = self.state['archived_totals'].setdefault(tier, _zero())
                for field in FIELDS:
                    totals[field] += values[field]
            self.state['epochs'].remove(epoch)
            self.state['archived_epoch_count'] += 1
        pinned_or_active = sum(e['epoch_id'] == self.state['active_epoch_id'] or
                               e['epoch_id'] in pinned for e in self.state['epochs'])
        if pinned_or_active > MAX_PINNED_AND_ACTIVE_EPOCHS:
            raise ValueError('too many paper epochs with outstanding positions; rollout must pause')

    def export(self, positions):
        self.prune(positions)
        return copy.deepcopy(self.state)

    def snapshot(self, engine, lifetime, now):
        strategies = {}
        carryover = {'active_positions': 0, 'pending_entries': 0, 'pending_funding': 0,
                     'reserved_usd': 0, 'remaining_quantity_by_market': {}}
        for tier in engine.ledgers:
            current = [p for p in engine.positions.values() if p['strategy'] == tier
                       and p['paper_epoch_id'] == self.active['epoch_id']]
            marked = [engine.liquidation(p, now) for p in current if p['status'] != 'AWAITING_FUNDING']
            strategies[tier] = {**_zero(), **self.active['strategies'].get(tier, {}),
                'open_liquidation_pnl': sum(marked) if all(m is not None for m in marked) else None,
                'open_positions': sum(any(l['remaining'] > 0 for l in p['legs']) for p in current),
                'pending_funding': sum(p['status'] == 'AWAITING_FUNDING' for p in current)}
        for p in engine.positions.values():
            if p['paper_epoch_id'] == self.active['epoch_id']:
                continue
            carryover['active_positions'] += any(l['remaining'] > 0 for l in p['legs'])
            carryover['pending_entries'] += p['status'] == 'ENTRY_PENDING'
            carryover['pending_funding'] += p['status'] == 'AWAITING_FUNDING'
            # Display original obligations; spendable venue collateral remains
            # the engine's own (possibly unknown) full-wallet calculation.
            carryover['reserved_usd'] += sum(p['reserved'].values())
            for leg in p['legs']:
                if leg['remaining'] > 0:
                    k = leg['key'] + ':' + leg['side']
                    carryover['remaining_quantity_by_market'][k] = (
                        carryover['remaining_quantity_by_market'].get(k, 0) + leg['remaining'])
        return {'version': self.active['version'], 'epoch_id': self.active['epoch_id'],
                'started_at': self.active['started_at'], 'started_utc': self.active['started_utc'],
                'strategies': strategies, 'carryover': carryover,
                'wallets_all_versions': {
                    tier: {'wallet_cash_usd': row['wallet_cash_usd'], 'wallets': row['wallets'],
                           'available_collateral_by_venue': {
                               venue: engine.cash_available(tier, venue, now)
                               for venue in row['wallets']}}
                    for tier, row in lifetime.items()},
                'fees_scope': 'settled_closed_trades_only',
                'historical_epoch_count': len(self.state['epochs']) - 1,
                'archived_epoch_count': self.state['archived_epoch_count']}
