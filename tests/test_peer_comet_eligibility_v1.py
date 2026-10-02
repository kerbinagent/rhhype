"""Synthetic Comet gate checks; no network, saved market inputs, or output files."""
import copy
import hashlib
import io
import json
import socket
import unittest
from unittest import mock

from scripts import peer_comet_eligibility_v1 as gate


SELECTORS = {
    "assetList()": "e372f03a", "baseToken()": "c55dae63",
    "baseScale()": "44c1e5eb", "getAssetInfoByAddress(address)": "3b3bec2e",
    "isBuyPaused()": "d8e5f611", "getReserves()": "0902f1ac",
    "targetReserves()": "32176c49", "getCollateralReserves(address)": "9ff567f8",
    "getPool(address,address,uint24)": "1698ee82", "factory()": "c45a0155",
    "token0()": "0dfe1681", "token1()": "d21220a7", "fee()": "ddca3f43",
    "tickSpacing()": "d0c93a7c",
}
IMPL = "0x" + "11" * 20
ASSETS = "0x" + "22" * 20
POOL = "0x" + "33" * 20
FEED = "0x" + "44" * 20
USDC_IMPL = "0x" + "55" * 20
USDC_ADMIN = "0x" + "66" * 20
USDC_IMPL_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"
USDC_ADMIN_SLOT = "0x10d6a54a4754c8869d6886b5f5d7fbfa5b4522237ea5c60d11bc4e7a1ff9390b"
PARENT = {"number": "0x2a", "hash": "0x" + "ab" * 32,
          "parentHash": "0x" + "cd" * 32, "timestamp": "0x4b0",
          "stateRoot": "0x" + "ef" * 32}
DECISION_MS = 1_200_000
CODE = {
    "proxy": (gate.COMET, b"\x60\x00\x00"),
    "implementation": (IMPL, b"\x60\x01\x00"),
    "asset_list": (ASSETS, b"\x60\x02\x00"),
    "weth": (gate.WETH, b"\x60\x03\x00"),
    "usdc_proxy": (gate.USDC, b"\x60\x06\x00"),
    "usdc_implementation": (USDC_IMPL, b"\x60\x07\x00"),
    "factory": (gate.FACTORY, b"\x60\x04\x00"),
    "pool": (POOL, b"\x60\x05\x00"),
}


def word(number):
    return "0x" + (number % (1 << 256)).to_bytes(32, "big").hex()


def addr(value):
    return "0x" + "00" * 12 + value[2:]


def view_words(reserves=-1, target=0, inventory=10**18, paused=False):
    return [word(int(paused)), word(reserves), word(target), word(inventory)]


def weth_tuple():
    words = [word(0), addr(gate.WETH), addr(FEED), word(10**18),
             word(8 * 10**17), word(85 * 10**16), word(93 * 10**16),
             word(500_000 * 10**18)]
    return "0x" + "".join(w[2:] for w in words)


def certificate(kind="synthetic_fixture"):
    return {"kind": kind, "root_review_ref": "synthetic-only; not deployed EVM evidence",
            "artifact_set_sha256": "a" * 64,
            "roles": {role: {"address": target,
                             "runtime_sha256": hashlib.sha256(code).hexdigest()}
                      for role, (target, code) in CODE.items()}}


