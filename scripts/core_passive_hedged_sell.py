"""Read-only RH maker ask and contingent Core taker buy paper branch.

The branch shares market validation, timers, cash accounting, and exit intent
handling with the frozen maker-bid engine. Directional book, queue, hedge, and
mark decisions live here; no live orders or private fills are represented.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Mapping

from scripts.core_passive_hedged_base import (Book, Config, D0, MakerBranch, Quote, Rules,
                                     dec, floor_step)


@dataclass
class BuyHedgeIntent:
    qty: Decimal
    due_ns: int
    timeout_ns: int
    anchor_ask: Decimal
    flow_receipt_ns: int


def buy_limit_at_or_below(rules: Rules, upper_bound: Decimal) -> Decimal:
    """Round an Core buy IOC cap toward a stricter, never higher, valid price."""
    if upper_bound <= 0:
        raise ValueError("nonpositive buy limit")
    if rules.price_tick_semantics == "hedge_perp":
        assert rules.sz_decimals is not None
        step = max(Decimal(10) ** (upper_bound.adjusted() - 4),
                   Decimal(10) ** -(6 - rules.sz_decimals))
        if upper_bound >= 100_000:
            step = Decimal(1)
    else:
        assert rules.price_tick is not None
        step = rules.price_tick
    candidate = floor_step(upper_bound, step)
    for _ in range(12):
        if candidate > 0 and candidate <= upper_bound and rules.valid_price(candidate):
            return candidate
        candidate -= step
    raise ValueError("cannot form valid buy limit")


class MakerSellBranch(MakerBranch):
    """One independent RH-short / Core-long public-flow counterfactual ledger."""

    def _episode_executable_exit_mark(self, now_ns: int) -> Decimal | None:
        if not self._fresh_pair(now_ns):
            return None
        if self.maker_pos >= 0 or self.hedge_pos <= 0 or -self.maker_pos != self.hedge_pos:
            return None
        maker_book, hedge_book = self.books["maker"], self.books["hedge"]
        qty = self.hedge_pos
        if (not self.maker.valid_order(qty, maker_book.asks[0][0])
                or not self.hedge.valid_order(qty, hedge_book.bids[0][0])):
            return None
        maker_filled, maker_cost = maker_book.walk("buy", qty)
        hedge_filled, hedge_proceeds = hedge_book.walk("sell", qty)
        if maker_filled != qty or hedge_filled != qty:
            return None
        cash = self.cash_maker + self.cash_hedge - self._episode_start_cash
        exit_fees = (maker_cost * self.maker.taker_fee_bps
                     + hedge_proceeds * self.hedge.taker_fee_bps) / 10_000
        return (cash - maker_cost + hedge_proceeds - exit_fees
                - (self.reserve_cost - self._episode_start_reserve)
                - (self.capital_cost - self._episode_start_capital))

    def _on_book(self, book: Book) -> None:
        now_ns = book.received_ns
        if now_ns - book.source_ns > self.cfg.max_book_age_ns:
            self._log("stale_source_book", now_ns, venue=book.venue)
            if self.quote or self.maker_pos != 0 or self.hedge_pos != 0:
                self._unknown("stale_source_during_obligation", now_ns)
            return
        previous = self.books.get(book.venue)
        if (previous is not None and previous.generation != book.generation
                and (self.quote or self.maker_pos != 0 or self.hedge_pos != 0)):
            self._unknown("book_generation_changed_during_obligation", now_ns)
            return
        self.books[book.venue] = book
        q = self.quote
        if q and book.venue == "maker":
            if q.activated_ns is None and now_ns >= q.activation_due_ns:
                if book.source_ns < q.activation_due_ns:
                    self._log("activation_stale_source", now_ns)
                elif q.price <= book.bids[0][0]:
                    q.canceled_ns = now_ns
                    self._log("post_only_reject", now_ns)
                else:
                    q.activated_ns = now_ns
                    q.activated_source_ns = book.source_ns
                    q.generation = book.generation
                    q.ahead_same = sum((size for price, size in book.asks if price == q.price), D0)
                    self._log("activated", now_ns, ahead_same=q.ahead_same)
            if q.cancel_due_ns is not None and q.canceled_ns is None and now_ns >= q.cancel_due_ns:
                if book.source_ns >= q.cancel_due_ns:
                    q.canceled_ns = now_ns
                    self._log("cancel_effective", now_ns, reason=q.cancel_reason)
                else:
                    self._log("cancel_stale_source", now_ns)
        if book.venue == "hedge":
            for intent in list(self.hedges):
                if now_ns >= intent.due_ns and book.source_ns >= intent.due_ns:
                    self._fill_hedge(intent, book)
                    if self.unknown_reason:
                        return
            self._fill_exit("hedge", book)
        else:
            self._fill_exit("maker", book)
        if self.unknown_reason:
            return
        if (self.first_full_hedge_ns is not None and self.exit_requested_ns is None
                and not self.hedges):
            mark = self._episode_executable_exit_mark(now_ns)
            if mark is not None and mark >= self.cfg.take_profit_usd:
                self._log("take_profit_mark", now_ns, projected_net=mark)
                self._start_exit(now_ns, "take_profit_mark")
        self._close_episode_if_flat(now_ns)

    def _fill_hedge(self, intent: BuyHedgeIntent, book: Book) -> None:
        now_ns = book.received_ns
        self.hedges.remove(intent)
        limit = buy_limit_at_or_below(
            self.hedge, intent.anchor_ask * (1 + self.cfg.hedge_limit_bps / 10_000))
        desired = floor_step(intent.qty, self.hedge.qty_step)
        if desired <= 0 or not self.hedge.valid_order(desired, limit):
            self._log("hedge_lot_or_min_reject", now_ns, desired=desired,
                      original=intent.qty)
            self._start_exit(now_ns, "hedge_lot_or_min_reject")
            return
        filled, value = book.walk("buy", desired, limit=limit)
        filled = floor_step(filled, self.hedge.qty_step)
        if filled > 0:
            filled, value = book.walk("buy", filled, limit=limit)
        if filled > 0 and not self._valid_execution_slice("hedge", filled, value):
            self._unknown("offlot_hedge_execution", now_ns)
            return
        if filled > 0:
            self._apply_fill("hedge", "buy", filled, value, now_ns)
            self._episode_hedge_entries += value
            self._refresh_reserve()
        self._log("hedge_result", now_ns, requested=intent.qty,
                  filled=filled, limit=limit)
        if filled != intent.qty:
            self._start_exit(now_ns, "partial_or_zero_hedge")
        elif self.first_full_hedge_ns is None:
            self.first_full_hedge_ns = now_ns
            self._log("first_full_hedge", now_ns,
                      hold_due_ns=now_ns + self.cfg.hold_ns)
        if self.exit_requested_ns is not None:
            self._start_exit(now_ns, "late_hedge_after_exit_request")

    def _on_trade(self, event: Mapping[str, Any]) -> None:
        q = self.quote
        now_ns = int(event.get("received_ns", event.get("receipt_ns")))
        if q is None or q.activated_ns is None:
            if (q is not None and q.canceled_ns is None and event.get("side") == "buy"
                    and dec(event.get("price", 0)) >= q.price
                    and int(event.get("source_ns", 0)) >= q.activation_due_ns):
                self._unknown("eligible_flow_before_activation_book", now_ns)
            return
        source_ns = int(event["source_ns"])
        if source_ns > now_ns or not event.get("clock_valid", True):
            self._unknown("trade_clock_invalid", now_ns)
            return
        if now_ns - source_ns > self.cfg.max_book_age_ns:
            self._unknown("stale_trade_source_during_queue", now_ns)
            return
        if event.get("generation") != q.generation:
            self._unknown("trade_generation_changed", now_ns)
            return
        if source_ns < q.activation_due_ns:
            return
        if source_ns < (q.activated_source_ns or q.activation_due_ns):
            if event.get("side") == "buy" and dec(event.get("price", 0)) >= q.price:
                self._unknown("eligible_flow_before_queue_snapshot", now_ns)
            return
        if now_ns < q.activated_ns:
            return
        trade_id = str(event.get("trade_id", event.get("id", "")))
        if not trade_id:
            self._unknown("missing_trade_id", now_ns)
            return
        if trade_id in self.seen_trades:
            return
        self.seen_trades.add(trade_id)
        if event.get("side") != "buy":
            return
        price, size = dec(event["price"]), dec(event["qty"])
        if price <= 0 or size <= 0:
            self._unknown("invalid_trade_value", now_ns)
            return
        if price < q.price:
            return  # A buy matched below our ask cannot consume our queue.
        if q.canceled_ns is not None:
            if q.cancel_due_ns is None or source_ns > q.cancel_due_ns:
                return
            if source_ns == q.cancel_due_ns:
                self._unknown("cancel_fill_same_source_time", now_ns)
                return
            self._count("late_pending_cancel_flow")
        if q.cancel_due_ns is not None and source_ns > q.cancel_due_ns:
            self._unknown("trade_cancel_order_ambiguous", now_ns)
            return
        q.touched = True
        self._count("touch")
        if price > q.price:
            q.through = True
            self._count("trade_through")
        else:
            self._count("equal_price_touch")
        consumed = min(q.ahead_same, size)
        q.ahead_same -= consumed
        eligible = size - consumed
        if eligible <= 0 or q.remaining <= 0:
            return
        attributed = min(eligible, q.remaining)
        if q.increments >= self.cfg.max_increments:
            self.truncated = True
            self._unknown("increment_cap", now_ns)
            return
        q.increments += 1
        q.remaining -= attributed
        q.maker_attributed += attributed
        self._apply_fill("maker", "sell", attributed, attributed * q.price,
                         now_ns, maker=True)
        self._episode_maker_entries += attributed * q.price
        self._refresh_reserve()
        self._log("maker_increment", now_ns, qty=attributed,
                  remaining=q.remaining, trade_id=trade_id)
        self._request_cancel(now_ns, "first_maker_flow")
        hedge_book = self.books.get("hedge")
        if hedge_book is None or not self._fresh_pair(now_ns):
            self._log("hedge_anchor_missing", now_ns, qty=attributed)
            self._start_exit(now_ns, "hedge_anchor_missing")
            return
        found, value = hedge_book.walk("buy", attributed)
        if found < attributed:
            self._log("hedge_anchor_shallow", now_ns, qty=attributed)
            self._start_exit(now_ns, "hedge_anchor_shallow")
            return
        anchor = value / found
        self.hedges.append(BuyHedgeIntent(
            attributed, now_ns + self.cfg.hedge_ioc_latency_ns,
            now_ns + self.cfg.intent_timeout_ns, anchor, now_ns))
        self._log("hedge_scheduled", now_ns,
                  due_ns=now_ns + self.cfg.hedge_ioc_latency_ns,
                  qty=attributed, anchor_ask=anchor)

    def _on_diagnostic(self, diag: Mapping[str, Any], now_ns: int) -> None:
        q = self.quote
        if self.unknown_reason:
            return
        if q is None:
            if self.maker_pos != 0 or self.hedge_pos != 0 or self.hedges or self.exits:
                return
            self._count("decision_opportunity")
            if not self._fresh_pair(now_ns):
                self._log("abstain", now_ns, reason="stale_or_skewed_pair")
                return
            if diag.get("reason") != "quote" or diag.get("price") is None:
                self._log("abstain", now_ns, reason=diag.get("reason", "no_quote"))
                return
            price, qty = dec(diag["price"]), dec(diag["quantity"])
            maker_book, hedge_book = self.books["maker"], self.books["hedge"]
            if (qty * price > dec(self.cfg.budget_usd)
                    or not self.maker.valid_order(qty, price)
                    or not self.hedge.valid_order(qty, hedge_book.asks[0][0])):
                self._log("abstain", now_ns, reason="lot_min_budget_or_grid")
                return
            found, hedge_entry_value = hedge_book.walk("buy", qty)
            if found < qty:
                self._log("abstain", now_ns, reason="hedge_depth")
                return
            if (2 * dec(self.cfg.budget_usd) + self.cash_maker < qty * price
                    or 2 * dec(self.cfg.budget_usd) + self.cash_hedge < hedge_entry_value):
                self._log("abstain", now_ns, reason="venue_prefund_capacity")
                return
            if price <= maker_book.bids[0][0]:
                self._log("abstain", now_ns, reason="post_only_cross")
                return
            self.episode_no += 1
            self._episode_start_cash = self.cash_maker + self.cash_hedge
            self._episode_start_capital = self.capital_cost
            self._episode_start_reserve = self.reserve_cost
            self.quote = Quote(price, qty, now_ns,
                               now_ns + self.cfg.maker_latency_ns, remaining=qty)
            self.capital_base = D0
            classification = ("inside" if price < maker_book.asks[0][0] else
                              "join" if price == maker_book.asks[0][0] else "behind")
            self._log("quote_requested", now_ns, price=price, qty=qty,
                      competitiveness=classification,
                      due_ns=self.quote.activation_due_ns)
            return
        if q.canceled_ns is not None or q.cancel_due_ns is not None or q.activated_ns is None:
            return
        if not self._fresh_pair(now_ns):
            self._request_cancel(now_ns, "invalid_pair")
            return
        current_maker, current_hedge = self.books["maker"], self.books["hedge"]
        found, _ = current_hedge.walk("buy", q.remaining)
        if found < q.remaining:
            self._request_cancel(now_ns, "hedge_depth_gone")
            return
        if self.cfg.policy == "fixed_best":
            if current_maker.asks[0][0] != q.price:
                self._request_cancel(now_ns, "best_ask_changed")
            return
        if diag.get("reason") != "quote" or diag.get("price") is None or dec(diag["price"]) != q.price:
            self._request_cancel(now_ns, "model_reprice_or_threshold")

    def summary(self) -> dict[str, Any]:
        result = super().summary()
        result["direction"] = "maker_maker_sell_hedge_taker_buy"
        return result
