"""Synthetic fixtures with explicit expected values; no fabricated project results."""
import tempfile
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

try:
    import duckdb
except ImportError:
    duckdb = None

from fabric_project.bronze import BronzeStore
from fabric_project.local_build import build_tables, find_inputs, literal, main, table_fingerprint, verify


@unittest.skipIf(duckdb is None, "Install requirements-local.txt for integration tests")
class LocalBuildTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.con = duckdb.connect()
        self.path = Path(self.folder.name) / "fixture.parquet"
        self.con.execute("""CREATE TABLE fixture AS
          SELECT * FROM (VALUES
            ('2025-06-06 10:00:00','2025-06-06 10:05:00',1,0.,110.,110.),
            ('2025-06-07 10:00:00','2025-06-07 10:05:00',1,1.,-11.,-11.),
            ('2025-06-08 10:00:00','2025-06-08 10:05:00',999,2.,22.,22.),
            ('2025-06-08 11:00:00','2025-06-08 11:05:00',1,1.,NULL,NULL),
            ('2025-06-09 10:00:00','2025-06-09 10:05:00',1,1.,44.,44.),
            (NULL,'2025-06-08 10:05:00',1,1.,5.,5.)
          ) AS t(tpep_pickup_datetime,tpep_dropoff_datetime,PULocationID,trip_distance,fare_amount,total_amount)""")
        self.con.execute(f"COPY fixture TO {literal(self.path)} (FORMAT PARQUET)")
        self.con.execute("CREATE TABLE dim_zone AS SELECT * FROM (VALUES (1,'Manhattan','Example','Yellow'),(-1,'Unknown','Unknown',NULL)) t(zone_id,borough,zone_name,service_zone)")
        self.con.execute("CREATE TABLE silver_fx AS SELECT * FROM (VALUES (DATE '2025-06-06',1.1,true),(DATE '2025-06-09',2.0,true)) t(source_rate_date,usd_per_eur,is_valid_rate)")

    def tearDown(self):
        self.con.close()
        self.folder.cleanup()

    def run_build(self):
        build_tables(self.con, self.path, date(2025,6,6), date(2025,6,8))

    def seed_cache(self):
        store = BronzeStore(Path(self.folder.name) / "cache")
        capture_id = "a" * 32
        gdp = [{"pages": 1, "total": 1}, [
            {"countryiso3code": "USA", "date": "2024", "indicator": {"id": "NY.GDP.MKTP.CD"}, "value": 50}
        ]]
        sources = [
            ("nyc_taxi", self.path.read_bytes(), "parquet", "yellow_tripdata_2025-06.parquet"),
            ("taxi_zones", b"LocationID,Borough,Zone,service_zone\n1,Manhattan,Example,Yellow\n", "csv", "zones.csv"),
            ("world_bank_gdp", json.dumps(gdp).encode(), "json", "gdp.json"),
            ("ecb_fx", b"CURRENCY,CURRENCY_DENOM,TIME_PERIOD,OBS_VALUE\nUSD,EUR,2025-06-06,1.10\n", "csv", "fx.csv"),
        ]
        store.write_manifest(capture_id, [
            store.save(source, raw, extension, f"https://example.test/{name}", capture_id)
            for source, raw, extension, name in sources
        ])
        return store.root

    def test_real_sql_preserves_zero_negative_and_null_records(self):
        self.run_build()
        result = verify(self.con)
        self.assertEqual(result["source_rows"], 6)
        self.assertEqual(result["silver_rows"], 6)
        self.assertEqual(result["reporting_rows"], 4)
        self.assertEqual(result["outside_reporting_window_rows"], 1)
        self.assertEqual(result["missing_pickup_date_rows"], 1)
        self.assertEqual(result["zero_distance_trips_in_window"], 1)
        self.assertEqual(result["unknown_zone_trips"], 1)
        self.assertEqual(self.con.execute("SELECT sum(base_fare_usd) FROM fact_taxi_daily").fetchone()[0], Decimal("121"))
        self.assertEqual(self.con.execute("SELECT sum(known_base_fare_count) FROM fact_taxi_daily").fetchone()[0], 3)

    def test_sunday_uses_friday_rate_and_correct_conversion(self):
        self.run_build()
        day, rate = self.con.execute("SELECT source_rate_date, usd_per_eur FROM dim_fx WHERE report_date=DATE '2025-06-08'").fetchone()
        self.assertEqual(day, date(2025,6,6))
        self.assertAlmostEqual(float(rate), 1.1)
        self.assertEqual(self.con.execute("SELECT sum(total_charged_eur) FROM fact_taxi_daily").fetchone()[0], Decimal("110"))

    def test_rerun_keeps_same_counts_and_values(self):
        self.run_build()
        before = table_fingerprint(self.con, "fact_taxi_daily")
        self.run_build()
        self.assertEqual(before, table_fingerprint(self.con, "fact_taxi_daily"))
        self.assertEqual(verify(self.con)["reporting_rows"], 4)

    def test_missing_fx_does_not_delete_or_zero_charge(self):
        self.con.execute("DELETE FROM silver_fx")
        self.run_build()
        self.assertEqual(verify(self.con)["reporting_rows"], 4)
        self.assertIsNone(self.con.execute("SELECT sum(total_charged_eur) FROM fact_taxi_daily").fetchone()[0])
        self.assertEqual(self.con.execute("SELECT sum(total_charged_usd) FROM fact_taxi_daily").fetchone()[0], Decimal("121"))

    def test_duplicate_rate_fails_validation_instead_of_inflating_totals(self):
        self.run_build()
        self.con.execute("INSERT INTO dim_fx SELECT * FROM dim_fx LIMIT 1")
        with self.assertRaises(AssertionError):
            verify(self.con)

    def test_failed_build_preserves_last_success_pointer_and_releases_lock(self):
        workspace = Path(self.folder.name) / "runs"
        workspace.mkdir()
        pointer = workspace / "latest_success.json"
        original = '{"run_id":"previous-good-run"}'
        pointer.write_text(original)
        with self.assertRaises(ValueError):
            main(["--workspace", str(workspace), "--cache", str(Path(self.folder.name)/"missing")])
        self.assertEqual(pointer.read_text(), original)
        self.assertFalse((workspace / "build.lock").exists())
        failed = list((workspace / "runs").glob("*/run.json"))
        self.assertEqual(len(failed), 1)
        self.assertEqual(json.loads(failed[0].read_text())["status"], "failed")

    def test_cached_taxi_file_must_match_reporting_month(self):
        cache = self.seed_cache()
        self.assertEqual(find_inputs(cache, "2025-06")["nyc_taxi"]["bytes"], self.path.stat().st_size)
        with self.assertRaisesRegex(ValueError, "Cached taxi file does not match 2024-06"):
            find_inputs(cache, "2024-06")

    def test_failed_evidence_write_preserves_previous_success_pointer(self):
        workspace = Path(self.folder.name) / "build"
        workspace.mkdir()
        pointer = workspace / "latest_success.json"
        previous = '{"run_id":"previous-good-run"}'
        pointer.write_text(previous)
        report = Path(self.folder.name) / "occupied-directory"
        report.mkdir()
        with self.assertRaises(OSError):
            main(["--workspace", str(workspace), "--cache", str(self.seed_cache()), "--report", str(report)])
        self.assertEqual(pointer.read_text(), previous)
        failed, = (workspace / "runs").glob("*/run.json")
        self.assertEqual(json.loads(failed.read_text())["status"], "failed")

    def test_concurrent_build_is_rejected_before_touching_outputs(self):
        workspace = Path(self.folder.name) / "locked"
        workspace.mkdir()
        lock = workspace / "build.lock"
        lock.write_text("existing run")
        with self.assertRaises(FileExistsError):
            main(["--workspace", str(workspace), "--cache", str(workspace/"missing")])
        self.assertEqual(lock.read_text(), "existing run")


if __name__ == "__main__":
    unittest.main()
