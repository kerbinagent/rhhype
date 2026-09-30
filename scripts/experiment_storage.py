#!/usr/bin/env python3
"""Read-only inventory and retention plan for allowlisted public study archives.

This intentionally has no deletion mode. A plan names only compressed raw
frames from finished studies; manifests, metadata, source and protocol records
remain in place. Operators can review a plan before any separate cleanup.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
MANAGED_ROOTS = (
    'rh-passive-exit-v1', 'rh-passive-exit-preflight',
    'rh-small-maker', 'maker-capture', 'rh-maker-symmetric-v1',
    'passive-three-venue',
)
DEFAULT_ROOTS = ('rh-passive-exit-v1',)
PINNED = frozenset((
    'rh-small-maker/20260929T212132Z',
    'maker-capture/20260929T1823Z',
))
COMPLETE_REASONS = frozenset(('duration_limit', 'compressed_size_cap'))
MAX_STUDIES_SCANNED = 256
MAX_ENTRIES_PER_STUDY = 4096
MAX_MANIFEST_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 1_000_000
STUDY_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def _timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return None
        return parsed.timestamp()
    except (ValueError, OverflowError):
        return None


def _tree_bytes(study: Path) -> tuple[int, bool]:
    """Count apparent regular-file bytes; never follow links or special files."""
    total, entries, unsafe = 0, 0, False
    stack = [study]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as listing:
            for entry in listing:
                entries += 1
                if entries > MAX_ENTRIES_PER_STUDY:
                    raise ValueError('study entry count exceeds scan cap')
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISDIR(mode):
                    stack.append(Path(entry.path))
                elif stat.S_ISREG(mode):
                    total += entry.stat(follow_symlinks=False).st_size
                else:
                    unsafe = True
    return total, unsafe


def _pid_status(study: Path) -> str:
    for name in ('capture.pid', 'pid', '.pid'):
        path = study / name
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode) or path.stat().st_size > 32:
            return 'unverifiable_pid_file'
        try:
            pid = int(path.read_text().strip())
        except (OSError, UnicodeError, ValueError):
            return 'unverifiable_pid_file'
        if pid <= 0:
            return 'unverifiable_pid_file'
        # A process outside this PID namespace may be invisible in /proc.
        # Therefore even a stale-looking PID record blocks a raw-removal plan.
        return 'live_or_reused_pid' if Path(f'/proc/{pid}').exists() else 'pid_record_unverified'
    return 'no_pid_recorded'


def _study(root_name: str, study: Path, *, min_age_seconds: int,
           now: float) -> dict:
    rel = f'{root_name}/{study.name}'
    result = {'study': rel, 'path': str(study), 'pinned': rel in PINNED,
              'bytes': 0, 'raw_frame_bytes': 0, 'manifest_status': 'missing',
              'pid_status': 'not_checked', 'candidate': False, 'reasons': []}
    mode = study.lstat().st_mode
    if not stat.S_ISDIR(mode) or not STUDY_NAME.fullmatch(study.name):
        result['reasons'].append('unsafe_study_path')
        return result
    total, unsafe = _tree_bytes(study)
    result['bytes'] = total
    if unsafe:
        result['reasons'].append('symlink_or_special_file')
    frame = study / 'frames.jsonl.gz'
    try:
        frame_stat = frame.lstat()
    except FileNotFoundError:
        frame_stat = None
    if frame_stat is None:
        result['reasons'].append('no_raw_frames')
    elif not stat.S_ISREG(frame_stat.st_mode) or frame_stat.st_nlink != 1:
        result['reasons'].append('unsafe_raw_frame_path')
    elif frame_stat.st_size <= 0:
        result['reasons'].append('empty_raw_frames')
    else:
        result['raw_frame_bytes'] = frame_stat.st_size
    manifest_path = study / 'manifest.json'
    try:
        manifest_stat = manifest_path.lstat()
        if not stat.S_ISREG(manifest_stat.st_mode) or manifest_stat.st_size > MAX_MANIFEST_BYTES:
            raise ValueError('unsafe or oversized manifest')
        manifest = json.loads(manifest_path.read_bytes())
        if not isinstance(manifest, dict):
            raise ValueError('manifest must be an object')
        ended = _timestamp(manifest.get('ended_utc'))
        if (manifest.get('read_only') is not True or ended is None
                or manifest.get('end_reason') not in COMPLETE_REASONS
                or not isinstance(manifest.get('frames_sha256'), str)
                or not SHA256.fullmatch(manifest['frames_sha256'])):
            result['manifest_status'] = 'incomplete_or_invalid'
        else:
            result['manifest_status'] = 'complete'
            result['ended_at'] = ended
            result['end_reason'] = manifest['end_reason']
            if now - ended < min_age_seconds:
                result['reasons'].append('recent_completion')
    except (FileNotFoundError, OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        result['manifest_status'] = 'missing_or_invalid'
    if result['manifest_status'] != 'complete':
        result['reasons'].append('active_or_incomplete_manifest')
    result['pid_status'] = _pid_status(study)
    if result['pid_status'] != 'no_pid_recorded':
        result['reasons'].append(result['pid_status'])
    if result['pinned']:
        result['reasons'].append('pinned_original_capture')
    result['candidate'] = not result['reasons']
    return result


def inventory(workspace: Path = ROOT, *, roots=DEFAULT_ROOTS,
              max_retained_studies: int = 4, max_total_bytes: int = 512_000_000,
              min_age_seconds: int = 3600, now: float | None = None) -> dict:
    """Return a stat-bounded plan; no raw or metadata bytes are modified."""
    import time
    workspace = Path(workspace).resolve()
    for ancestor in (workspace / 'data', workspace / 'data' / 'raw'):
        if ancestor.is_symlink() or (ancestor.exists() and not ancestor.is_dir()):
            raise ValueError('unsafe data/raw path')
    roots = tuple(roots)
    if (not roots or len(set(roots)) != len(roots)
            or any(name not in MANAGED_ROOTS for name in roots)):
        raise ValueError('roots must be unique explicit managed-study names')
    if (type(max_retained_studies) is not int or max_retained_studies < 0
            or type(max_total_bytes) is not int or max_total_bytes < 0
            or type(min_age_seconds) is not int or min_age_seconds < 0):
        raise ValueError('retention budgets and minimum age must be nonnegative integers')
    now = time.time() if now is None else float(now)
    studies = []
    for name in roots:
        root = workspace / 'data' / 'raw' / name
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise ValueError(f'unsafe managed root: {name}')
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if len(studies) >= MAX_STUDIES_SCANNED:
                raise ValueError('managed study count exceeds scan cap')
            studies.append(_study(name, child,
                                  min_age_seconds=min_age_seconds, now=now))
    count = sum(bool(row['raw_frame_bytes']) for row in studies)
    total = sum(row['bytes'] for row in studies)
    projected_count, projected_total = count, total
    plan = []
    candidates = sorted((row for row in studies if row['candidate']),
                        key=lambda row: (row['ended_at'], row['study']))
    for row in candidates:
        if projected_count <= max_retained_studies and projected_total <= max_total_bytes:
            break
        # Preserve study directory, manifest and metadata. This exact relative
        # raw file is the only prospective removal target.
        plan.append({'study': row['study'], 'raw_file': f"data/raw/{row['study']}/frames.jsonl.gz",
                     'estimated_reclaimable_bytes': row['raw_frame_bytes'],
                     'preserve': ['manifest.json', 'metadata/', 'source/protocol records']})
        projected_count -= 1
        projected_total -= row['raw_frame_bytes']
    result = {
        'schema': 'experiment-storage-inventory-v1',
        'mode': 'dry_run_inventory_only', 'deletion_supported': False,
        'managed_roots': list(roots), 'pinned_studies': sorted(PINNED),
        'budgets': {'max_retained_raw_studies': max_retained_studies,
                    'max_total_apparent_bytes': max_total_bytes,
                    'minimum_completed_age_seconds': min_age_seconds},
        'current': {'raw_studies': count, 'total_apparent_bytes': total},
        'projected_after_plan': {'raw_studies': projected_count,
                                 'total_apparent_bytes': projected_total},
        'budgets_met_after_plan': (projected_count <= max_retained_studies
                                   and projected_total <= max_total_bytes),
        'plan': plan, 'studies': studies,
        'notes': ('No files are deleted. Raw count means studies with frames.jsonl.gz. '
                  'Total bytes are apparent regular-file sizes, including retained metadata. '
                  'An absent or invalid final manifest is active/incomplete and never planned.'),
    }
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(encoded) + 1 > MAX_OUTPUT_BYTES:
        raise ValueError('inventory output exceeds 1 MB bound')
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', dest='roots', action='append', choices=MANAGED_ROOTS)
    parser.add_argument('--max-retained-studies', type=int, default=4)
    parser.add_argument('--max-total-bytes', type=int, default=512_000_000)
    parser.add_argument('--min-age-seconds', type=int, default=3600)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    report = inventory(roots=tuple(args.roots or DEFAULT_ROOTS),
                       max_retained_studies=args.max_retained_studies,
                       max_total_bytes=args.max_total_bytes,
                       min_age_seconds=args.min_age_seconds)
    body = (json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if args.out:
        if args.out.exists():
            parser.error('output must be a new file')
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(body)
        print(json.dumps({'out': str(args.out), 'planned_raw_files': len(report['plan']),
                          'budgets_met': report['budgets_met_after_plan']}))
    else:
        sys.stdout.buffer.write(body)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
