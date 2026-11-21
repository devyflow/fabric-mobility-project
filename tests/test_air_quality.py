"""Synthetic observation tests only; these values are not project findings."""
import copy
import json
import unittest
from datetime import date

from fabric_project.air_quality import deduplicate_observations, fetch_hourly_pages, normalize_observation


def fixture(start="2025-06-02T03:00:00Z", end="2025-06-02T04:00:00Z"):
    return {"value": 10, "parameter": {"name": "pm25", "units": "ug/m3"},
        "flagInfo": {"hasFlags": False}, "period": {"datetimeFrom": {"utc": start}, "datetimeTo": {"utc": end}}}


class AirQualityTests(unittest.TestCase):
    def test_midnight_ending_interval_belongs_to_previous_local_day(self):
        row = normalize_observation(fixture(), 1, 10)
        self.assertEqual(row["report_date"], date(2025,6,1))
        self.assertEqual(row["report_hour"], 23)
        self.assertTrue(row["is_reportable"])

    def test_fall_dst_repeated_local_hour_is_two_distinct_utc_hours(self):
        a = normalize_observation(fixture("2025-11-02T05:00:00Z", "2025-11-02T06:00:00Z"), 1, 10)
        b = normalize_observation(fixture("2025-11-02T06:00:00Z", "2025-11-02T07:00:00Z"), 1, 10)
        self.assertEqual(a["report_hour"], 1)
        self.assertEqual(b["report_hour"], 1)
        self.assertEqual(len(deduplicate_observations([a,b])[0]), 2)

    def test_negative_and_source_flags_are_retained_but_not_reportable(self):
        raw = fixture()
        raw["value"], raw["flagInfo"]["hasFlags"] = -1, True
        row = normalize_observation(raw, 1, 10)
        self.assertEqual(row["value"], -1)
        self.assertIn("negative_value", row["quality_flags"])
        self.assertFalse(row["is_reportable"])

    def test_missing_offset_and_long_interval_are_flagged(self):
        self.assertFalse(normalize_observation(fixture("2025-06-02T03:00:00"),1,10)["is_reportable"])
        self.assertIn("not_one_hour_interval", normalize_observation(fixture(end="2025-06-02T05:00:00Z"),1,10)["quality_flags"])

    def test_exact_repeat_deduplicates_but_conflicting_values_fail(self):
        a = normalize_observation(fixture(), 1, 10)
        self.assertEqual(deduplicate_observations([a, copy.deepcopy(a)])[1], 1)
        b = {**a, "value": 11}
        with self.assertRaises(ValueError):
            deduplicate_observations([a,b])

    def test_incomplete_page_count_fails(self):
        raw = json.dumps({"meta": {"page":1,"found":2}, "results":[fixture()]}).encode()
        with self.assertRaises(ValueError):
            list(fetch_hourly_pages(1,"2025-06-01T00:00:00Z","2025-06-02T00:00:00Z","fake",fetch=lambda *a, **kw:raw))


if __name__ == "__main__":
    unittest.main()
