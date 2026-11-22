"""Validate Air Quality aggregation with labelled, synthetic hourly fixtures."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None

from fabric_project.local_air import build_air
from test_air_quality import fixture


@unittest.skipIf(duckdb is None, "Install local requirements")
class LocalAirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.con = duckdb.connect()
        self.con.execute("CREATE TABLE dim_date AS SELECT DATE '2025-06-01' AS report_date")
        self.con.execute("CREATE TABLE fact_taxi_daily AS SELECT DATE '2025-06-01' AS report_date,1 AS pickup_zone_id,100 AS trip_count")

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def prepare(self, rows):
        payload = json.dumps({"meta":{"page":1},"results":rows}).encode()
        (self.cache/"page.json").write_bytes(payload)
        (self.cache/"manifest.json").write_text(json.dumps([{
            "source":"openaq_hourly","path":"page.json","sha256":hashlib.sha256(payload).hexdigest(),
            "sensor_id":1,"location_id":10,"result_count":len(rows)}]))
        (self.cache/"openaq_latest.json").write_text(json.dumps({"run_id":"synthetic-test-only", "manifest":"manifest.json",
            "stations":[{"location_id":10,"station_name":"Synthetic fixture","latitude":40.7,"longitude":-74.0,"zone_id":1}]}))

    def test_missing_capture_reports_blocker_without_fake_tables(self):
        result = build_air(self.con, self.cache)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["tables"], [])

    def test_exact_duplicates_and_negative_values_accounted_for(self):
        a = fixture("2025-06-01T04:00:00Z","2025-06-01T05:00:00Z")
        b = fixture("2025-06-01T05:00:00Z","2025-06-01T06:00:00Z")
        b["value"] = 20
        bad = fixture("2025-06-01T06:00:00Z","2025-06-01T07:00:00Z")
        bad["value"] = -1
        self.prepare([a,a,b,bad])
        result = build_air(self.con,self.cache)
        self.assertEqual(result["source_rows"],4)
        self.assertEqual(result["silver_rows"],3)
        self.assertEqual(result["exact_duplicate_rows"],1)
        self.assertEqual(result["non_reportable_rows"],1)
        self.assertEqual(self.con.execute("SELECT observed_hour_count,concentration_mean FROM fact_air_quality_daily").fetchone(),(2,15.0))
        self.assertEqual(self.con.execute("SELECT count(*),sum(trip_count) FROM matched_air_taxi").fetchone(),(1,100))

    def test_units_stay_separate(self):
        a = fixture("2025-06-01T04:00:00Z","2025-06-01T05:00:00Z")
        b = fixture("2025-06-01T05:00:00Z","2025-06-01T06:00:00Z")
        b["parameter"]["units"] = "ppb"
        self.prepare([a,b])
        build_air(self.con,self.cache)
        self.assertEqual(self.con.execute("SELECT count(*) FROM fact_air_quality_daily").fetchone()[0],2)

    def test_low_coverage_stays_in_air_fact_but_does_not_pair(self):
        self.prepare([fixture("2025-06-01T04:00:00Z", "2025-06-01T05:00:00Z")])
        result = build_air(self.con, self.cache, min_hours=18)
        self.assertEqual(result["daily_rows"], 1)
        self.assertEqual(result["matched_days_by_series"], 0)
        self.assertEqual(self.con.execute("SELECT observed_hour_count FROM fact_air_quality_daily").fetchone(), (1,))

    def test_conflicting_sensor_hour_fails_before_publication(self):
        a = fixture("2025-06-01T04:00:00Z","2025-06-01T05:00:00Z")
        b = fixture("2025-06-01T04:00:00Z","2025-06-01T05:00:00Z")
        b["value"] = 20
        self.prepare([a,b])
        with self.assertRaises(ValueError):
            build_air(self.con,self.cache)


if __name__ == "__main__":
    unittest.main()
