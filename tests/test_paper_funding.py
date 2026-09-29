"""Settlement-aware funding tests with public API responses mocked in memory."""
import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paper_funding import FundingService


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self.body


class Session:
    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.calls = []

    def request(self, method, url, *, params=None, json=None):
        self.calls.append((method, url, params, json))
        if not self.bodies:
            raise AssertionError("unexpected API call")
        return Response(self.bodies.pop(0))


def leg(venue, market, side="long", start=10, end=20, quantity=2):
    return {"venue": venue, "market": market, "side": side,
            "entry_time": start, "exit_time": end, "quantity": quantity}


class FundingTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_hour_crossing_needs_no_request(self):
        session = Session()
        service = FundingService(session)
        result = await service.cashflows({"legs": [leg("hyperliquid", "BTC"), leg("rh_lighter", 1)]})
        self.assertEqual(result["cashflow_usd"], 0)
        self.assertTrue(result["complete"])
        self.assertEqual(session.calls, [])

    async def test_hourly_settlement_sign_and_observed_oracle_estimate(self):
        session = Session([{"time": 3600004, "fundingRate": "0.001"}])
        service = FundingService(session)
        service.observe_reference("hyperliquid", "BTC", 3600.5, 100, "oracle")
        result = await service.cashflows({"legs": [leg("hyperliquid", "BTC", "short", 3590, 3610, 2)]})
        self.assertTrue(result["complete"])
        self.assertTrue(result["estimated"])
        self.assertAlmostEqual(result["cashflow_usd"], 0.2)
        self.assertEqual(result["events"][0]["source"], "sampled_oracle_price")
        self.assertEqual(result["events"][0]["quality"], "estimated")
        self.assertEqual(session.calls[0][3]["type"], "fundingHistory")

    async def test_missing_rate_and_price_are_incomplete(self):
        for response, reason in [([], "settlement_rate_missing"),
                                 ([{"time": 3600000, "fundingRate": "0.001"}], "settlement_reference_missing")]:
            service = FundingService(Session(response))
            result = await service.cashflows({"legs": [leg("hyperliquid", "BTC", start=3590, end=3610)]})
            self.assertFalse(result["complete"])
            self.assertIsNone(result["cashflow_usd"])
            self.assertEqual(result["missing"][0]["reason"], reason)

    async def test_lighter_percent_direction_value_and_refund(self):
        # $0.9376992 / (0.0012% of ~$78,141.60) is a per-BTC settlement value.
        row = {"timestamp": 3600, "rate": "0.0012", "direction": "long", "value": "0.93769920"}
        session = Session({"code": 200, "fundings": [row]})
        result = await FundingService(session).cashflows({"legs": [leg("rh_lighter", 42, "short", 3590, 3610, 2)]})
        self.assertTrue(result["complete"])
        self.assertTrue(result["estimated"])
        self.assertAlmostEqual(result["cashflow_usd"], 1.8753984)
        self.assertAlmostEqual(result["events"][0]["rate_fraction"], 0.000012)
        self.assertEqual(result["events"][0]["quality"], "estimated")
        self.assertEqual(session.calls[0][2]["resolution"], "1h")
        row = {"timestamp": 3600, "rate": "0.0012", "direction": "short", "value": "0.93769920"}
        result = await FundingService(Session({"code": 200, "fundings": [row]})).cashflows(
            {"legs": [leg("lighter", 42, "short", 3590, 3610, 2)]})
        self.assertAlmostEqual(result["cashflow_usd"], -1.8753984)
        self.assertLess(result["events"][0]["rate_fraction"], 0)

    async def test_lighter_missing_hour_is_not_zero(self):
        response = {"code": 200, "fundings": [{"timestamp": 3600, "rate": "0", "direction": "long", "value": "0"}]}
        result = await FundingService(Session(response)).cashflows(
            {"legs": [leg("lighter", 1, start=3500, end=7300)]})
        self.assertFalse(result["complete"])
        self.assertIsNone(result["cashflow_usd"])
        self.assertIn("settlement_rate_missing", [x["reason"] for x in result["missing"]])

    async def test_hourly_cache_reuses_market_settlement_across_changing_ends(self):
        session = Session({"code": 200, "fundings":
                           [{"timestamp": 3600, "rate": "0", "direction": "long", "value": "0"}]})
        service = FundingService(session)
        first = await service.cashflows({"legs": [leg("lighter", 7, start=3590, end=3610)]})
        second = await service.cashflows({"legs": [leg("lighter", 7, start=3500, end=3700)]})
        self.assertTrue(first["complete"] and second["complete"])
        self.assertEqual(len(session.calls), 1)

    async def test_aster_cache_reuses_same_asof_but_not_later_open_mark(self):
        session = Session([], [])
        service = FundingService(session)
        with patch("paper_funding.time.time", return_value=3631):
            first = await service.cashflows({"legs": [leg("aster", "BTCUSDT", start=3620, end=3630)]})
            again = await service.cashflows({"legs": [leg("aster", "BTCUSDT", start=3625, end=3630)]})
        self.assertTrue(first["complete"] and again["complete"])
        self.assertEqual(len(session.calls), 1)
        service._next_request["aster"] = 0
        with patch("paper_funding.time.time", return_value=3641):
            later = await service.cashflows({"legs": [leg("aster", "BTCUSDT", start=3620, end=3640)]})
        self.assertTrue(later["complete"])
        self.assertEqual(len(session.calls), 2)

    async def test_aster_variable_event_history_and_empty_window(self):
        session = Session([])
        result = await FundingService(session).cashflows({"legs": [leg("aster", "BTCUSDT", start=30, end=40)]})
        self.assertTrue(result["complete"])
        self.assertEqual(result["cashflow_usd"], 0)
        self.assertEqual(session.calls[0][2]["startTime"], 0)
        service = FundingService(Session([{"symbol": "BTCUSDT", "fundingTime": 3650000, "fundingRate": "-0.002"}]))
        service.observe_reference("aster", "BTCUSDT", 3650, 100, "mark")
        result = await service.cashflows({"legs": [leg("aster", "BTCUSDT", "long", start=3620, end=3700, quantity=2)]})
        self.assertTrue(result["complete"])
        self.assertTrue(result["estimated"])
        self.assertAlmostEqual(result["cashflow_usd"], 0.4)

    async def test_aster_charge_window_ambiguous_near_entry(self):
        session = Session([{"symbol": "BTCUSDT", "fundingTime": 3600000, "fundingRate": "0.001"}])
        result = await FundingService(session).cashflows(
            {"legs": [leg("aster", "BTCUSDT", start=3605, end=3800)]})
        self.assertFalse(result["complete"])
        self.assertIsNone(result["cashflow_usd"])
        self.assertIn("settlement_sequence_uncertain_15s", [x["reason"] for x in result["missing"]])

    async def test_aster_empty_crossed_hour_needs_prior_schedule_proof(self):
        first = await FundingService(Session([])).cashflows(
            {"legs": [leg("aster", "BTCUSDT", start=3590, end=3610)]})
        self.assertFalse(first["complete"])
        self.assertIsNone(first["cashflow_usd"])
        self.assertEqual(first["missing"][0]["reason"], "aster_empty_hour_schedule_unverified")
        service = FundingService(Session([]))
        service.observe_aster_schedule("BTCUSDT", 3595, 7200)
        result = await service.cashflows({"legs": [leg("aster", "BTCUSDT", start=3590, end=3610)]})
        self.assertTrue(result["complete"])
        self.assertEqual(result["cashflow_usd"], 0)
        service = FundingService(Session([]))
        service.observe_aster_schedule("BTCUSDT", 3605, 7200)  # after boundary cannot prove it
        result = await service.cashflows({"legs": [leg("aster", "BTCUSDT", start=3590, end=3610)]})
        self.assertFalse(result["complete"])
        near = await FundingService(Session([])).cashflows(
            {"legs": [leg("aster", "BTCUSDT", start=3580, end=3595)]})
        self.assertFalse(near["complete"])
        self.assertEqual(near["missing"][0]["reason"], "aster_empty_hour_schedule_unverified")

    async def test_entry_boundary_excluded_and_exit_boundary_included(self):
        result = await FundingService(Session()).cashflows(
            {"legs": [leg("hyperliquid", "BTC", start=3600, end=3601)]})
        self.assertEqual(result["cashflow_usd"], 0)
        response = {"code": 200, "fundings": [{"timestamp": 3600, "rate": "0", "direction": "long", "value": "0"}]}
        result = await FundingService(Session(response)).cashflows(
            {"legs": [leg("lighter", 1, start=3599, end=3600)]})
        self.assertEqual(result["cashflow_usd"], 0)
        self.assertEqual(len(result["events"]), 1)

    async def test_bounded_state_roundtrip(self):
        service = FundingService(Session(), max_cache_events=2)
        for i in range(5):
            service.observe_reference("hyperliquid", "BTC", i, 100 + i)
        self.assertEqual(len(service.dump_state()["references"]), 1)
        loaded = FundingService(Session(), max_cache_events=2)
        loaded.load_state(service.dump_state())
        self.assertEqual(len(loaded.dump_state()["references"]), 1)
        self.assertIsNotNone(loaded._reference("hyperliquid", "BTC", 0))
        loaded.observe_aster_schedule("BTCUSDT", 3595, 7200)
        replay = FundingService(Session([]))
        replay.load_state(loaded.dump_state())
        self.assertTrue((await replay.cashflows({"legs": [leg("aster", "BTCUSDT", start=3590, end=3610)]}))["complete"])

    async def test_stream_reference_retention_keeps_nearest_boundary_sample(self):
        service = FundingService(Session(), max_cache_events=2)
        service.observe_reference("hyperliquid", "BTC", 3600.4, 100, "oracle")
        for second in range(3601, 4500):
            service.observe_reference("hyperliquid", "BTC", second, 200, "book")
        self.assertEqual(len(service.dump_state()["references"]), 1)
        ref = service._reference("hyperliquid", "BTC", 3600)
        self.assertEqual(ref[2], 100)
        self.assertEqual(ref[3], "oracle")
        service.observe_reference("aster", "BTCUSDT", 3600.2, 103)
        self.assertEqual(service._reference("aster", "BTCUSDT", 3600)[3], "mark")

    async def test_public_reference_batches(self):
        hl = [{"universe": [{"name": "BTC"}, {"name": "ETH"}]},
              [{"oraclePx": "100"}, {"oraclePx": "200"}]]
        session = Session(hl, {"code": 200, "order_book_details":
                               [{"market_id": 7, "index_price": "103"}]},
                          [{"symbol": "BTCUSDT", "markPrice": "104", "time": 3595000,
                            "nextFundingTime": 7200000}])
        service = FundingService(session)
        self.assertEqual((await service.sample_references([{"venue": "hyperliquid", "market": "BTC"}]))["sampled"],
                         {"hyperliquid": 1})
        self.assertEqual((await service.sample_references([{"venue": "rh_lighter", "market": 7}]))["sampled"],
                         {"rh_lighter": 1})
        self.assertEqual((await service.sample_references([{"venue": "aster", "market": "BTCUSDT"}]))["sampled"],
                         {"aster": 1})
        self.assertIsNotNone(service._reference("aster", "BTCUSDT", 3600))
        self.assertTrue(service._aster_hour_proven("BTCUSDT", 3600, 3590, 3610))


if __name__ == "__main__":
    unittest.main()
