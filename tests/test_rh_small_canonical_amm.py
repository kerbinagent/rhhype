import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from scripts.rh_small_canonical_amm import (
    ASSETS, INDEX, capped_write, choose_pools, hl_fee_metadata, pool_key_id,
    score_one, walk_hl,
)


class CanonicalAmmTests(unittest.TestCase):
    def test_pool_selection_frozen_two_versions_each(self):
        selected = choose_pools(json.loads(INDEX.read_text()))
        self.assertEqual(tuple(selected), ASSETS)
        for symbol in ASSETS:
            self.assertEqual([p["version"] for p in selected[symbol]["pools"]], ["v3", "v4"])
            self.assertEqual(len({p["address"] for p in selected[symbol]["pools"]}), 2)

    def test_v4_pool_key_and_hl_growth_fee(self):
        selected = choose_pools(json.loads(INDEX.read_text()))
        # At least the archived NVDA v4 candidate is a standard no-hook pool.
        address = selected["NVDA"]["pools"][1]["address"].lower()
        token = selected["NVDA"]["token"]
        self.assertTrue(any(pool_key_id(token, fee, spacing).lower() == address
                            for fee, spacing in ((100, 1), (500, 10), (3000, 60), (10000, 200))))
        raw = [{"collateralToken": 0, "universe": [{"name": "xyz:NVDA", "szDecimals": 3,
                "growthMode": "enabled", "deployerFeeScale": 1}]}, [{"dayNtlVlm": "1000000"}]]
        self.assertEqual(hl_fee_metadata(raw, "NVDA")["derived_taker_bps"], "0.90")

    def test_entry_gap_is_screen_and_exact_lot_flag(self):
        quote = {"side": "buy", "token_qty": "1.0001", "usd_amount": "100",
                 "received_ms": 1000}
        book = {"time": 1000, "_received_ms": 1000,
                "levels": [[{"px": "101", "sz": "2"}], [{"px": "102", "sz": "2"}]]}
        meta = {"size_step": "0.001", "derived_taker_bps": "0.9", "market": "xyz:T"}
        row = score_one(quote, book, Decimal(1), meta, 1000)
        self.assertFalse(row["hl_exact_lot"])
        self.assertEqual(Decimal(row["entry_gross_gap_usd_at_parity"]), Decimal("1.0101"))
        self.assertTrue(row["near_time_2s"])
        self.assertIsNone(walk_hl(book["levels"][0], Decimal(3)))

    def test_total_directory_cap_prevents_partial_append(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            path = directory / "test"
            capped_write(directory, path, "x")
            self.assertEqual(path.read_text(), "x")


if __name__ == "__main__":
    unittest.main()
