"""One frozen metadata/capability probe; dry validation is the default.

No quote, market state, wallet, transaction submission, retry or endpoint discovery.
The numeric simulation parent plus final recheck cannot rule out reorg-out-and-back.
"""
import argparse
import contextlib
import gzip
import hashlib
import json
import math
import platform
import re
import signal
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "scripts/peer_primary_issuance_preflight_v2.py"
TEST = "tests/test_peer_primary_issuance_preflight_v2.py"
PROPOSAL = "research/peer-primary-issuance-v1-proposal.json"
PROPOSAL_SHA = "f096be8addac4f1f4b8acdb276fff920afd56dfb557a6ac6ae97c66841fc0757"
ENDPOINT = "https://ethereum-rpc.publicnode.com"
MANIFEST_SHA = "c465c5f7df48df6a7ecc8a8ea5d3f17eb603d015eb566f19fcc71d2d37514de9"
SYNTHETIC_SHA = "e4fa640be3230433692995ba45d30f3b757f2c3d8d14e20e2a3933fd71b2df7f"
AMENDMENT = {"path": "reports/experiment-storage/parler-peer-primary-issuance-v1.json",
    "sha256": "da22971ab71885b344f5ff153f9c50520fecb6313a7432aaed72786c52141da2", "bytes": 2923}
SOURCE_CAP_AUTHORITY = "e1d30215-38d4-4c85-935c-34812280f4bf"
RUNTIME = {"path": "research/peer-primary-issuance-v1-runtime.json",
           "sha256": "c42a21452f0c9840e41523339608390ec05a9ce52872a997f1776fb98d1fb23c"}
# Retained v1 artifacts, excluding shared proposal/runtime/amendment in the v2 core,
# plus envelopes, handoffs and ledger allowance; parent reconciles actual retention.
SOURCE_ENVELOPE_ALLOWANCE = 131072
CAPS = dict(max_rpc_requests=20, max_runtime_seconds=180,
    request_timeout_seconds=12, minimum_request_start_spacing_seconds=1,
    max_response_bytes=131072, max_total_response_bytes=1048576,
    max_retained_raw_bytes_per_session=262144,
    max_retained_derived_bytes_per_session=65536,
            max_source_tests_protocol_and_remote_review_copies_bytes=294912)
CONTRACTS = dict(lido_steth_proxy="0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
    documented_lido_implementation="0x028271E30a695c0527A0C50cA30603feD004cDb0",
    curve_legacy_steth_eth="0xDC24316b9AE028F1497c275EB9192a3Ea0f67022",
    curve_coin_0_native_sentinel="0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    curve_coin_1="0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84",
    dust_sink="0x000000000000000000000000000000000000dEaD")
SCRATCH = dict(scratch_success="0x000000000000000000000000000000000000f101",
    scratch_revert="0x000000000000000000000000000000000000f102",
    scratch_sender="0x000000000000000000000000000000000000f103")
# Offline Keccak-256 derivation independently checked against ERC20 transfer.
SELECTORS = dict(zip(("implementation()", "proxyType()", "getContractVersion()",
    "decimals()", "isStakingPaused()", "getCurrentStakeLimit()",
    "coins(uint256)", "fee()", "admin_fee()"),
    ("5c60da1b", "4555d5c9", "8aa10435", "313ce567", "1ea7ca89",
    "609c4c6c", "c6610657", "ddca3f43", "fee3f7f9")))
ARMS = (10**16, 10**17, 10**18, 10**19)
REORG_LIMIT = "numeric_simulation_parent_with_header_recheck_cannot_exclude_reorg_out_and_back"
RESOURCE = "transport_or_resource_unavailable"
IDENTITY = "identity_or_abi_mismatch"
CAPABILITY = "provider_capability_unavailable"


class ProbeError(Exception):
    def __init__(self, category, message):
        super().__init__(message)
        self.category = category


class TransportError(Exception):
    def __init__(self, message, partial=b"", status=None):
        super().__init__(message)
        self.partial, self.status = partial, status


