"""Deterministic, read-only RH maker -> Core hedge paper lifecycle.

Inputs are receipt-ordered normalized public events from ``maker_maker_events``.
All quantities/prices/cash use Decimal. No trading endpoint is used. Each
asset/budget/policy/tier branch is an independent counterfactual ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Callable, Mapping


NS = 1_000_000_000
YEAR_NS = Decimal(365 * 24 * 3600 * NS)
D0 = Decimal("0")


def venue_key(value: Any) -> str:
    value = str(value).lower()
    return {"rh_lighter": "maker", "lighter": "hedge"}.get(value, value)


def dec(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def on_step(value: Decimal, step: Decimal) -> bool:
    return value > 0 and floor_step(value, step) == value


@dataclass(frozen=True)
class Rules:
    price_tick: Decimal | None
    qty_step: Decimal
    min_qty: Decimal
    max_qty: Decimal | None
    min_notional: Decimal
    taker_fee_bps: Decimal
    maker_fee_bps: Decimal = D0
    price_tick_semantics: str = "fixed"
    sz_decimals: int | None = None
    max_quote: Decimal | None = None

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "Rules":
        required = ("min_notional", "taker_fee_bps")
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError(f"missing venue rules: {missing}")
        semantics = str(raw.get("price_tick_semantics", "fixed"))
        step = raw.get("qty_step", raw.get("size_step"))
        sz_dec = raw.get("sz_decimals", raw.get("szDecimals"))
        if step is None and sz_dec is not None:
            step = Decimal(10) ** -int(sz_dec)
        tick = raw.get("price_tick")
        if step is None or (tick is None and semantics != "hedge_perp"):
            raise ValueError("missing price or size grid")
        result = cls(
            price_tick=None if tick is None else dec(tick), qty_step=dec(step),
            min_qty=dec(raw.get("min_qty") if raw.get("min_qty") is not None else step),
            max_qty=None if raw.get("max_qty") is None else dec(raw["max_qty"]),
            min_notional=dec(raw["min_notional"]), taker_fee_bps=dec(raw["taker_fee_bps"]),
            maker_fee_bps=dec(raw.get("maker_fee_bps", 0)), price_tick_semantics=semantics,
            sz_decimals=None if sz_dec is None else int(sz_dec),
            max_quote=None if raw.get("max_quote") is None else dec(raw["max_quote"]),
        )
        if result.qty_step <= 0 or result.min_qty <= 0 or (result.price_tick is not None and result.price_tick <= 0):
            raise ValueError("nonpositive market grid/quantity")
        if result.min_notional < 0 or (result.max_qty is not None and result.min_qty > result.max_qty):
            raise ValueError("invalid minimum/maximum")
        if semantics == "hedge_perp" and (result.sz_decimals is None or not 0 <= result.sz_decimals <= 6):
            raise ValueError("Core perp needs sz_decimals")
        return result

    def valid_price(self, price: Decimal) -> bool:
        if price <= 0:
            return False
        if self.price_tick_semantics != "hedge_perp":
            return self.price_tick is not None and on_step(price, self.price_tick)
        assert self.sz_decimals is not None
        max_decimal_step = Decimal(10) ** -(6 - self.sz_decimals)
        if not on_step(price, max_decimal_step):
            return False
        if price == price.to_integral_value():
            return True
        digits = len(price.normalize().as_tuple().digits)
        return digits <= 5

    def sell_limit_at_or_above(self, lower_bound: Decimal) -> Decimal:
        """Tightest valid sell IOC cap that never widens beyond lower_bound."""
        if self.price_tick_semantics != "hedge_perp":
            assert self.price_tick is not None
            step = self.price_tick
        else:
            assert self.sz_decimals is not None
            step = max(Decimal(10) ** (lower_bound.adjusted() - 4), Decimal(10) ** -(6 - self.sz_decimals))
            if lower_bound >= 100_000:
                step = Decimal(1)
        candidate = (lower_bound / step).to_integral_value(rounding=ROUND_CEILING) * step
        for _ in range(12):
            if self.valid_price(candidate) and candidate >= lower_bound:
                return candidate
            candidate += step
        raise ValueError("cannot form valid limit price")

    def valid_order(self, qty: Decimal, price: Decimal) -> bool:
        return (
            self.valid_price(price)
            and on_step(qty, self.qty_step)
            and self.min_qty <= qty
            and (self.max_qty is None or qty <= self.max_qty)
            and qty * price >= self.min_notional
            and (self.max_quote is None or qty * price <= self.max_quote)
        )


@dataclass(frozen=True)
class Config:
    asset: str
    budget_usd: Decimal
    policy: str
    tier: str = "standard"
    maker_latency_ns: int = 400_000_000
    cancel_latency_ns: int = 400_000_000
    maker_taker_latency_ns: int = 400_000_000
    hedge_ioc_latency_ns: int = 400_000_000
    quote_rest_ns: int = 5 * NS
    hold_ns: int = 10 * NS
    intent_timeout_ns: int = 3 * NS
    max_book_age_ns: int = 2 * NS
    max_pair_skew_ns: int = NS
    hedge_limit_bps: Decimal = Decimal("10")
    reserve_bps: Decimal = Decimal("5")
    capital_rate: Decimal = Decimal("0.05")
    take_profit_usd: Decimal = Decimal("0.10")
    max_increments: int = 64
    max_audit: int = 4096
    max_episodes: int = 1024

    def __post_init__(self) -> None:
        if self.policy not in {"adaptive", "persistence", "fixed_best"}:
            raise ValueError("unknown policy")
        if self.tier not in {"standard", "plus", "premium"}:
            raise ValueError("unknown RH tier")
        if dec(self.budget_usd) <= 0:
            raise ValueError("nonpositive budget")
        if self.tier == "premium":
            # Published 0 ms maker/cancel and 200 ms taker processing, plus
            # frozen 100 ms client/network allowance. Preserve explicit
            # caller overrides when they differ from Standard defaults.
            if self.maker_latency_ns == 300_000_000:
                object.__setattr__(self, "maker_latency_ns", 100_000_000)
            if self.cancel_latency_ns == 300_000_000:
                object.__setattr__(self, "cancel_latency_ns", 100_000_000)
            if self.maker_taker_latency_ns == 400_000_000:
                object.__setattr__(self, "maker_taker_latency_ns", 300_000_000)


@dataclass
class Book:
    venue: str
    received_ns: int
    source_ns: int
    generation: Any
    bids: list[tuple[Decimal, Decimal]]
    asks: list[tuple[Decimal, Decimal]]

    @classmethod
    def parse(cls, event: Mapping[str, Any]) -> "Book":
        bids = [(dec(p), dec(q)) for p, q in event["bids"]]
        asks = [(dec(p), dec(q)) for p, q in event["asks"]]
        if not bids or not asks or any(p <= 0 or q <= 0 for p, q in bids + asks):
            raise ValueError("empty or nonpositive book")
        if any(bids[i][0] <= bids[i + 1][0] for i in range(len(bids) - 1)):
            raise ValueError("unordered bids")
        if any(asks[i][0] >= asks[i + 1][0] for i in range(len(asks) - 1)):
            raise ValueError("unordered asks")
        if bids[0][0] >= asks[0][0]:
            raise ValueError("crossed book")
        received = int(event.get("received_ns", event.get("receipt_ns")))
        source = int(event["source_ns"])
        if source > received or not event.get("clock_valid", True):
            raise ValueError("uncalibrated or future source clock")
        if event["venue"] not in ("rh_lighter", "lighter"):
            raise ValueError("unexpected source venue")
        return cls(venue_key(event["venue"]), received, source, event.get("generation"), bids, asks)

    def walk(self, side: str, qty: Decimal, limit: Decimal | None = None) -> tuple[Decimal, Decimal]:
        levels = self.bids if side == "sell" else self.asks
        filled = value = D0
        for price, available in levels:
            if limit is not None and ((side == "sell" and price < limit) or (side == "buy" and price > limit)):
                break
            take = min(available, qty - filled)
            if take <= 0:
                break
            filled += take
            value += take * price
            if filled == qty:
                break
        return filled, value

    def mid(self) -> Decimal:
        return (self.bids[0][0] + self.asks[0][0]) / 2


@dataclass
class HedgeIntent:
    qty: Decimal
    due_ns: int
    timeout_ns: int
    anchor_bid: Decimal
    flow_receipt_ns: int
    first_seen: bool = False


@dataclass
class ExitIntent:
    venue: str
    due_ns: int
    timeout_ns: int
    reason: str
    first_seen: bool = False


@dataclass
class Quote:
    price: Decimal
    qty: Decimal
    decided_ns: int
    activation_due_ns: int
    activated_ns: int | None = None
    activated_source_ns: int | None = None
    generation: Any = None
    cancel_due_ns: int | None = None
    cancel_reason: str | None = None
    canceled_ns: int | None = None
    remaining: Decimal = D0
    ahead_better: Decimal = D0
    ahead_same: Decimal = D0
    touched: bool = False
    through: bool = False
    maker_attributed: Decimal = D0
    increments: int = 0


class MakerBranch:
    """One asset/budget/policy/tier ledger. All callbacks are read-only.

    ``process(event, quote_diag)`` requires receipt-ordered parser events.
    Pass ``model.quote(...)["policies"][policy]`` as quote_diag on paired
    book updates; the coordinator may cache that diagnostic across policies.
    Timers advance before the new event is made visible. ``tick`` advances
    timers in quiet periods. ``summary`` is safe at EOF without flattening.
    """

    def __init__(self, config: Config, metadata: Mapping[str, Mapping[str, Any]],
                 audit_sink: Callable[[dict[str, Any]], None] | None = None):
        if config.tier != "standard":
            raise ValueError("This Core study supports only verified Standard fees")
        self.cfg = config
        self.source_venues = {"maker": "rh_lighter", "hedge": "lighter"}
        self.audit_sink = audit_sink
        self.audit_omitted = 0
        def market(*keys: str) -> Mapping[str, Any]:
            raw = next((metadata[k] for k in keys if k in metadata), None)
            if raw is None:
                raise ValueError(f"missing metadata for {keys}")
            if config.asset in raw and isinstance(raw[config.asset], Mapping):
                return raw[config.asset]
            return raw
        self.maker = Rules.parse(market("maker", "rh_lighter"))
        self.hedge = Rules.parse(market("hedge", "lighter"))
        maker_fees = {"standard": ("0", "0"), "plus": ("0.5", "0.5"), "premium": ("1.2", "3.5")}
        maker_fee, taker_fee = maker_fees[config.tier]
        self.maker = replace(self.maker, maker_fee_bps=dec(maker_fee), taker_fee_bps=dec(taker_fee))
        self.books: dict[str, Book] = {}
        self.now_ns: int | None = None
        self.quote: Quote | None = None
        self.hedges: list[HedgeIntent] = []
        self.exits: dict[str, ExitIntent] = {}
        self.first_full_hedge_ns: int | None = None
        self.episode_no = 0
        self.episodes: list[dict[str, Any]] = []
        self.audit: list[dict[str, Any]] = []
        self.counts: dict[str, int] = {}
        self.seen_trades: set[str] = set()
        self.maker_pos = self.hedge_pos = D0
        self.open_lots: dict[str, list[list[Decimal]]] = {"maker": [], "hedge": []}
        self.cash_maker = self.cash_hedge = D0
        self.fees_maker = self.fees_hedge = D0
        self.reserve_cost = self.capital_cost = D0
        self.capital_base = D0
        self.funding_unknown = False
        self._episode_funding_unknown = False
        self.unknown_reason: str | None = None
        self.truncated = False
        self.last_entry_ns: int | None = None
        self.last_flat_ns: int | None = None
        self.exit_requested_ns: int | None = None
        self.last_close_mark: Decimal | None = None
        self.delta_exposure_base_ns = D0
        self.gross_inventory_base_ns = D0
        self._episode_maker_entries = D0
        self._episode_hedge_entries = D0
        self._episode_reserve = D0
        self._episode_start_cash = D0
        self._episode_start_capital = D0
        self._episode_start_reserve = D0

    def _count(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    def _log(self, event: str, now_ns: int, **details: Any) -> None:
        self._count(event)
        if "venue" in details:
            details["source_venue"] = self.source_venues.get(details["venue"])
        row = {"event": event, "ns": now_ns,
               **{k: str(v) if isinstance(v, Decimal) else v for k, v in details.items()}}
        if self.audit_sink is not None:
            self.audit_sink(row)  # A storage-cap exception propagates to stop the replay.
        if len(self.audit) < self.cfg.max_audit:
            self.audit.append(row)
        else:
            self.audit_omitted += 1
            if self.audit_sink is None:
                self.truncated = True
                self.unknown_reason = "audit_cap"

    def _unknown(self, reason: str, now_ns: int) -> None:
        if self.unknown_reason is None:
            self.unknown_reason = reason
            self._log("unknown", now_ns, reason=reason, maker_pos=self.maker_pos, hedge_pos=self.hedge_pos)

    def _fresh_pair(self, now_ns: int) -> bool:
        if "maker" not in self.books or "hedge" not in self.books:
            return False
        a, b = self.books["maker"], self.books["hedge"]
        return (
            0 <= now_ns - a.received_ns <= self.cfg.max_book_age_ns
            and 0 <= now_ns - b.received_ns <= self.cfg.max_book_age_ns
            and 0 <= now_ns - a.source_ns <= self.cfg.max_book_age_ns
            and 0 <= now_ns - b.source_ns <= self.cfg.max_book_age_ns
            and abs(a.received_ns - b.received_ns) <= self.cfg.max_pair_skew_ns
            and abs(a.source_ns - b.source_ns) <= self.cfg.max_pair_skew_ns
        )

    def _fee(self, venue: str, value: Decimal, maker: bool = False) -> None:
        rules = self.maker if venue == "maker" else self.hedge
        cost = value * (rules.maker_fee_bps if maker else rules.taker_fee_bps) / 10_000
        if venue == "maker":
            self.cash_maker -= cost
            self.fees_maker += cost
        else:
            self.cash_hedge -= cost
            self.fees_hedge += cost

    def _refresh_reserve(self) -> None:
        target = max(self._episode_maker_entries, self._episode_hedge_entries) * self.cfg.reserve_bps / 10_000
        self.reserve_cost += target - self._episode_reserve
        self._episode_reserve = target

    def _apply_fill(self, venue: str, side: str, qty: Decimal, value: Decimal, now_ns: int, maker: bool = False) -> None:
        if qty <= 0 or value <= 0:
            raise ValueError("nonpositive fill")
        sign = 1 if side == "buy" else -1
        old_pos = self.maker_pos if venue == "maker" else self.hedge_pos
        remaining = qty
        lots = self.open_lots[venue]
        if old_pos != 0 and (old_pos > 0) != (sign > 0):
            while remaining > 0 and lots:
                take = min(remaining, lots[0][0])
                lots[0][0] -= take
                remaining -= take
                if lots[0][0] == 0:
                    lots.pop(0)
        if remaining > 0:
            lots.append([remaining, value / qty])
        if venue == "maker":
            self.maker_pos += sign * qty
            self.cash_maker -= sign * value
        else:
            self.hedge_pos += sign * qty
            self.cash_hedge -= sign * value
        self._fee(venue, value, maker)
        self.capital_base = sum((lot_qty * entry_px for venue_lots in self.open_lots.values()
                                 for lot_qty, entry_px in venue_lots), D0)
        self._log("fill", now_ns, venue=venue, side=side, qty=qty, value=value, maker=maker)
        if self.last_entry_ns is None:
            self.last_entry_ns = now_ns

    def _valid_execution_slice(self, venue: str, qty: Decimal, value: Decimal) -> bool:
        if qty <= 0 or value <= 0:
            return False
        r = self.maker if venue == "maker" else self.hedge
        return (
            on_step(qty, r.qty_step)
            and (r.max_qty is None or qty <= r.max_qty)
        )

    def _close_episode_if_flat(self, now_ns: int) -> None:
        q = self.quote
        if q is None or q.canceled_ns is None or self.hedges or self.exits:
            return
        if q.cancel_due_ns is not None and now_ns < q.cancel_due_ns + self.cfg.max_book_age_ns:
            return  # Preserve the old quote for bounded late trade confirmations.
        if self.maker_pos != 0 or self.hedge_pos != 0:
            return
        if len(self.episodes) >= self.cfg.max_episodes:
            self.truncated = True
            self._unknown("episode_retention_cap", now_ns)
            return
        self.last_flat_ns = now_ns
        self.episodes.append({
            "number": self.episode_no, "decided_ns": q.decided_ns,
            "flat_ns": now_ns, "maker_attributed": str(q.maker_attributed),
            "touched": q.touched, "through": q.through,
            "no_flow": q.maker_attributed == 0,
            "partial_flow": D0 < q.maker_attributed < q.qty,
            "full_flow": q.maker_attributed == q.qty,
            "cash_known": str(self.cash_maker + self.cash_hedge - self._episode_start_cash),
            "reserve_cost": str(self.reserve_cost - self._episode_start_reserve),
            "capital_cost": str(self.capital_cost - self._episode_start_capital),
            "funding_unknown": self._episode_funding_unknown,
        })
        self._log("episode_flat", now_ns, maker_attributed=q.maker_attributed)
        self.quote = None
        self.first_full_hedge_ns = None
        self.exit_requested_ns = None
        self.capital_base = D0
        self._episode_maker_entries = self._episode_hedge_entries = self._episode_reserve = D0
        self._episode_funding_unknown = False
        self.seen_trades.clear()

    def tick(self, now_ns: int) -> None:
        now_ns = int(now_ns)
        if self.now_ns is not None and now_ns < self.now_ns:
            self._unknown("backward_receipt_time", now_ns)
            return
        if self.now_ns is not None and self.capital_base > 0 and now_ns > self.now_ns:
            self.capital_cost += self.capital_base * self.cfg.capital_rate * dec(now_ns - self.now_ns) / YEAR_NS
        if self.now_ns is not None and now_ns > self.now_ns:
            elapsed = dec(now_ns - self.now_ns)
            self.delta_exposure_base_ns += abs(self.maker_pos + self.hedge_pos) * elapsed
            self.gross_inventory_base_ns += (abs(self.maker_pos) + abs(self.hedge_pos)) * elapsed
        if self.now_ns is not None and (self.maker_pos != 0 or self.hedge_pos != 0):
            if now_ns // (3600 * NS) != self.now_ns // (3600 * NS):
                self.funding_unknown = True
                self._episode_funding_unknown = True
                self._log("funding_boundary_unknown", now_ns)
        self.now_ns = now_ns
        if self.unknown_reason:
            return
        q = self.quote
        if q is not None:
            if q.activated_ns is None and now_ns > q.activation_due_ns + self.cfg.max_book_age_ns:
                self._unknown("activation_book_timeout", now_ns)
                return
            if q.activated_ns is not None and q.cancel_due_ns is None and now_ns >= q.activation_due_ns + self.cfg.quote_rest_ns:
                self._request_cancel(q.activation_due_ns + self.cfg.quote_rest_ns, "rest_expired")
            if q.cancel_due_ns is not None and q.canceled_ns is None and now_ns > q.cancel_due_ns + self.cfg.max_book_age_ns:
                self._unknown("cancel_confirmation_book_timeout", now_ns)
                return
        for intent in list(self.hedges):
            if now_ns > intent.timeout_ns:
                self._log("hedge_timeout", now_ns, qty=intent.qty)
                self.hedges.remove(intent)
                self._start_exit(intent.timeout_ns, "hedge_timeout")
        if self.first_full_hedge_ns is not None and self.exit_requested_ns is None:
            if now_ns >= self.first_full_hedge_ns + self.cfg.hold_ns:
                self._start_exit(self.first_full_hedge_ns + self.cfg.hold_ns, "hold_deadline")
        for venue, intent in list(self.exits.items()):
            if now_ns > intent.timeout_ns:
                self._log("exit_timeout", now_ns, venue=venue)
                del self.exits[venue]
                if self.maker_pos != 0 or self.hedge_pos != 0:
                    self._unknown("terminal_inventory_after_exit_timeout", now_ns)
        self._close_episode_if_flat(now_ns)

    def _request_cancel(self, now_ns: int, reason: str) -> None:
        q = self.quote
        if q is not None and q.cancel_due_ns is None and q.canceled_ns is None:
            q.cancel_due_ns = now_ns + self.cfg.cancel_latency_ns
            q.cancel_reason = reason
            self._log("cancel_requested", now_ns, due_ns=q.cancel_due_ns, reason=reason)

    def _start_exit(self, now_ns: int, reason: str) -> None:
        if self.exit_requested_ns is None:
            self.exit_requested_ns = now_ns
            self._log("exit_requested", now_ns, reason=reason, maker_pos=self.maker_pos, hedge_pos=self.hedge_pos)
        self._request_cancel(now_ns, reason)
        for venue, pos, latency in (("maker", self.maker_pos, self.cfg.maker_taker_latency_ns), ("hedge", self.hedge_pos, self.cfg.hedge_ioc_latency_ns)):
            if pos != 0 and venue not in self.exits:
                self.exits[venue] = ExitIntent(venue, now_ns + latency, now_ns + self.cfg.intent_timeout_ns, reason)

    def _episode_executable_exit_mark(self, now_ns: int) -> Decimal | None:
        """Decision-time completed mark; actual exits still wait their delays."""
        if not self._fresh_pair(now_ns):
            return None
        if self.maker_pos <= 0 or self.hedge_pos >= 0 or self.maker_pos != -self.hedge_pos:
            return None
        maker_book, hedge_book = self.books["maker"], self.books["hedge"]
        maker_qty, hedge_qty = self.maker_pos, -self.hedge_pos
        if (not self.maker.valid_order(maker_qty, maker_book.bids[0][0])
                or not self.hedge.valid_order(hedge_qty, hedge_book.asks[0][0])):
            return None
        r_fill, r_value = maker_book.walk("sell", maker_qty)
        h_fill, h_value = hedge_book.walk("buy", hedge_qty)
        if r_fill != maker_qty or h_fill != hedge_qty:
            return None
        synthetic_cash = self.cash_maker + self.cash_hedge - self._episode_start_cash
        projected_exit_fees = (r_value * self.maker.taker_fee_bps + h_value * self.hedge.taker_fee_bps) / 10_000
        return (synthetic_cash + r_value - h_value - projected_exit_fees
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
                elif q.price >= book.asks[0][0]:
                    q.canceled_ns = now_ns
                    self._log("post_only_reject", now_ns)
                else:
                    q.activated_ns = now_ns
                    q.activated_source_ns = book.source_ns
                    q.generation = book.generation
                    q.ahead_better = sum((qty for price, qty in book.bids if price > q.price), D0)
                    q.ahead_same = sum((qty for price, qty in book.bids if price == q.price), D0)
                    self._log("activated", now_ns, ahead_better=q.ahead_better, ahead_same=q.ahead_same)
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

    def _fill_hedge(self, intent: HedgeIntent, book: Book) -> None:
        now_ns = book.received_ns
        self.hedges.remove(intent)
        limit = self.hedge.sell_limit_at_or_above(intent.anchor_bid * (1 - self.cfg.hedge_limit_bps / 10_000))
        desired = floor_step(intent.qty, self.hedge.qty_step)
        if desired <= 0 or not self.hedge.valid_order(desired, limit):
            self._log("hedge_lot_or_min_reject", now_ns, desired=desired, original=intent.qty)
            self._start_exit(now_ns, "hedge_lot_or_min_reject")
            return
        filled, value = book.walk("sell", desired, limit=limit)
        filled = floor_step(filled, self.hedge.qty_step)
        if filled > 0:
            filled, value = book.walk("sell", filled, limit=limit)
        if filled > 0 and not self._valid_execution_slice("hedge", filled, value):
            self._unknown("offlot_hedge_execution", now_ns)
            return
        if filled > 0:
            self._apply_fill("hedge", "sell", filled, value, now_ns)
            self._episode_hedge_entries += value
            self._refresh_reserve()
        self._log("hedge_result", now_ns, requested=intent.qty, filled=filled, limit=limit)
        if filled != intent.qty:
            self._start_exit(now_ns, "partial_or_zero_hedge")
        elif self.first_full_hedge_ns is None:
            self.first_full_hedge_ns = now_ns
            self._log("first_full_hedge", now_ns, hold_due_ns=now_ns + self.cfg.hold_ns)
        if self.exit_requested_ns is not None:
            self._start_exit(now_ns, "late_hedge_after_exit_request")

    def _fill_exit(self, venue: str, book: Book) -> None:
        intent = self.exits.get(venue)
        if intent is None or book.received_ns < intent.due_ns or book.source_ns < intent.due_ns:
            return
        now_ns = book.received_ns
        pos = self.maker_pos if venue == "maker" else self.hedge_pos
        if pos == 0:
            del self.exits[venue]
            return
        rules = self.maker if venue == "maker" else self.hedge
        side = "sell" if pos > 0 else "buy"
        qty = floor_step(abs(pos), rules.qty_step)
        filled = value = D0
        if qty != abs(pos) or qty <= 0 or not rules.valid_order(qty, book.bids[0][0] if side == "sell" else book.asks[0][0]):
            self._unknown("exit_order_lot_or_minimum_unknown", now_ns)
            return
        if qty > 0:
            filled, value = book.walk(side, qty)
            filled = floor_step(filled, rules.qty_step)
            if filled > 0:
                filled, value = book.walk(side, filled)
        if filled > 0 and not self._valid_execution_slice(venue, filled, value):
            self._unknown("offlot_exit_execution", now_ns)
            return
        if filled > 0:
            self._apply_fill(venue, side, filled, value, now_ns)
        self._log("exit_result", now_ns, venue=venue, requested=pos, filled=filled, reason=intent.reason)
        del self.exits[venue]
        residual = self.maker_pos if venue == "maker" else self.hedge_pos
        if residual != 0:
            if now_ns + (self.cfg.maker_taker_latency_ns if venue == "maker" else self.cfg.hedge_ioc_latency_ns) <= intent.timeout_ns:
                latency = self.cfg.maker_taker_latency_ns if venue == "maker" else self.cfg.hedge_ioc_latency_ns
                self.exits[venue] = ExitIntent(venue, now_ns + latency, intent.timeout_ns, "retry")
            else:
                self._unknown("unflattened_dust_or_depth", now_ns)

    def _on_trade(self, event: Mapping[str, Any]) -> None:
        q = self.quote
        if q is None or q.activated_ns is None:
            if (q is not None and q.canceled_ns is None and event.get("side") == "sell"
                    and dec(event.get("price", 0)) <= q.price
                    and int(event.get("source_ns", 0)) >= q.activation_due_ns):
                self._unknown("eligible_flow_before_activation_book", int(event.get("received_ns", event.get("receipt_ns"))))
            return
        now_ns = int(event.get("received_ns", event.get("receipt_ns")))
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
            if event.get("side") == "sell" and dec(event.get("price", 0)) <= q.price:
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
        side = event.get("side")
        if side != "sell":
            return
        price, qty = dec(event["price"]), dec(event["qty"])
        if price <= 0 or qty <= 0:
            self._unknown("invalid_trade_value", now_ns)
            return
        if price > q.price:
            return  # A sell matched above our bid cannot consume this queue.
        if q.canceled_ns is not None:
            if q.cancel_due_ns is None or source_ns > q.cancel_due_ns:
                return
            if source_ns == q.cancel_due_ns and price <= q.price:
                self._unknown("cancel_fill_same_source_time", now_ns)
                return
            # A delayed confirmation for flow that preceded modeled cancel
            # effectiveness still belongs to this old quote.
            if price <= q.price:
                self._count("late_pending_cancel_flow")
        if q.cancel_due_ns is not None and source_ns > q.cancel_due_ns:
            self._unknown("trade_cancel_order_ambiguous", now_ns)
            return
        q.touched = True
        self._count("touch")
        if price < q.price:
            q.through = True
            self._count("trade_through")
        else:
            self._count("equal_price_touch")
        remaining_trade = qty
        consume = min(q.ahead_same, remaining_trade)
        q.ahead_same -= consume
        remaining_trade -= consume
        if remaining_trade <= 0 or q.remaining <= 0:
            return
        attributed = min(remaining_trade, q.remaining)
        if q.increments >= self.cfg.max_increments:
            self.truncated = True
            self._unknown("increment_cap", now_ns)
            return
        q.increments += 1
        q.remaining -= attributed
        q.maker_attributed += attributed
        self._apply_fill("maker", "buy", attributed, attributed * q.price, now_ns, maker=True)
        self._episode_maker_entries += attributed * q.price
        self._refresh_reserve()
        self._log("maker_increment", now_ns, qty=attributed, remaining=q.remaining, trade_id=trade_id)
        self._request_cancel(now_ns, "first_maker_flow")
        hedge_book = self.books.get("hedge")
        if hedge_book is None or not self._fresh_pair(now_ns):
            self._log("hedge_anchor_missing", now_ns, qty=attributed)
            self._start_exit(now_ns, "hedge_anchor_missing")
            return
        found, value = hedge_book.walk("sell", attributed)
        if found < attributed:
            self._log("hedge_anchor_shallow", now_ns, qty=attributed)
            self._start_exit(now_ns, "hedge_anchor_shallow")
            return
        anchor = value / found
        self.hedges.append(HedgeIntent(attributed, now_ns + self.cfg.hedge_ioc_latency_ns,
                                       now_ns + self.cfg.intent_timeout_ns, anchor, now_ns))
        self._log("hedge_scheduled", now_ns, due_ns=now_ns + self.cfg.hedge_ioc_latency_ns,
                  qty=attributed, anchor_bid=anchor)

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
            hedge_entry_value = qty * hedge_book.bids[0][0]
            if (qty * price > dec(self.cfg.budget_usd)
                    or not self.maker.valid_order(qty, price)
                    or not self.hedge.valid_order(qty, hedge_book.bids[0][0])):
                self._log("abstain", now_ns, reason="lot_min_budget_or_grid")
                return
            if (2 * dec(self.cfg.budget_usd) + self.cash_maker < qty * price
                    or 2 * dec(self.cfg.budget_usd) + self.cash_hedge < hedge_entry_value):
                self._log("abstain", now_ns, reason="venue_prefund_capacity")
                return
            if price >= maker_book.asks[0][0]:
                self._log("abstain", now_ns, reason="post_only_cross")
                return
            found, _ = hedge_book.walk("sell", qty)
            if found < qty:
                self._log("abstain", now_ns, reason="hedge_depth")
                return
            self.episode_no += 1
            self._episode_start_cash = self.cash_maker + self.cash_hedge
            self._episode_start_capital = self.capital_cost
            self._episode_start_reserve = self.reserve_cost
            self.quote = Quote(price, qty, now_ns, now_ns + self.cfg.maker_latency_ns, remaining=qty)
            self.capital_base = D0  # No actual entry, so no model capital charge yet.
            classification = "inside" if price > maker_book.bids[0][0] else "join" if price == maker_book.bids[0][0] else "behind"
            self._log("quote_requested", now_ns, price=price, qty=qty,
                      competitiveness=classification, due_ns=self.quote.activation_due_ns)
            return
        if q.canceled_ns is not None or q.cancel_due_ns is not None or q.activated_ns is None:
            return
        if not self._fresh_pair(now_ns):
            self._request_cancel(now_ns, "invalid_pair")
            return
        current_maker, current_hedge = self.books["maker"], self.books["hedge"]
        found, _ = current_hedge.walk("sell", q.remaining)
        if found < q.remaining:
            self._request_cancel(now_ns, "hedge_depth_gone")
            return
        if self.cfg.policy == "fixed_best":
            if current_maker.bids[0][0] != q.price:
                self._request_cancel(now_ns, "best_bid_changed")
            return
        if diag.get("reason") != "quote" or diag.get("price") is None or dec(diag["price"]) != q.price:
            self._request_cancel(now_ns, "model_reprice_or_threshold")

    def process(self, event: Mapping[str, Any], quote_diag: Mapping[str, Any] | None = None) -> None:
        kind = event.get("type", event.get("kind"))
        if kind == "end":
            if event.get("truncated"):
                self.truncated = True
            if self.quote or self.maker_pos != 0 or self.hedge_pos != 0 or self.hedges or self.exits:
                self._unknown("capture_end_with_open_obligation", self.now_ns or 0)
            return
        now_ns = int(event.get("received_ns", event.get("receipt_ns")))
        self.tick(now_ns)  # Deadlines see only preceding public information.
        if self.unknown_reason:
            return
        if event.get("asset") not in (None, self.cfg.asset):
            return
        if kind == "invalidate" or event.get("valid") is False:
            venue = venue_key(event.get("venue", ""))
            if venue in self.books:
                del self.books[venue]
            self._log("invalidation", now_ns, venue=venue, reason=event.get("reason"))
            if self.quote or self.maker_pos != 0 or self.hedge_pos != 0:
                self._unknown("coverage_gap_open_obligation", now_ns)
            return
        if kind == "book":
            try:
                book = Book.parse(event)
            except (ValueError, KeyError, TypeError) as exc:
                venue = venue_key(event.get("venue", ""))
                self.books.pop(venue, None)
                self._log("invalidation", now_ns, venue=venue, reason=f"invalid_book:{exc}")
                if self.quote or self.maker_pos != 0 or self.hedge_pos != 0 or self.hedges or self.exits:
                    self._unknown(f"invalid_book_during_obligation:{exc}", now_ns)
                return
            self._on_book(book)
            if quote_diag is not None:
                self._on_diagnostic(quote_diag, now_ns)
        elif kind == "trade" and venue_key(event.get("venue")) == "maker":
            self._on_trade(event)

    def summary(self) -> dict[str, Any]:
        book_maker, book_hedge = self.books.get("maker"), self.books.get("hedge")
        mark_maker = self.maker_pos * book_maker.mid() if book_maker else None
        mark_hedge = self.hedge_pos * book_hedge.mid() if book_hedge else None
        marked = None if mark_maker is None or mark_hedge is None else self.cash_maker + self.cash_hedge + mark_maker + mark_hedge
        liquidation: Decimal | None = None
        if self.now_ns is not None and self._fresh_pair(self.now_ns):
            value = self.cash_maker + self.cash_hedge - self.reserve_cost - self.capital_cost
            possible = True
            for venue, pos, book, rules in (("maker", self.maker_pos, book_maker, self.maker), ("hedge", self.hedge_pos, book_hedge, self.hedge)):
                if pos == 0:
                    continue
                assert book is not None
                side = "sell" if pos > 0 else "buy"
                qty = abs(pos)
                if not on_step(qty, rules.qty_step):
                    possible = False
                    break
                filled, cash_value = book.walk(side, qty)
                if (not rules.valid_order(qty, book.bids[0][0] if side == "sell" else book.asks[0][0])
                        or filled != qty or not self._valid_execution_slice(venue, filled, cash_value)):
                    possible = False
                    break
                value += cash_value if side == "sell" else -cash_value
                value -= cash_value * rules.taker_fee_bps / 10_000
            if possible:
                liquidation = value
        flat = self.maker_pos == 0 and self.hedge_pos == 0 and not self.hedges and not self.exits and self.quote is None
        net = self.cash_maker + self.cash_hedge - self.reserve_cost - self.capital_cost if flat and not self.funding_unknown and not self.unknown_reason else None
        return {
            "source_venues": dict(self.source_venues),
            "role_semantics": "maker/hedge are internal roles; source venue fields retain RH Lighter/Core identities",
            "asset": self.cfg.asset, "budget_usd": str(self.cfg.budget_usd),
            "policy": self.cfg.policy, "tier": self.cfg.tier,
            "counts": dict(self.counts), "episodes": list(self.episodes),
            "audit": list(self.audit), "audit_retained": len(self.audit),
            "audit_omitted_from_summary": self.audit_omitted,
            "audit_streamed_complete": self.audit_sink is not None,
            "audit_truncated": self.truncated,
            "unknown_reason": self.unknown_reason,
            "maker_position": str(self.maker_pos), "hedge_position": str(self.hedge_pos),
            "delta": str(self.maker_pos + self.hedge_pos),
            "gross_inventory": str(abs(self.maker_pos) + abs(self.hedge_pos)),
            "cash_known": str(self.cash_maker + self.cash_hedge),
            "cash_maker_usdg": str(self.cash_maker), "cash_hedge_usdc": str(self.cash_hedge),
            "cash_accounting_note": "Synthetic perp entry/exit notional cash-flow ledger; not live wallet balances. At flat, per-venue cash is modeled realized P&L in that venue's quote unit.",
            "initial_prefund_maker_usdg": str(2 * dec(self.cfg.budget_usd)),
            "initial_prefund_hedge_usdc": str(2 * dec(self.cfg.budget_usd)),
            "fees_maker": str(self.fees_maker), "fees_hedge": str(self.fees_hedge),
            "reserve_cost": str(self.reserve_cost), "capital_cost": str(self.capital_cost),
            "funding_unknown": self.funding_unknown,
            "delta_exposure_base_seconds": str(self.delta_exposure_base_ns / NS),
            "gross_inventory_base_seconds": str(self.gross_inventory_base_ns / NS),
            "indicative_mid_equity_before_model_costs": None if marked is None else str(marked),
            "executable_liquidation_net_if_fresh_and_order_valid": None if liquidation is None else str(liquidation),
            "conversion_omitted": True,
            "net_unit_note": "Combined net assumes USDG=USDC; executable conversion is unmodeled.",
            "complete_net": None if net is None else str(net),
        }
