"""Offline, price-free Clipper census. No network adapter, live CLI or writer."""
import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "research/peer-clipper-census-v1.json"
PIN_PATHS = frozenset(("scripts/peer_clipper_census_v1.py", "tests/test_peer_clipper_census_v1.py",
                       "research/peer-clipper-census-v1-design.txt"))
CLIPPER = "0xc67963a226eddd77b91ad8c421630a1b0adff270"
ILK = "0x4554482d41000000000000000000000000000000000000000000000000000000"
ZERO = "0x" + "00" * 20
SELECTORS = {"ilk()": "c5ce281e", "count()": "06661abd", "list()": "0f560cd7"}
CAPS = {"requests": 8, "response_bytes": 65536, "total_body_bytes": 196608,
        "trace_bytes": 196608, "request_seconds": 10, "run_seconds": 90,
        "file_bytes": 65536, "source_package_all_copies_bytes": 131072}
CENSUS_LIMIT = 64


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
    def pairs(items):
        result = {}
        for key, value in items:
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
    result = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject, parse_float=finite)
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


def uint(value):
    return int.from_bytes(hex_bytes(value, 32), "big")


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


def state_selector(parent):
    return {"blockHash": parent["hash"], "requireCanonical": True}


def call_object(signature):
    return {"from": ZERO, "to": CLIPPER, "input": "0x" + SELECTORS[signature],
            "gas": hex(200000), "value": "0x0"}


def decode_ids(value, count):
    if type(count) is not int or not 1 <= count <= CENSUS_LIMIT:
        fail("census_over_cap", "full-list count must be 1..64")
    raw = hex_bytes(value, 64 + 32 * count)
    words = [int.from_bytes(raw[i:i + 32], "big") for i in range(0, len(raw), 32)]
    if words[:2] != [32, count] or 0 in words[2:] or len(set(words[2:])) != count:
        fail("abi_unavailable", "list offset/length or positive unique IDs mismatch")
    return words[2:]  # Preserve storage order; never truncate or sample.


def manifest():
    anchor = {"blockHash": "$parent.hash", "requireCanonical": True}
    rows = [("chain", "eth_chainId", []),
            ("parent", "eth_getBlockByNumber", ["latest", False]),
            ("clipper_code", "eth_getCode", [CLIPPER, anchor])]
    rows += [(name, "eth_call", [call_object(sig), anchor]) for name, sig in
             (("ilk", "ilk()"), ("count", "count()"), ("list", "list()"), ("final_count", "count()"))]
    rows.append(("final_parent", "eth_getBlockByNumber", ["$parent.number", False]))
    return [{"name": name, "method": method, "params": params,
             "condition": "1<=count<=64" if name == "list" else "always"}
            for name, method, params in rows]


