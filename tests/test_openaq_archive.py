"""Probe the archive's time-ending format and reviewed geographic joins."""
import gzip
import unittest
from datetime import date

from fabric_project.openaq_archive import locate_station, parse_archive


class OpenAQArchiveTests(unittest.TestCase):
    def test_ending_at_midnight_maps_to_previous_date_with_unknown_flag(self):
        raw = gzip.compress(
            "location_id,sensors_id,datetime,lat,lon,parameter,units,value\n"
            "384,673,2025-07-01T00:00:00-04:00,40.8197,-73.9481,pm25,µg/m³,3.7\n".encode("utf-8")
        )
        station = {"location_id": 384, "latitude": 40.8197, "longitude": -73.9481, "frequency_minutes": 60}
        row, = parse_archive(raw, station)
        self.assertEqual((row["report_date"], row["report_hour"]), (date(2025, 6, 30), 23))
        self.assertEqual(row["measurement_unit"], "µg/m³")
        self.assertIsNone(row["source_flagged"])
        self.assertTrue(row["is_reportable"])

    def test_geographic_match_rejects_holes_and_boundaries(self):
        shape = {"features": [{
            "properties": {"locationid": 152, "zone": "Test zone", "borough": "Manhattan"},
            "geometry": {"type": "MultiPolygon", "coordinates": [[
                [[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]],
                [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
            ]]},
        }]}
        station = {"location_id": 384, "longitude": 4, "latitude": 2}
        self.assertEqual(locate_station(station, shape)["zone_id"], 152)
        for longitude in (0, 1, 2, 6):
            with self.subTest(longitude=longitude), self.assertRaises(ValueError):
                locate_station({**station, "longitude": longitude}, shape)


if __name__ == "__main__":
    unittest.main()
