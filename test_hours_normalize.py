import unittest
from hours_normalize import normalize_opening_hours, parse_place_details_response


class NormalizeOpeningHours(unittest.TestCase):
    def test_none_or_empty_returns_none(self):
        self.assertIsNone(normalize_opening_hours(None))
        self.assertIsNone(normalize_opening_hours([]))

    def test_open_24_7_expands_to_seven_full_days(self):
        periods = [{"open": {"day": 0, "time": "0000"}}]
        result = normalize_opening_hours(periods)
        self.assertEqual(len(result), 7)
        self.assertEqual(result[0], {"d": 0, "o": "0000", "c": "2400"})
        self.assertEqual(result[6], {"d": 6, "o": "0000", "c": "2400"})

    def test_two_shifts_same_day(self):
        periods = [
            {"open": {"day": 1, "time": "1100"}, "close": {"day": 1, "time": "1430"}},
            {"open": {"day": 1, "time": "1700"}, "close": {"day": 1, "time": "2100"}},
        ]
        self.assertEqual(
            normalize_opening_hours(periods),
            [{"d": 1, "o": "1100", "c": "1430"}, {"d": 1, "o": "1700", "c": "2100"}],
        )

    def test_single_day_open_24h_is_kept(self):
        # Google 以「該日有 open、無 close」表示這天 24 小時營業；不能整天丟掉
        periods = [
            {"open": {"day": 1, "time": "0000"}},
            {"open": {"day": 2, "time": "1100"}, "close": {"day": 2, "time": "2100"}},
        ]
        self.assertEqual(
            normalize_opening_hours(periods),
            [{"d": 1, "o": "0000", "c": "2400"}, {"d": 2, "o": "1100", "c": "2100"}],
        )

    def test_cross_midnight_keeps_close_time(self):
        periods = [{"open": {"day": 5, "time": "1800"}, "close": {"day": 6, "time": "0200"}}]
        self.assertEqual(normalize_opening_hours(periods), [{"d": 5, "o": "1800", "c": "0200"}])

    def test_malformed_period_is_skipped(self):
        periods = [
            {"open": {"day": 2, "time": "0900"}, "close": {"day": 2, "time": "1700"}},
            {"open": {"day": 3}},  # 缺 time/close
        ]
        self.assertEqual(normalize_opening_hours(periods), [{"d": 2, "o": "0900", "c": "1700"}])

    def test_all_malformed_returns_none(self):
        self.assertIsNone(normalize_opening_hours([{"open": {"day": 3}}]))


class ParsePlaceDetails(unittest.TestCase):
    def test_full_response(self):
        data = {"result": {
            "formatted_address": "台北市大安區信義路二段194號",
            "opening_hours": {
                "periods": [{"open": {"day": 1, "time": "1100"}, "close": {"day": 1, "time": "1430"}}],
                "weekday_text": ["星期一: 11:00 – 14:30", "星期二: 休息"],
            },
        }}
        out = parse_place_details_response(data)
        self.assertEqual(out["address"], "台北市大安區信義路二段194號")
        self.assertEqual(out["hours"], [{"d": 1, "o": "1100", "c": "1430"}])
        self.assertEqual(out["hours_text"], "星期一: 11:00 – 14:30 / 星期二: 休息")

    def test_no_opening_hours(self):
        data = {"result": {"formatted_address": "某地址"}}
        out = parse_place_details_response(data)
        self.assertEqual(out["address"], "某地址")
        self.assertIsNone(out["hours"])
        self.assertEqual(out["hours_text"], "")

    def test_empty_data(self):
        out = parse_place_details_response({})
        self.assertEqual(out["address"], "")
        self.assertIsNone(out["hours"])
        self.assertEqual(out["hours_text"], "")


if __name__ == "__main__":
    unittest.main()
