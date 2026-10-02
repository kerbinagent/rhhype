"""Offline successor for the finished news capture's final status inventory.

This adapter delegates economics, ordinary event decoding, independent audits,
and comparisons to the unchanged frozen corrected modules. The only capture
input change is the mandatory, pinned final status.json control file.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import single_venue_news_ordinary_fix as fix

SOURCE = 'scripts/single_venue_news_inventory_fix_v2.py'
TEST = 'tests/test_single_venue_news_inventory_fix_v2.py'
PLAN = ROOT / 'reports/experiment-storage/single-venue-news-inventory-fix-v2.json'
OLD_PLAN = ROOT / 'reports/experiment-storage/single-venue-news-ordinary-feed-fix-v1.json'
PREPARATION = {'path': 'reports/experiment-storage/single-venue-news-inventory-fix-preparation-v2.json',
               'bytes': 3185, 'sha256': '5867d94fcf0244de6ec1605a3343f9d080b7193f085c6e172f1343f48433787c'}
OLD_PLAN_PIN = {'path': 'reports/experiment-storage/single-venue-news-ordinary-feed-fix-v1.json',
                'sha256': '45ba5e949a317eef63fdd1e4dede1748a488a85f0cfa8a27fe5fcc0210dc126d'}
FAILED_TERMINAL = {'path': 'reports/single-venue-news-ordinary-fix-v1/analysis-terminal.json',
                   'bytes': 345, 'sha256': 'ae05e9613584fae6605340974c2a1e6b7ee0b1b30339aad89e4daef543c059b7'}
CAPTURE_STATUS = {'path': 'reports/single-venue-news/capture/status.json',
                  'bytes': 164, 'sha256': '29302929d711fa4d7a61d15a67f458550e804916bbe52235cb4c37d27977ca6f'}
CONTROL_ROOT = 'reports/single-venue-news-inventory-fix-v2'
OUTPUT_STEM = 'single-venue-news-inventory-fix'
CONTROL_CAP = 49152
SOURCE_CAP = 32768
TEST_CAP = 16384
PLAN_CAP = 16384
OLD_VERIFY = fix.verify
OLD_CAPS = dict(fix.CAPS)
OLD_INPUT_SNAPSHOT = fix.input_snapshot


def _pinned(pin):
    path = ROOT / pin['path']
    assert not path.is_symlink() and path.resolve() == ROOT.resolve() / pin['path'], 'input_symlink'
    if 'bytes' in pin:
        assert path.stat().st_size == pin['bytes'], 'input_byte_identity_changed'
    assert fix.sha(path) == pin['sha256'], 'input_sha_identity_changed'
    return path


def _old_contract(family):
    # The old verifier is called with its original process-local bindings.
    prior_plan, prior_caps = fix.PLAN, fix.CAPS
    try:
        fix.PLAN, fix.CAPS = OLD_PLAN, OLD_CAPS
        return OLD_VERIFY(family)
    finally:
        fix.PLAN, fix.CAPS = prior_plan, prior_caps


def verify(family='relative'):
    assert family in ('relative', 'depth'), 'unsupported_family'
    _pinned(OLD_PLAN_PIN)
    _pinned(PREPARATION)
    _pinned(FAILED_TERMINAL)
    _pinned(CAPTURE_STATUS)
    failed = fix.read(ROOT / FAILED_TERMINAL['path'], 8192)
    assert failed['state'] == 'finished' and failed['success'] is False
    assert failed['economic_evaluation'] is False and failed['error'] == 'AssertionError: capture_inventory_changed'
    old = _old_contract(family)
    assert fix.PLAN == PLAN, 'successor_binding_changed'
    assert not PLAN.is_symlink() and PLAN.stat().st_size <= PLAN_CAP, 'successor_plan_cap'
    plan = fix.read(PLAN, PLAN_CAP)
    assert plan['schema'] == 'single-venue-news-inventory-fix-v2' and plan['status'] == 'frozen', 'successor_not_frozen'
    for key, value in (('previous_analysis_plan', OLD_PLAN_PIN), ('preparation', PREPARATION),
                       ('failed_analysis_terminal', FAILED_TERMINAL), ('capture_status', CAPTURE_STATUS),
                       ('capture_root', old['capture_root']), ('capture_plan', old['capture_plan']),
                       ('control_root', CONTROL_ROOT), ('output_stem', OUTPUT_STEM),
                       ('original_capture_plan_sha256', fix.CAPTURE_PLAN_SHA),
                       ('adapter_bounds', fix.BOUNDS)):
        assert plan[key] == value, 'successor_scope_changed:' + key
    for key in ('assets', 'selected', 'families', 'execution_parameters', 'duration_seconds',
                'capture_hard_bytes', 'scheduled_start_epoch', 'event_epoch'):
        assert plan[key] == old[key], 'economic_or_calendar_scope_changed:' + key
    expected_caps = {**OLD_CAPS, 'controls': CONTROL_CAP}
    assert plan['output_caps'] == expected_caps, 'output_caps_changed'
    pins = plan['source_pins']
    assert isinstance(pins, list) and pins[:len(old['source_pins'])] == old['source_pins']
    own = pins[len(old['source_pins']):]
    assert len(own) == 2 and {entry['path'] for entry in own} == {SOURCE, TEST}, 'successor_pins_required'
    for pin in pins:
        path = _pinned(pin)
        if pin['path'] == SOURCE: assert path.stat().st_size <= SOURCE_CAP
        if pin['path'] == TEST: assert path.stat().st_size <= TEST_CAP
    fix.CAPS = expected_caps
    fix.configure(plan, family)
    return plan


def input_snapshot(plan):
    # Identical sealed-input checks to the old snapshot, with status mandatory.
    terminal = fix.read(fix.news.OUT / 'terminal.json')
    fix.require_terminal(terminal)
    cap = ROOT / plan['capture_root']
    manifest = fix.read(cap / 'manifest.json')
    assert manifest['market_plan_sha256'] == fix.CAPTURE_PLAN_SHA
    assert manifest['end_reason'] == 'duration_limit' and not manifest['truncated'] and fix.news.coverage(manifest)
    assert manifest['selected_markets'] == fix.news.SELECTED
    capture_terminal = fix.read(cap / 'terminal.json')
    assert capture_terminal['plan_sha256'] == fix.CAPTURE_PLAN_SHA and capture_terminal['status'] == 'capture_completed'
    assert capture_terminal['end_reason'] == 'duration_limit'
    digest = fix.sha(cap / 'manifest.json')
    raw = fix.sha(cap / 'frames.jsonl.gz')  # Opaque checksum only; never decode frames here.
    assert raw == manifest['frames_sha256']
    assert digest == capture_terminal['manifest_sha256'] == terminal['terminal']['manifest_sha256']
    status_path = _pinned(CAPTURE_STATUS)
    status = fix.read(status_path, 8192)
    assert status['economic_evaluation'] is False and status['errors'] == [], 'capture_status_invalid'
    for prior_key, final_key in (('compressed_bytes', 'compressed_payload_bytes'), ('records', 'payload_records')):
        prior, final = status[prior_key], manifest[final_key]
        assert type(prior) is int and type(final) is int and 0 <= prior <= final, 'capture_status_not_prior_heartbeat'
    elapsed = status['elapsed_seconds']
    span = (datetime.datetime.fromisoformat(manifest['ended_utc']) -
            datetime.datetime.fromisoformat(manifest['started_utc'])).total_seconds()
    assert type(elapsed) in (int, float) and 0 <= elapsed <= span + 1, 'capture_status_elapsed_invalid'
    names = [f'metadata/{name}{suffix}' for name in fix.news.study.capture.REQUESTS
             for suffix in ('.json.gz', '.request.json')]
    names += ['metadata/market_plan.json', 'metadata/normalized.json',
              'manifest.json', 'frames.jsonl.gz', 'terminal.json', 'status.json']
    assert set(str(p.relative_to(cap)) for p in cap.rglob('*') if p.is_file()) == set(names), 'capture_inventory_changed'
    assert fix.tree_bytes(cap) <= fix.BOUNDS['raw_bytes']
    metadata = fix.ordinary._metadata(cap, manifest, fix.ordinary._epoch_ns(manifest['started_utc']))[0]
    assert metadata['market_plan_sha256'] == fix.CAPTURE_PLAN_SHA
    assert sum((cap / n).stat().st_size for n in names if n.startswith('metadata/')) <= fix.BOUNDS['metadata_bytes']
    files = [cap / n for n in names] + [fix.news.OUT / 'terminal.json', fix.news.PLAN, PLAN]
    return dict(manifest_sha256=digest, raw_sha256=raw, analysis_plan_sha256=fix.sha(PLAN),
                capture_plan_sha256=fix.CAPTURE_PLAN_SHA,
                files={str(p.relative_to(ROOT)):dict(sha256=fix.sha(p), bytes=p.stat().st_size) for p in files})


def commands(digest):
    plan_sha = fix.sha(PLAN)
    for family in ('relative', 'depth'):
        yield [SOURCE, 'replay', family, digest, plan_sha]
        for asset in fix.news.ASSETS:
            yield [SOURCE, 'audit', family, asset, digest, plan_sha]
        yield [SOURCE, 'readout', family, plan_sha]


def install():
    # Bind only the current Python process. Frozen files and sibling runs stay untouched.
    fix.PLAN = PLAN
    fix.verify = verify
    fix.input_snapshot = input_snapshot
    fix.commands = commands
    fix.CAPS = {**OLD_CAPS, 'controls': CONTROL_CAP}


def _claim(plan_sha):
    plan = verify()
    assert fix.sha(PLAN) == plan_sha, 'successor_plan_sha_mismatch'
    out = ROOT / plan['control_root']
    out.mkdir(parents=True, exist_ok=False)
    fix.control(plan, 'launch-claim.json', dict(schema='single-venue-news-inventory-fix-launch-v2',
        plan_sha256=plan_sha, started_utc=fix.utc(), analysis_seconds=fix.ANALYSIS_SECONDS,
        child_seconds=600, no_retry=True, source=CAPTURE_STATUS['path']))
    return plan


def _economic_stage(out):
    for name in ('analysis-terminal.json', 'analysis-status.json'):
        path = out / name
        try:
            if path.exists():
                value = fix.read(path, 8192).get('economic_evaluation')
                if type(value) is bool:
                    return value
        except Exception:
            pass
    return None


def launch(plan_sha):
    plan = _claim(plan_sha)
    args = [sys.executable, '-B', str(Path(__file__).resolve()), 'supervise', plan_sha]
    try:
        child_env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        child = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, close_fds=True, env=child_env)
    except Exception as exc:
        fix.control(plan, 'wrapper-terminal.json', dict(status='launch_failed',
            error=type(exc).__name__ + ': ' + str(exc)[:500], plan_sha256=plan_sha,
            ended_utc=fix.utc(), economic_evaluation=False))
        raise
    record = dict(pid=child.pid, command=args, launched_utc=fix.utc(), plan_sha256=plan_sha,
                  offline_sealed_input=True, analysis_seconds=fix.ANALYSIS_SECONDS,
                  child_seconds=600, no_retry=True)
    try:
        fix.control(plan, 'analysis-process.json', record)
    except Exception as exc:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
        fix.control(plan, 'wrapper-terminal.json', dict(status='process_receipt_failed',
            error=type(exc).__name__ + ': ' + str(exc)[:500], plan_sha256=plan_sha,
            ended_utc=fix.utc(), economic_evaluation=_economic_stage(ROOT / plan['control_root'])))
        raise
    return record


def supervise(plan_sha):
    out = ROOT / CONTROL_ROOT
    ok, error = False, None
    try:
        assert fix.sha(PLAN) == plan_sha, 'successor_plan_sha_mismatch'
        verify()
        fix.supervise()
        terminal = fix.read(out / 'analysis-terminal.json', 8192)
        ok = terminal.get('success') is True and terminal.get('completed_commands') == 24
        assert ok, 'successor_terminal_incomplete'
        verify()
        fix.require_pins(fix.read(PLAN, PLAN_CAP))
    except BaseException as exc:
        error = type(exc).__name__ + ': ' + str(exc)[:500]
    finally:
        if out.exists() and not (out / 'wrapper-terminal.json').exists():
            fix.control({'control_root': CONTROL_ROOT}, 'wrapper-terminal.json',
                        dict(status='finished' if ok and error is None else 'failed',
                             success=ok and error is None, error=error,
                             plan_sha256=plan_sha, ended_utc=fix.utc(),
                             economic_evaluation=_economic_stage(out)))
    if error is not None:
        raise SystemExit(1)


def _expected_sha(value):
    assert isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)
    assert fix.sha(PLAN) == value, 'successor_plan_sha_mismatch'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('dry', 'launch', 'supervise', 'replay', 'audit', 'readout'), default='dry')
    parser.add_argument('args', nargs='*')
    parsed = parser.parse_args(argv)
    if parsed.action == 'dry':
        assert not parsed.args
        print(json.dumps({'status': 'dry_no_input_reads_no_commands', 'commands': 0}))
        return 0
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    install()
    if parsed.action == 'launch':
        assert len(parsed.args) == 1
        _expected_sha(parsed.args[0]); print(json.dumps(launch(parsed.args[0])))
    elif parsed.action == 'supervise':
        assert len(parsed.args) == 1
        supervise(parsed.args[0])
    elif parsed.action == 'replay':
        assert len(parsed.args) == 3
        family, digest, plan_sha = parsed.args
        _expected_sha(plan_sha); fix.replay(family, digest)
    elif parsed.action == 'audit':
        assert len(parsed.args) == 4
        family, asset, digest, plan_sha = parsed.args
        _expected_sha(plan_sha); fix.audit(family, asset, digest)
    else:
        assert len(parsed.args) == 2
        family, plan_sha = parsed.args
        _expected_sha(plan_sha)
        from scripts import single_venue_news_ordinary_fix_readout as readout
        readout.main(family)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