def fail(category, message):
    raise ProbeError(category, message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def bounded_file(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(CAPS["max_response_bytes"] + 1)
    if len(raw) > CAPS["max_response_bytes"]:
        fail(RESOURCE, "source/protocol file exceeds bounded read")
    return raw


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def decode_json(raw):
    def reject(value):
        raise ValueError("nonfinite JSON constant")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            reject(value)
        return number
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject,
        parse_float=finite_float)


def validate_plan(plan):
    """Check executable semantics, without authorizing or touching a provider."""
    if not isinstance(plan, dict):
        fail(IDENTITY, "protocol must be an object")
    probe, fixed = plan.get("metadata_probe", {}), plan.get("fixed_contracts", {})
    sizes = plan.get("later_economic_falsifier_requirements_not_authorized", {})
    if not all(isinstance(v, dict) for v in (probe, fixed, sizes)):
        fail(IDENTITY, "invalid protocol section")
    arms = sizes.get("native_principal_arms_wei")
    if any(fixed.get(k) != v for k, v in CONTRACTS.items()):
        fail(IDENTITY, "fixed address mismatch")
    expected_caps = CAPS.copy()
    if plan.get("status") == "proposal_only_no_rpc_authority_no_economic_observations":
        expected_caps["max_source_tests_protocol_and_remote_review_copies_bytes"] = 131072
    if any(type(probe.get(k)) is not type(v) or probe[k] != v for k, v in expected_caps.items()):
        fail(IDENTITY, "fixed resource policy mismatch")
    if (probe.get("endpoint") != ENDPOINT or probe.get("endpoint_fallbacks") != []
        or type(probe.get("run_count")) is not int or probe["run_count"] != 1
        or any(probe.get(k) != v for k, v in SCRATCH.items())
        or arms != [str(v) for v in ARMS]):
        fail(IDENTITY, "endpoint, scratch account or fixed size mismatch")
    try:
        manifests_match = (digest(encoded(probe["request_manifest"])) == MANIFEST_SHA
            if "request_manifest" in probe else
            probe.get("request_manifest_sha256") == MANIFEST_SHA)
        synthetic_match = (digest(encoded(probe["synthetic_probe"])) == SYNTHETIC_SHA
            if "synthetic_probe" in probe else
            probe.get("synthetic_probe_sha256") == SYNTHETIC_SHA)
    except (KeyError, TypeError, ValueError):
        fail(IDENTITY, "invalid manifest or synthetic specification")
    if not manifests_match or not synthetic_match:
        fail(IDENTITY, "exact twenty-call manifest/synthetic specification mismatch")
    if plan.get("status") not in ("proposal_only_no_rpc_authority_no_economic_observations",
        "frozen_metadata_probe"):
        fail(IDENTITY, "unknown protocol status")
    return {"status": "dry_validated_no_rpc_authority", "requests_permitted": 0,
        "manifest_calls": 20, "native_arms_wei": [str(v) for v in ARMS],
        "reorg_limitation": REORG_LIMIT, "economic_observations": 0}


def authorize(plan, plan_raw, *, expected_plan_sha, coordinator_authority,
    endpoint, expected_source_sha, expected_test_sha):
    validate_plan(plan)
    if plan.get("status") != "frozen_metadata_probe":
        fail(IDENTITY, "proposal has no run authority")
    if len(plan_raw) > CAPS["max_response_bytes"] or encoded(decode_json(plan_raw)) != encoded(plan):
        fail(IDENTITY, "parsed protocol does not match pinned bytes")
    auth = plan.get("authorization", {})
    if not isinstance(auth, dict):
        fail(IDENTITY, "invalid authority section")
    authority = auth.get("coordinator_message")
    if (not isinstance(authority, str) or not authority.strip()
        or coordinator_authority != authority
        or type(auth.get("raw_bytes")) is not int or auth["raw_bytes"] != 524288
        or auth.get("source_cap_authority_message") != SOURCE_CAP_AUTHORITY):
        fail(IDENTITY, "explicit coordinator raw authority mismatch")
    if endpoint != ENDPOINT or digest(plan_raw) != expected_plan_sha:
        fail(IDENTITY, "explicit endpoint/protocol pin mismatch")
    reference = plan.get("proposal", {})
    if reference != {"path": PROPOSAL, "sha256": PROPOSAL_SHA}:
        fail(IDENTITY, "proposal context reference mismatch")
    context = bounded_file(ROOT / PROPOSAL)
    if digest(context) != PROPOSAL_SHA:
        fail(IDENTITY, "proposal context bytes changed")
    original = decode_json(context)["metadata_probe"]
    if (digest(encoded(original["request_manifest"])) != MANIFEST_SHA
        or digest(encoded(original["synthetic_probe"])) != SYNTHETIC_SHA):
        fail(IDENTITY, "proposal section digests changed")
    if (plan.get("allocation_amendment") != AMENDMENT
        or plan.get("additional_retained_source_allowance_bytes") != SOURCE_ENVELOPE_ALLOWANCE):
        fail(IDENTITY, "allocation amendment/source envelope allowance mismatch")
    amendment = bounded_file(ROOT / AMENDMENT["path"])
    if len(amendment) != AMENDMENT["bytes"] or digest(amendment) != AMENDMENT["sha256"]:
        fail(IDENTITY, "allocation amendment bytes changed")
    if plan.get("runtime") != RUNTIME:
        fail(IDENTITY, "runtime reference mismatch")
    runtime_raw = bounded_file(ROOT / RUNTIME["path"])
    if digest(runtime_raw) != RUNTIME["sha256"]:
        fail(IDENTITY, "runtime bytes changed")
    runtime = decode_json(runtime_raw)
    actual = dict(python_version=sys.version, python_executable=sys.executable,
                  python_implementation=platform.python_implementation(), machine=platform.machine(),
                  platform=platform.platform(), openssl=ssl.OPENSSL_VERSION)
    if any(runtime.get(k) != v for k, v in actual.items()):
        fail(IDENTITY, "actual runtime differs from frozen runtime")
    pins = plan.get("source_pins")
    if (not isinstance(pins, list) or len(pins) != 2
            or any(not isinstance(p, dict) or set(p) != {"path", "sha256"}
                   or not isinstance(p["path"], str) or not isinstance(p["sha256"], str) for p in pins)
        or {p["path"] for p in pins} != {SOURCE, TEST}):
        fail(IDENTITY, "exact source/test pins required")
    expected = {SOURCE: expected_source_sha, TEST: expected_test_sha}
    package_bytes = len(plan_raw) + len(context) + len(amendment) + len(runtime_raw)
    for pin in pins:
        raw = bounded_file(ROOT / pin["path"])
        if digest(raw) != pin["sha256"] or pin["sha256"] != expected[pin["path"]]:
            fail(IDENTITY, "source/test bytes or explicit pin mismatch")
        package_bytes += len(raw)
    package_total = package_bytes * 2 + SOURCE_ENVELOPE_ALLOWANCE
    if package_total > CAPS["max_source_tests_protocol_and_remote_review_copies_bytes"]:
        fail(RESOURCE, "source/tests/proposal/protocol two-copy package cap")
    return {"protocol_sha256": digest(plan_raw), "source_pins": pins,
        "proposal": reference, "coordinator_authority": authority,
        "raw_authority_bytes": 524288, "package_two_copy_bytes": package_total,
        "allocation_amendment": AMENDMENT, "runtime": RUNTIME, "actual_runtime": actual,
        "source_cap_authority_message": SOURCE_CAP_AUTHORITY,
        "source_envelope_allowance_bytes": SOURCE_ENVELOPE_ALLOWANCE}


def quantity(value):
    if (not isinstance(value, str) or not re.fullmatch(r"0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)", value)
        or len(value) > 66):
        fail(IDENTITY, "noncanonical uint256 RPC quantity")
    return int(value, 16)


def hex_data(value, size=None):
    if (not isinstance(value, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", value)
        or (size is not None and len(value) != 2 + 2 * size)):
        fail(IDENTITY, "invalid exact-width hex data")
    return bytes.fromhex(value[2:])


def abi_uint(value):
    return int.from_bytes(hex_data(value, 32), "big")


def abi_bool(value):
    number = abi_uint(value)
    if number not in (0, 1):
        fail(IDENTITY, "noncanonical ABI bool")
    return bool(number)


def abi_address(value):
    raw = hex_data(value, 32)
    if raw[:12] != b"\0" * 12:
        fail(IDENTITY, "nonzero ABI address padding")
    return "0x" + raw[12:].hex()


def header(value):
    if not isinstance(value, dict):
        fail("canonicality_unavailable", "missing header")
    out = {k: value.get(k) for k in ("number", "hash", "parentHash", "timestamp", "stateRoot")}
    quantity(out["number"])
    quantity(out["timestamp"])
    for key in ("hash", "parentHash", "stateRoot"):
        hex_data(out[key], 32)
    return out


def synthetic_params(block):
    sender = SCRATCH["scratch_sender"]
    calls = []
    for nonce, target in enumerate(("scratch_success", "scratch_revert")):
        calls.append({"from": sender, "to": SCRATCH[target], "gas": hex(100000),
            "maxFeePerGas": hex(2 * 10**9), "maxPriorityFeePerGas": hex(10**9),
            "value": "0x0", "input": "0x", "nonce": hex(nonce)})
    overrides = {SCRATCH["scratch_success"]: {"code": "0x602a60005260206000f3"},
        SCRATCH["scratch_revert"]: {"code": "0x60006000fd"},
        sender: {"balance": hex(10**18), "nonce": "0x0"}}
    return [{"blockStateCalls": [{"blockOverrides": {"baseFeePerGas": hex(10**9)},
        "stateOverrides": overrides, "calls": calls}],
        "validation": True, "traceTransfers": False, "returnFullTransactions": False},
        block["number"]]


def validate_synthetic(value, block):
    try:
        if not isinstance(value, list) or len(value) != 1:
            raise ValueError("exactly one simulated child required")
        child = value[0]
        if (quantity(child["number"]) != quantity(block["number"]) + 1
            or child["parentHash"].lower() != block["hash"].lower()
            or quantity(child["baseFeePerGas"]) != 10**9):
            raise ValueError("synthetic child context mismatch")
        calls = child["calls"]
        if not isinstance(calls, list) or len(calls) != 2:
            raise ValueError("exactly two simulated call receipts required")
        good, bad = calls
        if (quantity(good["status"]) != 1 or abi_uint(good["returnData"]) != 42
            or quantity(good["gasUsed"]) != 21018 or good.get("error") is not None
            or quantity(bad["status"]) != 0 or bad["returnData"] != "0x"
            or quantity(bad["gasUsed"]) != 21006):
            raise ValueError("synthetic status/return/intrinsic-inclusive gas mismatch")
        error = bad.get("error")
        if (not isinstance(error, dict) or type(error.get("code")) is not int
            or error["code"] != 3 or not isinstance(error.get("message"), str)
            or "revert" not in error["message"].lower()
            or good.get("logs", []) != [] or bad.get("logs", []) != []):
            raise ValueError("explicit revert evidence/empty logs required")
    except (KeyError, TypeError, AttributeError, ValueError, ProbeError) as exc:
        fail(CAPABILITY, "synthetic interface rejected: " + str(exc)[:240])
    return {"success_return": 42, "success_gas_used": 21018, "revert_gas_used": 21006,
        "intrinsic_gas_included": True, "parent_binding": "number_with_final_header_recheck"}


@contextlib.contextmanager
def hard_timeout(seconds):
    """Nested POSIX wall timers include slow-drip reads and spacing sleeps."""
    if not hasattr(signal, "setitimer"):
        fail(RESOURCE, "POSIX hard wall timer unavailable")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()
    budget = min(seconds, previous_timer[0]) if previous_timer[0] > 0 else seconds
    def expired(signum, frame):
        fail(RESOURCE, "hard wall deadline expired")
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, max(0.000001, budget))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            remaining = previous_timer[0] - (time.monotonic() - started)
            signal.setitimer(signal.ITIMER_REAL, max(0.000001, remaining), previous_timer[1])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect prohibited", headers, fp)


def http_transport(payload, timeout, limit):
    """Fixed anonymous endpoint; disable environment proxies and all redirects."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(ENDPOINT, encoded(payload), method="POST",
        headers={"Content-Type": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "rhhype-metadata-preflight/1"})
    chunks, status = [], None
    try:
        with hard_timeout(timeout):
            try:
                response = opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                status = response.code
                total = 0
                while total < limit:
                    chunk = response.read(min(8192, limit - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
        return status, b"".join(chunks)
    except Exception as exc:
        raise TransportError(type(exc).__name__ + ": " + str(exc)[:240],
            b"".join(chunks), status) from exc


class Probe:
    def __init__(self, out, claim, *, transport=http_transport, clock=time.monotonic,
        sleep=time.sleep):
        self.out, self.transport, self.clock, self.sleep = Path(out), transport, clock, sleep
        self.started = clock()
        self.deadline = self.started + 170  # Ten seconds for cleanup inside the outer 180s wall cap.
        self.last_start = None
        self.trace, self.total_response, self.trace_bytes = [], 0, 0
        self.metadata, self.current = {}, None
        self.claim_raw = encoded({**claim, "reorg_limitation": REORG_LIMIT,
            "eligibility_policy": "report_all_fixed_arms_then_finish_identity",
            "incoming_raw_envelope_bytes": 0})
        # mkdir is the claim: an existing directory, including an empty one, is rejected.
        self.out.mkdir(parents=False, exist_ok=False)
        with (self.out / "claim.json").open("xb") as handle:
            handle.write(self.claim_raw)
        self.flush()

    def remaining(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            fail(RESOURCE, "170-second request deadline; ten-second cleanup reserve")
        return remaining

    def flush(self):
        raw = encoded(self.trace)
        if len(raw) > CAPS["max_retained_raw_bytes_per_session"]:
            fail(RESOURCE, "retained raw trace cap")
        packed = gzip.compress(raw, mtime=0)
        if len(packed) > CAPS["max_retained_raw_bytes_per_session"]:
            fail(RESOURCE, "compressed trace cap")
        (self.out / "trace.json.gz").write_bytes(packed)
        self.trace_bytes = len(packed)

    def rpc(self, method, params):
        self.current = None
        self.remaining()
        body_budget = CAPS["max_total_response_bytes"] - self.total_response
        if body_budget <= 0:
            fail(RESOURCE, "cumulative response body budget exhausted before request")
        read_limit = min(CAPS["max_response_bytes"] + 1, body_budget)
        cumulative_limited = read_limit < CAPS["max_response_bytes"] + 1
        if self.last_start is not None:
            delay = 1 - (self.clock() - self.last_start)
            if delay > 0:
                self.sleep(min(delay, self.remaining()))
                self.remaining()
        if len(self.trace) >= 20:
            fail(RESOURCE, "twenty request cap")
        request = {"jsonrpc": "2.0", "id": len(self.trace) + 1,
            "method": method, "params": params}
        self.last_start = self.clock()
        entry = {"request": request, "start_elapsed_seconds": self.last_start - self.started,
            "outcome": "admitted", "body_read_limit": read_limit}
        self.trace.append(entry)
        self.current = entry
        self.flush()
        timeout = min(12, self.remaining())
        transport_failure = None
        try:
            status, raw = self.transport(request, timeout, read_limit)
        except TransportError as exc:
            status, raw, transport_failure = exc.status, exc.partial, str(exc)
        except Exception as exc:
            status, raw, transport_failure = None, b"", type(exc).__name__ + ": " + str(exc)[:240]
        if not isinstance(raw, bytes):
            raw, transport_failure = b"", "transport returned nonbytes"
        cumulative_boundary = cumulative_limited and len(raw) >= read_limit
        if cumulative_boundary:
            transport_failure = "cumulative response body boundary reached; EOF unproven"
        self.total_response += len(raw)
        entry.update(end_elapsed_seconds=self.clock() - self.started, http_status=status,
            raw_response_bytes=len(raw), raw_response_sha256=digest(raw),
            response_truncated=len(raw) > CAPS["max_response_bytes"] or cumulative_boundary,
            raw_hash_is_prefix=len(raw) > CAPS["max_response_bytes"] or bool(transport_failure))
        obj = None
        if len(raw) <= CAPS["max_response_bytes"] and not transport_failure:
            try:
                obj = decode_json(raw)
                if method == "eth_getBlockByNumber":
                    if isinstance(obj, dict):
                        result = obj.get("result")
                        entry["header_projection"] = ({k: result.get(k) for k in
                            ("number", "hash", "parentHash", "timestamp", "stateRoot")}
                            if isinstance(result, dict) else None)
                        if "error" in obj:
                            error = obj["error"]
                            if isinstance(error, dict):
                                code, message = error.get("code"), error.get("message")
                                entry["rpc_error"] = {
                                    "code": code if type(code) is int and -(2**31) <= code < 2**31 else "malformed",
                                    "message": message[:320] if isinstance(message, str) else "malformed"}
                                entry["rpc_error_message_truncated"] = isinstance(message, str) and len(message) > 320
                            else:
                                entry["rpc_error"] = "malformed"
                    entry["transaction_history_not_retained"] = True
                else:
                    entry["response"] = obj
            except (ValueError, TypeError, UnicodeError):
                transport_failure = "malformed JSON response"
        try:
            retainable = len(encoded(self.trace)) <= CAPS["max_retained_raw_bytes_per_session"] - 8192
        except (ValueError, TypeError, RecursionError):
            retainable = False
        if not retainable:
            for key in ("response", "header_projection", "rpc_error", "rpc_error_message_truncated"):
                entry.pop(key, None)
            entry["response_omitted_for_raw_cap"] = True
            transport_failure = "retained raw cap would be exceeded"
        entry["outcome"] = "received" if not transport_failure else "transport_error"
        self.flush()
        if (transport_failure or status != 200 or len(raw) > CAPS["max_response_bytes"]
            or self.total_response > CAPS["max_total_response_bytes"]
            or self.clock() - self.last_start > timeout):
            fail(RESOURCE, transport_failure or "HTTP/response/cumulative/request-time resource failure")
        self.remaining()
        if (not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0"
            or type(obj.get("id")) is not int or obj["id"] != request["id"]
            or ("error" in obj) == ("result" in obj)):
            fail(IDENTITY, "JSON-RPC envelope mismatch")
        if "error" in obj:
            fail(CAPABILITY if method == "eth_simulateV1" else RESOURCE,
                "RPC error at request " + str(request["id"]))
        return obj["result"]

    def code(self, target, block, empty=False):
        value = self.rpc("eth_getCode", [target, {"blockHash": block["hash"], "requireCanonical": True}])
        raw = hex_data(value)
        if bool(raw) == empty:
            fail(IDENTITY, "scratch must be empty/live runtime must be nonempty")
        if not empty:
            self.metadata.setdefault("code_sha256", {})[target] = digest(raw)

    def call(self, target, signature, block, arg=None):
        data = "0x" + SELECTORS[signature]
        if arg is not None:
            data += format(arg, "064x")
        return self.rpc("eth_call", [{"to": target, "data": data},
            {"blockHash": block["hash"], "requireCanonical": True}])

    def execute(self):
        terminal = {"status": RESOURCE, "economics": None, "full_route_proven": False,
            "reorg_limitation": REORG_LIMIT}
        try:
            if self.rpc("eth_chainId", []) != "0x1":
                fail(IDENTITY, "wrong chain id")
            block = header(self.rpc("eth_getBlockByNumber", ["latest", False]))
            self.metadata["header"] = block
            for address in SCRATCH.values():
                self.code(address, block, empty=True)
            self.metadata["synthetic"] = validate_synthetic(
                self.rpc("eth_simulateV1", synthetic_params(block)), block)
            lido, impl, curve = (CONTRACTS[k] for k in
                ("lido_steth_proxy", "documented_lido_implementation", "curve_legacy_steth_eth"))
            self.code(lido, block)
            if abi_address(self.call(lido, "implementation()", block)) != impl.lower():
                fail(IDENTITY, "Lido implementation address mismatch")
            if abi_uint(self.call(lido, "proxyType()", block)) != 2:
                fail(IDENTITY, "Lido proxy type mismatch")
            self.code(impl, block)
            for signature, expected in (("getContractVersion()", 4), ("decimals()", 18)):
                if abi_uint(self.call(lido, signature, block)) != expected:
                    fail(IDENTITY, "Lido version/decimals mismatch")
            paused = abi_bool(self.call(lido, "isStakingPaused()", block))
            limit = abi_uint(self.call(lido, "getCurrentStakeLimit()", block))
            self.metadata.update(staking_paused=paused, current_stake_limit_wei=str(limit),
                native_arm_eligibility=[{"principal_wei": str(arm),
                "eligible": not paused and arm <= limit,
                "reason": "paused" if paused else
                "stake_limit" if arm > limit else "eligible"} for arm in ARMS])
            self.code(curve, block)
            for index, name in ((0, "curve_coin_0_native_sentinel"), (1, "curve_coin_1")):
                if abi_address(self.call(curve, "coins(uint256)", block, index)) != CONTRACTS[name].lower():
                    fail(IDENTITY, "Curve coin identity mismatch")
            for signature, key in (("fee()", "fee"), ("admin_fee()", "admin_fee")):
                fee = abi_uint(self.call(curve, signature, block))
                if fee > 10**10:
                    fail(IDENTITY, "fee outside documented denominator")
                self.metadata[key] = str(fee)
            self.metadata["fee_denominator"] = "10000000000"
            final = header(self.rpc("eth_getBlockByNumber", [block["number"], False]))
            if final != block:
                fail("canonicality_unavailable", "same-number header identity changed")
            terminal["status"] = ("metadata_compatible_full_route_unproven" if
                all(row["eligible"] for row in self.metadata["native_arm_eligibility"])
                else "issuance_eligibility_unavailable")
        except ProbeError as exc:
            terminal.update(status=exc.category, error=str(exc)[:320])
            if self.current is not None:
                self.current.update(outcome="failed", failure={"category": exc.category, "message": str(exc)[:320]})
        except Exception as exc:
            terminal.update(status=RESOURCE, error=type(exc).__name__ + ": " + str(exc)[:240])
            if self.current is not None:
                self.current.update(outcome="failed", failure={"category": RESOURCE, "message": terminal["error"]})
        self.flush()
        terminal.update(requests=len(self.trace), total_response_bytes=self.total_response,
            retained_raw_bytes=self.trace_bytes, metadata=self.metadata,
            elapsed_seconds=self.clock() - self.started,
            trace_sha256=digest((self.out / "trace.json.gz").read_bytes()))
        body = encoded(terminal)
        if len(self.claim_raw) + len(body) > CAPS["max_retained_derived_bytes_per_session"]:
            fail(RESOURCE, "claim plus terminal derived cap")
        with (self.out / "terminal.json").open("xb") as handle:
            handle.write(body)
        return terminal


def run(plan, plan_raw, out, *, expected_plan_sha, coordinator_authority, endpoint,
    expected_source_sha, expected_test_sha, transport=http_transport,
    clock=time.monotonic, sleep=time.sleep):
    claim = authorize(plan, plan_raw, expected_plan_sha=expected_plan_sha,
        coordinator_authority=coordinator_authority, endpoint=endpoint,
        expected_source_sha=expected_source_sha, expected_test_sha=expected_test_sha)
    return Probe(out, claim, transport=transport, clock=clock, sleep=sleep).execute()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / PROPOSAL)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/peer-research/primary-issuance-preflight-v2")
    for name in ("expected-plan-sha256", "coordinator-authority", "endpoint",
        "expected-source-sha256", "expected-test-sha256"):
        parser.add_argument("--" + name)
    args = parser.parse_args(argv)
    try:
        raw = bounded_file(args.plan)
        plan = decode_json(raw)
        if not args.run:
            result = validate_plan(plan)
            result["protocol_sha256"] = digest(raw)
            print(encoded(result).decode())
            return 0
        with hard_timeout(180):
            result = run(plan, raw, args.out, expected_plan_sha=args.expected_plan_sha256,
                coordinator_authority=args.coordinator_authority, endpoint=args.endpoint,
                expected_source_sha=args.expected_source_sha256, expected_test_sha=args.expected_test_sha256)
        print(encoded({k: result[k] for k in ("status", "requests", "economics", "trace_sha256")}).decode())
        return 0 if result["status"] == "metadata_compatible_full_route_unproven" else 1
    except (ProbeError, ValueError, OSError) as exc:
        print(encoded({"status": getattr(exc, "category", RESOURCE), "error": str(exc)[:320]}).decode())
        return 2


if __name__ == "__main__":
    sys.exit(main())
