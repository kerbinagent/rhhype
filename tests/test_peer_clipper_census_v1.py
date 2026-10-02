"""Offline census tests using closed synthetic replies; no output artifacts."""
import copy
import hashlib
import io
import json
import socket
import unittest
from unittest import mock

from scripts import peer_clipper_census_v1 as gate

CLIPPER = "0xc67963a226eddd77b91ad8c421630a1b0adff270"
ILK = "0x4554482d41000000000000000000000000000000000000000000000000000000"
ZERO = "0x" + "00" * 20
RUNTIME = b"\x60\x00\x00"
PARENT = {"number": "0x2a", "hash": "0x" + "ab" * 32,
          "parentHash": "0x" + "cd" * 32, "timestamp": "0x4b0",
          "stateRoot": "0x" + "ef" * 32}
SELECTORS = {"ilk": "c5ce281e", "count": "06661abd", "list": "0f560cd7"}


def word(number):
    return "0x" + number.to_bytes(32, "big").hex()


def abi_list(ids, count=None, offset=32):
    count = len(ids) if count is None else count
    return word(offset) + word(count)[2:] + "".join(word(i)[2:] for i in ids)


def certificate(kind="synthetic_fixture"):
    return {"kind": kind, "root_review_ref": "caller claim; not authenticated review",
            "artifact_set_sha256": "a" * 64,
            "roles": {"clipper": {"address": CLIPPER,
                                  "runtime_sha256": hashlib.sha256(RUNTIME).hexdigest()}}}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RecordingStream(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.returned = 0
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        result = super().read(size)
        self.returned += len(result)
        return result


class SyntheticTransport:
    """Unexpected RPCs or parameters fail locally; nothing can dispatch."""
    def __init__(self, count=1, *, ids=None, replies=None,
                 padding=0, clock=None, elapsed=0, status=200):
        self.count = count
        self.ids = list(range(1, count + 1)) if ids is None else ids
        self.replies = replies or {}
        self.padding, self.clock, self.elapsed, self.status = padding, clock, elapsed, status
        self.requests, self.streams, self.bodies = [], [], []
        self.count_reads = 0

    def result(self, request):
        method, params = request["method"], request["params"]
        if method == "eth_chainId":
            assert params == []
            return self.replies.get("chain", "0x1")
        if method == "eth_getBlockByNumber":
            assert params in (["latest", False], [PARENT["number"], False])
            key = "parent" if params[0] == "latest" else "final_parent"
            return copy.deepcopy(self.replies.get(key, PARENT))
        assert params[-1] == {"blockHash": PARENT["hash"], "requireCanonical": True}
        if method == "eth_getCode":
            assert params == [CLIPPER, params[-1]]
            return self.replies.get("code", "0x" + RUNTIME.hex())
        assert method == "eth_call", "unexpected RPC"
        assert len(params) == 2
        call = params[0]
        key = {value: key for key, value in SELECTORS.items()}[call["input"][2:]]
        assert call == {"from": ZERO, "to": CLIPPER, "input": "0x" + SELECTORS[key],
                        "gas": "0x30d40", "value": "0x0"}
        if key == "ilk":
            return self.replies.get(key, ILK)
        if key == "count":
            self.count_reads += 1
            key = "count" if self.count_reads == 1 else "final_count"
            return self.replies.get(key, word(self.count))
        assert self.count > 0
        return self.replies.get("list", abi_list(self.ids))

    def __call__(self, request, timeout):
        assert 0 < timeout <= 10
        assert request["jsonrpc"] == "2.0" and request["id"] == len(self.requests) + 1
        self.requests.append(copy.deepcopy(request))
        result = self.result(request)
        raw = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result},
                         separators=(",", ":"), ensure_ascii=False).encode()
        if self.padding:
            assert len(raw) <= self.padding
            raw += b" " * (self.padding - len(raw))
        if self.clock:
            self.clock.now += self.elapsed
        stream = RecordingStream(raw)
        self.bodies.append(raw)
        self.streams.append(stream)
        return self.status, stream


