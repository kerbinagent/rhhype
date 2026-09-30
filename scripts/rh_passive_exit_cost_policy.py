"""Prospective passive target quote selection with a separate reserve allowance.

This module does not alter the frozen passive-exit engine. ``quote_reserve_bps``
changes only the requested RH target ask. The inherited cash, actual fees,
5 bp reported reserve, capital charge, queue, cancel, and fallback mechanics
remain unchanged. No live orders or private data are used.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Mapping

from scripts.rh_maker_engine import Book, Config, YEAR_NS, dec
from scripts.rh_passive_exit_engine import PassiveExitBranch


def required_target_ask(*, qty: Decimal, target_usd: Decimal,
                        existing_cash: Decimal, hl_buy_value: Decimal,
                        adverse_bps: Decimal, hl_taker_fee_bps: Decimal,
                        rh_maker_fee_bps: Decimal, quote_reserve_usd: Decimal,
                        capital_usd: Decimal) -> Decimal:
    """Pure algebra for the minimum RH maker-sell price per base unit.

    The projected HL buy value includes frozen adverse allowance and its
    actual-notional taker fee. The RH maker fee applies to the requested ask.
    This is a conditional quote-selection hurdle, not a realized P&L estimate.
    """
    qty = dec(qty)
    target_usd = dec(target_usd)
    existing_cash = dec(existing_cash)
    hl_buy_value = dec(hl_buy_value)
    adverse_bps = dec(adverse_bps)
    hl_taker_fee_bps = dec(hl_taker_fee_bps)
    rh_maker_fee_bps = dec(rh_maker_fee_bps)
    quote_reserve_usd = dec(quote_reserve_usd)
    capital_usd = dec(capital_usd)
    if (qty <= 0 or hl_buy_value <= 0 or target_usd < 0 or adverse_bps < 0
            or hl_taker_fee_bps < 0 or not 0 <= rh_maker_fee_bps < 10_000
            or quote_reserve_usd < 0 or capital_usd < 0):
        raise ValueError("invalid target quote inputs")
    adjusted_hl = hl_buy_value * (1 + adverse_bps / 10_000)
    return (target_usd - existing_cash
            + adjusted_hl * (1 + hl_taker_fee_bps / 10_000)
            + quote_reserve_usd + capital_usd) / (qty * (1 - rh_maker_fee_bps / 10_000))


class CostPolicyPassiveExitBranch(PassiveExitBranch):
    """Prospective 0/5 bp quote hurdle variant; inherited ledger stays 5 bp."""

    def __init__(self, config: Config, metadata: Mapping[str, Mapping[str, Any]],
                 *, exit_policy: str, quote_reserve_bps: Decimal,
                 exit_adverse_bps: Decimal | None = None,
                 audit_sink: Callable[[dict[str, Any]], None] | None = None):
        chosen = dec(quote_reserve_bps)
        if chosen not in {Decimal("0"), Decimal("5")}:
            raise ValueError("quote_reserve_bps must be 0 or 5")
        if dec(config.reserve_bps) != Decimal("5"):
            raise ValueError("reported ledger reserve must remain 5 bp")
        self.quote_reserve_bps = chosen
        super().__init__(config, metadata, exit_policy=exit_policy,
                         exit_adverse_bps=exit_adverse_bps, audit_sink=audit_sink)

    def _target_price(self, now_ns: int, qty: Decimal,
                      rh_book: Book, hl_book: Book) -> Decimal | None:
        # Delegate the 5 bp arm byte-for-byte to the frozen selection code.
        if self.quote_reserve_bps == Decimal("5"):
            return super()._target_price(now_ns, qty, rh_book, hl_book)
        if self.exit_adverse_bps is None:
            self._log("passive_target_abstain", now_ns, reason="missing_frozen_adverse_bps")
            return None
        found, hl_value = hl_book.walk("buy", qty)
        if found != qty:
            self._log("passive_target_abstain", now_ns, reason="shallow_hl_buy_mark")
            return None
        capital = self.capital_cost - self._episode_start_capital
        hold_due = (self.first_full_hedge_ns or now_ns) + self.cfg.hold_ns
        capital += (self.capital_base * self.cfg.capital_rate
                    * dec(max(0, hold_due - now_ns)) / YEAR_NS)
        reserve = max(self._episode_rh_entries, self._episode_hl_entries) * self.quote_reserve_bps / 10_000
        required = required_target_ask(
            qty=qty, target_usd=dec(self.cfg.take_profit_usd),
            existing_cash=self.cash_rh + self.cash_hl - self._episode_start_cash,
            hl_buy_value=hl_value, adverse_bps=self.exit_adverse_bps,
            hl_taker_fee_bps=self.hl.taker_fee_bps,
            rh_maker_fee_bps=self.rh.maker_fee_bps,
            quote_reserve_usd=reserve, capital_usd=capital,
        )
        best_ask = rh_book.asks[0][0]
        price = self.rh.sell_limit_at_or_above(max(best_ask, required))
        ceiling = best_ask * (1 + Decimal("5") / 10_000)
        if price > ceiling:
            self._log("passive_target_abstain", now_ns,
                      reason="target_above_5bp_ask_cap", required_price=required,
                      capped_price=ceiling)
            return None
        return price

    def summary(self) -> dict[str, Any]:
        out = super().summary()
        out["quote_reserve_bps"] = str(self.quote_reserve_bps)
        out["reported_stress_reserve_bps"] = str(self.cfg.reserve_bps)
        out["quote_reserve_note"] = (
            "Selection-only allowance; complete/stressed cash and 5 bp reported "
            "reserve are inherited unchanged. A 0 bp selected quote can still "
            "miss the stressed $0.10 target.")
        return out
