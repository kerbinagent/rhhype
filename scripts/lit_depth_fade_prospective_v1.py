#!/usr/bin/env python3
"""Default-dry preparation for two fixed LIT depth cohorts; no collector or orders."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
from contextlib import contextmanager
import csv
from decimal import Decimal as D
import gzip
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import news_candidate_rolling_v1 as old
fix, rolling, strategy = old.fix, old.rolling, old.strategy
SOURCE = 'scripts/lit_depth_fade_prospective_v1.py'
TEST = 'tests/test_lit_depth_fade_prospective_v1.py'
DESIGN = 'reports/lit-depth-fade-prospective-v1/design.txt'
PLAN = ROOT / 'reports/experiment-storage/lit-depth-fade-prospective-v1.json'
OUT = ROOT / 'reports/lit-depth-fade-prospective-v1/run-v1'
ALLOCATION = {'path': 'reports/experiment-storage/lit-depth-fade-prospective-preparation-v1.json',
              'bytes': 5850, 'sha256': '83f012d4726ee58c41a6788736dab39a160418e1997f8bbf2eef3480b4a3c793'}
SCHEMA = 'lit-depth-fade-prospective-v1'
NUMBERS = (96, 100)
NS = 10**9
FREEZE_NS = 1790966400000000000  # 2026-10-02T18:40:00Z
DEADLINES = {96: 1790972100000000000, 100: 1790974800000000000}  # 20:15 / 21:00 UTC
HARD_END_NS = DEADLINES[100] + 3600 * NS
ANALYSIS_SECONDS, CHILD_SECONDS, CPU_SECONDS, RAM_BYTES = 1900, 600, 570, 4 * 1024**3
ASSETS, VENUES, RULES = ('LIT',), ('lighter', 'rh_lighter'), ('depth_fade', 'depth_follow')
BOUNDS, CAPS = dict(old.BOUNDS), dict(old.CAPS, controls=32768)
CATEGORIES = dict(comparisons=98304, controls_allocation_reviews_receipts=98304,
                  margin=294912, readouts=32768,
                  source_tests_design_draft_final_and_sequential_fixtures=262144,
                  two_ledger_directories=262144)
CONTROL_SHARES = dict(per_chunk=32768, shared_runtime=16384, outside_allocation_reviews=16384,
                      shared_nonfinal=8192, shared_final_reserve=8192)
BASE_CONFIGURE = old.configure
BASE_SNAPSHOT = old.input_snapshot
BASE_STORE = old.store_identity


def require(test, reason):
    if not test:
        raise ValueError(reason)


def read(path, cap=32768):
    return old.read(path, cap)


def chunk_name(n):
    require(n in NUMBERS, 'fixed_chunk_number')
    return f'chunk-{n:06d}'


def stem(n):
    return f'lit-depth-fade-prospective-v1-{n:06d}'


def controls(n):
    return OUT / chunk_name(n)


def ledger(n):
    return fix.RESEARCH / (stem(n) + '-depth-lit')


def fields():
    return dict(allocation=ALLOCATION, fixed_chunk_numbers=list(NUMBERS), role='reserved_validation',
                latest_freeze_ns=FREEZE_NS, input_deadlines_ns={str(k): v for k, v in DEADLINES.items()},
                overall_hard_end_ns=HARD_END_NS, control_root=str(OUT.relative_to(ROOT)),
                store_root='data/rolling/market-research-v1', assets=list(ASSETS),
                selected=rolling.SELECTED, venues=list(VENUES), rules=list(RULES), family='depth',
                rows_per_chunk=4, audits_per_chunk=1, commands_per_chunk=3,
                primary=['rh_lighter', 'depth_fade'], comparator=['rh_lighter', 'depth_follow'],
                execution_parameters=strategy.PARAMS, adapter_bounds=BOUNDS, output_caps=CAPS,
                child_seconds=CHILD_SECONDS, child_cpu_seconds=CPU_SECONDS,
                child_ram_bytes=RAM_BYTES, analysis_seconds_per_chunk=ANALYSIS_SECONDS,
                categories_bytes=CATEGORIES, control_shares_bytes=CONTROL_SHARES, raw_copy_bytes=0)


def source_contracts():
    allocation = read(old.pin_file(ALLOCATION), 32768)
    require(allocation['categories_bytes'] == CATEGORIES and allocation['added_reserved_bytes'] == 1048576,
            'allocation_contract')
    for pin in allocation['existing_input_references']:
        old.pin_file(pin)
    # This checks the full original science/capture universe and entire old source chain.
    parent = old.source_contracts()
    require(parent['execution_parameters'] == strategy.PARAMS, 'original_science_changed')
    return allocation


def verify(expected, *, before_freeze=False, now_ns=None):
    require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected), 'exact_plan_sha_required')
    require(fix.sha(PLAN) == expected, 'plan_sha256')
    p = read(PLAN, 16384)  # unchanged fix.events also reads its plan with this cap
    require(p.get('schema') == SCHEMA and p.get('status') == 'frozen', 'plan_not_frozen')
    source_contracts()
    require(all(p.get(k) == v for k, v in fields().items()), 'plan_scope')
    require(type(p.get('frozen_utc_ns')) is int and 0 < p['frozen_utc_ns'] < FREEZE_NS, 'freeze_missed_cutoff')
    require(isinstance(p.get('store_identity_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', p['store_identity_sha256']), 'store_identity_pin')
    pins = p.get('source_pins')
    require(isinstance(pins, list) and len(pins) == 3
            and {x.get('path') for x in pins} == {SOURCE, TEST, DESIGN}, 'own_source_pins')
    for pin in pins:
        old.pin_file(pin)
    require(sum(x['bytes'] for x in pins) + PLAN.stat().st_size <= 262144, 'source_package_cap')
    if before_freeze:
        now = time.time_ns() if now_ns is None else now_ns
        require(p['frozen_utc_ns'] <= now < FREEZE_NS, 'launch_missed_cutoff')
    return p


def unique_bytes(directory, *, recursive=True):
    total, seen, count = 0, set(), 0
    paths = Path(directory).rglob('*') if recursive else Path(directory).iterdir()
    for path in paths:
        count += 1
        require(count <= 256 and not path.is_symlink(), 'bounded_output_tree')
        if path.is_file():
            stat = path.stat(); identity = (stat.st_dev, stat.st_ino)
            if identity not in seen:
                total += stat.st_size; seen.add(identity)
    return total


def publish(path, body, cap, *, directory_cap=None, replace=False):
    path = Path(path)
    require(not replace and isinstance(body, bytes) and len(body) <= cap, 'publication_cap_or_replace')
    require(not path.exists() and not path.is_symlink(), 'output_exists')
    require(path.parent.is_dir() and not path.parent.is_symlink(), 'output_parent')
    if directory_cap is not None:
        require(unique_bytes(path.parent, recursive=path.parent != OUT) + len(body) <= directory_cap,
                'category_peak_cap')
    pending = path.with_name(path.name + '.pending')
    with pending.open('xb') as stream:
        stream.write(body); stream.flush(); os.fsync(stream.fileno())
    os.link(pending, path)
    pending.unlink()


def control(n, name, value, *, final=False):
    directory = OUT if n is None else controls(n)
    # Keep a protected terminal reserve in every control category.
    cap = (16384 if final else 8192) if n is None else (32768 if final else 24576)
    publish(directory / name, fix.encode(value), 8192, directory_cap=cap)


def selected_entry(index, n):
    require(index.get('schema') == 'rolling-research-index-v1', 'index_schema')
    name = chunk_name(n)
    require(not any(x.get('chunk_id') == name for x in index.get('expired', [])), 'fixed_attempt_expired')
    e = index.get('chunks', {}).get(name)
    if e is None:
        require(index.get('next_number', 1) <= n, 'fixed_attempt_missing')
        return None
    require(e.get('number') == n and e.get('role') == rolling.role(n) == 'reserved_validation'
            and type(e.get('launched_ns')) is int and e['launched_ns'] > 0, 'fixed_attempt_identity')
    return e


def store_identity(p):
    return BASE_STORE(p)


def nominate(expected, p):
    """Fixed number declaration before either reservation exists; never inspect coverage or economics."""
    store = store_identity(p)
    with store.locked():
        index = store.index()
        require(all(selected_entry(index, n) is None for n in NUMBERS), 'selected_already_started')
        stamp = time.time_ns()
        require(p['frozen_utc_ns'] <= stamp < FREEZE_NS, 'nomination_missed_cutoff')
        control(None, 'nomination.json', dict(schema=SCHEMA + '-nomination', plan_sha256=expected,
            fixed_chunk_numbers=list(NUMBERS), nominated_ns=stamp, role='reserved_validation',
            input_deadlines_ns={str(k): v for k, v in DEADLINES.items()}, no_replacement=True))


def nomination(n, expected):
    common = read(OUT / 'nomination.json', 8192)
    require(common.get('schema') == SCHEMA + '-nomination' and common.get('plan_sha256') == expected
            and common.get('fixed_chunk_numbers') == list(NUMBERS)
            and common.get('nominated_ns', FREEZE_NS) < FREEZE_NS, 'fixed_nomination_binding')
    value = read(controls(n) / 'nomination.json', 8192)
    require(value.get('schema') == SCHEMA + '-selected' and value.get('plan_sha256') == expected
            and value.get('chunk') == chunk_name(n) and value.get('number') == n
            and value.get('role') == 'reserved_validation'
            and common['nominated_ns'] <= value['launched_ns'] <= DEADLINES[n], 'selected_nomination_binding')
    return value


def wait_selected(n, p, expected, *, wall=time.time_ns, mono=time.monotonic, sleep=time.sleep):
    store = store_identity(p)
    bound = mono() + max(0, (DEADLINES[n] - wall()) / NS)
    chosen = None
    while wall() <= DEADLINES[n] and mono() <= bound:
        verify(expected)
        e = selected_entry(store.index(), n)
        if e is not None:
            choice = dict(chunk=chunk_name(n), number=n, role=e['role'], launched_ns=e['launched_ns'])
            require(choice['launched_ns'] <= DEADLINES[n], 'fixed_attempt_launched_after_deadline')
            if chosen is None:
                common = read(OUT / 'nomination.json', 8192)
                require(e['launched_ns'] >= common['nominated_ns'], 'selected_before_nomination')
                control(n, 'nomination.json', dict(schema=SCHEMA + '-selected', plan_sha256=expected, **choice))
                chosen = choice
            require(choice == chosen, 'selected_identity_changed')
            if e['state'] == 'sealed_failed':
                # Preserve the known failed reservation/seal declaration, without opening raw files.
                control(n, 'failed-attempt.json', dict(**chosen, seal_sha256=e.get('seal_sha256'),
                    state=e['state'], raw_opened=False, no_replacement=True))
                raise ValueError('fixed_attempt_failed')
            if e['state'] == 'sealed_complete':
                store.pin([choice['chunk']], f'lit_depth_fade_v1_{n}')
                control(n, 'pin.json', dict(chunk=choice['chunk'], owner=f'lit_depth_fade_v1_{n}',
                    seal_sha256=e['seal_sha256'], retained_until_root_release=True, plan_sha256=expected))
                return choice
            require(e['state'] == 'collecting', 'fixed_attempt_state')
        sleep(min(15, max(0, (DEADLINES[n] - wall()) / NS), max(0, bound - mono())))
    raise TimeoutError('fixed_input_deadline_no_replacement')


def chunk_pins(n, p, expected, digest=None):
    """Original full snapshot comparison, with its reader routed to this chunk's control directory."""
    require(fix.sha(PLAN) == expected, 'input_plan_changed')
    pinned = read(controls(n) / 'input-pins.json', 8192)
    current = BASE_SNAPSHOT(p)
    require(current == pinned, 'frozen_input_changed')
    if digest is not None:
        require(current['manifest_sha256'] == digest, 'input_manifest_changed')
    return current


