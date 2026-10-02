#!/usr/bin/env python3
"""One explicitly authorized pre-cutoff repair of a vanished sandbox launcher."""
import sys
sys.dont_write_bytecode = True
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import news_candidate_rolling_v1 as w

PLAN_SHA = 'e3a09177b2e38ca78ee7f1a97b2ce5e00ce14bd15cdc6c53164472888cd2ee33'
RECOVERY = ROOT / 'reports/experiment-storage/news-candidate-host-startup-recovery-v1.json'
HOST_NAMESPACE = 'pid:[4026532219]'
INITIAL = {
    'launch-claim.json': (364, 'c89472a42c98cde4c593dec686f606f029155154723582bc1f5ec800b003d216'),
    'process.json': (466, '521317dcd63ad0f06e987de47932d1a9eb656fadca54d4e149130293f457bd98'),
}


def existing_supervisors():
    result = []
    targets = {w.SOURCE, str(ROOT / w.SOURCE)}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            args = (directory / 'cmdline').read_bytes().split(b'\0')
            decoded = [a.decode('utf-8', 'replace') for a in args]
            if targets.intersection(decoded):
                result.append(int(directory.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def preflight(expected, *, run=False):
    w.require(isinstance(expected, str) and len(expected) == 64, 'recovery_sha_required')
    w.require(w.fix.sha(RECOVERY) == expected, 'recovery_sha')
    r = w.read(RECOVERY, 8192)
    w.require(r['schema'] == 'news-candidate-host-startup-recovery-v1'
              and r['status'] == 'frozen_preselection_environment_repair'
              and r['plan_sha256'] == PLAN_SHA, 'recovery_scope')
    w.require(type(r['frozen_utc_ns']) is int and 0 < r['frozen_utc_ns'] < w.CUTOFF_NS,
              'recovery_freeze_missed_cutoff')
    w.require(w.fix.sha(Path(__file__)) == r['launcher']['sha256']
              and Path(__file__).stat().st_size == r['launcher']['bytes'], 'launcher_pin')
    w.verify(PLAN_SHA, before_cutoff=True)
    w.require(set(p.name for p in w.OUT.iterdir()) == set(INITIAL), 'startup_outputs_changed')
    for name, (size, digest) in INITIAL.items():
        path = w.OUT / name
        w.require(path.is_file() and not path.is_symlink()
                  and path.stat().st_size == size and w.fix.sha(path) == digest, 'startup_pin')
    namespace = os.readlink('/proc/self/ns/pid')
    if run:
        w.require(namespace == HOST_NAMESPACE and Path('/proc/1/comm').read_text().strip() == 'systemd',
                  'persistent_host_namespace_required')
        w.require(not existing_supervisors(), 'existing_supervisor_refuse_duplicate')
    return {'plan_sha256': PLAN_SHA, 'recovery_sha256': expected,
            'pid_namespace': namespace, 'persistent_host_namespace': namespace == HOST_NAMESPACE,
            'nominations': 0, 'pins': 0, 'raw_reads': 0, 'http_requests': 0}


def launch(expected):
    checked = preflight(expected, run=True)
    w.require(time.time_ns() < w.CUTOFF_NS, 'recovery_claim_missed_cutoff')
    w.control('host-launch-claim.json', dict(**checked, launched_ns=time.time_ns(),
        original_startup_artifacts_preserved=True, one_repair_only=True))
    args = [sys.executable, '-B', str(ROOT / w.SOURCE), 'supervise', '--plan-sha256', PLAN_SHA]
    child = None
    try:
        spawn_requested_ns = time.time_ns()
        w.require(spawn_requested_ns < w.CUTOFF_NS, 'recovery_spawn_missed_cutoff')
        child = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        spawn_returned_ns = time.time_ns()
        w.require(spawn_returned_ns < w.CUTOFF_NS, 'recovery_spawn_returned_after_cutoff')
        time.sleep(.2)
        w.require(child.poll() is None, 'supervisor_exited_at_startup')
        fields = Path(f'/proc/{child.pid}/stat').read_text().rsplit(') ', 1)[1].split()
        w.control('host-process.json', dict(**checked, pid=child.pid, start_ticks=fields[19],
            command=args, original_sandbox_pid=3, started_utc=w.fix.utc(),
            spawn_requested_ns=spawn_requested_ns, spawn_returned_ns=spawn_returned_ns))
    except BaseException as exc:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        w.control('host-startup-failure.json', dict(**checked, reason=type(exc).__name__ + ': ' + str(exc)[:500],
            status='unavailable', no_retry=True))
        raise
    return dict(status='host_supervisor_started', pid=child.pid, **checked)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('dry', 'run'), nargs='?', default='dry')
    p.add_argument('--recovery-sha256', required=True)
    a = p.parse_args()
    result = launch(a.recovery_sha256) if a.action == 'run' else preflight(a.recovery_sha256)
    print(json.dumps(result, separators=(',', ':')))


if __name__ == '__main__':
    main()
