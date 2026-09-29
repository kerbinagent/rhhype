"""Durable, compact exit-request diagnostics for the unfrozen paper monitor.

This subclass observes the first exit-intent request without changing the
base engine's timers, orders, fills, books, or accounting. A restored retry
cannot manufacture an observation at the earlier request time.
"""

from __future__ import annotations

import math

from monitor import walk
from paper_engine import PaperEngine, scenario_fee, valid_book


class ObservedPaperEngine(PaperEngine):
    def _exit_intent(self, p, leg, now):
        if "exit_request_observation" not in p:
            try:
                p["exit_request_observation"] = self._exit_request_observation(p, now)
            except Exception as exc:  # Diagnostics must not change order scheduling.
                p["exit_request_observation"] = {
                    "version": 1, "capture_type": "request_evidence_unavailable",
                    "requested_at": p.get("exit_requested_at"), "captured_at": now,
                    "exit_reason": p.get("exit_reason"),
                    "unavailable_reason": "diagnostic_error",
                    "diagnostic_error_type": type(exc).__name__,
                    "closing_price_status": "unavailable",
                    "requested_closing_liability_usd": None,
                    "mark_status": "unavailable", "net_liquidation_pnl_usd": None,
                    "legs": [],
                }
        return super()._exit_intent(p, leg, now)

    def _exit_request_observation(self, p, now):
        reason = p.get("exit_reason")
        requested_at = p.get("exit_requested_at")
        if reason == "entry_failure" and p.get("opened_at") == now:
            capture_type = "entry_failure_first_intent"
            requested_at = now
        elif (reason != "entry_failure" and requested_at is not None
              and requested_at == now):
            capture_type = "normal_request"
        else:
            # Existing EXITING positions may be restored before this extension
            # was deployed. Current books and reduced quantities are not the
            # old request-time observation.
            return {
                "version": 1, "capture_type": "request_evidence_unavailable",
                "requested_at": requested_at, "captured_at": now,
                "exit_reason": reason,
                "unavailable_reason": "preinstrumentation_or_retry",
                "closing_price_status": "unavailable",
                "requested_closing_liability_usd": None,
                "mark_status": "unavailable", "net_liquidation_pnl_usd": None,
                "legs": [],
            }

        rows = []
        books = []
        for leg in p["legs"][:2]:
            book = self.books.get(leg["key"])
            book_valid = valid_book(book, now, self.config)
            remaining = leg["remaining"]
            meta = self.market_meta.get(leg["key"])
            fee_bps = scenario_fee(meta, p["strategy"]) if meta else leg["fee_bps"]
            side = "bids" if leg["side"] == "long" else "asks"
            value = walk(book[side], remaining) if book_valid and remaining > 0 else None
            receipt = book.get("received") if book else None
            source = book.get("engine_time") if book else None
            clock_valid = (receipt is not None and source is not None
                           and source <= receipt <= now)
            row = {
                "key": str(leg["key"])[:160], "side": leg["side"],
                "remaining_quantity": remaining,
                "exit_side": "sell" if leg["side"] == "long" else "buy",
                "book_received_at": receipt,
                "book_engine_time": source,
                "book_source": str(book.get("source"))[:80] if book and book.get("source") is not None else None,
                "book_generation": str(book.get("generation"))[:100] if book and book.get("generation") is not None else None,
                "receipt_age_seconds": now-receipt if receipt is not None else None,
                "source_age_seconds": now-source if source is not None else None,
                "book_valid": bool(book_valid),
                "clock_valid": clock_valid,
                "walk_status": ("no_remaining" if remaining <= 0 else
                                "invalid_or_stale_book" if not book_valid else
                                "insufficient_depth" if value is None else "valid"),
                "exit_walk_value_usd": value,
                "exit_fee_bps": fee_bps,
            }
            rows.append(row)
            books.append(book)

        skew = (abs(books[0]["received"] - books[1]["received"])
                if len(books) == 2 and all(b and b.get("received") is not None for b in books)
                else None)
        skew_valid = skew is not None and skew <= self.config.max_skew
        observation = {
            "version": 1, "capture_type": capture_type,
            "requested_at": requested_at, "captured_at": now,
            "exit_reason": reason, "legs": rows,
            "received_skew_seconds": skew,
            "receipt_pair_skew_valid": skew_valid,
            "requested_closing_liability_usd": None,
            "net_liquidation_pnl_usd": None,
        }
        if capture_type == "entry_failure_first_intent":
            observation["closing_price_status"] = "entry_failure_unpaired"
            observation["mark_status"] = "entry_failure_unpaired"
            return observation

        full_pair = (len(p["legs"]) == len(rows) == 2
                     and {r["side"] for r in rows} == {"long", "short"}
                     and all(leg.get("entry_result") == "filled" for leg in p["legs"])
                     and all(r["remaining_quantity"] > 0 for r in rows)
                     and abs(rows[0]["remaining_quantity"] - rows[1]["remaining_quantity"]) <= 1e-9
                     and all(abs(leg["remaining"] - leg["quantity"]) <= 1e-9
                             for leg in p["legs"]))
        if not full_pair:
            price_status = "unpaired_or_partial_inventory"
        elif not all(r["book_valid"] for r in rows):
            price_status = "invalid_or_stale_book"
        elif not all(r["clock_valid"] for r in rows):
            price_status = "clock_order_invalid"
        elif not skew_valid:
            price_status = "receipt_skew"
        elif not all(r["walk_status"] == "valid" for r in rows):
            price_status = "insufficient_depth"
        else:
            price_status = "valid"
        observation["closing_price_status"] = price_status
        if price_status != "valid":
            observation["mark_status"] = price_status
            return observation

        long = next(r for r in rows if r["side"] == "long")
        short = next(r for r in rows if r["side"] == "short")
        observation["requested_closing_liability_usd"] = (
            short["exit_walk_value_usd"] - long["exit_walk_value_usd"])
        mark = self.liquidation(p, now)
        if mark is not None and math.isfinite(mark):
            observation["mark_status"] = "valid"
            observation["net_liquidation_pnl_usd"] = mark
        else:
            # Valid executable closing prices remain useful even when a
            # crossed funding boundary prevents a trustworthy net mark.
            crossed = any(l.get("entry_time") is not None
                          and int(l["entry_time"] // 3600) < int(now // 3600)
                          for l in p["legs"])
            observation["mark_status"] = "funding_unknown" if crossed else "net_mark_unavailable"
        return observation