def draft():
    return json.loads(gate.PLAN_PATH.read_bytes())


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class RecordingStream(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.read_sizes = []
        self.returned = 0

    def read(self, size=-1):
        self.read_sizes.append(size)
        result = super().read(size)
        self.returned += len(result)
        return result


class SyntheticTransport:
    """Closed fake server. Unexpected targets/selectors fail, never dispatch."""
    def __init__(self, *, parent_values=None, child_values=None,
                 mutate_child=None, replies=None, pad=0, clock=None, elapsed=0):
        self.parent_values = parent_values or view_words()
        self.child_values = child_values or self.parent_values
        self.mutate_child = mutate_child
        self.replies = replies or {}
        self.pad = pad
        self.clock, self.elapsed = clock, elapsed
        self.requests, self.streams, self.bodies, self.timeouts = [], [], [], []
        self.storage_reads = {gate.COMET: 0, gate.USDC: 0}

    def child(self, request):
        opts, anchor = request["params"]
        assert anchor == PARENT["number"]
        assert opts["validation"] is False
        assert opts["traceTransfers"] is False
        assert opts["returnFullTransactions"] is False
        assert len(opts["blockStateCalls"]) == 1
        block = opts["blockStateCalls"][0]
        assert set(block) == {"blockOverrides", "calls"}
        assert set(block["blockOverrides"]) == {"number", "time"}
        assert len(block["calls"]) == 4
        for call, sig in zip(block["calls"],
                             ("isBuyPaused()", "getReserves()", "targetReserves()",
                              "getCollateralReserves(address)")):
            argument = addr(gate.WETH)[2:] if sig.endswith("(address)") else ""
            assert call == {"from": gate.ZERO, "to": gate.COMET,
                            "input": "0x" + SELECTORS[sig] + argument,
                            "gas": "0x30d40", "value": "0x0"}
        result = [{"number": block["blockOverrides"]["number"],
                   "parentHash": PARENT["hash"],
                   "timestamp": block["blockOverrides"]["time"],
                   "calls": [{"status": "0x1", "gasUsed": "0x5208",
                              "returnData": value, "logs": []}
                             for value in self.child_values]}]
        if self.mutate_child:
            self.mutate_child(result)
        return result

    def result(self, request):
        method, params = request["method"], request["params"]
        if method == "eth_chainId":
            assert params == []
            return "0x1"
        if method == "eth_getBlockByNumber":
            assert params in (["latest", False], [PARENT["number"], False])
            key = "final_parent" if params[0] != "latest" else "parent"
            return copy.deepcopy(self.replies.get(key, PARENT))
        if method in ("eth_call", "eth_getCode", "eth_getStorageAt"):
            assert params[-1] == {"blockHash": PARENT["hash"], "requireCanonical": True}
        if method == "eth_getCode":
            assert len(params) == 2
            roles = {target: role for role, (target, _) in CODE.items()}
            role = roles[params[0]]
            return self.replies.get(role + "_code", "0x" + CODE[role][1].hex())
        if method == "eth_getStorageAt":
            if params[0] == gate.USDC:
                if params[1] == USDC_ADMIN_SLOT:
                    return self.replies.get("usdc_admin_slot", addr(USDC_ADMIN))
                assert params[1] == USDC_IMPL_SLOT
                self.storage_reads[gate.USDC] += 1
                key = "final_usdc_implementation" if self.storage_reads[gate.USDC] > 1 else "usdc_implementation_slot"
                return self.replies.get(key, addr(USDC_IMPL))
            assert params[:2] == [gate.COMET, gate.IMPLEMENTATION_SLOT]
            self.storage_reads[gate.COMET] += 1
            return self.replies.get("final_implementation", addr(IMPL)) if self.storage_reads[gate.COMET] > 1 else addr(IMPL)
        if method == "eth_simulateV1":
            return self.child(request)
        assert method == "eth_call", "unapproved RPC method"
        call = params[0]
        assert set(call) == {"from", "to", "input", "gas", "value"}
        assert call["from"] == gate.ZERO and call["value"] == "0x0"
        assert call["gas"] == "0x30d40"
        signature = {selector: sig for sig, selector in SELECTORS.items()}[call["input"][2:10]]
        expected_target = gate.FACTORY if signature.startswith("getPool(") else (
            POOL if signature in ("factory()", "token0()", "token1()", "fee()", "tickSpacing()") else gate.COMET)
        assert call["to"] == expected_target
        expected_args = (addr(gate.USDC)[2:] + addr(gate.WETH)[2:] + word(3000)[2:]) if signature.startswith("getPool(") else (
            addr(gate.WETH)[2:] if signature.endswith("(address)") else "")
        assert call["input"] == "0x" + SELECTORS[signature] + expected_args
        values = {"assetList()": addr(ASSETS), "baseToken()": addr(gate.USDC),
                  "baseScale()": word(10**6), "getAssetInfoByAddress(address)": weth_tuple(),
                  "isBuyPaused()": self.parent_values[0], "getReserves()": self.parent_values[1],
                  "targetReserves()": self.parent_values[2],
                  "getCollateralReserves(address)": self.parent_values[3],
                  "getPool(address,address,uint24)": addr(POOL), "factory()": addr(gate.FACTORY),
                  "token0()": addr(gate.USDC), "token1()": addr(gate.WETH),
                  "fee()": word(3000), "tickSpacing()": word(60)}
        return self.replies.get(signature, values[signature])

    def __call__(self, request, timeout):
        assert 0 < timeout <= 10
        assert request["jsonrpc"] == "2.0" and request["id"] == len(self.requests) + 1
        self.requests.append(copy.deepcopy(request))
        self.timeouts.append(timeout)
        result = self.result(request)
        envelope = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        body = json.dumps(envelope, separators=(",", ":"), ensure_ascii=False).encode()
        if self.pad:
            assert len(body) <= self.pad
            body += b" " * (self.pad - len(body))
        if self.clock:
            self.clock.now += self.elapsed
        stream = RecordingStream(body)
        self.streams.append(stream)
        self.bodies.append(body)
        return 200, stream


class CometEligibilityTests(unittest.TestCase):
    def run_gate(self, transport=None, binding="fixture", decision_ms=DECISION_MS, **kwargs):
        transport = transport or SyntheticTransport()
        supplied = certificate() if binding == "fixture" else binding
        collector = gate.Collector(transport, binding=supplied, **kwargs)
        result = collector.execute(decision_ms)
        return result, collector, transport

    def assert_unknown_economics(self, result):
        self.assertIsNone(result["economics"])
        self.assertFalse(result["cash_closed"])
        self.assertFalse(result["source_equivalence_proven_by_collector"])
        self.assertFalse(result["private_ack_proves_inclusion"])
        self.assertEqual(result["network_requests_permitted"], 0)
        self.assertFalse(result["runtime_dependency_closure_complete"])
        self.assertFalse(result["certificate_authority_verified"])
        self.assertNotIn("source_roles_checked", result)
        self.assertEqual(result["requests"] + len(result["unexecuted_steps"]), 31)
        self.assertEqual(len({row["name"] for row in result["unexecuted_steps"]}),
                         len(result["unexecuted_steps"]))

    def test_signed_thresholds(self):
        for target, reserves, eligible in ((0, -1, True), (0, 0, False), (0, 1, False),
                                            (1, -1, True), (1, 0, True), (1, 1, False), (1, 2, False)):
            with self.subTest(target=target, reserves=reserves):
                value = gate.eligibility(view_words(reserves, target))
                self.assertEqual(value["reported_eligible"], eligible)
                self.assertEqual(value["signed_reserves"], str(reserves))
                self.assertEqual(value["arm_inventory_sufficiency"], "not_evaluated")
        self.assertEqual(gate.sint(word(-(1 << 255))), -(1 << 255))
        self.assertEqual(gate.sint(word((1 << 255) - 1)), (1 << 255) - 1)

    def test_abi_domains(self):
        self.assertEqual(gate.sint(word(-60), 24), -60)
        self.assertEqual(gate.sint(word((1 << 23) - 1), 24), (1 << 23) - 1)
        bad_decoders = ((gate.uint, "0x" + "00" * 31), (gate.uint, "0x" + "00" * 33),
                        (gate.boolean, word(2)), (lambda v: gate.uint(v, 104), word(1 << 104)),
                        (lambda v: gate.sint(v, 24), word((1 << 24) - 60)),
                        (lambda v: gate.sint(v, 24), word(1 << 23)),
                        (gate.address, "0x01" + "00" * 31))
        for decoder, value in bad_decoders:
            with self.subTest(value=value):
                with self.assertRaises(gate.GateError):
                    decoder(value)
        self.assertEqual(gate.asset_info(weth_tuple())["asset"], gate.WETH)
        raw = weth_tuple()[2:]
        for index, replacement in ((0, word(24)), (1, addr(gate.USDC)), (3, word(10**6)),
                                   (4, word(8 * 10**17 + 1)), (6, word(10**18 + 1))):
            changed = "0x" + raw[:index * 64] + replacement[2:] + raw[(index + 1) * 64:]
            with self.subTest(index=index):
                with self.assertRaises(gate.GateError):
                    gate.asset_info(changed)

    def test_child_slot_grid_and_four_views(self):
        self.assertEqual(gate.child_time(PARENT, DECISION_MS), 1212)
        self.assertEqual(gate.child_time(PARENT, 1_211_600), 1212)
        self.assertEqual(gate.child_time(PARENT, 1_211_601), 1224)
        self.assertEqual(gate.child_time(PARENT, 1_212_600), 1224)
        for invalid in (True, -1, 1.5, 2**40 * 1000):
            with self.subTest(invalid=invalid), self.assertRaises(gate.GateError):
                gate.child_time(PARENT, invalid)
        result, _, transport = self.run_gate(decision_ms=1_211_601)
        self.assertEqual(result["status"], "reported_eligible_metadata_only")
        simulation = next(r for r in transport.requests if r["method"] == "eth_simulateV1")
        opts, anchor = simulation["params"]
        self.assertEqual(anchor, "0x2a")
        self.assertEqual(opts["blockStateCalls"][0]["blockOverrides"], {"number": "0x2b", "time": hex(1224)})
        self.assertNotIn("stateOverrides", opts["blockStateCalls"][0])
        self.assertFalse(opts["validation"])

    def test_accrual_changes_eligibility(self):
        # I=1e15,F=1e18,dt=12. At rate1e10, index delta=120000000.
        # Supply1e8 projects to100000012, so balance100000001 gives R=-11.
        # Borrow1e8 projects to100000012 against fixed supply1e8, so R=12.
        self.assertEqual((10**15 * 10**10 * 12) // 10**18, 120_000_000)
        for parent_r, child_r, expected, requests in ((1, -11, True, 31), (0, 12, False, 23)):
            with self.subTest(parent_r=parent_r, child_r=child_r):
                transport = SyntheticTransport(parent_values=view_words(parent_r, 1),
                                               child_values=view_words(child_r, 1))
                result, _, transport = self.run_gate(transport)
                self.assertEqual(result["metadata"]["parent_eligibility_claim"]["signed_reserves"], str(parent_r))
                self.assertEqual(result["metadata"]["child_eligibility_claim"]["signed_reserves"], str(child_r))
                self.assertEqual(result["metadata"]["child_eligibility_claim"]["reported_eligible"], expected)
                self.assertEqual(result["requests"], requests)
                self.assertEqual(any(r["method"] == "eth_getCode" and r["params"][0] == gate.FACTORY for r in transport.requests), expected)

    def test_child_context(self):
        mutations = (lambda x: x[0].update(number="0x2a"),
                     lambda x: x[0].update(timestamp="0x4bb"),
                     lambda x: x[0].update(parentHash="0x" + "00" * 32),
                     lambda x: x[0].update(parentHash=None),
                     lambda x: x.append(copy.deepcopy(x[0])),
                     lambda x: x[0]["calls"].pop())
        for mutate in mutations:
            transport = SyntheticTransport(mutate_child=mutate)
            request = {"params": gate.simulation_params(PARENT, 1212)}
            child = transport.child(request)
            with self.subTest(mutate=mutate), self.assertRaises(gate.GateError):
                gate.validate_child(child, PARENT, 1212)

    def test_all_child_failures(self):
        def all_fail(children):
            for receipt in children[0]["calls"]:
                receipt.update(status="0x0", returnData="0x", error={"code": 3, "message": "revert"})
        result, collector, _ = self.run_gate(SyntheticTransport(mutate_child=all_fail))
        self.assertEqual(result["status"], "child_views_unavailable")
        self.assertIn("0,1,2,3", result["error"])
        self.assertEqual(result["requests"], 20)
        self.assertNotIn("child_eligibility_claim", result["metadata"])
        self.assertEqual(len(collector.trace[-1]["response"]["result"][0]["calls"]), 4)
        self.assert_unknown_economics(result)
        for index in range(4):
            def one_fail(x, index=index):
                x[0]["calls"][index]["error"] = {"code": 3, "message": "revert"}
            result, _, _ = self.run_gate(SyntheticTransport(mutate_child=one_fail))
            self.assertEqual(result["status"], "child_views_unavailable")
            self.assertIn(str(index), result["error"])

    def test_pause_and_inventory(self):
        values = view_words(reserves=0, target=0, inventory=0, paused=True)
        result, _, transport = self.run_gate(SyntheticTransport(child_values=values))
        self.assertEqual(result["status"], "reported_ineligible_metadata_only")
        self.assertEqual(result["metadata"]["child_eligibility_claim"]["reasons"],
                         ["buy_paused", "not_for_sale", "no_weth_inventory"])
        self.assertEqual(result["requests"], 23)
        self.assertEqual(set(result["runtime_roles_checked"]),
                         {"proxy", "implementation", "asset_list", "weth", "usdc_proxy", "usdc_implementation"})
        self.assertFalse(any(r["method"] == "eth_getCode" and r["params"][0] == gate.FACTORY for r in transport.requests))
        self.assertEqual(len(result["unexecuted_steps"]), 8)
        self.assertEqual({row["reason"] for row in result["unexecuted_steps"]}, {"condition_not_met"})
        self.assert_unknown_economics(result)

    def test_pool_proof(self):
        wrong = {"getPool(address,address,uint24)": addr(gate.ZERO), "factory()": addr(IMPL),
                 "token0()": addr(gate.WETH), "token1()": addr(gate.USDC),
                 "fee()": word(500), "tickSpacing()": word(-60)}
        for signature, value in wrong.items():
            with self.subTest(signature=signature):
                result, _, transport = self.run_gate(SyntheticTransport(replies={signature: value}))
                self.assertEqual(result["status"], "identity_unavailable")
                self.assertNotIn("pool_identity", result["metadata"])
                self.assertEqual(sum(r["method"] == "eth_simulateV1" for r in transport.requests), 1)

    def test_binding_never_proves_source(self):
        missing, _, _ = self.run_gate(binding=None)
        self.assertEqual(missing["status"], "source_binding_unavailable")
        self.assertTrue(missing["canonical_parent_rechecked"])
        self.assertIsNone(missing["certificate_kind_claim"])
        self.assertIsNone(missing["certificate_review_ref_claim"])
        self.assertEqual(missing["certificate_roles_matched"], [])
        self.assertEqual(missing["certificate_roles_unverified"], sorted(CODE))
        self.assert_unknown_economics(missing)
        for kind in ("synthetic_fixture", "root_reviewed_artifact_certificate"):
            matched, _, _ = self.run_gate(binding=certificate(kind))
            self.assertEqual(matched["status"], "reported_eligible_metadata_only")
            self.assertEqual(set(matched["runtime_roles_checked"]), set(CODE))
            self.assert_unknown_economics(matched)
        bad = certificate()
        bad["roles"]["asset_list"]["runtime_sha256"] = "b" * 64
        result, _, _ = self.run_gate(binding=bad)
        self.assertEqual(result["status"], "binding_mismatch")
        self.assertEqual(result["requests"], 8)
        self.assertEqual(result["certificate_roles_matched"], ["implementation", "proxy", "weth"])
        self.assertIn("asset_list", result["certificate_roles_unverified"])
        self.assert_unknown_economics(result)

    def test_caller_certificate_reports_only_compared_roles(self):
        for values, status, unverified, requests in (
                (view_words(reserves=0), "reported_ineligible_metadata_only", ["factory", "pool"], 23),
                (view_words(), "reported_eligible_metadata_only", [], 31)):
            binding = certificate("root_reviewed_artifact_certificate")
            binding["root_review_ref"] = "caller claim only; no authenticated review"
            if unverified:
                binding["roles"]["factory"]["runtime_sha256"] = "b" * 64
            with self.subTest(status=status):
                result, _, _ = self.run_gate(SyntheticTransport(child_values=values), binding=binding)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["requests"], requests)
                self.assertEqual(result["source_binding"], "checked_runtime_roles_match_caller_supplied_certificate")
                self.assertEqual(result["certificate_kind_claim"], binding["kind"])
                self.assertEqual(result["certificate_review_ref_claim"], binding["root_review_ref"])
                self.assertEqual(result["certificate_roles_matched"], sorted(set(CODE) - set(unverified)))
                self.assertEqual(result["certificate_roles_unverified"], unverified)
                self.assertEqual(result["runtime_roles_checked"], result["certificate_roles_matched"])
                self.assert_unknown_economics(result)

    def test_malformed_binding(self):
        for field, value in (("artifact_set_sha256", None), ("artifact_set_sha256", 42),
                             ("runtime_sha256", None), ("runtime_sha256", 42)):
            binding = certificate()
            if field == "runtime_sha256":
                binding["roles"]["proxy"][field] = value
            else:
                binding[field] = value
            transport = mock.Mock(side_effect=AssertionError("transport must not run"))
            with self.subTest(field=field, value=value), self.assertRaises(gate.GateError):
                gate.Collector(transport, binding=binding)
            transport.assert_not_called()
        binding = certificate()
        del binding["roles"]["usdc_implementation"]
        with self.assertRaises(gate.GateError):
            gate.Collector(mock.Mock(), binding=binding)

    def test_usdc_dependencies_fail_before_eligibility_views(self):
        padding = "0x01" + "00" * 31
        cases = (
            ("usdc_proxy_code", "0x", "identity_unavailable", 12),
            ("usdc_proxy_code", "0x600800", "binding_mismatch", 12),
            ("usdc_implementation_slot", addr(gate.ZERO), "identity_unavailable", 13),
            ("usdc_implementation_slot", padding, "abi_unavailable", 13),
            ("usdc_implementation_slot", addr(ASSETS), "binding_mismatch", 14),
            ("usdc_implementation_code", "0x", "identity_unavailable", 14),
            ("usdc_implementation_code", "0x600800", "binding_mismatch", 14),
            ("usdc_admin_slot", addr(gate.ZERO), "identity_unavailable", 15),
            ("usdc_admin_slot", addr(gate.COMET), "identity_unavailable", 15),
            ("usdc_admin_slot", padding, "abi_unavailable", 15),
        )
        for key, value, status, requests in cases:
            with self.subTest(key=key, value=value):
                result, collector, transport = self.run_gate(SyntheticTransport(replies={key: value}))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["requests"], requests)
                self.assertNotIn("usdc_proxy", result["metadata"])
                self.assertNotIn("parent_eligibility_claim", result["metadata"])
                self.assertFalse(any(r["method"] == "eth_simulateV1" for r in transport.requests))
                self.assertEqual(collector.trace[-1]["gate_failure"]["category"], status)
                self.assert_unknown_economics(result)
        result, _, transport = self.run_gate()
        self.assertEqual(result["metadata"]["usdc_proxy"]["implementation"], USDC_IMPL)
        self.assertEqual(result["metadata"]["usdc_proxy"]["admin"], USDC_ADMIN)
        slots = [r["params"][1] for r in transport.requests
                 if r["method"] == "eth_getStorageAt" and r["params"][0] == gate.USDC]
        self.assertEqual(slots, [USDC_IMPL_SLOT, USDC_ADMIN_SLOT, USDC_IMPL_SLOT])

    def test_body_budgets(self):
        for caps, padding, expected_bytes, expected_requests in (
                ({"response_bytes": 128}, 1024, 129, 1),
                ({"response_bytes": 1024, "total_body_bytes": 2500}, 1024, 2500, 3)):
            with self.subTest(caps=caps), mock.patch.dict(gate.CAPS, caps):
                result, collector, transport = self.run_gate(SyntheticTransport(pad=padding))
                self.assertEqual(result["status"], "resource_unavailable")
                self.assertEqual(result["body_bytes"], expected_bytes)
                self.assertEqual(result["requests"], expected_requests)
                self.assertLessEqual(result["body_bytes"], gate.CAPS["total_body_bytes"])
                self.assertEqual(sum(s.returned for s in transport.streams), expected_bytes)
                last = collector.trace[-1]
                self.assertFalse(last["eof"])
                self.assertEqual(last["body_sha256"], hashlib.sha256(transport.bodies[-1][:last["body_bytes"]]).hexdigest())
                self.assertTrue(all(0 < n <= 8192 for s in transport.streams for n in s.read_sizes))

    def test_trace_budget(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0x1", "extra": "\U0001f600" * 400},
                          ensure_ascii=False).encode()
        with mock.patch.dict(gate.CAPS, {"trace_bytes": 6000}):
            result, collector, _ = self.run_gate(lambda r, t: (200, io.BytesIO(body)))
            self.assertEqual(result["status"], "resource_unavailable")
            self.assertEqual(result["requests"], 1)
            self.assertTrue(collector.trace[0]["response_omitted_for_cap"])
            self.assertEqual(collector.trace[0]["body_sha256"], hashlib.sha256(body).hexdigest())
            self.assertLessEqual(len(gate.encoded(collector.trace)), 6000)
            self.assert_unknown_economics(result)

    def test_eight_large_runtime_replies_fit_accounted_caps(self):
        # Fingerprint/memory fixture only; no EVM or deployed-runtime claim.
        runtimes = {role: bytes([i + 1]) * 24576 for i, role in enumerate(CODE)}
        binding = certificate()
        for role, raw in runtimes.items():
            binding["roles"][role]["runtime_sha256"] = hashlib.sha256(raw).hexdigest()
        replies = {role + "_code": "0x" + raw.hex() for role, raw in runtimes.items()}
        result, collector, transport = self.run_gate(SyntheticTransport(replies=replies), binding=binding)
        self.assertEqual(result["status"], "reported_eligible_metadata_only")
        self.assertEqual(result["requests"], 31)
        self.assertEqual(len(collector.trace), 31)
        self.assertEqual(result["body_bytes"], sum(map(len, transport.bodies)))
        self.assertLessEqual(result["body_bytes"], gate.CAPS["total_body_bytes"])
        self.assertLessEqual(len(gate.encoded(collector.trace)), gate.CAPS["trace_bytes"])
        for row, body in zip(collector.trace, transport.bodies):
            self.assertEqual(row["body_bytes"], len(body))
            self.assertEqual(row["body_sha256"], hashlib.sha256(body).hexdigest())
            self.assertTrue(row["eof"])
            self.assertIn("response", row)
        for role, raw in runtimes.items():
            record = result["metadata"]["code_fingerprints"][role]
            self.assertEqual(record["address"], CODE[role][0])
            self.assertEqual(record["runtime_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(set(result["runtime_roles_checked"]), set(runtimes))
        self.assert_unknown_economics(result)

    def test_deadline_and_single_use(self):
        clock = Clock()
        result, collector, transport = self.run_gate(SyntheticTransport(clock=clock, elapsed=11), clock=clock)
        self.assertEqual(result["status"], "resource_unavailable")
        self.assertEqual(result["requests"], 1)
        self.assertGreater(result["body_bytes"], 0)
        self.assertEqual(transport.timeouts, [10])
        self.assertEqual(collector.trace[0]["elapsed_seconds"], 11)
        with self.assertRaises(gate.GateError) as context:
            collector.execute(DECISION_MS)
        self.assertEqual(context.exception.category, "one_run_consumed")
        self.assertEqual(len(transport.requests), 1)
        result, collector, transport = self.run_gate()
        with self.assertRaises(gate.GateError):
            collector.execute(DECISION_MS)
        self.assertEqual(len(transport.requests), 31)

    def test_final_rechecks(self):
        other_parent = dict(PARENT, hash="0x" + "00" * 32)
        for replies in ({"final_parent": other_parent}, {"final_implementation": addr(ASSETS)},
                        {"final_usdc_implementation": addr(ASSETS)}):
            with self.subTest(replies=replies):
                result, _, _ = self.run_gate(SyntheticTransport(replies=replies))
                self.assertEqual(result["status"], "canonicality_unavailable")
                self.assertFalse(result["canonical_parent_rechecked"])
                self.assert_unknown_economics(result)
        for value in (addr(gate.ZERO), "0x01" + "00" * 31):
            result, _, _ = self.run_gate(SyntheticTransport(replies={"final_usdc_implementation": value}))
            self.assertIn(result["status"], ("identity_unavailable", "abi_unavailable"))
            self.assertEqual(result["requests"], 29)
            self.assertFalse(result["canonical_parent_rechecked"])

    def test_dry_cli(self):
        plan = draft()
        plan["source_pins"] = []
        raw = json.dumps(plan).encode()
        reader = gate.bounded_file
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(gate, "bounded_file", side_effect=lambda p: raw if p == gate.PLAN_PATH else reader(p)), \
                mock.patch.object(gate, "Collector", side_effect=AssertionError("CLI must stay dry")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("no network")), \
                mock.patch("sys.stdout", stdout):
            self.assertEqual(gate.main([]), 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["requests_permitted"], 0)
        self.assertEqual(report["source_pin_status"], "pending_unpinned")
        self.assertEqual(report["prospective_max_requests"], 31)
        self.assertEqual(report["manifest_sha256"],
                         "b29bacbcdb4f028f8ec64b62259979d12d9d3af4ec6bf32e66098c33edc9c4e2")
        for args in (("--run",), ("--live",), ("--endpoint", "https://invalid.example")):
            with self.subTest(args=args), mock.patch("sys.stderr", stderr), self.assertRaises(SystemExit) as context:
                gate.main(list(args))
            self.assertEqual(context.exception.code, 2)

    def test_local_source_pin_gate(self):
        paths = ("scripts/peer_comet_eligibility_v1.py", "tests/test_peer_comet_eligibility_v1.py",
                 "research/peer-comet-eligibility-v1-design.txt")
        pins = []
        for path in paths:
            raw = gate.bounded_file(gate.ROOT / path)
            pins.append({"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        plan = {"source_pins": pins}
        self.assertEqual(gate.verify_file_pins({"source_pins": []}), "pending_unpinned")
        self.assertEqual(gate.verify_file_pins(plan), "verified")
        for field, value in (("sha256", "0" * 64), ("bytes", True), ("bytes", pins[0]["bytes"] + 1),
                             ("path", "../outside.py"), ("sha256", None), ("extra", 0)):
            bad = copy.deepcopy(plan)
            bad["source_pins"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(gate.GateError) as error:
                gate.verify_file_pins(bad)
            self.assertEqual(error.exception.category, "source_pin_mismatch")
        for bad in (pins[:2], [pins[1], pins[1], pins[2]]):
            with self.assertRaises(gate.GateError) as error:
                gate.verify_file_pins({"source_pins": bad})
            self.assertEqual(error.exception.category, "source_pin_mismatch")
        with mock.patch.object(gate.Path, "is_symlink", return_value=True), self.assertRaises(gate.GateError):
            gate.verify_file_pins(plan)


if __name__ == "__main__":
    unittest.main()
