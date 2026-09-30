"""Read-only RH maker-buy / HL short branch with a bounded passive exit.

This subclasses the frozen entry engine without changing its entry decisions.
Public books and prints are conditional observations, not order acknowledgments
or proof of fills. An unresolved quote, clock, cancel, lot, or hedge obligation
keeps the outcome unknown. The two venue cash ledgers assume USDG=USDC solely
for the displayed comparison; no conversion is modeled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Mapping

from scripts.rh_maker_engine import (
    Book, Config, D0, NS, YEAR_NS, dec, floor_step, on_step,
)
from scripts.rh_maker_late_flow_guard import GuardedMakerBuyBranch
from scripts.rh_maker_sell_engine import buy_limit_at_or_below


POLICY_HOLDS = {
    "control10s": 10 * NS,
    "passive_best10s": 10 * NS,
    "passive_target10s": 10 * NS,
    "passive_target60s": 60 * NS,
}
MAX_EXIT_TRADE_IDS = 16_384


@dataclass
class PassiveAsk:
    episode_number: int
    price: Decimal
    qty: Decimal
    decided_ns: int
    activation_due_ns: int
    remaining: Decimal
    activated_ns: int | None = None
    activated_source_ns: int | None = None
    generation: Any = None
    cancel_due_ns: int | None = None
    cancel_reason: str | None = None
    canceled_ns: int | None = None
    ahead_better: Decimal = D0
    ahead_same: Decimal = D0
    maker_attributed: Decimal = D0
    increments: int = 0
    seen_ids: set[str] = field(default_factory=set)
    retired_ns: int | None = None


@dataclass
class PassiveBuy:
    qty: Decimal
    due_ns: int
    timeout_ns: int
    anchor_ask: Decimal
    flow_receipt_ns: int


class PassiveExitBranch(GuardedMakerBuyBranch):
    """One buy-RH/short-HL branch. ``process`` matches ``MakerBranch``.

    ``exit_adverse_bps`` is a frozen nonnegative 75th-percentile HL buy
    markout input for target quote *selection*, not an extra realized fee.
    ``control10s`` delegates its exit mechanics to the inherited engine.
    """

    def __init__(self, config: Config, metadata: Mapping[str, Mapping[str, Any]],
                 *, exit_policy: str, exit_adverse_bps: Decimal | None = None,
                 audit_sink: Callable[[dict[str, Any]], None] | None = None):
        if exit_policy not in POLICY_HOLDS:
            raise ValueError("unknown passive-exit policy")
        if config.policy != "fixed_best" or config.hold_ns != POLICY_HOLDS[exit_policy]:
            raise ValueError("fixed_best entry and policy-matching hold_ns required")
        if exit_adverse_bps is not None and dec(exit_adverse_bps) < 0:
            raise ValueError("negative adverse calibration")
        super().__init__(config, metadata, audit_sink=audit_sink)
        self.exit_policy = exit_policy
        self.exit_adverse_bps = None if exit_adverse_bps is None else dec(exit_adverse_bps)
        self.passive_ask: PassiveAsk | None = None
        self.passive_buys: list[PassiveBuy] = []
        self.passive_attempted = False
        self.fallback_requested_ns: int | None = None
        self.fallback_reason: str | None = None
        self.cohort_id: str | None = None
        self._retired_passive: list[PassiveAsk] = []
        self._episode_hl_entry_qty = D0
        self._episode_start_fees_rh = D0
        self._episode_start_fees_hl = D0
        self._episode_passive_rh_exit_value = D0
        self._episode_passive_hl_buy_value = D0
        self._episode_passive_hl_buy_qty = D0
        self._episode_taker_rh_exit_value = D0
        self._episode_taker_rh_exit_qty = D0
        self._episode_taker_hl_exit_value = D0
        self._episode_taker_hl_exit_qty = D0

    @property
    def _passive(self) -> bool:
        return self.exit_policy != "control10s"

    def _on_diagnostic(self, diag: Mapping[str, Any], now_ns: int) -> None:
        previous = self.quote
        super()._on_diagnostic(diag, now_ns)
        if previous is None and self.quote is not None:
            self.cohort_id = (f"{self.cfg.asset}:{self.cfg.budget_usd}:"
                              f"{self.cfg.tier}:{self.quote.decided_ns}")
            self._episode_start_fees_rh = self.fees_rh
            self._episode_start_fees_hl = self.fees_hl

    def _episode_executable_exit_mark(self, now_ns: int) -> Decimal | None:
        # The control retains the original 10 s OR $0.10 early-take-profit
        # policy. Passive arms retain their specified fixed hold.
        if self._passive:
            return None
        return super()._episode_executable_exit_mark(now_ns)

    @staticmethod
    def _deplete(book: Book, side: str, qty: Decimal) -> None:
        """Reserve public displayed quantity for this branch after one fill."""
        levels = book.bids if side == "sell" else book.asks
        remaining = qty
        for index, (price, available) in enumerate(levels):
            used = min(remaining, available)
            levels[index] = (price, available - used)
            remaining -= used
            if remaining == 0:
                break
        if remaining != 0:
            raise RuntimeError("filled quantity exceeded branch-local public depth")
        levels[:] = [(price, available) for price, available in levels if available > 0]

    def _fresh_pair(self, now_ns: int) -> bool:
        if not super()._fresh_pair(now_ns):
            return False
        return all(book.bids and book.asks for book in self.books.values())

    def _fill_hedge(self, intent: Any, book: Book) -> None:
        before = self.hl_pos
        super()._fill_hedge(intent, book)
        if self.hl_pos < before:
            filled = before - self.hl_pos
            self._episode_hl_entry_qty += filled
            self._deplete(book, "sell", filled)

    def _fill_exit(self, venue: str, book: Book) -> None:
        intent = self.exits.get(venue)
        if intent is not None and book.received_ns >= intent.due_ns and book.source_ns >= intent.due_ns:
            pos = self.rh_pos if venue == "rh" else self.hl_pos
            if (pos > 0 and not book.bids) or (pos < 0 and not book.asks):
                self._unknown("exit_public_depth_unavailable", book.received_ns)
                return
        before = self.rh_pos if venue == "rh" else self.hl_pos
        old_cash = self.cash_rh if venue == "rh" else self.cash_hl
        old_fee = self.fees_rh if venue == "rh" else self.fees_hl
        super()._fill_exit(venue, book)
        after = self.rh_pos if venue == "rh" else self.hl_pos
        new_cash = self.cash_rh if venue == "rh" else self.cash_hl
        new_fee = self.fees_rh if venue == "rh" else self.fees_hl
        if before > 0 and after < before:
            filled = before - after
            self._deplete(book, "sell", filled)
            if venue == "rh":
                self._episode_taker_rh_exit_qty += filled
                self._episode_taker_rh_exit_value += new_cash - old_cash + new_fee - old_fee
        elif before < 0 and after > before:
            filled = after - before
            self._deplete(book, "buy", filled)
            if venue == "hl":
                self._episode_taker_hl_exit_qty += filled
                self._episode_taker_hl_exit_value += old_cash - new_cash - (new_fee - old_fee)

    def _request_passive_cancel(self, now_ns: int, reason: str) -> None:
        p = self.passive_ask
        if p is not None and p.canceled_ns is None and p.cancel_due_ns is None:
            p.cancel_due_ns = now_ns + self.cfg.cancel_latency_ns
            p.cancel_reason = reason
            self._log("passive_cancel_requested", now_ns, due_ns=p.cancel_due_ns, reason=reason)

    def _entry_reconciled(self, now_ns: int) -> bool:
        q = self.quote
        return (q is not None and q.canceled_ns is not None and not self.hedges
                and (q.cancel_due_ns is None or
                     now_ns >= q.cancel_due_ns + self.cfg.max_book_age_ns))

    def _passive_reconciled(self, now_ns: int) -> bool:
        p = self.passive_ask
        if p is None:
            return True
        if p.canceled_ns is None or self.passive_buys:
            return False
        return (p.cancel_due_ns is None or
                now_ns >= p.cancel_due_ns + self.cfg.max_book_age_ns)

    def _maybe_start_fallback(self, now_ns: int) -> None:
        if (self.fallback_requested_ns is None or self.exit_requested_ns is not None
                or self.unknown_reason):
            return
        if not self._entry_reconciled(now_ns) or not self._passive_reconciled(now_ns):
            return
        self._log("passive_fallback_reconciled", now_ns,
                  requested_ns=self.fallback_requested_ns,
                  rh_pos=self.rh_pos, hl_pos=self.hl_pos)
        super()._start_exit(now_ns, self.fallback_reason or "passive_deadline")

    def _start_exit(self, now_ns: int, reason: str) -> None:
        if not self._passive:
            super()._start_exit(now_ns, reason)
            return
        if self.fallback_requested_ns is None:
            self.fallback_requested_ns = now_ns
            self.fallback_reason = reason
            self._log("passive_fallback_requested", now_ns, reason=reason,
                      rh_pos=self.rh_pos, hl_pos=self.hl_pos)
        self._request_cancel(now_ns, reason)
        self._request_passive_cancel(now_ns, reason)
        self._maybe_start_fallback(now_ns)

    def tick(self, now_ns: int) -> None:
        super().tick(now_ns)
        if not self._passive or self.unknown_reason:
            return
        p = self.passive_ask
        if p is not None:
            if (p.activated_ns is None and p.canceled_ns is None and
                    now_ns > p.activation_due_ns + self.cfg.max_book_age_ns):
                self._unknown("passive_activation_book_timeout", now_ns)
                return
            if (p.cancel_due_ns is not None and p.canceled_ns is None and
                    now_ns > p.cancel_due_ns + self.cfg.max_book_age_ns):
                self._unknown("passive_cancel_confirmation_timeout", now_ns)
                return
        for intent in self.passive_buys:
            if now_ns > intent.timeout_ns:
                self._unknown("passive_buy_timeout_unhedged_short", now_ns)
                return
        self._maybe_start_fallback(now_ns)
        self._close_episode_if_flat(now_ns)

    def _target_price(self, now_ns: int, qty: Decimal,
                      rh_book: Book, hl_book: Book) -> Decimal | None:
        if self.exit_adverse_bps is None:
            self._log("passive_target_abstain", now_ns, reason="missing_frozen_adverse_bps")
            return None
        found, hl_value = hl_book.walk("buy", qty)
        if found != qty:
            self._log("passive_target_abstain", now_ns, reason="shallow_hl_buy_mark")
            return None
        adjusted_hl = hl_value * (1 + self.exit_adverse_bps / 10_000)
        existing_cash = self.cash_rh + self.cash_hl - self._episode_start_cash
        reserve = self.reserve_cost - self._episode_start_reserve
        capital = self.capital_cost - self._episode_start_capital
        hold_due = (self.first_full_hedge_ns or now_ns) + self.cfg.hold_ns
        capital += (self.capital_base * self.cfg.capital_rate
                    * dec(max(0, hold_due - now_ns)) / YEAR_NS)
        denominator = qty * (1 - self.rh.maker_fee_bps / 10_000)
        if denominator <= 0:
            self._log("passive_target_abstain", now_ns, reason="invalid_maker_fee")
            return None
        required = (dec(self.cfg.take_profit_usd) - existing_cash + adjusted_hl
                    * (1 + self.hl.taker_fee_bps / 10_000) + reserve + capital) / denominator
        best_ask = rh_book.asks[0][0]
        price = self.rh.sell_limit_at_or_above(max(best_ask, required))
        ceiling = best_ask * (1 + Decimal("5") / 10_000)
        if price > ceiling:
            self._log("passive_target_abstain", now_ns,
                      reason="target_above_5bp_ask_cap", required_price=required,
                      capped_price=ceiling)
            return None
        return price

    def _maybe_request_passive(self, now_ns: int) -> None:
        if (not self._passive or self.passive_attempted or self.fallback_requested_ns is not None
                or self.first_full_hedge_ns is None or not self._entry_reconciled(now_ns)):
            return
        if now_ns >= self.first_full_hedge_ns + self.cfg.hold_ns:
            return
        if self.rh_pos <= 0 or self.hl_pos >= 0 or self.rh_pos != -self.hl_pos:
            return
        if not self._fresh_pair(now_ns):
            return
        rh_book, hl_book = self.books["rh"], self.books["hl"]
        qty = self.rh_pos
        self.passive_attempted = True
        if self.exit_policy.startswith("passive_best"):
            price = self.rh.sell_limit_at_or_above(rh_book.asks[0][0])
        else:
            price = self._target_price(now_ns, qty, rh_book, hl_book)
            if price is None:
                return
        if price <= rh_book.bids[0][0] or not self.rh.valid_order(qty, price):
            self._log("passive_exit_abstain", now_ns, reason="postonly_or_order_rule",
                      price=price, qty=qty)
            return
        self.passive_ask = PassiveAsk(self.episode_no, price, qty, now_ns,
                                      now_ns + self.cfg.maker_latency_ns, qty)
        self._log("passive_quote_requested", now_ns, price=price, qty=qty,
                  due_ns=self.passive_ask.activation_due_ns,
                  exit_policy=self.exit_policy)

    def _on_book(self, book: Book) -> None:
        # The parser/cache may share this immutable snapshot across branches.
        # Make a branch-local copy, then reserve depth across every intent
        # executed on this event and carry that depletion until a new book.
        book = Book(book.venue, book.received_ns, book.source_ns,
                    book.generation, list(book.bids), list(book.asks))
        super()._on_book(book)
        if not self._passive or self.unknown_reason:
            return
        now_ns = book.received_ns
        p = self.passive_ask
        if p is not None and book.venue == "rh":
            if (p.activated_ns is None and p.canceled_ns is None
                    and now_ns >= p.activation_due_ns):
                if book.source_ns < p.activation_due_ns:
                    self._log("passive_activation_stale_source", now_ns)
                elif p.cancel_due_ns is not None and book.source_ns >= p.cancel_due_ns:
                    p.canceled_ns = now_ns
                    self._log("passive_cancel_effective_without_snapshot", now_ns)
                elif p.price <= book.bids[0][0]:
                    p.canceled_ns = now_ns
                    self._log("passive_post_only_reject", now_ns)
                else:
                    p.activated_ns = now_ns
                    p.activated_source_ns = book.source_ns
                    p.generation = book.generation
                    p.ahead_better = sum((q for px, q in book.asks if px < p.price), D0)
                    p.ahead_same = sum((q for px, q in book.asks if px == p.price), D0)
                    self._log("passive_activated", now_ns, ahead_better=p.ahead_better,
                              ahead_same=p.ahead_same)
            if (p.cancel_due_ns is not None and p.canceled_ns is None
                    and now_ns >= p.cancel_due_ns):
                if book.source_ns >= p.cancel_due_ns:
                    p.canceled_ns = now_ns
                    self._log("passive_cancel_effective", now_ns,
                              reason=p.cancel_reason)
                else:
                    self._log("passive_cancel_stale_source", now_ns)
        if book.venue == "hl":
            for intent in list(self.passive_buys):
                if now_ns >= intent.due_ns and book.source_ns >= intent.due_ns:
                    self._fill_passive_buy(intent, book)
                    if self.unknown_reason:
                        return
        self._maybe_request_passive(now_ns)
        self._maybe_start_fallback(now_ns)
        self._close_episode_if_flat(now_ns)

    def _fill_passive_buy(self, intent: PassiveBuy, book: Book) -> Decimal:
        self.passive_buys.remove(intent)
        now_ns = book.received_ns
        qty = intent.qty
        if qty > -self.hl_pos:
            self._unknown("passive_buy_exceeds_short", now_ns)
            return D0
        limit = buy_limit_at_or_below(
            self.hl, intent.anchor_ask * (1 + self.cfg.hedge_limit_bps / 10_000))
        if not on_step(qty, self.hl.qty_step) or not self.hl.valid_order(qty, limit):
            self._unknown("passive_buy_lot_or_minimum_unresolved", now_ns)
            return D0
        filled, value = book.walk("buy", qty, limit=limit)
        filled = floor_step(filled, self.hl.qty_step)
        if filled > 0:
            filled, value = book.walk("buy", filled, limit=limit)
            if not self._valid_execution_slice("hl", filled, value):
                self._unknown("offlot_passive_buy_execution", now_ns)
                return D0
            self._apply_fill("hl", "buy", filled, value, now_ns)
            self._episode_passive_hl_buy_qty += filled
            self._episode_passive_hl_buy_value += value
            self._deplete(book, "buy", filled)
        self._log("passive_hl_buy_result", now_ns, requested=qty, filled=filled,
                  value=value, limit=limit)
        if filled != qty:
            self._start_exit(now_ns, "partial_or_zero_passive_hl_buy")
        return filled

    def _retired_flow_check(self, event: Mapping[str, Any]) -> bool:
        if event.get("side") != "buy":
            return False
        try:
            source = int(event.get("source_ns", 0))
            receipt = int(event.get("received_ns", event.get("receipt_ns")))
            price = dec(event.get("price", 0))
            qty = dec(event.get("qty", 0))
        except (TypeError, ValueError, ArithmeticError):
            self._unknown("retired_passive_trade_malformed", self.now_ns or 0)
            return True
        if source <= 0 or source > receipt or not event.get("clock_valid", True):
            self._unknown("retired_passive_trade_clock_invalid", receipt)
            return True
        trade_id = str(event.get("trade_id", event.get("id", "")))
        for old in self._retired_passive:
            if (old.remaining > 0 and old.activated_ns is not None
                    and old.cancel_due_ns is not None
                    and old.activation_due_ns <= source <= old.cancel_due_ns
                    and price >= old.price and qty > 0
                    and trade_id not in old.seen_ids):
                now_ns = receipt
                episode = next((row for row in reversed(self.episodes)
                                if row["number"] == old.episode_number), None)
                if episode is None:
                    self.truncated = True
                    self._unknown("retired_passive_episode_missing", now_ns)
                    return True
                episode["execution_unknown"] = True
                episode["execution_unknown_reason"] = "retired_passive_quote_late_flow"
                episode["late_retired_passive_flow"] = {
                    "trade_id": trade_id[:100], "receipt_ns": now_ns,
                    "source_ns": source, "price": str(price), "qty": str(qty),
                    "quote_price": str(old.price),
                    "quote_remaining": str(old.remaining),
                    "activation_due_ns": old.activation_due_ns,
                    "cancel_due_ns": old.cancel_due_ns,
                    "retired_ns": old.retired_ns,
                }
                self._unknown("retired_passive_quote_late_flow", now_ns)
                return True
        return False

    def _on_trade(self, event: Mapping[str, Any]) -> None:
        if self._passive and self._retired_flow_check(event):
            return
        super()._on_trade(event)
        if not self._passive or self.unknown_reason:
            return
        p = self.passive_ask
        if p is None or event.get("side") != "buy":
            return
        now_ns = int(event.get("received_ns", event.get("receipt_ns")))
        source_ns = int(event["source_ns"])
        price, qty = dec(event.get("price", 0)), dec(event.get("qty", 0))
        if source_ns > now_ns or not event.get("clock_valid", True) or price <= 0 or qty <= 0:
            self._unknown("passive_trade_clock_or_value_invalid", now_ns)
            return
        if now_ns - source_ns > self.cfg.max_book_age_ns:
            self._unknown("passive_trade_stale_source", now_ns)
            return
        if price < p.price or source_ns < p.activation_due_ns:
            return
        if p.activated_ns is None:
            if (p.canceled_ns is None
                    or (p.cancel_due_ns is not None and source_ns <= p.cancel_due_ns)
                    or (p.cancel_due_ns is None and source_ns <= p.canceled_ns)):
                self._unknown("passive_eligible_flow_before_activation_snapshot", now_ns)
            return
        if event.get("generation") != p.generation:
            self._unknown("passive_trade_generation_changed", now_ns)
            return
        if source_ns < (p.activated_source_ns or p.activation_due_ns):
            self._unknown("passive_eligible_flow_before_queue_snapshot", now_ns)
            return
        trade_id = str(event.get("trade_id", event.get("id", "")))
        if not trade_id:
            self._unknown("passive_missing_trade_id", now_ns)
            return
        if trade_id in p.seen_ids:
            return
        if len(p.seen_ids) >= MAX_EXIT_TRADE_IDS:
            self._unknown("passive_trade_id_cap", now_ns)
            return
        p.seen_ids.add(trade_id)
        if p.canceled_ns is not None:
            if p.cancel_due_ns is None or source_ns > p.cancel_due_ns:
                return
            if source_ns == p.cancel_due_ns:
                self._unknown("passive_cancel_fill_same_source_time", now_ns)
                return
            self._count("passive_late_pending_cancel_flow")
        if p.cancel_due_ns is not None and source_ns > p.cancel_due_ns:
            self._unknown("passive_trade_cancel_order_ambiguous", now_ns)
            return
        if price > p.price:
            self._count("passive_trade_through")
        else:
            self._count("passive_equal_price_touch")
        # A print at/above our ask implies traversal of better asks. Attribute
        # only after consuming the entire observed same-price queue ahead.
        remaining = qty
        same = min(remaining, p.ahead_same)
        p.ahead_same -= same
        remaining -= same
        if remaining <= 0 or p.remaining <= 0:
            return
        take = min(remaining, p.remaining)
        if p.increments >= self.cfg.max_increments:
            self._unknown("passive_increment_cap", now_ns)
            return
        if (not on_step(take, self.rh.qty_step) or
                not self._valid_execution_slice("rh", take, take * p.price)):
            self._unknown("passive_offlot_increment_unresolved", now_ns)
            return
        if take > self.rh_pos:
            self._unknown("passive_sell_exceeds_rh_inventory", now_ns)
            return
        p.increments += 1
        p.remaining -= take
        p.maker_attributed += take
        self._apply_fill("rh", "sell", take, take * p.price, now_ns, maker=True)
        self._episode_passive_rh_exit_value += take * p.price
        self._log("passive_maker_sell_increment", now_ns, qty=take,
                  remaining=p.remaining, trade_id=trade_id)
        self._request_passive_cancel(now_ns, "first_passive_sell_flow")
        hl_book = self.books.get("hl")
        if hl_book is None or not self._fresh_pair(now_ns):
            self._unknown("passive_hl_buy_anchor_missing", now_ns)
            return
        found, value = hl_book.walk("buy", take)
        if found != take:
            self._unknown("passive_hl_buy_anchor_shallow", now_ns)
            return
        if not self.hl.valid_order(take, hl_book.asks[0][0]):
            self._unknown("passive_hl_buy_anchor_minimum", now_ns)
            return
        self.passive_buys.append(PassiveBuy(take, now_ns + self.cfg.hl_ioc_latency_ns,
                                            now_ns + self.cfg.intent_timeout_ns,
                                            value / take, now_ns))
        self._log("passive_hl_buy_scheduled", now_ns, qty=take,
                  due_ns=now_ns + self.cfg.hl_ioc_latency_ns,
                  anchor_ask=value / take)

    def _close_episode_if_flat(self, now_ns: int) -> None:
        if self._passive:
            p = self.passive_ask
            if p is not None:
                if p.remaining == 0 and p.cancel_due_ns is None and p.canceled_ns is None:
                    self._request_passive_cancel(now_ns, "full_passive_sell")
                if not self._passive_reconciled(now_ns):
                    return
            if self.passive_buys:
                return
        previous_count = len(self.episodes)
        q, p = self.quote, self.passive_ask
        first_hedge = self.first_full_hedge_ns
        fallback = self.fallback_requested_ns
        cohort = self.cohort_id
        rh_entry = self._episode_rh_entries
        hl_entry = self._episode_hl_entries
        hl_entry_qty = self._episode_hl_entry_qty
        passive_rh_value = self._episode_passive_rh_exit_value
        passive_hl_value = self._episode_passive_hl_buy_value
        passive_hl_qty = self._episode_passive_hl_buy_qty
        taker_rh_value = self._episode_taker_rh_exit_value
        taker_rh_qty = self._episode_taker_rh_exit_qty
        taker_hl_value = self._episode_taker_hl_exit_value
        taker_hl_qty = self._episode_taker_hl_exit_qty
        fees_rh = self.fees_rh - self._episode_start_fees_rh
        fees_hl = self.fees_hl - self._episode_start_fees_hl
        if (p is not None and p.activated_ns is not None and p.remaining > 0
                and len(self._retired_passive) >= self.cfg.max_episodes):
            self.truncated = True
            self._unknown("passive_tombstone_cap", now_ns)
            return
        super()._close_episode_if_flat(now_ns)
        if len(self.episodes) == previous_count:
            return
        episode = self.episodes[-1]
        episode.update({
            "cohort_id": cohort,
            "entry_quote_price": None if q is None else str(q.price),
            "entry_quote_qty": None if q is None else str(q.qty),
            "entry_maker_qty": None if q is None else str(q.maker_attributed),
            "entry_rh_notional": str(rh_entry),
            "entry_hl_notional": str(hl_entry),
            "entry_hl_qty": str(hl_entry_qty),
            "entry_rh_fee": str(rh_entry * self.rh.maker_fee_bps / 10_000),
            "entry_hl_fee": str(hl_entry * self.hl.taker_fee_bps / 10_000),
            "actual_fees_rh": str(fees_rh),
            "actual_fees_hl": str(fees_hl),
            "first_full_hedge_ns": first_hedge,
            "passive_exit_quote_price": None if p is None else str(p.price),
            "passive_exit_quote_qty": None if p is None else str(p.qty),
            "passive_exit_maker_qty": None if p is None else str(p.maker_attributed),
            "passive_exit_maker_notional": str(passive_rh_value),
            "passive_exit_maker_fee": str(passive_rh_value * self.rh.maker_fee_bps / 10_000),
            "contingent_hl_buy_qty": str(passive_hl_qty),
            "contingent_hl_buy_notional": str(passive_hl_value),
            "contingent_hl_buy_fee": str(passive_hl_value * self.hl.taker_fee_bps / 10_000),
            "taker_fallback_rh_qty": str(taker_rh_qty),
            "taker_fallback_rh_notional": str(taker_rh_value),
            "taker_fallback_hl_qty": str(taker_hl_qty),
            "taker_fallback_hl_notional": str(taker_hl_value),
            "fallback_requested_ns": fallback,
            "fee_only_net": episode["cash_known"] if not episode["funding_unknown"] else None,
            "stressed_net": None if episode["funding_unknown"] else str(
                dec(episode["cash_known"]) - dec(episode["reserve_cost"])
                - dec(episode["capital_cost"])),
        })
        if p is not None and p.activated_ns is not None and p.remaining > 0:
            p.retired_ns = now_ns
            self._retired_passive.append(p)
            if len(self._retired_passive) > self.cfg.max_episodes:
                self._unknown("passive_tombstone_cap", now_ns)
        self.passive_ask = None
        self.passive_buys.clear()
        self.passive_attempted = False
        self.fallback_requested_ns = None
        self.fallback_reason = None
        self.cohort_id = None
        self._episode_hl_entry_qty = D0
        self._episode_start_fees_rh = self._episode_start_fees_hl = D0
        self._episode_passive_rh_exit_value = D0
        self._episode_passive_hl_buy_value = self._episode_passive_hl_buy_qty = D0
        self._episode_taker_rh_exit_value = self._episode_taker_rh_exit_qty = D0
        self._episode_taker_hl_exit_value = self._episode_taker_hl_exit_qty = D0

    def process(self, event: Mapping[str, Any], quote_diag: Mapping[str, Any] | None = None) -> None:
        if event.get("type", event.get("kind")) == "end":
            if self.passive_ask or self.passive_buys or self.fallback_requested_ns is not None:
                self._unknown("capture_end_with_passive_obligation", self.now_ns or 0)
        super().process(event, quote_diag)

    def summary(self) -> dict[str, Any]:
        out = super().summary()
        complete = out["complete_net"]
        passive_open = (self.passive_ask is not None or bool(self.passive_buys)
                        or self.fallback_requested_ns is not None)
        if passive_open:
            complete = None
        fee_only = (str(self.cash_rh + self.cash_hl)
                    if complete is not None else None)
        out.update({
            "exit_policy": self.exit_policy,
            "exit_adverse_bps": None if self.exit_adverse_bps is None else str(self.exit_adverse_bps),
            "cohort_id_active": self.cohort_id,
            "passive_quote_open": self.passive_ask is not None,
            "passive_buy_intents_open": len(self.passive_buys),
            "fallback_pending": self.fallback_requested_ns is not None,
            "retired_passive_quote_guard_count": len(self._retired_passive),
            "fee_only_complete_net": fee_only,
            "stressed_complete_net": complete,
            "complete_net": complete,
            "fee_only_note": "Known flat synthetic cash after four actual-notional venue fees; excludes conversion, financing, and the separate 5 bp reserve.",
            "stressed_note": "Fee-only cash less 5 bp reserve and modeled 5% annual capital charge; undefined when funding, execution, or quote obligations are unknown.",
        })
        return out
