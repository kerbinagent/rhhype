"""Separate correction for a frozen passive-v1 entry retirement boundary.

This class does not change ACK, queue, fill, price, or economic assumptions.
It marks previously finalized execution unknown when qualifying delayed entry
flow arrives on the callback that retires the entry quote. The original v1
class and its protocol remain untouched; corrected replay requires a distinct
study label. No trading endpoint or public capture is accessed here.
"""

from __future__ import annotations

from typing import Any, Mapping

from scripts.core_passive_hedged_base import dec, venue_key
from scripts.core_passive_hedged_late_flow import RetiredQuote
from scripts.core_passive_hedged_exit import PassiveExitBranch


class RetirementGuardPassiveExitBranch(PassiveExitBranch):
    """Preserve parent economics and include receipt == entry retirement."""

    def _late_retired_match(self, event: Mapping[str, Any]) -> RetiredQuote | None:
        old = super()._late_retired_match(event)
        if old is not None:
            return old
        if (event.get("type", event.get("kind")) != "trade"
                or venue_key(event.get("venue")) != "maker"
                or event.get("asset") != self.cfg.asset
                or event.get("side") != self.guard_flow_side):
            return None
        try:
            receipt = int(event.get("received_ns", event.get("receipt_ns")))
            source = int(event["source_ns"])
            price, quantity = dec(event["price"]), dec(event["qty"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return None
        if source <= 0 or source > receipt or quantity <= 0 or price <= 0:
            return None
        for old in reversed(self.retired_quotes):
            if (receipt == old.retired_ns
                    and old.activation_due_ns <= source <= old.cancel_due_ns
                    and price <= old.price):
                return old
        return None

    def process(self, event: Mapping[str, Any],
                quote_diag: Mapping[str, Any] | None = None) -> None:
        # The inherited guard checks before tick. This second check sees a
        # tombstone created inside this same callback, including the endpoint.
        # Reenter only when the parent guard will consume the event without
        # tick, attribution, or diagnostic processing; never replay economics.
        super().process(event, quote_diag)
        # A retention/audit cap can set a branch unknown during retirement;
        # that must not leave this finalized episode falsely known. The
        # parent guard can mark the episode even when a prior reason exists.
        if self._late_retired_match(event) is not None:
            super().process(event, quote_diag)

    def summary(self) -> dict[str, Any]:
        out = super().summary()
        out["retirement_guard_revision"] = "entry-same-receipt-v1"
        out["frozen_v1_result"] = False
        return out
