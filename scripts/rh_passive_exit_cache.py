"""Event-scoped parse sharing for the prospective RH passive-exit replay.

The 128 independent portfolios still process every event. Only validated,
read-only representations of the same input book are shared within that
event. Call ``next_event()`` immediately before every iterator yield.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping

from scripts import rh_maker_model, rh_maker_sell_model
from scripts.rh_maker_engine import Book


@dataclass(frozen=True, slots=True)
class ImmutableBook:
    venue: str
    received_ns: int
    source_ns: int
    generation: Any
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    def walk(self, side: str, qty: Decimal,
             limit: Decimal | None = None) -> tuple[Decimal, Decimal]:
        return Book.walk(self, side, qty, limit)

    def mid(self) -> Decimal:
        return Book.mid(self)


@contextmanager
def cached_event_parses():
    """Yield ``(stats, next_event)`` and restore both parsers on exit.

    Model books and engine books have different numeric types. They are
    cached separately; no model state or quote decision is shared across
    fee tiers or portfolios. Invalid inputs are revalidated on every call
    so the existing per-consumer error handling remains intact.
    """
    book_descriptor = Book.__dict__['parse']
    original_book = Book.parse
    original_model = rh_maker_model._parse_book
    original_sell_alias = rh_maker_sell_model._parse_book
    stats = {'book_calls': 0, 'book_hits': 0, 'book_misses': 0,
             'model_calls': 0, 'model_hits': 0, 'model_misses': 0}
    cached_book_event = cached_book_value = None
    cached_model_event = cached_model_value = None

    def next_event():
        nonlocal cached_book_event, cached_book_value
        nonlocal cached_model_event, cached_model_value
        cached_book_event = cached_book_value = None
        cached_model_event = cached_model_value = None

    def parse_book(cls, event: Mapping[str, Any]):
        nonlocal cached_book_event, cached_book_value
        stats['book_calls'] += 1
        if event is cached_book_event:
            stats['book_hits'] += 1
            return cached_book_value
        parsed = original_book(event)
        value = ImmutableBook(parsed.venue, parsed.received_ns, parsed.source_ns,
                              parsed.generation, tuple(parsed.bids), tuple(parsed.asks))
        cached_book_event, cached_book_value = event, value
        stats['book_misses'] += 1
        return value

    def parse_model(event: Mapping[str, Any]):
        nonlocal cached_model_event, cached_model_value
        stats['model_calls'] += 1
        if event is cached_model_event:
            stats['model_hits'] += 1
            return cached_model_value
        parsed = original_model(event)
        value = MappingProxyType({**parsed,
                                  'bids': tuple(tuple(row) for row in parsed['bids']),
                                  'asks': tuple(tuple(row) for row in parsed['asks'])})
        cached_model_event, cached_model_value = event, value
        stats['model_misses'] += 1
        return value

    Book.parse = classmethod(parse_book)
    rh_maker_model._parse_book = parse_model
    rh_maker_sell_model._parse_book = parse_model
    try:
        yield stats, next_event
    finally:
        Book.parse = book_descriptor
        rh_maker_model._parse_book = original_model
        rh_maker_sell_model._parse_book = original_sell_alias