def chunk_events(n, expected, source, *, expected_manifest_sha256, max_raw_bytes):
    """Original ordinary iterator and bounds; no alternate plan or metadata projection."""
    require(max_raw_bytes == BOUNDS['raw_bytes'], 'event_raw_bound')
    pinned = read(controls(n) / 'input-pins.json', 8192)
    require(pinned['manifest_sha256'] == expected_manifest_sha256
            and pinned['analysis_plan_sha256'] == expected == fix.sha(PLAN), 'event_provenance_binding')
    return fix.ordinary.iter_events(source, expected_manifest_sha256=expected_manifest_sha256,
        expected_raw_sha256=pinned['raw_sha256'], max_raw_bytes=max_raw_bytes,
        max_decoded_bytes=BOUNDS['decoded_bytes'], max_records=BOUNDS['records'], max_ids=BOUNDS['trade_ids'])


@contextmanager
def aliases(n, p, expected):
    """Full original source checks precede any narrowed alias; every alias is restored on error."""
    verify(expected)
    changes = []
    def setv(module, key, value):
        changes.append((module, key, getattr(module, key))); setattr(module, key, value)
    def configure(plan, family):
        BASE_CONFIGURE(plan, family)
        study = fix.news.study
        study.ASSETS = ASSETS
        study.NAMES = {'LIT': stem(n) + '-depth-lit'}
        return study
    try:
        for key, value in dict(PLAN=PLAN, OUT=controls(n), STEM=stem(n), OWNER=f'lit_depth_fade_v1_{n}',
            CAPS=CAPS, BOUNDS=BOUNDS, configure=configure,
            verify=lambda *a, **k: verify(expected), nomination=lambda ignored: nomination(n, expected)).items():
            setv(old, key, value)
        with old.bindings(p, 'depth'):
            # fix.replay iterates news.ASSETS, not only study.ASSETS.
            previous_assets, previous_publish = fix.news.ASSETS, fix.publish
            previous_pins, previous_events = fix.require_pins, fix.events
            fix.news.ASSETS, fix.publish = ASSETS, publish
            fix.require_pins = lambda plan, digest=None: chunk_pins(n, plan, expected, digest)
            fix.events = lambda source, **kwargs: chunk_events(n, expected, source, **kwargs)
            fix.news.study.iter_events = fix.events
            try:
                yield
            finally:
                fix.news.ASSETS, fix.publish = previous_assets, previous_publish
                fix.require_pins, fix.events = previous_pins, previous_events
    finally:
        for module, key, value in reversed(changes):
            setattr(module, key, value)