class ClipperCensusTests(unittest.TestCase):
    def run_gate(self, transport=None, binding="fixture", **kwargs):
        transport = transport or SyntheticTransport()
        supplied = certificate() if binding == "fixture" else binding
        collector = gate.Collector(transport, binding=supplied, **kwargs)
        return collector.execute(), collector, transport

    def assert_metadata_only(self, result):
        self.assertIsNone(result["economics"])
        self.assertFalse(result["source_equivalence_proven_by_collector"])
        self.assertFalse(result["runtime_dependency_closure_complete"])
        self.assertFalse(result["certificate_authority_verified"])
        self.assertEqual(result["network_requests_permitted"], 0)
        for key in ("cash_closed", "reset_eligibility_established", "inclusion_established"):
            self.assertFalse(result[key])
        self.assertEqual(result["requests"] + len(result["unexecuted_steps"]), 8)

    def test_complete_census(self):
        for ids in ([], [7], list(range(64, 0, -1)), [17, 3, (1 << 256) - 1]):
            with self.subTest(count=len(ids)):
                result, collector, transport = self.run_gate(SyntheticTransport(len(ids), ids=ids))
                status = "reported_nonempty_metadata_only" if ids else "reported_empty_metadata_only"
                self.assertEqual(result["status"], status)
                self.assertTrue(result["provider_census_complete"])
                self.assertEqual(result["metadata"]["reported_count"], len(ids))
                self.assertEqual(result["metadata"]["reported_ids"], ids)
                self.assertEqual(result["requests"], 8 if ids else 7)
                self.assertEqual(len(collector.trace), len(transport.bodies))
                self.assertEqual(result["body_bytes"], sum(map(len, transport.bodies)))
                for row, body in zip(collector.trace, transport.bodies):
                    self.assertEqual(row["body_bytes"], len(body))
                    self.assertEqual(row["body_sha256"], hashlib.sha256(body).hexdigest())
                    self.assertTrue(row["eof"])
                self.assert_metadata_only(result)

    def test_census_cap_stops_before_list(self):
        result, _, transport = self.run_gate(SyntheticTransport(65))
        self.assertFalse(result["provider_census_complete"])
        self.assertEqual(result["requests"], 5)
        self.assertEqual(result["status"], "census_over_cap")
        self.assertFalse(any(r["method"] == "eth_call" and r["params"][0]["input"] == "0x0f560cd7"
                             for r in transport.requests))
        self.assert_metadata_only(result)

    def test_malformed_list_never_repairs(self):
        valid = abi_list([3, 1])
        cases = (abi_list([3, 1], offset=64), abi_list([3, 1], count=1),
                 abi_list([3, 1], count=3), valid[:-2], valid + "00", "0x",
                 abi_list([0, 1]), abi_list([1, 1]), valid[:-1] + "g")
        for raw in cases:
            with self.subTest(raw=raw):
                result, collector, _ = self.run_gate(SyntheticTransport(2, replies={"list": raw}))
                self.assertFalse(result["provider_census_complete"])
                self.assertEqual(result["status"], "abi_unavailable")
                self.assertEqual(result["requests"], 6)
                self.assertEqual(collector.trace[-1]["name"], "list")
                self.assert_metadata_only(result)

    def test_malformed_count_and_ilk(self):
        for key, raw in (("count", "0x01"), ("count", word(1) + "00"),
                         ("count", "0x" + "00" * 31), ("ilk", ILK[:-2]),
                         ("ilk", ILK + "00")):
            result, _, _ = self.run_gate(SyntheticTransport(replies={key: raw}))
            self.assertEqual(result["status"], "abi_unavailable")
            self.assertFalse(result["provider_census_complete"])
            self.assertEqual(result["requests"], 5 if key == "count" else 4)

    def test_identity_failures(self):
        for replies, requests in (({"chain": "0x2"}, 1), ({"code": "0x"}, 3),
                                  ({"ilk": "0x" + "00" * 32}, 4)):
            result, _, _ = self.run_gate(SyntheticTransport(replies=replies))
            self.assertEqual(result["status"], "identity_unavailable")
            self.assertEqual(result["requests"], requests)
            self.assertFalse(result["provider_census_complete"])
        result, _, _ = self.run_gate(SyntheticTransport(replies={"code": "0x600100"}))
        self.assertEqual(result["status"], "binding_mismatch")
        self.assertEqual(result["certificate_roles_matched"], [])
        self.assertEqual(result["certificate_roles_unverified"], ["clipper"])

    def test_final_rechecks(self):
        for replies, requests in (({"final_count": word(2)}, 7),
                                  ({"final_parent": dict(PARENT, hash="0x" + "00" * 32)}, 8)):
            result, _, _ = self.run_gate(SyntheticTransport(replies=replies))
            self.assertEqual(result["status"], "canonicality_unavailable")
            self.assertEqual(result["requests"], requests)
            self.assertFalse(result["provider_census_complete"])
            self.assert_metadata_only(result)

    def test_header_validation_and_projection(self):
        for parent, status in ((None, "canonicality_unavailable"),
                               (dict(PARENT, hash=None), "abi_unavailable"),
                               (dict(PARENT, number="0x02a"), "abi_unavailable")):
            result, _, _ = self.run_gate(SyntheticTransport(replies={"parent": parent}))
            self.assertEqual(result["status"], status)
            self.assertEqual(result["requests"], 2)
            self.assertFalse(result["provider_census_complete"])
        history = dict(PARENT, transactions=[{"input": "synthetic private-looking field"}])
        result, collector, _ = self.run_gate(SyntheticTransport(replies={"parent": history}))
        self.assertEqual(result["metadata"]["parent"], PARENT)
        self.assertNotIn("transactions", collector.trace[1]["response"]["result"])

    def test_caller_certificate_and_absence(self):
        for count in (0, 1):
            for kind in ("synthetic_fixture", "root_reviewed_artifact_certificate"):
                supplied = certificate(kind)
                result, _, _ = self.run_gate(SyntheticTransport(count), binding=supplied)
                self.assertEqual(result["certificate_kind_claim"], kind)
                self.assertEqual(result["certificate_review_ref_claim"], supplied["root_review_ref"])
                self.assertEqual(result["certificate_roles_matched"], ["clipper"])
                self.assertEqual(result["certificate_roles_unverified"], [])
                self.assert_metadata_only(result)
        missing, _, _ = self.run_gate(binding=None)
        self.assertEqual(missing["status"], "source_binding_unavailable")
        self.assertTrue(missing["provider_census_complete"])
        self.assertIsNone(missing["certificate_kind_claim"])
        self.assertIsNone(missing["certificate_review_ref_claim"])
        self.assertEqual(missing["certificate_roles_matched"], [])
        self.assertEqual(missing["certificate_roles_unverified"], ["clipper"])
        self.assert_metadata_only(missing)

    def test_malformed_certificate_never_calls_transport(self):
        for field, value in (("kind", "authenticated"), ("root_review_ref", None),
                             ("artifact_set_sha256", None), ("artifact_set_sha256", 42),
                             ("roles", {}), ("extra", 0)):
            bad = certificate()
            bad[field] = value
            transport = mock.Mock(side_effect=AssertionError("must not dispatch"))
            with self.subTest(field=field), self.assertRaises(gate.GateError):
                gate.Collector(transport, binding=bad)
            transport.assert_not_called()

    def test_bounded_reads_and_receipts(self):
        for caps, size, total, calls in (({"response_bytes": 128}, 1024, 129, 1),
                                        ({"total_body_bytes": 196608}, 65536, 196608, 3)):
            with self.subTest(caps=caps), mock.patch.dict(gate.CAPS, caps):
                result, collector, transport = self.run_gate(SyntheticTransport(padding=size))
                self.assertEqual(result["status"], "resource_unavailable")
                self.assertEqual(result["requests"], calls)
                self.assertEqual(result["body_bytes"], total)
                self.assertEqual(sum(s.returned for s in transport.streams), total)
                self.assertFalse(collector.trace[-1]["eof"])
                prefix = transport.bodies[-1][:transport.streams[-1].returned]
                self.assertEqual(collector.trace[-1]["body_sha256"], hashlib.sha256(prefix).hexdigest())
                self.assertLessEqual(len(gate.encoded(collector.trace)), gate.CAPS["trace_bytes"])

    def test_deadline_and_single_use(self):
        result, _, transport = self.run_gate(clock=mock.Mock(side_effect=[0, 80]))
        self.assertEqual(result["status"], "resource_unavailable")
        self.assertEqual(transport.requests, [])
        clock = Clock()
        result, collector, transport = self.run_gate(SyntheticTransport(clock=clock, elapsed=11), clock=clock)
        self.assertEqual(result["status"], "resource_unavailable")
        self.assertEqual(result["requests"], 1)
        with self.assertRaises(gate.GateError):
            collector.execute()
        self.assertEqual(len(transport.requests), 1)
        _, collector, transport = self.run_gate()
        with self.assertRaises(gate.GateError):
            collector.execute()
        self.assertEqual(len(transport.requests), 8)

    def test_trace_cap_retains_failure_hash(self):
        with mock.patch.dict(gate.CAPS, {"trace_bytes": 6000}):
            result, collector, transport = self.run_gate(SyntheticTransport(replies={"chain": "😀" * 400}))
        self.assertEqual(result["status"], "resource_unavailable")
        row = collector.trace[-1]
        self.assertEqual(row["outcome"], "failed")
        self.assertTrue(row["response_omitted_for_cap"])
        self.assertNotIn("response", row)
        self.assertEqual(row["body_sha256"], hashlib.sha256(transport.bodies[-1]).hexdigest())
        self.assertLessEqual(len(gate.encoded(collector.trace)), 6000)

    def test_dry_cli_and_pins(self):
        plan = json.loads(gate.PLAN_PATH.read_bytes())
        plan["source_pins"] = []
        stdout = io.StringIO()
        with mock.patch.object(gate, "bounded_file", return_value=gate.encoded(plan)), \
                mock.patch.object(gate, "Collector", side_effect=AssertionError("dry only")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("no network")), \
                mock.patch("sys.stdout", stdout):
            self.assertEqual(gate.main([]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["requests_permitted"], 0)
        for args in (("--run",), ("--live",), ("--endpoint", "https://invalid.example")):
            with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
                gate.main(list(args))
        pins = []
        for path in gate.PIN_PATHS:
            raw = gate.bounded_file(gate.ROOT / path)
            pins.append({"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertEqual(gate.verify_file_pins({"source_pins": pins}), "verified")
        pins[0]["sha256"] = "0" * 64
        with self.assertRaises(gate.GateError):
            gate.verify_file_pins({"source_pins": pins})


if __name__ == "__main__":
    unittest.main()
