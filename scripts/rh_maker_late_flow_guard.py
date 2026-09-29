"""Future-study guard for delayed RH trade reports after quote retirement.

The existing maker-bid pilot stays frozen. These subclasses retain bounded
evidence for canceled quotes with unfilled remainder. A qualifying public
trade whose source time belongs to a retired quote's active interval makes
that old episode's execution unknown, regardless of any newer quote state.
No inventory or cash is fabricated from the delayed print.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from scripts.rh_maker_engine import MakerBranch, Quote, dec, venue_key
from scripts.rh_maker_sell_engine import MakerSellBranch


@dataclass(frozen=True)
class RetiredQuote:
    episode_number: int
    side: str
    price: Decimal
    remaining: Decimal
    activation_due_ns: int
    activated_source_ns: int
    cancel_due_ns: int
    generation: Any
    retired_ns: int


class LateFlowGuardMixin:
    """Retain one bounded tombstone per retired activated partial quote."""

    guard_flow_side: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retired_quotes: list[RetiredQuote] = []
        self.late_retired_flow_count = 0

    def _close_episode_if_flat(self, now_ns: int) -> None:
        q: Quote | None = self.quote
        candidate = (q is not None and q.activated_ns is not None
                     and q.canceled_ns is not None and q.cancel_due_ns is not None
                     and q.remaining > 0)
        retiring = (candidate and not self.hedges and not self.exits
                    and self.rh_pos == 0 and self.hl_pos == 0
                    and now_ns >= q.cancel_due_ns + self.cfg.max_book_age_ns)
        if retiring and len(self.retired_quotes) >= self.cfg.max_episodes:
            self.truncated = True
            self._unknown("retired_quote_guard_cap", now_ns)
            return  # Keep the quote and obligation rather than dropping evidence.
        super()._close_episode_if_flat(now_ns)
        if not candidate or self.quote is not None:
            return
        assert q is not None and q.cancel_due_ns is not None
        assert q.activated_source_ns is not None
        tombstone = RetiredQuote(
            episode_number=self.episode_no, side=self.guard_flow_side,
            price=q.price, remaining=q.remaining,
            activation_due_ns=q.activation_due_ns,
            activated_source_ns=q.activated_source_ns,
            cancel_due_ns=q.cancel_due_ns, generation=q.generation,
            retired_ns=now_ns,
        )
        self.retired_quotes.append(tombstone)
        self._log("retired_quote_guarded", now_ns,
                  episode_number=tombstone.episode_number,
                  side=tombstone.side, price=tombstone.price,
                  remaining=tombstone.remaining,
                  activation_due_ns=tombstone.activation_due_ns,
                  cancel_due_ns=tombstone.cancel_due_ns,
                  generation=tombstone.generation)

    def _late_retired_match(self, event: Mapping[str, Any]) -> RetiredQuote | None:
        if event.get("type", event.get("kind")) != "trade":
            return None
        if venue_key(event.get("venue")) != "rh" or event.get("asset") != self.cfg.asset:
            return None
        if event.get("side") != self.guard_flow_side:
            return None
        try:
            source = int(event["source_ns"])
            receipt = int(event.get("received_ns", event.get("receipt_ns")))
            price = dec(event["price"])
            quantity = dec(event["qty"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None  # The validated event adapter owns malformed-row invalidation.
        if source <= 0 or source > receipt or quantity <= 0 or price <= 0:
            return None
        for old in reversed(self.retired_quotes):
            if (receipt > old.retired_ns
                    and old.activation_due_ns <= source <= old.cancel_due_ns
                    and ((old.side == "sell" and price <= old.price)
                         or (old.side == "buy" and price >= old.price))):
                return old
        return None

    def process(self, event: Mapping[str, Any], quote_diag: Mapping[str, Any] | None = None) -> None:
        old = self._late_retired_match(event)
        if old is None:
            super().process(event, quote_diag=quote_diag)
            return
        now_ns = int(event.get("received_ns", event.get("receipt_ns")))
        episode = next((row for row in reversed(self.episodes)
                        if row["number"] == old.episode_number), None)
        if episode is None:
            self.truncated = True
            self._unknown("retired_quote_episode_missing", now_ns)
            return
        if not episode.get("execution_unknown"):
            generation_changed = event.get("generation") != old.generation
            reason = ("late_retired_quote_flow_generation_ambiguous"
                      if generation_changed else "late_retired_quote_flow")
            evidence = {
                "trade_id": str(event.get("trade_id", event.get("id", "")))[:100],
                "receipt_ns": now_ns,
                "source_ns": int(event["source_ns"]),
                "price": str(dec(event["price"])),
                "quantity": str(dec(event["qty"])),
                "generation": str(event.get("generation"))[:100],
                "quote_generation": str(old.generation)[:100],
                "quote_price": str(old.price),
                "quote_remaining": str(old.remaining),
                "activation_due_ns": old.activation_due_ns,
                "cancel_due_ns": old.cancel_due_ns,
                "retired_ns": old.retired_ns,
            }
            episode["execution_unknown"] = True
            episode["execution_unknown_reason"] = reason
            episode["late_retired_flow"] = evidence
            self.late_retired_flow_count += 1
            self._log("late_retired_quote_flow", now_ns,
                      episode_number=old.episode_number,
                      trade_id=evidence["trade_id"],
                      trade_source_ns=evidence["source_ns"],
                      trade_price=evidence["price"],
                      trade_quantity=evidence["quantity"],
                      quote_price=old.price,
                      quote_remaining=old.remaining,
                      cancel_due_ns=old.cancel_due_ns,
                      quote_generation=evidence["quote_generation"],
                      trade_generation=evidence["generation"],
                      reason=reason)
            self._unknown(reason, now_ns)
        # Do not apply a hypothetical fill after the old episode was finalized.

    def summary(self) -> dict[str, Any]:
        result = super().summary()
        result["retired_quote_guard_count"] = len(self.retired_quotes)
        result["late_retired_flow_count"] = self.late_retired_flow_count
        result["execution_unknown_episodes"] = sum(
            bool(row.get("execution_unknown")) for row in self.episodes)
        return result


class GuardedMakerBuyBranch(LateFlowGuardMixin, MakerBranch):
    guard_flow_side = "sell"


class GuardedMakerSellBranch(LateFlowGuardMixin, MakerSellBranch):
    guard_flow_side = "buy"
