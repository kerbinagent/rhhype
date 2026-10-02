"""Offline Comet eligibility/runtime-gate collector. No network adapter or live CLI.

The manifest is prospective. Injected transports are for bounded synthetic tests
or separately authorized saved-response replay. A runtime hash is a fingerprint;
source equivalence depends on a separately reviewed artifact certificate.
"""
import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "research/peer-comet-eligibility-v1.json"
PIN_PATHS = frozenset(("scripts/peer_comet_eligibility_v1.py",
    "tests/test_peer_comet_eligibility_v1.py", "research/peer-comet-eligibility-v1-design.txt"))
COMET = "0xc3d688b66703497daa19211eedff47f25384cdc3"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
FACTORY = "0x1f98431c8ad98523631ae4a59f267346ea31f984"
ZERO = "0x" + "00" * 20
IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
USDC_IMPLEMENTATION_SLOT = "0x7050c9e0f4ca769c69bd3a8ef740bc37934f8e2c036e5a723fd8ee048ed3f8c3"
USDC_ADMIN_SLOT = "0x10d6a54a4754c8869d6886b5f5d7fbfa5b4522237ea5c60d11bc4e7a1ff9390b"
SELECTORS = {
    "assetList()": "e372f03a", "baseToken()": "c55dae63",
    "baseScale()": "44c1e5eb", "getAssetInfoByAddress(address)": "3b3bec2e",
    "isBuyPaused()": "d8e5f611", "getReserves()": "0902f1ac",
    "targetReserves()": "32176c49", "getCollateralReserves(address)": "9ff567f8",
    "getPool(address,address,uint24)": "1698ee82", "factory()": "c45a0155",
    "token0()": "0dfe1681", "token1()": "d21220a7", "fee()": "ddca3f43",
    "tickSpacing()": "d0c93a7c",
}
CAPS = {"requests": 31, "response_bytes": 65536, "total_body_bytes": 524288,
        "trace_bytes": 524288, "request_seconds": 10, "run_seconds": 120,
        "file_bytes": 131072, "source_package_all_copies_bytes": 262144}
ROLES = ("proxy", "implementation", "asset_list", "weth", "usdc_proxy", "usdc_implementation", "factory", "pool")
ELIGIBILITY_VIEWS = ("isBuyPaused()", "getReserves()", "targetReserves()",
                     "getCollateralReserves(address)")


class GateError(Exception):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


def fail(category, message):
    raise GateError(category, message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode_json(raw):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite JSON")
    def finite(value):
        result = float(value)
        if not math.isfinite(result):
            reject(value)
        return result
    result = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=reject, parse_float=finite)
    pending, nodes = [(result, 0)], 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > 32 or nodes > 4096:
            raise ValueError("JSON depth/node cap")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
    return result


def hex_bytes(value, length=None):
    if (not isinstance(value, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", value)
            or (length is not None and len(value) != 2 + 2 * length)):
        fail("abi_unavailable", "invalid exact-width hex data")
    return bytes.fromhex(value[2:])


def uint(value, bits=256):
    number = int.from_bytes(hex_bytes(value, 32), "big")
    if not 0 <= number < 2**bits:
        fail("abi_unavailable", "noncanonical narrow uint")
    return number


def sint(value, bits=256):
    number = int.from_bytes(hex_bytes(value, 32), "big", signed=True)
    if not -(2**(bits - 1)) <= number < 2**(bits - 1):
        fail("abi_unavailable", "noncanonical signed integer or sign extension")
    return number


def boolean(value):
    number = uint(value)
    if number not in (0, 1):
        fail("abi_unavailable", "noncanonical bool")
    return bool(number)


def address(value, nonzero=True):
    raw = hex_bytes(value, 32)
    if raw[:12] != bytes(12):
        fail("abi_unavailable", "nonzero address padding")
    result = "0x" + raw[12:].hex()
    if nonzero and result == ZERO:
        fail("identity_unavailable", "zero contract address")
    return result


def quantity(value):
    if (not isinstance(value, str) or len(value) > 66
            or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value)):
        fail("abi_unavailable", "noncanonical RPC quantity")
    return int(value, 16)