def unknown(n, reason, expected):
    return dict(schema=SCHEMA + '-unavailable', plan_sha256=expected, number=n, denominator=4,
        audit_denominator=1, audit={'status': 'unavailable', 'reason': reason},
        rows=[dict(asset='LIT', family='depth', venue=v, rule=r,
            collateral='USDC' if v == 'lighter' else 'USDG', attempts=None, closed=None,
            closed_stressed_cash=None, closed_cash_after_capital=None, complete=False,
            unknown=reason, position_open=None, pending_order=None) for v in VENUES for r in RULES],
        no_replacement=True, claim='Unavailable cash is unknown, never a favorable zero.')


def gate(rows, audit_passed):
    require(len(rows) == 4 and {(r['asset'], r['venue'], r['rule']) for r in rows}
            == {('LIT', v, r) for v in VENUES for r in RULES}, 'exact_four_row_cohort')
    complete = all(r['complete'] is True and not r['unknown'] and r['position_open'] is False
                   and r['pending_order'] is False for r in rows)
    p = next(r for r in rows if (r['venue'], r['rule']) == ('rh_lighter', 'depth_fade'))
    c = next(r for r in rows if (r['venue'], r['rule']) == ('rh_lighter', 'depth_follow'))
    stress, delta = None, None
    if complete:
        require(all(type(r['attempts']) is int and type(r['closed']) is int
                    and 0 <= r['closed'] <= r['attempts'] for r in rows), 'counts_domain')
        stress = D(p['closed_stressed_cash']); delta = stress - D(c['closed_stressed_cash'])
        require(stress.is_finite() and delta.is_finite(), 'finite_native_cash')
    passed = complete and audit_passed is True and p['attempts'] >= 1 and p['closed'] >= 1 and stress > 0 and delta > 0
    return dict(passed=bool(passed), all_four_flat_known=complete, audit_passed=audit_passed is True,
                primary_attempts=p['attempts'], primary_closed=p['closed'],
                primary_stressed_USDG=str(stress) if stress is not None else None,
                fade_minus_follow_stressed_USDG=str(delta) if delta is not None else None,
                objective_achieved=False)