def validate_binding(binding):
    if binding is None:
        return
    if (not isinstance(binding, dict) or set(binding) != {"kind", "root_review_ref", "artifact_set_sha256", "roles"}
            or binding["kind"] not in ("synthetic_fixture", "root_reviewed_artifact_certificate")
            or not isinstance(binding["root_review_ref"], str) or not 0 < len(binding["root_review_ref"]) <= 240
            or not isinstance(binding["artifact_set_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", binding["artifact_set_sha256"])
            or not isinstance(binding["roles"], dict) or set(binding["roles"]) != {"clipper"}):
        fail("binding_unavailable", "invalid caller-supplied certificate")
    role = binding["roles"]["clipper"]
    if (not isinstance(role, dict) or set(role) != {"address", "runtime_sha256"}
            or role["address"] != CLIPPER or not isinstance(role["runtime_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", role["runtime_sha256"])):
        fail("binding_unavailable", "invalid Clipper certificate role")


def validate_plan(plan):
    if (not isinstance(plan, dict) or plan.get("schema") != "peer-clipper-census-v1"
            or plan.get("status") != "offline_draft_no_network_authority"
            or plan.get("network_authorized") is not False or type(plan.get("raw_allocation_bytes")) is not int
            or plan["raw_allocation_bytes"] != 0 or type(plan.get("census_limit")) is not int
            or plan["census_limit"] != CENSUS_LIMIT or encoded(plan.get("caps")) != encoded(CAPS)
            or plan.get("contracts") != {"clipper": CLIPPER, "ilk": ILK}
            or encoded(plan.get("manifest")) != encoded(manifest())):
        fail("manifest_mismatch", "fixed offline plan/manifest mismatch")
    validate_binding(plan.get("runtime_binding"))
    return {"status": "dry_validated_no_network", "requests_permitted": 0, "economics": None,
            "prospective_max_requests": 8, "manifest_sha256": sha(encoded(manifest())),
            "runtime_binding_present": plan.get("runtime_binding") is not None}


class Collector:
    """One instance/one offline transcript; injected streams are not a live adapter."""
    def __init__(self, transport, *, binding=None, clock=time.monotonic):
        validate_binding(binding)
        self.transport, self.binding, self.clock = transport, binding, clock
        self.used, self.started, self.total_bytes = False, None, 0
        self.trace, self.metadata, self.matched = [], {}, False

    def rpc(self, name, method, params):
        remaining = CAPS["total_body_bytes"] - self.total_bytes
        if (remaining <= 0 or len(self.trace) >= CAPS["requests"]
                or self.clock() - self.started >= CAPS["run_seconds"] - 10):
            fail("resource_unavailable", "request/body/overall deadline cap")
        request = {"jsonrpc": "2.0", "id": len(self.trace) + 1, "method": method, "params": params}
        row = {"name": name, "request": request, "outcome": "pending"}
        if len(encoded(request)) > 8192 or len(encoded(self.trace + [row])) + 4096 > CAPS["trace_bytes"]:
            fail("resource_unavailable", "request/trace admission cap")
        self.trace.append(row)
        raw, eof, started = bytearray(), False, self.clock()
        limit = min(CAPS["response_bytes"] + 1, remaining)
        try:
            status, stream = self.transport(request, min(CAPS["request_seconds"],
                CAPS["run_seconds"] - 10 - (started - self.started)))
            while len(raw) < limit:
                part = stream.read(min(8192, limit - len(raw)))
                if not isinstance(part, bytes) or len(part) > min(8192, limit - len(raw)):
                    fail("resource_unavailable", "transport violated bounded byte reads")
                if not part:
                    eof = True
                    break
                raw.extend(part)
                if self.clock() - started > CAPS["request_seconds"]:
                    fail("resource_unavailable", "response deadline")
            if not eof or len(raw) > CAPS["response_bytes"] or status != 200:
                fail("resource_unavailable", "response cap, unproven EOF or status")
            if self.clock() - started > CAPS["request_seconds"]:
                fail("resource_unavailable", "response deadline")
            obj = decode_json(raw)
            row["response"] = obj
            if (not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0"
                    or type(obj.get("id")) is not int or obj["id"] != request["id"]
                    or set(obj) not in ({"jsonrpc", "id", "result"}, {"jsonrpc", "id", "error"})):
                fail("rpc_unavailable", "invalid JSON-RPC envelope")
            if "error" in obj:
                fail("rpc_unavailable", "provider returned an error")
            if name in ("parent", "final_parent") and isinstance(obj["result"], dict):
                row["response"] = {**obj, "result": {key: obj["result"].get(key) for key in
                    ("number", "hash", "parentHash", "timestamp", "stateRoot")}}
            row["outcome"] = "returned"
            return obj["result"]
        except GateError:
            row["outcome"] = "failed"
            raise
        except Exception as exc:
            row["outcome"] = "failed"
            fail("resource_unavailable", type(exc).__name__ + ": " + str(exc)[:160])
        finally:
            self.total_bytes += len(raw)
            row.update(body_bytes=len(raw), body_sha256=sha(raw), eof=eof, elapsed_seconds=self.clock() - started)
            if len(encoded(self.trace)) > CAPS["trace_bytes"] - 2048:
                row.pop("response", None)
                row["response_omitted_for_cap"] = True
                row["outcome"] = "failed"
                fail("resource_unavailable", "bounded in-memory trace cap")

    def view(self, name, signature, parent):
        return self.rpc(name, "eth_call", [call_object(signature), state_selector(parent)])

    def execute(self):
        if self.used:
            fail("one_run_consumed", "collector instance already used")
        self.used, self.started = True, self.clock()
        result = {"status": "unavailable", "provider_census_complete": False,
                  "canonical_parent_rechecked": False, "network_requests_permitted": 0,
                  "evidence_kind": "offline_transport", "economics": None, "cash_closed": False,
                  "source_equivalence_proven_by_collector": False, "runtime_dependency_closure_complete": False,
                  "source_binding": "unavailable", "certificate_authority_verified": False,
                  "certificate_kind_claim": self.binding["kind"] if self.binding else None,
                  "certificate_review_ref_claim": self.binding["root_review_ref"] if self.binding else None,
                  "reset_eligibility_established": False, "inclusion_established": False}
        try:
            if self.rpc("chain", "eth_chainId", []) != "0x1":
                fail("identity_unavailable", "chain must be Ethereum mainnet")
            parent = header(self.rpc("parent", "eth_getBlockByNumber", ["latest", False]))
            self.metadata["parent"] = parent
            raw = hex_bytes(self.rpc("clipper_code", "eth_getCode", [CLIPPER, state_selector(parent)]))
            if not raw:
                fail("identity_unavailable", "empty Clipper runtime")
            fingerprint = {"address": CLIPPER, "runtime_sha256": sha(raw)}
            self.metadata["code_fingerprints"] = {"clipper": fingerprint}
            if self.binding:
                if fingerprint != self.binding["roles"]["clipper"]:
                    fail("binding_mismatch", "Clipper runtime differs from supplied certificate")
                self.matched = True
            if hex_bytes(self.view("ilk", "ilk()", parent), 32) != bytes.fromhex(ILK[2:]):
                fail("identity_unavailable", "wrong collateral ilk")
            count = uint(self.view("count", "count()", parent))
            self.metadata["reported_count"] = count
            if count > CENSUS_LIMIT:
                fail("census_over_cap", "complete census exceeds fixed 64-item ceiling")
            ids = decode_ids(self.view("list", "list()", parent), count) if count else []
            self.metadata["reported_ids"] = ids
            if uint(self.view("final_count", "count()", parent)) != count:
                fail("canonicality_unavailable", "anchored count changed")
            final_parent = header(self.rpc("final_parent", "eth_getBlockByNumber", [parent["number"], False]))
            if final_parent != parent:
                fail("canonicality_unavailable", "original numbered parent changed")
            result.update(provider_census_complete=True, canonical_parent_rechecked=True)
            if not self.binding:
                result["status"] = "source_binding_unavailable"
            else:
                result["status"] = "reported_nonempty_metadata_only" if count else "reported_empty_metadata_only"
                result["source_binding"] = ("synthetic_fixture_only" if self.binding["kind"] == "synthetic_fixture"
                    else "checked_runtime_roles_match_caller_supplied_certificate")
                result["binding_certificate_sha256"] = sha(encoded(self.binding))
        except GateError as exc:
            result.update(status=exc.category, error=str(exc)[:240])
            if self.trace:
                self.trace[-1]["gate_failure"] = {"category": exc.category, "message": str(exc)[:240]}
        except Exception as exc:
            result.update(status="resource_unavailable", error=type(exc).__name__ + ": " + str(exc)[:160])
        selected = {row["name"] for row in self.trace}
        result["unexecuted_steps"] = [{"name": row["name"], "reason": "condition_not_met" if
            row["name"] == "list" and self.metadata.get("reported_count") == 0 else "not_reached_after_failure"}
            for row in manifest() if row["name"] not in selected]
        if len(encoded(self.trace)) > CAPS["trace_bytes"]:
            fail("resource_unavailable", "terminal trace cap invariant failed")
        result.update(requests=len(self.trace), body_bytes=self.total_bytes, metadata=self.metadata,
                      trace_sha256=sha(encoded(self.trace)), certificate_roles_matched=["clipper"] if self.matched else [],
                      certificate_roles_unverified=[] if self.matched else ["clipper"])
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
        fail("source_pin_mismatch", "exact source/test/design pins required")
    seen = set()
    for pin in pins:
        if (not isinstance(pin, dict) or set(pin) != {"path", "bytes", "sha256"}
                or not isinstance(pin["path"], str) or pin["path"] not in PIN_PATHS or pin["path"] in seen
                or type(pin["bytes"]) is not int or not 0 < pin["bytes"] <= CAPS["file_bytes"]
                or not isinstance(pin["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])):
            fail("source_pin_mismatch", "invalid fixed-path pin")
        seen.add(pin["path"])
        path = ROOT
        for part in Path(pin["path"]).parts:
            path = path / part
            if path.is_symlink():
                fail("source_pin_mismatch", "symlink pin path")
        raw = bounded_file(path)
        if len(raw) != pin["bytes"] or sha(raw) != pin["sha256"]:
            fail("source_pin_mismatch", "local bytes differ: " + pin["path"])
    return "verified"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN_PATH)
    args = parser.parse_args(argv)
    try:
        raw = bounded_file(args.plan)
        plan = decode_json(raw)
        result = validate_plan(plan)
        result.update(source_pin_status=verify_file_pins(plan), plan_sha256=sha(raw))
        print(encoded(result).decode())
        return 0
    except (GateError, ValueError, OSError) as exc:
        print(encoded({"status": getattr(exc, "category", "file_unavailable"), "error": str(exc)[:240]}).decode())
        return 2


if __name__ == "__main__":
    sys.exit(main())