def header(value):
    if not isinstance(value, dict):
        fail("canonicality_unavailable", "missing header")
    result = {key: value.get(key) for key in ("number", "hash", "parentHash", "timestamp", "stateRoot")}
    if quantity(result["number"]) >= 2**64 or quantity(result["timestamp"]) >= 2**40:
        fail("canonicality_unavailable", "header number/time domain")
    for key in ("hash", "parentHash", "stateRoot"):
        hex_bytes(result[key], 32)
        result[key] = result[key].lower()
    return result


def calldata(signature, *args):
    if signature not in SELECTORS:
        fail("manifest_mismatch", "non-allowlisted selector")
    return "0x" + SELECTORS[signature] + "".join(
        format(int(arg, 16) if isinstance(arg, str) else arg, "064x") for arg in args)


def call_object(target, signature, *args):
    return {"from": ZERO, "to": target, "input": calldata(signature, *args),
            "gas": hex(200000), "value": "0x0"}


def state_selector(parent):
    return {"blockHash": parent["hash"], "requireCanonical": True}


def child_time(parent, decision_ms):
    if type(decision_ms) is not int or not 0 <= decision_ms < 2**40 * 1000:
        fail("clock_unavailable", "decision clock must be integer UTC milliseconds")
    # Ethereum mainnet's 12-second slot grid; a later slot can skip a slot.
    # This is still a conditional child model, not proof of scheduled inclusion.
    parent_time = quantity(parent["timestamp"])
    slots = max(1, (decision_ms + 400 - parent_time * 1000 + 11999) // 12000)
    timestamp = parent_time + 12 * slots
    if timestamp >= 2**40:
        fail("clock_unavailable", "Comet uint40 child time overflow")
    return timestamp


def simulation_params(parent, timestamp):
    calls = [call_object(COMET, name, *([WETH] if name.endswith("(address)") else []))
             for name in ELIGIBILITY_VIEWS]
    return [{"blockStateCalls": [{"blockOverrides": {
        "number": hex(quantity(parent["number"]) + 1), "time": hex(timestamp)},
        "calls": calls}], "validation": False, "traceTransfers": False,
        "returnFullTransactions": False}, parent["number"]]


def eligibility(values):
    if not isinstance(values, list) or len(values) != 4:
        fail("abi_unavailable", "exactly four eligibility return words required")
    paused, reserves, target, inventory = boolean(values[0]), sint(values[1]), uint(values[2], 104), uint(values[3])
    reasons = (["buy_paused"] if paused else []) + (["not_for_sale"] if reserves >= target else [])
    reasons += ["no_weth_inventory"] if inventory == 0 else []
    return {"paused": paused, "signed_reserves": str(reserves), "target_reserves": str(target),
            "weth_inventory": str(inventory), "reported_eligible": not reasons, "reasons": reasons,
            "arm_inventory_sufficiency": "not_evaluated"}


def asset_info(value):
    raw = hex_bytes(value, 256)
    words = ["0x" + raw[i:i + 32].hex() for i in range(0, 256, 32)]
    result = dict(zip(("offset", "asset", "price_feed", "scale", "borrow_factor", "liquidate_factor",
                       "liquidation_factor", "supply_cap"),
                      (uint(words[0], 8), address(words[1]), address(words[2]), uint(words[3], 64),
                       uint(words[4], 64), uint(words[5], 64), uint(words[6], 64), uint(words[7], 128))))
    if (result["asset"] != WETH or result["scale"] != 10**18 or result["offset"] >= 24
            or not 0 <= result["borrow_factor"] < result["liquidate_factor"] <= 10**18
            or not 0 <= result["liquidation_factor"] <= 10**18
            or any(result[k] % 10**14 for k in ("borrow_factor", "liquidate_factor", "liquidation_factor"))):
        fail("identity_unavailable", "WETH AssetList tuple outside reviewed model")
    return result


def validate_child(value, parent, timestamp):
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        fail("child_context_unavailable", "exactly one simulated child required")
    child = value[0]
    if (quantity(child.get("number")) != quantity(parent["number"]) + 1
            or not isinstance(child.get("parentHash"), str)
            or child["parentHash"].lower() != parent["hash"]
            or quantity(child.get("timestamp")) != timestamp):
        fail("child_context_unavailable", "child number, parent or timestamp mismatch")
    calls = child.get("calls")
    if not isinstance(calls, list) or len(calls) != 4:
        fail("child_context_unavailable", "exact four view-call receipts required")
    failures = []
    values = []
    for index, receipt in enumerate(calls):
        if not isinstance(receipt, dict):
            fail("child_context_unavailable", "malformed view receipt")
        status = quantity(receipt.get("status"))
        gas = quantity(receipt.get("gasUsed"))
        if status not in (0, 1) or gas > 200000:
            fail("child_context_unavailable", "view status/gas domain")
        hex_bytes(receipt.get("returnData"))
        if status != 1 or receipt.get("error") is not None or receipt.get("logs", []) != []:
            failures.append(index)
        values.append(receipt.get("returnData"))
    if failures:
        fail("child_views_unavailable", "failed view indices: " + ",".join(map(str, failures)))
    return eligibility(values)


def manifest():
    # Named dependencies are substitutions, never arbitrary caller-supplied RPCs.
    anchor = {"blockHash": "$parent.hash", "requireCanonical": True}
    def view(target, signature, *args):
        return [call_object(target, signature, *args), anchor]
    child_calls = [call_object(COMET, name, *([WETH] if name.endswith("(address)") else []))
                   for name in ELIGIBILITY_VIEWS]
    items = [
        ("chain", "eth_chainId", []),
        ("parent", "eth_getBlockByNumber", ["latest", False]),
        ("proxy_code", "eth_getCode", [COMET, anchor]),
        ("implementation_slot", "eth_getStorageAt", [COMET, IMPLEMENTATION_SLOT, anchor]),
        ("implementation_code", "eth_getCode", ["$implementation", anchor]),
        ("weth_code", "eth_getCode", [WETH, anchor]),
        ("asset_list_address", "eth_call", view(COMET, "assetList()")),
        ("asset_list_code", "eth_getCode", ["$asset_list", anchor]),
        ("base_token", "eth_call", view(COMET, "baseToken()")),
        ("base_scale", "eth_call", view(COMET, "baseScale()")),
        ("weth_asset_info", "eth_call", view(COMET, "getAssetInfoByAddress(address)", WETH)),
        ("usdc_proxy_code", "eth_getCode", [USDC, anchor]),
        ("usdc_implementation_slot", "eth_getStorageAt", [USDC, USDC_IMPLEMENTATION_SLOT, anchor]),
        ("usdc_implementation_code", "eth_getCode", ["$usdc_implementation", anchor]),
        ("usdc_admin_slot", "eth_getStorageAt", [USDC, USDC_ADMIN_SLOT, anchor]),
        ("parent_pause", "eth_call", view(COMET, "isBuyPaused()")),
        ("parent_reserves", "eth_call", view(COMET, "getReserves()")),
        ("parent_target", "eth_call", view(COMET, "targetReserves()")),
        ("parent_inventory", "eth_call", view(COMET, "getCollateralReserves(address)", WETH)),
        ("child_eligibility", "eth_simulateV1", [{"blockStateCalls": [{"blockOverrides": {
            "number": "$child.number", "time": "$child.timestamp"}, "calls": child_calls}],
            "validation": False, "traceTransfers": False, "returnFullTransactions": False}, "$parent.number"]),
        ("factory_code", "eth_getCode", [FACTORY, anchor]),
        ("factory_pool", "eth_call", view(FACTORY, "getPool(address,address,uint24)", USDC, WETH, 3000)),
        ("pool_code", "eth_getCode", ["$pool", anchor]),
        ("pool_factory", "eth_call", view("$pool", "factory()")),
        ("pool_token0", "eth_call", view("$pool", "token0()")),
        ("pool_token1", "eth_call", view("$pool", "token1()")),
        ("pool_fee", "eth_call", view("$pool", "fee()")),
        ("pool_tick_spacing", "eth_call", view("$pool", "tickSpacing()")),
        ("final_usdc_implementation", "eth_getStorageAt", [USDC, USDC_IMPLEMENTATION_SLOT, anchor]),
        ("final_implementation", "eth_getStorageAt", [COMET, IMPLEMENTATION_SLOT, anchor]),
        ("final_parent", "eth_getBlockByNumber", ["$parent.number", False]),
    ]
    return [{"position": i + 1, "name": name, "method": method, "params": params,
             "condition": "child_reported_eligible" if 20 <= i < 28 else "required_until_failure"}
            for i, (name, method, params) in enumerate(items)]


def validate_binding(binding):
    if binding is None:
        return
    if not isinstance(binding, dict) or set(binding) != {"kind", "root_review_ref", "artifact_set_sha256", "roles"}:
        fail("binding_unavailable", "binding certificate schema")
    if (binding["kind"] not in ("synthetic_fixture", "root_reviewed_artifact_certificate")
            or not isinstance(binding["root_review_ref"], str) or not binding["root_review_ref"]
            or len(binding["root_review_ref"]) > 240
            or not isinstance(binding["artifact_set_sha256"], str)
            or not re.fullmatch("[0-9a-f]{64}", binding["artifact_set_sha256"])
            or not isinstance(binding["roles"], dict) or set(binding["roles"]) != set(ROLES)):
        fail("binding_unavailable", "binding certificate domain")
    for record in binding["roles"].values():
        if (not isinstance(record, dict) or set(record) != {"address", "runtime_sha256"}
                or not isinstance(record["address"], str)
                or not re.fullmatch("0x[0-9a-f]{40}", record["address"])
                or record["address"] == ZERO or not isinstance(record["runtime_sha256"], str)
                or not re.fullmatch("[0-9a-f]{64}", record["runtime_sha256"])):
            fail("binding_unavailable", "binding role identity")


def validate_plan(plan):
    if (not isinstance(plan, dict) or plan.get("schema") != "peer-comet-eligibility-v1"
            or plan.get("status") != "offline_draft_no_network_authority"
            or plan.get("network_authorized") is not False or plan.get("raw_allocation_bytes") != 0
            or encoded(plan.get("caps")) != encoded(CAPS)
            or plan.get("contracts") != {"comet": COMET, "usdc": USDC, "weth": WETH, "factory": FACTORY, "fee": 3000}
            or encoded(plan.get("manifest")) != encoded(manifest())):
        fail("manifest_mismatch", "fixed offline plan/manifest mismatch")
    validate_binding(plan.get("runtime_binding"))
    return {"status": "dry_validated_no_network", "requests_permitted": 0,
            "prospective_max_requests": CAPS["requests"], "manifest_sha256": sha(encoded(manifest())),
            "runtime_binding_present": plan.get("runtime_binding") is not None, "economics": None}


class Collector:
    """Single-use engine with an injected *offline* stream transport only.

    transport(request, timeout_seconds) -> (HTTP-like status, byte stream).
    There is deliberately no URL, opener, network implementation or live CLI.
    A later network adapter requires separate allocation/freeze/review and a
    persistent one-run claim plus hard transport timeout, absent from this draft.
    """
    def __init__(self, transport, *, binding=None, clock=time.monotonic):
        validate_binding(binding)
        self.transport, self.binding, self.clock = transport, binding, clock
        self.started = None
        self.used = False
        self.trace, self.metadata = [], {}
        self.total_bytes = 0
        self.code_roles = set()

    def rpc(self, name, method, params):
        remaining = CAPS["total_body_bytes"] - self.total_bytes
        if (remaining <= 0 or len(self.trace) >= CAPS["requests"]
                or self.clock() - self.started >= CAPS["run_seconds"] - 10):
            fail("resource_unavailable", "request/body/time budget exhausted before admission")
        request = {"jsonrpc": "2.0", "id": len(self.trace) + 1, "method": method, "params": params}
        row = {"name": name, "request": request, "outcome": "admitted"}
        if len(encoded(request)) > 8192 or len(encoded(self.trace + [row])) + 4096 > CAPS["trace_bytes"]:
            fail("resource_unavailable", "trace/request budget exhausted before admission")
        self.trace.append(row)
        limit = min(CAPS["response_bytes"] + 1, remaining)
        started = self.clock()
        raw = bytearray()
        eof = False
        try:
            status, stream = self.transport(request, min(CAPS["request_seconds"],
                CAPS["run_seconds"] - 10 - (started - self.started)))
            with stream:
                while len(raw) < limit:
                    chunk = stream.read(min(8192, limit - len(raw)))
                    if not isinstance(chunk, bytes) or len(chunk) > min(8192, limit - len(raw)):
                        fail("resource_unavailable", "offline stream violated bounded read")
                    if not chunk:
                        eof = True
                        break
                    raw.extend(chunk)
            if (not eof or len(raw) > CAPS["response_bytes"] or status != 200
                    or self.clock() - started > CAPS["request_seconds"]):
                fail("resource_unavailable", "response limit, unproven EOF, status or deadline")
            obj = decode_json(raw)
            if (not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0"
                    or type(obj.get("id")) is not int or obj["id"] != request["id"]
                    or ("result" in obj) == ("error" in obj)):
                fail("abi_unavailable", "JSON-RPC envelope mismatch")
            if method == "eth_getBlockByNumber" and "result" in obj:
                projection = obj["result"]
                if isinstance(projection, dict):
                    projection = {k: projection.get(k) for k in ("number", "hash", "parentHash", "timestamp", "stateRoot")}
                row["response"] = {"jsonrpc": obj["jsonrpc"], "id": obj["id"], "result": projection}
                row["header_projection_only"] = True
            else:
                row["response"] = obj
            if "error" in obj:
                fail("rpc_unavailable", "provider error at " + name)
            row["outcome"] = "received"
            return obj["result"]
        except GateError:
            row["outcome"] = "failed"
            raise
        except Exception as exc:
            row["outcome"] = "failed"
            fail("resource_unavailable", type(exc).__name__ + ": " + str(exc)[:160])
        finally:
            self.total_bytes += len(raw)
            row.update(body_bytes=len(raw), body_sha256=sha(raw), eof=eof,
                       elapsed_seconds=self.clock() - started)
            if len(encoded(self.trace)) > CAPS["trace_bytes"] - 2048:
                row.pop("response", None)
                row["response_omitted_for_cap"] = True
                fail("resource_unavailable", "bounded in-memory trace cap")

    def code(self, name, role, target, parent):
        value = self.rpc(name, "eth_getCode", [target, state_selector(parent)])
        raw = hex_bytes(value)
        if not raw:
            fail("identity_unavailable", "empty " + role + " runtime")
        record = {"address": target, "runtime_sha256": sha(raw)}
        self.metadata.setdefault("code_fingerprints", {})[role] = record
        if self.binding is not None and record != self.binding["roles"][role]:
            fail("binding_mismatch", role + " runtime/address differs from certificate")
        self.code_roles.add(role)

    def call(self, name, target, signature, parent, *args):
        return self.rpc(name, "eth_call", [call_object(target, signature, *args), state_selector(parent)])

    def execute(self, decision_ms):
        if self.used:
            fail("one_run_consumed", "collector instance already used")
        self.used = True
        self.started = self.clock()
        result = {"status": "unavailable", "economics": None, "cash_closed": False,
                  "source_equivalence_proven_by_collector": False, "network_requests_permitted": 0,
                  "runtime_dependency_closure_complete": False,
                  "evidence_kind": "offline_transport", "source_binding": "unavailable",
                  "certificate_kind_claim": self.binding["kind"] if self.binding else None,
                  "certificate_review_ref_claim": self.binding["root_review_ref"] if self.binding else None,
                  "certificate_authority_verified": False,
                  "canonical_parent_rechecked": False, "private_ack_proves_inclusion": False}
        try:
            if self.rpc("chain", "eth_chainId", []) != "0x1":
                fail("identity_unavailable", "chain must be Ethereum mainnet")
            parent = header(self.rpc("parent", "eth_getBlockByNumber", ["latest", False]))
            self.metadata["parent"] = parent
            timestamp = child_time(parent, decision_ms)
            self.metadata["decision_utc_ms"] = decision_ms
            self.metadata["conditional_child"] = {"number": quantity(parent["number"]) + 1, "timestamp": timestamp,
                "limitation": "numeric parent plus final recheck; no inclusion or reorg-out-and-back proof"}
            self.code("proxy_code", "proxy", COMET, parent)
            impl = address(self.rpc("implementation_slot", "eth_getStorageAt", [COMET, IMPLEMENTATION_SLOT, state_selector(parent)]))
            self.code("implementation_code", "implementation", impl, parent)
            self.code("weth_code", "weth", WETH, parent)
            assets = address(self.call("asset_list_address", COMET, "assetList()", parent))
            self.code("asset_list_code", "asset_list", assets, parent)
            if address(self.call("base_token", COMET, "baseToken()", parent)) != USDC:
                fail("identity_unavailable", "wrong base token")
            if uint(self.call("base_scale", COMET, "baseScale()", parent), 64) != 10**6:
                fail("identity_unavailable", "wrong base scale")
            self.metadata["weth_asset_info"] = asset_info(self.call("weth_asset_info", COMET, "getAssetInfoByAddress(address)", parent, WETH))
            self.code("usdc_proxy_code", "usdc_proxy", USDC, parent)
            usdc_impl = address(self.rpc("usdc_implementation_slot", "eth_getStorageAt",
                [USDC, USDC_IMPLEMENTATION_SLOT, state_selector(parent)]))
            self.code("usdc_implementation_code", "usdc_implementation", usdc_impl, parent)
            usdc_admin = address(self.rpc("usdc_admin_slot", "eth_getStorageAt",
                [USDC, USDC_ADMIN_SLOT, state_selector(parent)]))
            if usdc_admin == COMET:
                fail("identity_unavailable", "Comet cannot use USDC proxy fallback as its admin")
            self.metadata["usdc_proxy"] = {"implementation": usdc_impl, "admin": usdc_admin,
                "model": "Circle legacy ZeppelinOS proxy slots; deployed equivalence unproven"}
            values = [self.call(name, COMET, sig, parent, *([WETH] if sig.endswith("(address)") else []))
                for name, sig in zip(("parent_pause", "parent_reserves", "parent_target", "parent_inventory"), ELIGIBILITY_VIEWS)]
            self.metadata["parent_eligibility_claim"] = eligibility(values)
            child = self.rpc("child_eligibility", "eth_simulateV1", simulation_params(parent, timestamp))
            self.metadata["child_eligibility_claim"] = eligible = validate_child(child, parent, timestamp)
            if eligible["reported_eligible"]:
                self.code("factory_code", "factory", FACTORY, parent)
                pool = address(self.call("factory_pool", FACTORY, "getPool(address,address,uint24)", parent, USDC, WETH, 3000))
                self.code("pool_code", "pool", pool, parent)
                for name, signature, expected in (("pool_factory", "factory()", FACTORY),
                    ("pool_token0", "token0()", USDC), ("pool_token1", "token1()", WETH)):
                    if address(self.call(name, pool, signature, parent)) != expected:
                        fail("identity_unavailable", name + " mismatch")
                if uint(self.call("pool_fee", pool, "fee()", parent), 24) != 3000:
                    fail("identity_unavailable", "wrong pool fee")
                if sint(self.call("pool_tick_spacing", pool, "tickSpacing()", parent), 24) != 60:
                    fail("identity_unavailable", "wrong pool tick spacing")
                self.metadata["pool_identity"] = {"address": pool, "factory": FACTORY, "token0": USDC, "token1": WETH, "fee": 3000}
            final_usdc_impl = address(self.rpc("final_usdc_implementation", "eth_getStorageAt",
                [USDC, USDC_IMPLEMENTATION_SLOT, state_selector(parent)]))
            final_impl = address(self.rpc("final_implementation", "eth_getStorageAt", [COMET, IMPLEMENTATION_SLOT, state_selector(parent)]))
            final_parent = header(self.rpc("final_parent", "eth_getBlockByNumber", [parent["number"], False]))
            if final_impl != impl or final_usdc_impl != usdc_impl or final_parent != parent:
                fail("canonicality_unavailable", "parent header or anchored Comet/USDC implementation changed")
            result["canonical_parent_rechecked"] = True
            if self.binding is None:
                result["status"] = "source_binding_unavailable"
            else:
                result["source_binding"] = ("synthetic_fixture_only" if self.binding["kind"] == "synthetic_fixture"
                    else "checked_runtime_roles_match_caller_supplied_certificate")
                result["binding_certificate_sha256"] = sha(encoded(self.binding))
                result["status"] = "reported_eligible_metadata_only" if eligible["reported_eligible"] else "reported_ineligible_metadata_only"
        except GateError as exc:
            result.update(status=exc.category, error=str(exc)[:240])
            if self.trace:
                self.trace[-1]["gate_failure"] = {"category": exc.category, "message": str(exc)[:240]}
        except Exception as exc:
            result.update(status="resource_unavailable", error=type(exc).__name__ + ": " + str(exc)[:160])
        selected = {row["name"] for row in self.trace}
        ineligible = self.metadata.get("child_eligibility_claim", {}).get("reported_eligible") is False
        result["unexecuted_steps"] = [{"name": row["name"], "reason": "condition_not_met" if
            row["condition"] == "child_reported_eligible" and ineligible else "not_reached_after_failure"}
            for row in manifest() if row["name"] not in selected]
        # Defensive terminal invariant; fixed requests and the reserved error
        # margin should make this unreachable, including every failing prefix.
        if len(encoded(self.trace)) > CAPS["trace_bytes"]:
            fail("resource_unavailable", "terminal trace cap invariant failed")
        result.update(requests=len(self.trace), body_bytes=self.total_bytes, metadata=self.metadata,
                      trace_sha256=sha(encoded(self.trace)), runtime_roles_checked=sorted(self.code_roles),
                      certificate_roles_matched=sorted(self.code_roles) if self.binding else [],
                      certificate_roles_unverified=sorted(set(ROLES) - self.code_roles) if self.binding else sorted(ROLES))
        return result


def bounded_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        fail("file_unavailable", "regular non-symlink file required")
    with path.open("rb") as stream:
        raw = stream.read(CAPS["file_bytes"] + 1)
    if len(raw) > CAPS["file_bytes"]:
        fail("resource_unavailable", "file byte cap")
    return raw


def verify_file_pins(plan):
    pins = plan.get("source_pins")
    if pins == []:
        return "pending_unpinned"
    if not isinstance(pins, list) or len(pins) != len(PIN_PATHS):
        fail("source_pin_mismatch", "exact source/test/design pin set required")
    seen = set()
    for pin in pins:
        if (not isinstance(pin, dict) or set(pin) != {"path", "bytes", "sha256"}
                or not isinstance(pin["path"], str) or pin["path"] not in PIN_PATHS
                or pin["path"] in seen or type(pin["bytes"]) is not int
                or not 0 < pin["bytes"] <= CAPS["file_bytes"]
                or not isinstance(pin["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])):
            fail("source_pin_mismatch", "invalid or duplicate fixed-path pin")
        seen.add(pin["path"])
        path = ROOT
        for part in Path(pin["path"]).parts:
            path = path / part
            if path.is_symlink():
                fail("source_pin_mismatch", "symlink pin path is forbidden")
        raw = bounded_file(path)
        if len(raw) != pin["bytes"] or sha(raw) != pin["sha256"]:
            fail("source_pin_mismatch", "local bytes differ from pin: " + pin["path"])
    return "verified"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    args = parser.parse_args(argv)
    try:
        raw = bounded_file(args.plan)
        plan = decode_json(raw)
        result = validate_plan(plan)
        result["source_pin_status"] = verify_file_pins(plan)
        result["plan_sha256"] = sha(raw)
        print(encoded(result).decode())
        return 0
    except (GateError, ValueError, OSError) as exc:
        print(encoded({"status": getattr(exc, "category", "file_unavailable"), "error": str(exc)[:240]}).decode())
        return 2


if __name__ == "__main__":
    sys.exit(main())