def packed(path, cap):
    require(not path.is_symlink() and path.stat().st_size <= cap, 'packed_file_cap')
    with gzip.open(path, 'rb') as stream:
        body = stream.read(2097153)
    require(len(body) <= 2097152, 'decoded_summary_cap')
    return json.loads(body)


def report(n, expected):
    p = verify(expected)
    with aliases(n, p, expected):
        pins = fix.require_pins(p)
        directory, sample = ledger(n), stem(n) + '-depth-lit'
        require(unique_bytes(directory) <= 131072, 'ledger_directory_cap')
        summary = packed(directory / 'summary.json.gz', CAPS['summary'])
        audit = read(directory / 'independent-audit.json', CAPS['audit'])
        require(audit.get('status') == 'passed' and audit.get('sample') == sample
                and audit.get('raw_capture_verified') is True, 'independent_audit_failed')
        require(audit['summary_sha256'] == fix.sha(directory / 'summary.json.gz')
                and audit['trace_sha256'] == fix.sha(directory / 'trace.jsonl.gz') == summary['trace_sha256'], 'audit_output_binding')
        require(not summary['error'] and summary['complete_capture_verified'] is True
                and summary['asset'] == 'LIT' and summary['sample'] == sample
                and summary['source'] == pins['source'] and summary['manifest_sha256'] == pins['manifest_sha256']
                and summary['plan_sha256'] == expected, 'summary_input_binding')
        require(set(summary['arms']) == {r + ':' + v for r in RULES for v in VENUES}, 'four_arms')
        rows = []
        for arm, r in sorted(summary['arms'].items()):
            rule, venue = arm.split(':')
            net = sum((D(e['cash_after_capital']) for e in r['episodes']), D(0))
            stress = sum((D(e['stressed_net']) for e in r['episodes']), D(0))
            change = D(r['cash']) - D(strategy.PARAMS['initial_cash'])
            if r['complete']:
                require(not r['unknown'] and not r['position'] and not r['pending']
                        and abs(change - net) < D('1e-20'), 'flat_cash_reconciliation')
            rows.append(dict(asset='LIT', family='depth', rule=rule, venue=venue,
                collateral='USDC' if venue == 'lighter' else 'USDG', attempts=r['attempts'], closed=r['closed'],
                zero_fill_entries=r['counts'].get('entry_no_fill', 0),
                closed_cash_after_capital=str(net), closed_stressed_cash=str(stress),
                realized_cash_change=str(change), complete=r['complete'], unknown=r['unknown'],
                position_open=r['position'] is not None, pending_order=r['pending'] is not None))
        result = dict(schema=SCHEMA + '-comparison', number=n, plan_sha256=expected, rows=rows,
            denominator=4, audit_denominator=1, audit_sha256=fix.sha(directory / 'independent-audit.json'),
            summary_sha256=fix.sha(directory / 'summary.json.gz'), trace_sha256=audit['trace_sha256'],
            manifest_sha256=pins['manifest_sha256'], raw_sha256=pins['raw_sha256'], gate=gate(rows, True),
            claim='Separate native-collateral counterfactual IOC ledgers; no actual fills or portfolio sum. Core descriptive.')
        text = io.StringIO(); writer = csv.DictWriter(text, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        csv_body, body = text.getvalue().encode(), gzip.compress(fix.encode(result), mtime=0)
        require(len(body) <= 16384 and len(csv_body) <= 32768 and len(body) + len(csv_body) <= 49152, 'comparison_category_cap')
        verify(expected); fix.require_pins(p)
        publish(fix.RESEARCH / (stem(n) + '-comparison.json.gz'), body, 16384)
        publish(fix.RESEARCH / (stem(n) + '-comparison.csv'), csv_body, 32768)
        lines = [f'LIT fixed prospective chunk {n}: four independent ledgers, one matching audit.',
                 result['claim'], 'gate=' + json.dumps(result['gate'], sort_keys=True),
                 'Candidate only; previous ordinary positive and earlier news negative remain archived.']
        publish(fix.RESEARCH / (stem(n) + '-readout.txt'), ('\n'.join(lines) + '\n').encode(), 16384)
        verify(expected); fix.require_pins(p)
        return result


def combined(results):
    require(set(results) == set(NUMBERS), 'both_chunk_denominators')
    passed = all(results[n].get('passed') is True for n in NUMBERS)
    closes = sum(results[n]['primary_closed'] for n in NUMBERS) if passed else None
    return dict(status='conditional_candidate_only' if passed and closes >= 3 else 'does_not_advance',
                both_chunk_gates=passed, primary_closes_if_both_pass=closes,
                combined_close_hurdle=3, objective_achieved=False,
                independent_ledgers_not_additive=True, no_replacement=True)


def commands(n, expected, digest):
    return [[SOURCE, action, '--number', str(n), '--plan-sha256', expected, '--manifest-sha256', digest]
            for action in ('replay', 'audit', 'report')]


def child_setup(parent):
    import ctypes
    import resource
    # The compiler-free child cannot survive a supervisor death between spawn and PID receipt.
    require(ctypes.CDLL(None).prctl(1, signal.SIGKILL) == 0, 'parent_death_signal')
    if os.getppid() != parent:
        os.kill(os.getpid(), signal.SIGKILL)
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 5))
    resource.setrlimit(resource.RLIMIT_AS, (RAM_BYTES, RAM_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def command(args, deadline):
    remaining = min(CHILD_SECONDS, deadline - time.monotonic())
    require(remaining > 0, 'analysis_deadline')
    parent = os.getpid()
    child = subprocess.Popen(['nice', '-n', '19', sys.executable, '-B', str(ROOT / args[0]), *args[1:]],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True, close_fds=True, preexec_fn=lambda: child_setup(parent),
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    try:
        code = child.wait(timeout=remaining)
        require(code == 0, 'command_failed_no_retry')
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)


@contextmanager
def alarm(seconds):
    require(seconds > 0, 'overall_deadline')
    previous = signal.getsignal(signal.SIGALRM)
    def expired(*_): raise OverallDeadline('overall_hard_deadline')
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0); signal.signal(signal.SIGALRM, previous)


class OverallDeadline(TimeoutError):
    pass


def supervise(expected):
    p = verify(expected)
    shared = read(OUT / 'launch-claim.json', 8192)
    require(shared.get('plan_sha256') == expected and shared.get('launched_ns', FREEZE_NS) < FREEZE_NS, 'launch_claim')
    results = {n: dict(passed=False, primary_closed=None, unavailable=True) for n in NUMBERS}
    outer_reason = None
    try:
        with alarm(max(0, (HARD_END_NS - time.time_ns()) / NS - 15)):
            for n in NUMBERS:
                reason, completed, economics = None, 0, False
                try:
                    wait_selected(n, p, expected)
                    with aliases(n, p, expected):
                        snap = BASE_SNAPSHOT(p)
                        control(n, 'input-pins.json', snap)
                        fix.require_pins(p, snap['manifest_sha256'])
                    deadline = min(time.monotonic() + ANALYSIS_SECONDS,
                                   time.monotonic() + max(0, (HARD_END_NS - time.time_ns()) / NS - 15))
                    for args in commands(n, expected, snap['manifest_sha256']):
                        control(n, f'command-{completed + 1:02d}.json', dict(command=args, plan_sha256=expected,
                            entrypoint_sha256=fix.sha(ROOT / SOURCE), manifest_sha256=snap['manifest_sha256']))
                        economics = True; command(args, deadline); completed += 1
                    require(time.monotonic() < deadline, 'chunk_deadline_after_commands')
                    result = packed(fix.RESEARCH / (stem(n) + '-comparison.json.gz'), 16384)
                    require(result['plan_sha256'] == expected and result['number'] == n, 'comparison_identity')
                    with aliases(n, p, expected):
                        verify(expected); fix.require_pins(p, snap['manifest_sha256'])
                    results[n] = result['gate']
                except BaseException as exc:
                    reason = type(exc).__name__ + ': ' + str(exc)[:500]
                    results[n] = dict(passed=False, primary_closed=None, unavailable=True)
                    control(n, 'unavailable.json', unknown(n, reason, expected))
                    if isinstance(exc, OverallDeadline) or not isinstance(exc, Exception):
                        raise
                finally:
                    control(n, 'terminal.json', dict(status='completed' if reason is None else 'unavailable',
                        reason=reason, number=n, plan_sha256=expected, commands_completed=completed,
                        economic_evaluation=economics, denominator=4, audit_denominator=1,
                        no_retry=True, no_replacement=True, gate=results.get(n), ended_utc=fix.utc()), final=True)
    except BaseException as exc:
        outer_reason = type(exc).__name__ + ': ' + str(exc)[:500]
    finally:
        for n in NUMBERS:
            if not (controls(n) / 'terminal.json').exists():
                results[n] = dict(passed=False, primary_closed=None, unavailable=True)
                control(n, 'terminal.json', dict(status='unavailable', reason=outer_reason or 'supervisor_interrupted',
                    plan_sha256=expected, number=n, denominator=4, audit_denominator=1,
                    commands_completed=None, economic_evaluation=None, dispatch_unavailable=True,
                    rows=unknown(n, outer_reason or 'interrupted', expected)['rows'],
                    audit={'status': 'unavailable'}, no_retry=True, no_replacement=True), final=True)
        value = combined(results)
        control(None, 'terminal.json', dict(plan_sha256=expected, ended_utc=fix.utc(), reason=outer_reason,
            chunk_denominator=2, row_denominator=8, audit_denominator=2, result=value), final=True)
    return value


def launch(expected):
    p = verify(expected, before_freeze=True)
    require(not OUT.exists() and not OUT.is_symlink(), 'existing_output')
    for n in NUMBERS:
        require(not ledger(n).exists(), 'existing_ledger')
        require(not any((fix.RESEARCH / (stem(n) + suffix)).exists()
                        for suffix in ('-comparison.json.gz', '-comparison.csv', '-readout.txt')), 'existing_reports')
    # Validate both absent before creating any output/nomination.
    index = store_identity(p).index()
    require(all(selected_entry(index, n) is None for n in NUMBERS), 'selected_already_started')
    OUT.mkdir(parents=True, exist_ok=False)
    for n in NUMBERS: controls(n).mkdir()
    child = None
    try:
        nominate(expected, p)
        control(None, 'launch-claim.json', dict(plan_sha256=expected, launched_ns=time.time_ns(),
            source_sha256=fix.sha(ROOT / SOURCE), fixed_chunk_numbers=list(NUMBERS), no_retry=True))
        args = [sys.executable, '-B', str(ROOT / SOURCE), 'supervise', '--plan-sha256', expected]
        child = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        control(None, 'process.json', dict(pid=child.pid, command=args, plan_sha256=expected,
            entrypoint_sha256=fix.sha(ROOT / SOURCE), hard_end_ns=HARD_END_NS))
        return dict(status='launched', pid=child.pid, plan_sha256=expected, new_http_requests=0)
    except BaseException as exc:
        if child is not None:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait(timeout=5)
        for n in NUMBERS:
            if not (controls(n) / 'terminal.json').exists():
                control(n, 'terminal.json', dict(status='unavailable',
                    **unknown(n, 'launch_failed: ' + str(exc)[:300], expected),
                    economic_evaluation=None if child else False, dispatch_unavailable=child is not None), final=True)
        control(None, 'launch-terminal.json', dict(status='unavailable', reason=str(exc)[:500],
            plan_sha256=expected, chunk_denominator=2, row_denominator=8, audit_denominator=2,
            economic_evaluation=None if child else False, no_retry=True), final=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='dry', choices=('dry', 'run', 'supervise', 'replay', 'audit', 'report'))
    parser.add_argument('--plan-sha256'); parser.add_argument('--number', type=int, choices=NUMBERS)
    parser.add_argument('--manifest-sha256')
    args = parser.parse_args(argv)
    if args.action == 'dry':
        value = dict(status='dry', network_requests=0, store_reads=0, nominations=0, pins=0,
                     economic_evaluation=False, fixed_chunk_numbers=list(NUMBERS), rows=8, audits=2,
                     commands_per_chunk=3, final_plan=str(PLAN.relative_to(ROOT)))
    elif args.action == 'run': value = launch(args.plan_sha256)
    elif args.action == 'supervise': value = supervise(args.plan_sha256)
    else:
        p = verify(args.plan_sha256)
        require(args.number in NUMBERS and isinstance(args.manifest_sha256, str)
                and re.fullmatch('[0-9a-f]{64}', args.manifest_sha256), 'child_args')
        with aliases(args.number, p, args.plan_sha256):
            fix.require_pins(p, args.manifest_sha256)
            if args.action == 'replay': fix.replay('depth', args.manifest_sha256)
            elif args.action == 'audit': fix.audit('depth', 'LIT', args.manifest_sha256)
            else: report(args.number, args.plan_sha256)
        return
    print(json.dumps(value, separators=(',', ':')))


if __name__ == '__main__': main()
