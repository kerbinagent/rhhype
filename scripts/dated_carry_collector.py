#!/usr/bin/env python3
"""Bounded, one-shot public book sampler. No orders or economic evaluation."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SLOTS = 864
INTERVAL_NS = 300_000_000_000
DURATION_NS = SLOTS * INTERVAL_NS
LEAD_NS = 1_000_000_000
TOLERANCE_NS = 250_000_000
RESPONSE_CAP = 65_536
INDEX_RESERVE = 262_144
CAPS = {"source_control": 1 << 20, "metadata": 2 << 20,
        "samples": 8 << 20, "derived": 2 << 20, "terminal": 3 << 20}
CONSTANTS = {"slots": SLOTS, "interval_seconds": 300, "duration_seconds": 259200,
             "decision_slots": [0, 144, 288, 432, 576, 720], "dispatch_lead_seconds": 1,
             "request_timeout_seconds": 1, "response_cap_bytes": RESPONSE_CAP,
             "depth": 10, "mapping_drift_limit_ns": TOLERANCE_NS,
             "callback_lateness_limit_ns": TOLERANCE_NS, "source_age_limit_ns": 2_000_000_000,
             "paired_source_skew_limit_ns": TOLERANCE_NS,
             "maximum_sample_requests": 1728, "caps": CAPS,
             "restart_policy": "finalize_only_no_network", "automatic_retry": False}
SHA = re.compile(r"[0-9a-f]{64}\Z")


class BudgetExceeded(ValueError):
    pass


def utc(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1e9, dt.timezone.utc).isoformat()


def timestamp(value: str) -> int:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ValueError("t0_utc must include UTC timezone")
    epoch = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    delta = parsed - epoch
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def body(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def read(path: Path, cap: int) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > cap:
        raise ValueError(f"bounded regular file required: {path}")
    with path.open("rb") as handle:
        data = handle.read(cap + 1)
    if len(data) > cap:
        raise BudgetExceeded(f"read category=input requested={len(data)} cap={cap}")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clock_identity() -> dict:
    """Monotonic timestamps are comparable only on this host and kernel boot."""
    boot_id = read(Path("/proc/sys/kernel/random/boot_id"), 128).decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot_id):
        raise ValueError("invalid kernel boot identity")
    return {"host": os.uname().nodename, "boot_id": boot_id}


def relative_path(name: str) -> Path:
    candidate = Path(name)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise ValueError("pins require repository-relative paths")
    path = ROOT / candidate
    if any(part.is_symlink() for part in [path, *path.parents] if part != ROOT.parent):
        raise ValueError("symlink input prohibited")
    return path


def load_config(path: Path, expected_sha256: str) -> dict:
    data = read(path, 131072)
    if not SHA.fullmatch(expected_sha256) or digest(data) != expected_sha256:
        raise ValueError("config hash mismatch")
    config = json.loads(data)
    if config.get("schema") != "dated-carry-collector-config-v1":
        raise ValueError("config schema mismatch")
    instruments = config.get("instruments")
    if not isinstance(instruments, dict) or set(instruments) != {"spot", "future"}:
        raise ValueError("two fixed instrument roles required")
    if instruments["spot"] != "BTC_USDC" or not re.fullmatch(r"BTC_USDC-\d{1,2}[A-Z]{3}\d{2}", instruments["future"]):
        raise ValueError("fixed BTC_USDC spot and dated future required")
    timestamp(config["t0_utc"])
    for key in ("source_sha256", "metadata_sha256"):
        pins = config.get(key)
        if not isinstance(pins, dict) or not 1 <= len(pins) <= 64:
            raise ValueError(f"bounded nonempty {key} required")
        for name, sha in pins.items():
            relative_path(name)
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise ValueError("invalid pin digest")
    needed = {"scripts/dated_carry_collector.py", "tests/test_dated_carry_collector.py"}
    if not needed <= config["source_sha256"].keys():
        raise ValueError("collector and focused tests must be source-pinned")
    if set(config["source_sha256"]) & set(config["metadata_sha256"]):
        raise ValueError("source and metadata pins overlap")
    return config


def verify_pins(config: dict, study_dir: Path) -> dict:
    external = {category: 0 for category in CAPS}
    for key, category in (("source_sha256", "source_control"), ("metadata_sha256", "metadata")):
        total = 0
        for name, sha in config[key].items():
            path = relative_path(name)
            data = read(path, CAPS[category])
            if digest(data) != sha:
                raise ValueError(f"source/metadata hash mismatch: {name}")
            total += len(data)
            if not path.is_relative_to(study_dir):
                external[category] += len(data)
        if total > CAPS[category]:
            raise BudgetExceeded(f"pins category={category} requested={total} cap={CAPS[category]}")
    return external


class Store:
    """Physical byte accounting, atomic publication and durable no-retry claims."""
    def __init__(self, study_dir: Path, *, external_bytes=None):
        if study_dir.is_symlink() or any(p.is_symlink() for p in study_dir.parents):
            raise ValueError("study path must not traverse symlinks")
        self.path = study_dir.resolve()
        self.external = dict(external_bytes or {})
        self.lock_token = None

    def usage(self) -> dict:
        used = {key: self.external.get(key, 0) for key in CAPS}
        files = 0
        if self.path.exists():
            for directory, subdirs, names in os.walk(self.path):
                for name in subdirs:
                    if (Path(directory) / name).is_symlink():
                        raise ValueError("symlink study directory")
                for name in names:
                    path = Path(directory) / name
                    if path.is_symlink() or not path.is_file():
                        raise ValueError("nonregular study artifact")
                    relative = path.relative_to(self.path)
                    category = relative.parts[0] if relative.parts[0] in CAPS else "source_control"
                    used[category] += path.stat().st_size
                    files += 1
                    if files > 4000:
                        raise BudgetExceeded("file count exceeded 4000")
        for category, size in used.items():
            if size > CAPS[category]:
                raise BudgetExceeded(f"existing category={category} projected={size} cap={CAPS[category]}")
        if sum(used.values()) > 16 << 20:
            raise BudgetExceeded("aggregate physical bytes exceeded")
        return used

    def write(self, category: str, name: str, data: bytes, *, replace=False) -> Path:
        if category not in CAPS or Path(name).name != name:
            raise ValueError("invalid category/name")
        target = self.path / category / name
        if target.is_symlink() or (target.exists() and not replace):
            raise FileExistsError(target)
        used = self.usage()
        # Atomic replacement owns old AND temporary bytes until rename. Always reserve
        # a terminal index update, including when a sample/category is exhausted.
        projected = used[category] + len(data)
        reserve = 0 if category == "terminal" else INDEX_RESERVE
        if projected > CAPS[category] or sum(used.values()) + len(data) + reserve > (16 << 20):
            raise BudgetExceeded(f"write category={category} requested={len(data)} projected={projected} cap={CAPS[category]}")
        if category != "terminal" and used["terminal"] + INDEX_RESERVE > CAPS["terminal"]:
            raise BudgetExceeded("terminal index reserve unavailable")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / ("." + name + "." + uuid.uuid4().hex + ".tmp")
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if replace:
                os.replace(temporary, target)
            else:
                # An existence check followed by rename can overwrite a competing
                # launch's lock/claim. Hard-link publication fails atomically when
                # the target already exists; both names share the same inode.
                os.link(temporary, target)
                temporary.unlink()
            self.sync_dir(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    @staticmethod
    def sync_dir(path: Path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextlib.contextmanager
    def lock(self, *, finalize_only=False):
        self.path.mkdir(parents=True, exist_ok=True)
        lock = self.path / "terminal" / "collector.lock"
        lock.parent.mkdir(exist_ok=True)
        if lock.exists() or lock.is_symlink():
            previous = json.loads(read(lock, 4096))
            if not finalize_only:
                raise ValueError("existing launch lock: recovery is finalize-only")
            if previous.get("host") != os.uname().nodename:
                raise ValueError("cannot verify remote launch lock")
            try:
                os.kill(previous["pid"], 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError("collector lock owner may still be alive")
            lock.unlink()
        self.lock_token = uuid.uuid4().hex
        self.write("terminal", "collector.lock", body({"pid": os.getpid(), "host": os.uname().nodename,
                                                      "token": self.lock_token}))
        try:
            yield self
        finally:
            if lock.exists() and json.loads(read(lock, 4096)).get("token") == self.lock_token:
                lock.unlink()
                self.sync_dir(lock.parent)
            self.lock_token = None

    def claim(self, slot: int, scheduled_ns: int):
        self.write("terminal", f"claim-{slot:03d}.json", body({"slot": slot, "planned_utc_ns": scheduled_ns}))

    def sample(self, slot: int, record: dict) -> dict:
        encoded = body(record)
        if len(encoded) > 262144:
            raise BudgetExceeded(f"slot decoded category=samples requested={len(encoded)} cap=262144")
        compressed = gzip.compress(encoded, mtime=0)
        name = f"slot-{slot:03d}.json.gz"
        self.write("samples", name, compressed)
        return {"file": f"samples/{name}", "sha256": digest(compressed), "bytes": len(compressed)}

    def roster(self, config: dict, default="collector_interrupted") -> list:
        rows = []
        t0 = timestamp(config["t0_utc"])
        for slot in range(SLOTS):
            row = {"slot": slot, "decision": slot in CONSTANTS["decision_slots"],
                   "planned_utc_ns": t0 + slot * INTERVAL_NS, "status": default}
            sample = self.path / "samples" / f"slot-{slot:03d}.json.gz"
            claim = self.path / "terminal" / f"claim-{slot:03d}.json"
            if sample.exists():
                compressed = read(sample, 262144)
                with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                    decoded = stream.read(262145)
                if len(decoded) > 262144:
                    raise BudgetExceeded("recovery slot decoded limit")
                record = json.loads(decoded)
                if record.get("slot") != slot or record.get("planned_utc_ns") != row["planned_utc_ns"]:
                    raise ValueError("stored slot identity mismatch")
                row.update(status=record["status"], file=f"samples/{sample.name}",
                           sha256=digest(compressed), bytes=len(compressed))
            elif claim.exists():
                claimed = json.loads(read(claim, 4096))
                if claimed != {"slot": slot, "planned_utc_ns": row["planned_utc_ns"]}:
                    raise ValueError("claim identity mismatch")
                row["status"] = "claimed_without_sample"
            rows.append(row)
        return rows

    def index(self, config: dict, status: str, *, error=None):
        previous = self.path / "terminal" / "index.json"
        if previous.exists() or previous.is_symlink():
            prior = json.loads(read(previous, INDEX_RESERVE))
            entries = prior.get("slots")
            if (prior.get("schema") != "dated-carry-collector-index-v1"
                    or not isinstance(entries, list) or len(entries) != SLOTS
                    or [entry.get("slot") for entry in entries] != list(range(SLOTS))):
                raise ValueError("previous index identity mismatch")
            for entry in entries:
                if "file" not in entry:
                    continue
                if entry["file"] != f"samples/slot-{entry['slot']:03d}.json.gz":
                    raise ValueError("previous index file identity mismatch")
                compressed = read(self.path / entry["file"], 262144)
                if len(compressed) != entry["bytes"] or digest(compressed) != entry["sha256"]:
                    # Do not re-attest changed evidence or replace the last index.
                    raise ValueError("previously attested sample hash/bytes mismatch")
        rows = self.roster(config, "missing" if status == "complete" else "collector_interrupted")
        payload = {"schema": "dated-carry-collector-index-v1", "status": status,
                   "updated_utc": utc(time.time_ns()), "slots": rows, "error": error,
                   "economics_evaluated": False, "requests_retried": False}
        self.write("terminal", "index.json", body(payload), replace=True)
        self.write("terminal", "status.json", body({"schema": "dated-carry-collector-status-v1",
                   "status": status, "slots": SLOTS, "error": error, "economics_evaluated": False}), replace=True)
        return payload


def load_slot(study_dir: Path, entry: dict) -> dict | None:
    """Bounded endpoint reader; absent slots remain absent, never reconstructed."""
    slot = entry["slot"]
    if type(slot) is not int or not 0 <= slot < SLOTS:
        raise ValueError("invalid index slot")
    if "file" not in entry:
        return None
    if entry["file"] != f"samples/slot-{slot:03d}.json.gz":
        raise ValueError("index file identity mismatch")
    compressed = read(study_dir / entry["file"], 262144)
    if len(compressed) != entry["bytes"] or digest(compressed) != entry["sha256"]:
        raise ValueError("sample hash/bytes mismatch")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        decoded = stream.read(262145)
    if len(decoded) > 262144:
        raise BudgetExceeded("sample decoded limit")
    record = json.loads(decoded)
    if record.get("slot") != slot or record.get("planned_utc_ns") != entry["planned_utc_ns"]:
        raise ValueError("sample/index identity mismatch")
    return record


def prepare(config_path: Path, config_sha256: str, study_dir: Path, freeze_path: Path) -> dict:
    config = load_config(config_path, config_sha256)
    store = Store(study_dir, external_bytes=verify_pins(config, study_dir.resolve()))
    if freeze_path.resolve() != store.path / "source_control" / freeze_path.name:
        raise ValueError("freeze must live in study source_control directory")
    config_external = 0 if config_path.resolve().is_relative_to(store.path) else config_path.stat().st_size
    store.external["source_control"] += config_external
    frozen = {"schema": "dated-carry-collector-freeze-v1", "created_utc": utc(time.time_ns()),
              "config_path": str(config_path.resolve()), "config_sha256": config_sha256,
              "study_dir": str(store.path), "source_sha256": config["source_sha256"],
              "metadata_sha256": config["metadata_sha256"], "constants": CONSTANTS,
              "external_bytes": store.external, "runtime": {"python": sys.version,
              "aiohttp": __import__("aiohttp").__version__}, "network_performed": False}
    store.write("source_control", freeze_path.name, body(frozen))
    return frozen


def verify_freeze(config_path: Path, config_sha256: str, study_dir: Path,
                  freeze_path: Path, freeze_sha256: str):
    data = read(freeze_path, 131072)
    if not SHA.fullmatch(freeze_sha256) or digest(data) != freeze_sha256:
        raise ValueError("freeze hash mismatch")
    freeze = json.loads(data)
    config = load_config(config_path, config_sha256)
    external = verify_pins(config, study_dir.resolve())
    if not config_path.resolve().is_relative_to(study_dir.resolve()):
        external["source_control"] += config_path.stat().st_size
    expected = {"schema": "dated-carry-collector-freeze-v1", "config_path": str(config_path.resolve()),
                "config_sha256": config_sha256, "study_dir": str(study_dir.resolve()),
                "source_sha256": config["source_sha256"], "metadata_sha256": config["metadata_sha256"],
                "constants": CONSTANTS, "external_bytes": external,
                "runtime": {"python": sys.version, "aiohttp": __import__("aiohttp").__version__},
                "network_performed": False}
    if any(freeze.get(key) != value for key, value in expected.items()):
        raise ValueError("prepared freeze identity/runtime/pins mismatch")
    if freeze_path.resolve() != study_dir.resolve() / "source_control" / freeze_path.name:
        raise ValueError("freeze path mismatch")
    store = Store(study_dir, external_bytes=external)
    store.usage()
    return config, store


class SystemClock:
    def utc_ns(self):
        return time.time_ns()

    def monotonic_ns(self):
        return time.monotonic_ns()

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


async def until(clock, due_ns: int, stop: asyncio.Event):
    remaining = (due_ns - clock.monotonic_ns()) / 1e9
    if remaining <= 0 or stop.is_set():
        return
    sleeping = asyncio.create_task(clock.sleep(remaining))
    stopping = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait([sleeping, stopping], return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (sleeping, stopping):
            task.cancel()
        await asyncio.gather(sleeping, stopping, return_exceptions=True)


class PublicFetcher:
    def __init__(self, session):
        self.session = session

    async def __call__(self, role, instrument, timeout_seconds):
        import aiohttp
        timeout = aiohttp.ClientTimeout(total=min(1, timeout_seconds))
        async with self.session.get("https://www.deribit.com/api/v2/public/get_order_book",
                                    params={"instrument_name": instrument, "depth": 10},
                                    timeout=timeout, allow_redirects=False) as response:
            data = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                if len(data) + len(chunk) > RESPONSE_CAP:
                    raise BudgetExceeded(f"response category=samples requested={len(data)+len(chunk)} cap={RESPONSE_CAP}")
                data.extend(chunk)
            return {"http_status": response.status, "raw_utf8": bytes(data).decode("utf-8", errors="strict")}


async def collect(config: dict, store: Store, *, clock, fetch, stop=None) -> dict:
    """One launch only. fetch(role, instrument, timeout_seconds) performs ONE request.

    Test clocks expose utc_ns(), monotonic_ns(), async sleep(seconds). The launch
    mapping is durable and never rebased. Root's offline evaluator owns native
    timestamp/depth/rule/fee validation; collector exports arrival gates only.
    """
    stop = stop or asyncio.Event()
    if ((store.path / "terminal" / "launch.json").exists()
            or any((store.path / "terminal").glob("claim-*.json"))
            or any((store.path / "samples").glob("slot-*.json.gz"))):
        raise ValueError("study already launched: finalize-only recovery required")
    t0 = timestamp(config["t0_utc"])
    map_utc, map_mono = clock.utc_ns(), clock.monotonic_ns()
    if t0 - LEAD_NS <= map_utc:
        raise ValueError("launch must precede first dispatch deadline")
    t0_mono = map_mono + t0 - map_utc
    mapping = {"utc_ns": map_utc, "monotonic_ns": map_mono, "t0_utc_ns": t0,
               "t0_monotonic_ns": t0_mono, **clock_identity()}
    store.write("terminal", "launch.json", body({"schema": "dated-carry-collector-launch-v1", "mapping": mapping,
                "source_sha256": config["source_sha256"], "config_instruments": config["instruments"],
                "no_rebase": True, "slots": SLOTS}))
    store.index(config, "running")
    outcome = "complete"
    error = None

    def drift():
        return clock.utc_ns() - (map_utc + clock.monotonic_ns() - map_mono)

    async def request(role, instrument, deadline):
        started_utc, started_mono = clock.utc_ns(), clock.monotonic_ns()
        started_drift = started_utc - (map_utc + started_mono - map_mono)
        result = {"instrument": instrument, "request_utc": utc(started_utc), "request_utc_ns": started_utc,
                  "request_monotonic_ns": started_mono, "received_utc": None, "received_utc_ns": None,
                  "received_monotonic_ns": None, "status": "error", "http_status": None,
                  "raw_utf8": None, "error": None, "deadline_admitted": False,
                  "clock_drift_s": None, "clock_drift_ns": None}
        result.update(start_clock_drift_ns=started_drift, start_clock_drift_s=started_drift / 1e9)
        try:
            if abs(started_drift) > TOLERANCE_NS:
                result.update(status="clock_mapping_invalid", error="dispatch clock drift exceeded limit")
                return result
            remaining = (deadline - clock.monotonic_ns()) / 1e9
            if remaining <= 0:
                result.update(status="dispatch_deadline_missed", error="no request dispatched after deadline")
                return result
            response = await asyncio.wait_for(fetch(role, instrument, min(1, remaining)), min(1, remaining))
            received_utc, received_mono = clock.utc_ns(), clock.monotonic_ns()
            received_drift = received_utc - (map_utc + received_mono - map_mono)
            raw = response.get("raw_utf8")
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > RESPONSE_CAP:
                raise BudgetExceeded("response category=samples exceeds UTF8 byte cap")
            status = response.get("http_status")
            if type(status) is not int or not 100 <= status <= 599:
                raise ValueError("invalid HTTP status")
            result.update(received_utc=utc(received_utc), received_utc_ns=received_utc,
                          received_monotonic_ns=received_mono, raw_utf8=raw, http_status=status,
                          clock_drift_s=received_drift / 1e9, clock_drift_ns=received_drift,
                          deadline_admitted=received_utc <= t0 + (deadline - t0_mono) and received_mono <= deadline,
                          status="received" if status == 200 else "http_error")
        except asyncio.CancelledError:
            result.update(status="cancelled", error="collector termination")
        except Exception as exc:
            result.update(status="timeout" if isinstance(exc, (TimeoutError, asyncio.TimeoutError)) else "error",
                          error=f"{type(exc).__name__}: {str(exc)[:512]}")
        return result

    try:
        for slot in range(SLOTS):
            scheduled = t0 + slot * INTERVAL_NS
            deadline = t0_mono + slot * INTERVAL_NS
            await until(clock, deadline - LEAD_NS, stop)
            if stop.is_set():
                outcome = "interrupted"
                break
            if abs(drift()) > TOLERANCE_NS:
                outcome = "clock_mapping_invalid"
                break
            store.claim(slot, scheduled)
            if clock.monotonic_ns() >= deadline:
                responses = {role: {"instrument": name, "status": "dispatch_deadline_missed",
                                    "raw_utf8": None, "deadline_admitted": False, "error": "slot missed"}
                             for role, name in config["instruments"].items()}
            else:
                tasks = [asyncio.create_task(request(role, name, deadline)) for role, name in config["instruments"].items()]
                stopper = asyncio.create_task(stop.wait())
                bundle = asyncio.gather(*tasks)
                try:
                    await asyncio.wait([bundle, stopper], return_when=asyncio.FIRST_COMPLETED)
                    if stop.is_set():
                        for task in tasks:
                            task.cancel()
                    values = await bundle
                finally:
                    stopper.cancel()
                    await asyncio.gather(stopper, return_exceptions=True)
                responses = dict(zip(config["instruments"], values))
            await until(clock, deadline, stop)
            actual, mono = clock.utc_ns(), clock.monotonic_ns()
            offset = drift()
            lateness = max(0, actual - scheduled)
            status = "sampled"
            if stop.is_set():
                status = "interrupted"
            elif (abs(offset) > TOLERANCE_NS or any(
                    abs(response.get("start_clock_drift_ns") or 0) > TOLERANCE_NS
                    or abs(response.get("clock_drift_ns") or 0) > TOLERANCE_NS
                    for response in responses.values())):
                status = "clock_mapping_invalid"
            elif lateness > TOLERANCE_NS:
                status = "callback_late"
            elif not all(response.get("deadline_admitted") and response["status"] == "received" for response in responses.values()):
                status = "arrival_invalid"
            record = {"schema": "dated-carry-collector-slot-v1", "slot": slot,
                      "decision": slot in CONSTANTS["decision_slots"], "planned_utc": utc(scheduled),
                      "planned_utc_ns": scheduled, "dispatch_due_utc_ns": scheduled - LEAD_NS,
                      "actual_utc": utc(actual), "actual_utc_ns": actual,
                      "callback_monotonic_ns": mono, "clock_drift_s": offset / 1e9,
                      "clock_drift_ns": offset, "callback_lateness_ns": lateness,
                      "status": status, "responses": responses, "economics_evaluated": False,
                      "native_source_validation": "deferred_to_offline_evaluator"}
            store.sample(slot, record)
            store.index(config, "running")
            if status in ("interrupted", "clock_mapping_invalid"):
                outcome = status
                break
        if outcome == "complete":
            await until(clock, t0_mono + DURATION_NS, stop)
            if stop.is_set():
                outcome = "interrupted"
            elif abs(drift()) > TOLERANCE_NS:
                outcome = "clock_mapping_invalid"
    except (Exception, asyncio.CancelledError) as exc:
        outcome = "failed"
        error = f"{type(exc).__name__}: {str(exc)[:1024]}"
    return store.index(config, outcome, error=error)


async def live(config, store):
    import aiohttp
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        loop.add_signal_handler(signum, stop.set)
    try:
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=1),
                                         auto_decompress=False, cookie_jar=aiohttp.DummyCookieJar(),
                                         headers={"Accept-Encoding": "identity"}) as session:
            # aiohttp otherwise transparently retries idempotent methods after a
            # stale persistent connection. Freeze its runtime and disable this
            # implementation switch explicitly: one logical GET, one attempt.
            if not hasattr(session, "_retry_connection"):
                raise ValueError("aiohttp retry control unavailable")
            session._retry_connection = False
            return await collect(config, store, clock=SystemClock(), fetch=PublicFetcher(session), stop=stop)
    finally:
        for signum, handler in previous.items():
            loop.remove_signal_handler(signum)
            signal.signal(signum, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--finalize-only", action="store_true")
    parser.add_argument("--study-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--config-sha256")
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--freeze-sha256")
    args = parser.parse_args(argv)
    if not (args.prepare or args.run or args.finalize_only):
        print(json.dumps({"schema": "dated-carry-collector-dry-v1", "network_performed": False,
                          "constants": CONSTANTS, "required": ["study-dir", "config", "config-sha256", "freeze", "freeze-sha256"]}))
        return 0
    if not all((args.study_dir, args.config, args.config_sha256, args.freeze)):
        parser.error("study-dir/config/config-sha256/freeze required")
    if args.prepare:
        prepare(args.config, args.config_sha256, args.study_dir, args.freeze)
        print(json.dumps({"status": "prepared", "freeze_sha256": digest(read(args.freeze, 131072)), "network_performed": False}))
        return 0
    if not args.freeze_sha256:
        parser.error("reviewed freeze-sha256 required")
    config, store = verify_freeze(args.config, args.config_sha256, args.study_dir, args.freeze, args.freeze_sha256)
    with store.lock(finalize_only=args.finalize_only):
        if args.finalize_only:
            if not (store.path / "terminal" / "launch.json").exists():
                raise ValueError("cannot finalize an unlaunched study")
            result = store.index(config, "interrupted")
        else:
            result = asyncio.run(live(config, store))
        try:
            verify_freeze(args.config, args.config_sha256, args.study_dir, args.freeze, args.freeze_sha256)
        except Exception as exc:
            result = store.index(config, "source_changed", error=f"{type(exc).__name__}: {str(exc)[:1024]}")
    print(json.dumps({"status": result["status"], "slots": len(result["slots"]), "economics_evaluated": False}))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
