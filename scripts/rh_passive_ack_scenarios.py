"""Future-only deterministic ACK sensitivities on received public events.

No acknowledgement or execution is observed. All completed economics are
conditional on the fixed clock, carried-forward queue and public information
delay assumptions. The frozen strict engine and its correction are unchanged.
"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping

from scripts.rh_maker_engine import Book, Config, D0, dec, venue_key
from scripts.rh_passive_retirement_guard import RetirementGuardPassiveExitBranch


@dataclass(frozen=True)
class AckScenario:
    scenario_id: str
    additional_maker_latency_ns: int = 0
    additional_cancel_latency_ns: int = 0
    max_trade_ids: int = 65_536
    max_timer_steps: int = 1024

    def __post_init__(self) -> None:
        if (not self.scenario_id or not isinstance(self.scenario_id, str)
                or any(type(value) is not int or value < 0 for value in
                       (self.additional_maker_latency_ns, self.additional_cancel_latency_ns))
                or type(self.max_trade_ids) is not int or self.max_trade_ids <= 0
                or type(self.max_timer_steps) is not int or self.max_timer_steps <= 0):
            raise ValueError("invalid assumed ACK scenario")


BASE_SCENARIO = AckScenario("assumed_ack_base")
LONGER_LATENCY_SCENARIO = AckScenario("assumed_ack_plus_200ms", 200_000_000, 200_000_000)
ASSUMPTIONS = (
    "Counterfactual deterministic acceptance/cancellation; no private ACK or actual fill observed.",
    "Last previously received raw RH same-price depth is carried forward as queue ahead at due.",
    "No cancellation credit; additions between anchor and due remain unobserved queue uncertainty.",
    "Historical public flow is unaffected by the hypothetical order and its source clock orders flow.",
    "Activation wins an exact source tie; cancel ties are unknown; public receipt starts hedge latency.",
    "Feed freshness is checked; completeness and real private notification timing are not established.",
    "Native trade IDs are assumed unique/stable across transport generations; identical retransmits are duplicates.",
    "Completed net is conditional scenario economics, never an executable or guaranteed profit bound.",
)


class AssumedAckPassiveExitBranch(RetirementGuardPassiveExitBranch):
    """One independent scenario; delegates every fill and cash operation."""

    def __init__(self, config: Config, metadata: Mapping[str, Mapping[str, Any]],
                 *, scenario: AckScenario = BASE_SCENARIO, **kwargs: Any):
        self.scenario = scenario
        # Clone the already normalized frozen Config. Running __post_init__
        # again would reinterpret a Premium stress delay of exactly 300ms.
        effective = copy(config)
        object.__setattr__(effective, "maker_latency_ns",
                           config.maker_latency_ns + scenario.additional_maker_latency_ns)
        object.__setattr__(effective, "cancel_latency_ns",
                           config.cancel_latency_ns + scenario.additional_cancel_latency_ns)
        if effective.maker_latency_ns <= 0 or effective.cancel_latency_ns <= 0:
            raise ValueError("positive assumed maker/cancel latency required")
        self.raw_rh_anchor: Book | None = None
        self._timer_boundary: int | None = None
        self._processing_receipt_ns: int | None = None
        self._ack_evidence: dict[tuple[int, str], dict[str, Any]] = {}
        self._trade_evidence: dict[str, tuple[Any, ...]] = {}
        self._trade_episodes: dict[str, tuple[int, ...]] = {}
        self._trade_generations: dict[str, str] = {}
        super().__init__(effective, metadata, **kwargs)

    def _labels(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario.scenario_id, "execution_assumed": True,
                "private_ack_observed": False,
                "native_trade_ids_stable_across_generations_assumed": True,
                "assumed_maker_latency_ns": self.cfg.maker_latency_ns,
                "assumed_cancel_latency_ns": self.cfg.cancel_latency_ns}

    def _log(self, event: str, now_ns: int, **details: Any) -> None:
        processed = self._processing_receipt_ns if self._processing_receipt_ns is not None else now_ns
        super()._log(event, now_ns, **{**details, **self._labels(),
                                     "processed_receipt_ns": processed})

    def _has_obligation(self) -> bool:
        return bool(self.quote or self.passive_ask or self.hedges or self.exits
                    or self.passive_buys or self.rh_pos or self.hl_pos
                    or self.fallback_requested_ns is not None)

    def _check_coverage(self, now_ns: int) -> None:
        if not self._has_obligation():
            return
        for venue in ("rh", "hl"):
            book = self.books.get(venue)
            # These accounting snapshots can have depleted sides. Empty
            # execution depth is handled by the delegated economic methods;
            # it does not establish a missing public-feed interval.
            if (book is None
                    or not 0 <= now_ns - book.source_ns <= self.cfg.max_book_age_ns
                    or not 0 <= now_ns - book.received_ns <= self.cfg.max_book_age_ns):
                self._unknown("assumed_ack_coverage_gap_open_obligation", now_ns)
                return

    @staticmethod
    def _anchor_identity(book: Book) -> str:
        payload = [book.source_ns, book.received_ns, str(book.generation),
                   [(str(p), str(q)) for p, q in book.bids],
                   [(str(p), str(q)) for p, q in book.asks]]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()

    def _activate(self, quote: Any, role: str, now_ns: int) -> None:
        if (quote is None or quote.activated_ns is not None or quote.canceled_ns is not None
                or now_ns < quote.activation_due_ns):
            return
        due = quote.activation_due_ns
        anchor = self.raw_rh_anchor
        current = self.books.get("rh")
        if (anchor is None or current is None or anchor.generation != current.generation
                or not anchor.source_ns <= anchor.received_ns <= due
                or not 0 <= due - anchor.source_ns <= self.cfg.max_book_age_ns
                or not 0 <= due - anchor.received_ns <= self.cfg.max_book_age_ns
                or not anchor.bids or not anchor.asks):
            self._unknown("assumed_ack_anchor_unavailable", now_ns)
            return
        if not self.rh.valid_order(quote.qty, quote.price):
            self._unknown("assumed_ack_order_rule_invalid", now_ns)
            return
        rejected = (quote.price >= anchor.asks[0][0] if role == "entry"
                    else quote.price <= anchor.bids[0][0])
        if rejected:
            quote.canceled_ns = due
            self._log("assumed_post_only_reject", now_ns, role=role,
                      assumed_effective_ns=due, anchor_source_ns=anchor.source_ns,
                      anchor_received_ns=anchor.received_ns,
                      anchor_sha256=self._anchor_identity(anchor))
            # Frozen entry and ask handlers have differing unactivated reject
            # semantics. Stop conservatively instead of overriding their trade
            # gates or allowing a later snapshot to reactivate this request.
            self._unknown("assumed_post_only_reject_unresolved", now_ns)
            return
        if len(self._ack_evidence) >= 2 * self.cfg.max_episodes:
            self._unknown("assumed_ack_evidence_cap", now_ns)
            return
        levels = anchor.bids if role == "entry" else anchor.asks
        same = sum((qty for price, qty in levels if price == quote.price), D0)
        better = sum((qty for price, qty in levels if
                      (price > quote.price if role == "entry" else price < quote.price)), D0)
        quote.activated_ns = quote.activated_source_ns = due
        quote.generation = anchor.generation
        quote.ahead_same, quote.ahead_better = same, better
        evidence = {"role": role, "episode_number": self.episode_no,
                    "price": str(quote.price), "queue_ahead_assumed": str(same),
                    "assumed_effective_ns": due, "timer_boundary_ns": now_ns,
                    "processed_receipt_ns": (self._processing_receipt_ns
                                             if self._processing_receipt_ns is not None else now_ns),
                    "anchor_source_ns": anchor.source_ns,
                    "anchor_received_ns": anchor.received_ns,
                    "anchor_generation": str(anchor.generation),
                    "anchor_sha256": self._anchor_identity(anchor), **self._labels()}
        self._ack_evidence[(self.episode_no, role)] = evidence
        self._log("assumed_activation", now_ns, **evidence)

    def _cancel(self, quote: Any, role: str, now_ns: int) -> None:
        if (quote is not None and quote.cancel_due_ns is not None
                and quote.canceled_ns is None and now_ns >= quote.cancel_due_ns):
            quote.canceled_ns = quote.cancel_due_ns
            self._log("assumed_cancel", now_ns, role=role,
                      assumed_effective_ns=quote.cancel_due_ns, reason=quote.cancel_reason)

    def _settle_acks(self, now_ns: int) -> None:
        self._activate(self.quote, "entry", now_ns)
        if not self.unknown_reason:
            self._activate(self.passive_ask, "exit", now_ns)
        if not self.unknown_reason:
            self._cancel(self.quote, "entry", now_ns)
            self._cancel(self.passive_ask, "exit", now_ns)

    def _request_cancel(self, now_ns: int, reason: str) -> None:
        previous = None if self.quote is None else self.quote.cancel_due_ns
        super()._request_cancel(now_ns, reason)
        evidence = self._ack_evidence.get((self.episode_no, "entry"))
        if previous is None and evidence is not None and self.quote is not None:
            evidence.update(cancel_request_ns=now_ns, cancel_due_ns=self.quote.cancel_due_ns,
                            cancel_reason=self.quote.cancel_reason)
        boundary = self._timer_boundary if self._timer_boundary is not None else self.now_ns
        if boundary is not None and not self.unknown_reason:
            self._cancel(self.quote, "entry", boundary)

    def _request_passive_cancel(self, now_ns: int, reason: str) -> None:
        previous = None if self.passive_ask is None else self.passive_ask.cancel_due_ns
        super()._request_passive_cancel(now_ns, reason)
        evidence = self._ack_evidence.get((self.episode_no, "exit"))
        if previous is None and evidence is not None and self.passive_ask is not None:
            evidence.update(cancel_request_ns=now_ns, cancel_due_ns=self.passive_ask.cancel_due_ns,
                            cancel_reason=self.passive_ask.cancel_reason)
        boundary = self._timer_boundary if self._timer_boundary is not None else self.now_ns
        if boundary is not None and not self.unknown_reason:
            self._cancel(self.passive_ask, "exit", boundary)

    def _next_boundary(self, after_ns: int, target_ns: int) -> int:
        deadlines = [target_ns]
        for quote in (self.quote, self.passive_ask):
            if quote is None:
                continue
            if quote.activated_ns is None and quote.canceled_ns is None:
                deadlines.append(quote.activation_due_ns)
            if quote.cancel_due_ns is not None:
                deadlines.append(quote.cancel_due_ns if quote.canceled_ns is None else
                                 quote.cancel_due_ns + self.cfg.max_book_age_ns)
        if self.quote is not None and self.quote.activated_ns is not None and self.quote.cancel_due_ns is None:
            deadlines.append(self.quote.activation_due_ns + self.cfg.quote_rest_ns)
        if self.first_full_hedge_ns is not None and self.exit_requested_ns is None and self.fallback_requested_ns is None:
            deadlines.append(self.first_full_hedge_ns + self.cfg.hold_ns)
        deadlines.extend(intent.timeout_ns + 1 for intent in self.hedges)
        deadlines.extend(intent.timeout_ns + 1 for intent in self.exits.values())
        deadlines.extend(intent.timeout_ns + 1 for intent in self.passive_buys)
        if self._has_obligation():
            for book in self.books.values():
                deadlines.extend((book.source_ns + self.cfg.max_book_age_ns + 1,
                                  book.received_ns + self.cfg.max_book_age_ns + 1))
        return min(value for value in deadlines if after_ns < value <= target_ns)

    def tick(self, now_ns: int) -> None:
        previous = self._processing_receipt_ns
        self._processing_receipt_ns = int(now_ns)
        try:
            self._advance_to(int(now_ns))
        finally:
            self._processing_receipt_ns = previous

    def _advance_to(self, now_ns: int) -> None:
        now_ns = int(now_ns)
        if self.now_ns is not None and now_ns < self.now_ns:
            self._unknown("backward_receipt_time", now_ns)
            return
        if self.unknown_reason or self.now_ns is None:
            super().tick(now_ns)
            return
        steps = 0
        # Even an equal-receipt call can settle a newly created timer, while
        # repeated calls do not accrue cost twice or change the anchor.
        while True:
            boundary = (self._next_boundary(self.now_ns, now_ns)
                        if self.now_ns < now_ns else now_ns)
            steps += 1
            if steps > self.scenario.max_timer_steps:
                self._unknown("assumed_ack_timer_cap", boundary)
                return
            self._timer_boundary = boundary
            try:
                self._check_coverage(boundary)
                if not self.unknown_reason:
                    self._settle_acks(boundary)
                super().tick(boundary)
                if not self.unknown_reason:
                    self._settle_acks(boundary)
            finally:
                self._timer_boundary = None
            if boundary == now_ns or self.unknown_reason:
                return

    def _check_late_revision(self, book: Book) -> None:
        for evidence in self._ack_evidence.values():
            if not (evidence["anchor_source_ns"] <= book.source_ns <= evidence["assumed_effective_ns"]
                    and book.received_ns > evidence["anchor_received_ns"]):
                continue
            price = dec(evidence["price"])
            levels = book.bids if evidence["role"] == "entry" else book.asks
            same = sum((qty for px, qty in levels if px == price), D0)
            crossed = (price >= book.asks[0][0] if evidence["role"] == "entry"
                       else price <= book.bids[0][0])
            if (same != dec(evidence["queue_ahead_assumed"]) or crossed
                    or str(book.generation) != evidence["anchor_generation"]):
                reason = "assumed_ack_anchor_late_revision"
                evidence["execution_unknown_reason"] = reason
                evidence["late_revision"] = {
                    "source_ns": book.source_ns, "received_ns": book.received_ns,
                    "generation": str(book.generation), "same_price_depth": str(same),
                    "post_only_crossed": crossed, "book_sha256": self._anchor_identity(book)}
                for episode in self.episodes:
                    if episode["number"] == evidence["episode_number"]:
                        episode["execution_unknown"] = True
                        episode["execution_unknown_reason"] = reason
                        episode["fee_only_net"] = episode["stressed_net"] = None
                self._unknown(reason, book.received_ns)

    def _on_book(self, book: Book) -> None:
        raw = Book(book.venue, book.received_ns, book.source_ns, book.generation,
                   list(book.bids), list(book.asks))
        if book.venue == "rh":
            self._check_late_revision(raw)
            if self.unknown_reason:
                return
        super()._on_book(book)
        if (book.venue == "rh" and not self.unknown_reason
                and 0 <= book.received_ns - book.source_ns <= self.cfg.max_book_age_ns):
            self.raw_rh_anchor = raw

    def _guard_retired_trade(self, event: Mapping[str, Any]) -> bool:
        # Identity/storage failures must not leave an already finalized old
        # episode known. These paths only flag evidence, never apply a fill.
        if self._late_retired_match(event) is not None:
            super().process(event)
            return True
        elif self._passive:
            return self._retired_flow_check(event)
        return False

    def _mark_conflicting_trade_history(self, trade_id: str, signature: tuple[Any, ...]) -> None:
        source, side, price, _ = signature
        price = dec(price)
        affected = set(self._trade_episodes.get(trade_id, ()))
        # Include a changed signature that newly implicates a historical
        # order, and full orders with no unfilled-remainder tombstone.
        for evidence in self._ack_evidence.values():
            cancel = evidence.get("cancel_due_ns")
            quote_price = dec(evidence["price"])
            if (cancel is not None and evidence["assumed_effective_ns"] <= source <= cancel
                    and ((evidence["role"] == "entry" and side == "sell" and price <= quote_price)
                         or (evidence["role"] == "exit" and side == "buy" and price >= quote_price))):
                affected.add(evidence["episode_number"])
        for episode in self.episodes:
            if episode["number"] in affected:
                episode.update(execution_unknown=True,
                               execution_unknown_reason="assumed_ack_trade_id_conflict",
                               conflicting_trade_id=trade_id,
                               fee_only_net=None, stressed_net=None)

    def _live_trade_episodes(self, signature: tuple[Any, ...]) -> tuple[int, ...]:
        source, side, price, _ = signature
        price = dec(price)
        for quote, expected_side, role in ((self.quote, "sell", "entry"),
                                           (self.passive_ask, "buy", "exit")):
            if (quote is not None and quote.activated_ns is not None and side == expected_side
                    and source >= quote.activation_due_ns
                    and (quote.cancel_due_ns is None or source <= quote.cancel_due_ns)
                    and (price <= quote.price if role == "entry" else price >= quote.price)):
                return (self.episode_no,)
        return ()

    def process(self, event: Mapping[str, Any], quote_diag: Mapping[str, Any] | None = None) -> None:
        kind = event.get("type", event.get("kind"))
        if kind == "end":
            super().process(event, quote_diag)
            return
        receipt = int(event.get("received_ns", event.get("receipt_ns")))
        if self.now_ns is not None and receipt < self.now_ns:
            self._unknown("backward_receipt_time", receipt)
            return
        self.tick(receipt)
        matching = event.get("asset") in (None, self.cfg.asset)
        if matching and venue_key(event.get("venue")) == "rh":
            if kind == "invalidate" or event.get("valid") is False:
                self.raw_rh_anchor = None
            if kind == "book" and event.get("valid") is not False:
                # A branch halt stops new economics, not the review of late
                # historical evidence against already finalized episodes.
                try:
                    raw = Book.parse(event)
                except (ValueError, KeyError, TypeError, ArithmeticError):
                    raw = None
                if raw is not None:
                    self._check_late_revision(raw)
            if kind == "trade":
                try:
                    source = int(event["source_ns"])
                    price, qty = dec(event["price"]), dec(event["qty"])
                    native_id = event.get("trade_id", event.get("id"))
                    trade_id = (str(native_id) if
                                ((type(native_id) is int and native_id >= 0)
                                 or (isinstance(native_id, str) and native_id.strip()
                                     and len(native_id) <= 128)) else "")
                    valid = (0 < source <= receipt and event.get("clock_valid", True)
                             and price.is_finite() and qty.is_finite() and price > 0 and qty > 0)
                except (KeyError, TypeError, ValueError, ArithmeticError):
                    valid, trade_id = False, ""
                if not valid or not trade_id:
                    self._unknown("assumed_ack_trade_identity_or_clock_invalid", receipt)
                    # Do not pass malformed values to the parent's unchecked
                    # live-queue arithmetic. Well-formed missing-ID evidence
                    # can still invalidate a retired execution assumption.
                    if valid:
                        self._guard_retired_trade(event)
                    return
                signature = (source, event.get("side"), str(price.normalize()),
                             str(qty.normalize()))
                generation = str(event.get("generation"))[:100]
                if trade_id in self._trade_evidence:
                    if self._trade_evidence[trade_id] != signature:
                        self._unknown("assumed_ack_trade_id_conflict", receipt)
                        self._mark_conflicting_trade_history(trade_id, self._trade_evidence[trade_id])
                        self._mark_conflicting_trade_history(trade_id, signature)
                        self._guard_retired_trade(event)
                    elif generation != self._trade_generations[trade_id]:
                        self._log("assumed_duplicate_trade_generation", receipt,
                                  trade_id=trade_id,
                                  first_generation=self._trade_generations[trade_id],
                                  duplicate_generation=generation)
                    return
                if len(self._trade_evidence) >= self.scenario.max_trade_ids:
                    self._unknown("assumed_ack_trade_id_cap", receipt)
                    self._guard_retired_trade(event)
                    return
                self._trade_evidence[trade_id] = signature
                self._trade_episodes[trade_id] = self._live_trade_episodes(signature)
                self._trade_generations[trade_id] = generation
                if self._guard_retired_trade(event):
                    return
        super().process(event, quote_diag)

    def _close_episode_if_flat(self, now_ns: int) -> None:
        previous = len(self.episodes)
        episode_number = self.episode_no
        super()._close_episode_if_flat(now_ns)
        if len(self.episodes) > previous:
            self.episodes[-1].update({**self._labels(), "ack_assumptions": ASSUMPTIONS,
                "processed_receipt_ns": (self._processing_receipt_ns
                                         if self._processing_receipt_ns is not None else now_ns),
                "assumed_entry_ack": self._ack_evidence.get((episode_number, "entry")),
                "assumed_exit_ack": self._ack_evidence.get((episode_number, "exit"))})

    def summary(self) -> dict[str, Any]:
        out = super().summary()
        out.update({**self._labels(), "schema": "rh-passive-assumed-ack-scenario-v1",
                    "ack_assumptions": ASSUMPTIONS,
                    "guaranteed_profit_bound": False, "actual_fills_observed": False,
                    "assumed_ack_evidence": list(self._ack_evidence.values()),
                    "trade_ids_retained": len(self._trade_evidence),
                    "scenario_limits": {"max_trade_ids": self.scenario.max_trade_ids,
                                        "max_timer_steps": self.scenario.max_timer_steps}})
        for episode in out["episodes"]:
            if episode.get("execution_unknown"):
                episode["fee_only_net"] = episode["stressed_net"] = None
        return out
