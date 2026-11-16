import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from fabric_project.bronze import BronzeStore
from fabric_project.http import read_bytes
from fabric_project.preflight import get_openaq_locations, get_world_bank
from fabric_project.quality import preceding_rate, taxi_flags, usd_to_eur


class QualityTests(unittest.TestCase):
    def test_zero_distance_is_flagged_not_deleted(self):
        row = {"distance": 0, "fare": 5, "duration_seconds": 120}
        self.assertEqual(taxi_flags(**row), ["zero_distance"])
        self.assertEqual(row["fare"], 5)

    def test_missing_and_negative_values_are_distinct(self):
        self.assertIn("missing_distance", taxi_flags(None, 1, 1))
        self.assertIn("negative_fare_review", taxi_flags(1, -5, 1))
        self.assertIn("negative_duration", taxi_flags(1, 5, -1))

    def test_currency_direction(self):
        self.assertEqual(usd_to_eur(110, "1.10"), Decimal("100"))

    def test_unknown_rate_does_not_become_zero(self):
        self.assertIsNone(usd_to_eur(110, None))

    def test_bad_rate_rejected(self):
        for rate in [0, -1, "NaN", "Infinity"]:
            with self.assertRaises(ValueError):
                usd_to_eur(110, rate)

    def test_weekend_uses_previous_not_future_rate(self):
        rates = {"2025-06-06": 1.14, "2025-06-09": 1.15}
        self.assertEqual(preceding_rate("2025-06-08", rates)["source_date"], "2025-06-06")
        self.assertIsNone(preceding_rate("2025-06-05", rates))

    def test_stale_rate_is_unavailable(self):
        self.assertIsNone(preceding_rate("2025-06-20", {"2025-06-06": 1.14}))


class BronzeTests(unittest.TestCase):
    def test_repeat_payload_does_not_create_second_data_file(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BronzeStore(folder)
            first = store.save("source", b'{"value":0}', "json", "https://example.org", "a" * 32)
            second = store.save("source", b'{"value":0}', "json", "https://example.org", "b" * 32)
            self.assertEqual(first["path"], second["path"])
            self.assertTrue(second["reused_identical_payload"])
            self.assertEqual(len(list(Path(folder).rglob("*.json"))), 1)

    def test_changed_source_preserves_both_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BronzeStore(folder)
            first = store.save("source", b"old", "csv", "https://example.org", "a" * 32)
            second = store.save("source", b"new", "csv", "https://example.org", "b" * 32)
            self.assertNotEqual(first["path"], second["path"])
            self.assertEqual((Path(folder) / first["path"]).read_bytes(), b"old")

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                BronzeStore(folder).save("../outside", b"x", "csv", "https://example.org", "a" * 32)

    def test_corrupt_existing_payload_fails_loudly(self):
        with tempfile.TemporaryDirectory() as folder:
            store = BronzeStore(folder)
            first = store.save("source", b"original", "csv", "https://example.org", "a" * 32)
            (Path(folder) / first["path"]).write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                store.save("source", b"original", "csv", "https://example.org", "b" * 32)


class PaginationTests(unittest.TestCase):
    config = {"country": "USA", "gdp_start_year": 2024, "gdp_end_year": 2025, "openaq_bbox": "-74,40,-73,41"}

    def test_world_bank_fetches_every_page(self):
        payloads = iter([
            [{"page": 1, "pages": 2, "total": 2}, [{"date": "2025"}]],
            [{"page": 2, "pages": 2, "total": 2}, [{"date": "2024"}]],
        ])
        result = get_world_bank(self.config, lambda url: json.dumps(next(payloads)).encode())
        self.assertEqual(len(result), 2)
        self.assertIn("page=2", result[1][0])

    def test_world_bank_partial_response_not_successful(self):
        data = [{"page": 1, "pages": 1, "total": 2}, [{"date": "2025"}]]
        with self.assertRaises(ValueError):
            get_world_bank(self.config, lambda url: json.dumps(data).encode())

    def test_openaq_full_page_requires_next_page(self):
        pages = iter([{"results": [{"id": n} for n in range(1000)]}, {"results": [{"id": 1000}]}])
        result = get_openaq_locations(self.config, "test-not-real", lambda url, headers: json.dumps(next(pages)).encode())
        self.assertEqual(sum(len(x[2]) for x in result), 1001)

    def test_openaq_repeated_page_is_detected(self):
        data = {"results": [{"id": n} for n in range(1000)]}
        with self.assertRaises(ValueError):
            get_openaq_locations(self.config, "test-not-real", lambda url, headers: json.dumps(data).encode())

    def test_unauthorized_request_is_not_retried(self):
        error = HTTPError("https://example.org", 401, "Unauthorized", {}, None)
        with patch("fabric_project.http.urlopen", side_effect=error) as request, patch("fabric_project.http.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                read_bytes("https://example.org", headers={"X-API-Key": "not-a-real-key"})
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()

    def test_transient_error_is_retried(self):
        error = HTTPError("https://example.org", 503, "Unavailable", {}, None)
        with patch("fabric_project.http.urlopen", side_effect=error) as request, patch("fabric_project.http.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                read_bytes("https://example.org")
            self.assertEqual(request.call_count, 3)


if __name__ == "__main__":
    unittest.main()
