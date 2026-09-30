import asyncio
import contextlib
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import dated_carry_collector as c


class Clock:
    def __init__(self, stop, *, end_after=3, late=0):
        self.now = 1_800_000_000_000_000_000
        self.mono = 100_000_000_000
        self.stop = stop
        self.sleeps = 0
        self.end_after = end_after
        self.late = late

    def utc_ns(self):
        return self.now

    def monotonic_ns(self):
        return self.mono

    async def sleep(self, seconds):
        await asyncio.sleep(0)
        self.sleeps += 1
        if self.sleeps == self.end_after:
            self.stop.set()
            return
        advance = round(seconds * 1e9) + (self.late if self.sleeps == 2 else 0)
        self.now += advance
        self.mono += advance


def config_for(clock):
    return {"schema": "dated-carry-collector-config-v1", "t0_utc": c.utc(clock.now + 10_000_000_000),
            "instruments": {"spot": "BTC_USDC", "future": "BTC_USDC-9OCT26"},
            "source_sha256": {}, "metadata_sha256": {}}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def collect(self, *, late=0, mode=None):
        async def scenario():
            stop = asyncio.Event()
            clock = Clock(stop, late=late)
            config = config_for(clock)
            store = c.Store(self.path / "study")
            called = []

            async def fetch(role, instrument, timeout):
                called.append((role, instrument, timeout, clock.now))
                await asyncio.sleep(0)
                if mode == "oversize":
                    return {"http_status": 200, "raw_utf8": "a" * (c.RESPONSE_CAP + 1)}
                if mode == "drift":
                    clock.now += 300_000_000
                if mode == "late_receipt":
                    clock.now += 1_100_000_000
                    clock.mono += 1_100_000_000
                return {"http_status": 200, "raw_utf8": '{"result":{"timestamp":1}}'}

            with store.lock():
                result = await c.collect(config, store, clock=clock, fetch=fetch, stop=stop)
            return config, result, called
        return asyncio.run(scenario())

    def test_fixed_roster_claim_and_two_concurrent_requests(self):
        config, result, called = self.collect()
        self.assertEqual(len(result["slots"]), 864)
        self.assertEqual([r["slot"] for r in result["slots"] if r["decision"]], [0, 144, 288, 432, 576, 720])
        self.assertEqual(len(called), 2)
        self.assertEqual(called[0][3], called[1][3])
        self.assertEqual(called[0][3], c.timestamp(config["t0_utc"]) - 1_000_000_000)
        self.assertTrue((self.path / "study/terminal/claim-000.json").exists())
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["slots"][0]["status"], "sampled")
        record = c.load_slot(self.path / "study", result["slots"][0])
        self.assertEqual(record["actual_utc_ns"], record["planned_utc_ns"])
        self.assertTrue(all(r["deadline_admitted"] for r in record["responses"].values()))
        self.assertTrue(all(r["clock_drift_s"] == 0 for r in record["responses"].values()))
        self.assertEqual(record["responses"]["spot"]["raw_utf8"], '{"result":{"timestamp":1}}')
        self.assertFalse(record["economics_evaluated"])
        mapping = json.loads((self.path / "study/terminal/launch.json").read_bytes())["mapping"]
        self.assertEqual({key: mapping[key] for key in ("host", "boot_id")}, c.clock_identity())
        self.assertIsNone(c.load_slot(self.path / "study", result["slots"][1]))

    def test_callback_lateness_does_not_select_another_quote(self):
        _, result, called = self.collect(late=300_000_000)
        self.assertEqual(result["slots"][0]["status"], "callback_late")
        self.assertEqual(len(called), 2)

    def test_mapping_drift_is_permanent_no_rebase(self):
        _, result, called = self.collect(mode="drift")
        self.assertEqual(result["status"], "clock_mapping_invalid")
        self.assertEqual(len(called), 2)
        self.assertEqual(result["slots"][0]["status"], "clock_mapping_invalid")
        self.assertEqual(result["slots"][1]["status"], "collector_interrupted")

    def test_temporary_receipt_drift_remains_invalid_after_clock_recovers(self):
        async def scenario():
            stop = asyncio.Event()
            clock = Clock(stop)
            store = c.Store(self.path / "study")
            async def fetch(role, instrument, timeout):
                await asyncio.sleep(0)
                clock.now += 300_000_000 if role == "spot" else -300_000_000
                return {"http_status": 200, "raw_utf8": "{}"}
            result = await c.collect(config_for(clock), store, clock=clock, fetch=fetch, stop=stop)
            record = c.load_slot(store.path, result["slots"][0])
            self.assertEqual(record["clock_drift_ns"], 0)
            self.assertEqual(record["responses"]["spot"]["clock_drift_ns"], 300_000_000)
            self.assertEqual(result["status"], "clock_mapping_invalid")
        asyncio.run(scenario())

    def test_drift_after_claim_prevents_both_requests(self):
        async def scenario():
            stop = asyncio.Event()
            clock = Clock(stop)
            class DriftStore(c.Store):
                def claim(self, slot, scheduled):
                    super().claim(slot, scheduled)
                    clock.now += 300_000_000
            store = DriftStore(self.path / "study")
            async def forbidden(*args):
                self.fail("dispatch drift must prevent network")
            result = await c.collect(config_for(clock), store, clock=clock, fetch=forbidden, stop=stop)
            record = c.load_slot(store.path, result["slots"][0])
            self.assertEqual(result["status"], "clock_mapping_invalid")
            self.assertTrue(all(r["status"] == "clock_mapping_invalid" for r in record["responses"].values()))
        asyncio.run(scenario())

    def test_response_caps_and_late_receipts_are_not_admitted(self):
        _, result, called = self.collect(mode="oversize")
        record = c.load_slot(self.path / "study", result["slots"][0])
        self.assertEqual(record["status"], "arrival_invalid")
        self.assertTrue(all(r["raw_utf8"] is None for r in record["responses"].values()))
        self.assertEqual(len(called), 2)

    def test_claimed_slot_and_launch_cannot_resume_network(self):
        async def scenario():
            stop = asyncio.Event()
            clock = Clock(stop)
            config = config_for(clock)
            store = c.Store(self.path / "study")
            store.claim(0, c.timestamp(config["t0_utc"]))
            async def forbidden(*args):
                self.fail("recovery must never fetch")
            with self.assertRaisesRegex(ValueError, "finalize-only"):
                await c.collect(config, store, clock=clock, fetch=forbidden)
            result = store.index(config, "interrupted")
            self.assertEqual(result["slots"][0]["status"], "claimed_without_sample")
            self.assertEqual(len(result["slots"]), 864)
        asyncio.run(scenario())

    def test_stop_cancels_pending_requests_and_retains_roster(self):
        async def scenario():
            stop = asyncio.Event()
            clock = Clock(stop, end_after=999)
            config = config_for(clock)
            store = c.Store(self.path / "study")
            calls = []
            async def fetch(role, instrument, timeout):
                calls.append(role)
                if len(calls) == 2:
                    stop.set()
                await asyncio.sleep(10)
            result = await c.collect(config, store, clock=clock, fetch=fetch, stop=stop)
            record = c.load_slot(store.path, result["slots"][0])
            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(len(calls), 2)
            self.assertTrue(all(r["status"] == "cancelled" for r in record["responses"].values()))
            self.assertEqual(len(result["slots"]), 864)
        asyncio.run(scenario())

    def test_caps_include_gzip_trailer_and_atomic_replacement_peak(self):
        store = c.Store(self.path / "study")
        encoded = c.body({"slot": 0, "planned_utc_ns": 1, "status": "sampled"})
        size = len(gzip.compress(encoded, mtime=0))
        caps = dict(c.CAPS, samples=size - 1)
        with patch.object(c, "CAPS", caps), self.assertRaises(c.BudgetExceeded):
            store.sample(0, json.loads(encoded))
        self.assertFalse((store.path / "samples/slot-000.json.gz").exists())
        store.write("terminal", "one.json", b"a" * 20)
        with patch.dict(c.CAPS, {"terminal": 30}), self.assertRaises(c.BudgetExceeded):
            store.write("terminal", "one.json", b"b" * 20, replace=True)
        self.assertEqual((store.path / "terminal/one.json").read_bytes(), b"a" * 20)

    def test_exhausted_samples_still_have_terminal_failure_roster(self):
        async def scenario():
            stop = asyncio.Event()
            clock = Clock(stop)
            config = config_for(clock)
            store = c.Store(self.path / "study")
            async def fetch(*args):
                return {"http_status": 200, "raw_utf8": "{}"}
            with patch.dict(c.CAPS, {"samples": 1}):
                result = await c.collect(config, store, clock=clock, fetch=fetch, stop=stop)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(len(result["slots"]), 864)
            self.assertEqual(result["slots"][0]["status"], "claimed_without_sample")
            self.assertIn("category=samples", result["error"])
        asyncio.run(scenario())

    def test_no_overwrite_symlinks_lock_and_sample_hash(self):
        store = c.Store(self.path / "study")
        store.write("samples", "occupied", b"a")
        with self.assertRaises(FileExistsError):
            store.write("samples", "occupied", b"b")
        (store.path / "samples/dangling").symlink_to("absent")
        with self.assertRaises(FileExistsError):
            store.write("samples", "dangling", b"c")
        (store.path / "samples/dangling").unlink()
        with store.lock():
            with self.assertRaises(ValueError):
                with store.lock():
                    pass
        row = {"slot": 0, "planned_utc_ns": 1, "status": "sampled"}
        entry = store.sample(0, row)
        entry.update(slot=0, planned_utc_ns=1)
        self.assertEqual(c.load_slot(store.path, entry), row)
        entry["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            c.load_slot(store.path, entry)

    def test_atomic_no_overwrite_refuses_competing_claim_at_publication(self):
        store = c.Store(self.path / "study")
        original_link = c.os.link
        def raced_link(source, target):
            Path(target).write_bytes(b"competing claim")
            return original_link(source, target)
        with patch.object(c.os, "link", raced_link), self.assertRaises(FileExistsError):
            store.write("terminal", "claim-000.json", b"new claim")
        self.assertEqual((store.path / "terminal/claim-000.json").read_bytes(), b"competing claim")
        self.assertEqual(list((store.path / "terminal").glob("*.tmp")), [])

    def test_separate_preparation_and_source_mutation_refusal_zero_http(self):
        root = self.path / "repo"
        root.mkdir()
        pins = {}
        for name in ["scripts/dated_carry_collector.py", "tests/test_dated_carry_collector.py", "scripts/dated_carry_analysis.py"]:
            path = root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(name.encode())
            pins[name] = c.digest(path.read_bytes())
        metadata = root / "metadata.json"
        metadata.write_bytes(b"{}")
        config = {"schema": "dated-carry-collector-config-v1", "t0_utc": "2026-10-01T00:00:00+00:00",
                  "instruments": {"spot": "BTC_USDC", "future": "BTC_USDC-9OCT26"},
                  "source_sha256": pins, "metadata_sha256": {"metadata.json": c.digest(b"{}")},
                  "markets": {}, "fees": {"spot_taker": "0.0005"}}
        config_path = root / "config.json"
        config_path.write_bytes(c.body(config))
        config_sha = c.digest(config_path.read_bytes())
        study = root / "study"
        freeze = study / "source_control/freeze.json"
        with patch.object(c, "ROOT", root):
            c.prepare(config_path, config_sha, study, freeze)
            sha = c.digest(freeze.read_bytes())
            actual, store = c.verify_freeze(config_path, config_sha, study, freeze, sha)
            self.assertEqual(actual, config)
            self.assertGreater(store.usage()["source_control"], freeze.stat().st_size)
            (root / "scripts/dated_carry_analysis.py").write_bytes(b"mutated")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                c.verify_freeze(config_path, config_sha, study, freeze, sha)

    def test_default_dry_has_zero_files_or_fetch(self):
        with patch.object(c, "PublicFetcher", side_effect=AssertionError("no HTTP")), contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(c.main([]), 0)
        self.assertFalse(json.loads(stdout.getvalue())["network_performed"])
        self.assertEqual(list(self.path.iterdir()), [])

    def test_public_fetch_has_fixed_url_no_redirect_and_stream_cap(self):
        class Content:
            async def iter_chunked(self, size):
                yield b"{}"
        class Response:
            status = 200
            content = Content()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        class Session:
            def get(self, url, **kwargs):
                self.url, self.kwargs = url, kwargs
                return Response()
        session = Session()
        result = asyncio.run(c.PublicFetcher(session)("spot", "BTC_USDC", 1))
        self.assertEqual(result, {"http_status": 200, "raw_utf8": "{}"})
        self.assertEqual(session.url, "https://www.deribit.com/api/v2/public/get_order_book")
        self.assertEqual(session.kwargs["params"], {"instrument_name": "BTC_USDC", "depth": 10})
        self.assertFalse(session.kwargs["allow_redirects"])
        self.assertEqual(session.kwargs["timeout"].total, 1)

    def test_live_session_disables_environment_cookies_and_internal_get_retry(self):
        captured = {}
        class Session:
            _retry_connection = True
            def __init__(self, **kwargs):
                captured.update(kwargs)
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
        async def fake_collect(config, store, *, clock, fetch, stop):
            self.assertFalse(fetch.session._retry_connection)
            return {"status": "interrupted"}
        with patch("aiohttp.ClientSession", Session), patch.object(c, "collect", fake_collect):
            result = asyncio.run(c.live({}, None))
        self.assertEqual(result["status"], "interrupted")
        self.assertFalse(captured["trust_env"])
        self.assertFalse(captured["auto_decompress"])
        self.assertEqual(captured["cookie_jar"].__class__.__name__, "DummyCookieJar")
        self.assertEqual(captured["headers"], {"Accept-Encoding": "identity"})


if __name__ == "__main__":
    unittest.main()
