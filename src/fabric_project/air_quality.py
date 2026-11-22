"""OpenAQ v3 paging and UTC interval rules, reusable by the local verifier."""
import json
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from .http import read_bytes


def fetch_hourly_pages(sensor_id, start_utc, end_utc, key, fetch=read_bytes):
    if not isinstance(sensor_id, int) or sensor_id <= 0:
        raise ValueError("Sensor ID must be a positive integer")
    expected_total = None
    count = 0
    seen_pages = set()
    for page in range(1, 101):
        query = urlencode({"datetime_from": start_utc, "datetime_to": end_utc, "limit": 1000, "page": page})
        url = f"https://api.openaq.org/v3/sensors/{sensor_id}/hours?{query}"
        raw = fetch(url, headers={"X-API-Key": key})
        body = json.loads(raw)
        meta, rows = body.get("meta", {}), body.get("results")
        if not isinstance(rows, list) or int(meta.get("page", -1)) != page:
            raise ValueError("Invalid OpenAQ page envelope")
        if len(rows) > 1000:
            raise ValueError("OpenAQ page exceeds requested limit")
        signature = json.dumps(rows, sort_keys=True)
        if rows and signature in seen_pages:
            raise ValueError("OpenAQ repeated a page; refusing partial coverage")
        seen_pages.add(signature)
        found = meta.get("found")
        if isinstance(found, int) or (isinstance(found, str) and found.isdigit()):
            if expected_total is not None and expected_total != int(found):
                raise ValueError("OpenAQ result count changed during pagination; rerun window")
            expected_total = int(found)
        count += len(rows)
        yield url, raw, rows, page
        if len(rows) < 1000:
            if expected_total is not None and count != expected_total:
                raise ValueError("Incomplete OpenAQ pagination")
            return
    raise ValueError("OpenAQ paging exceeded safety bound")


def normalize_observation(row, sensor_id, location_id, require_source_flag=True):
    period = row.get("period") or {}
    flags = []
    def parse(label):
        text = (period.get(label) or {}).get("utc")
        try:
            stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Offset required")
            return stamp.astimezone(timezone.utc)
        except (ValueError, TypeError, AttributeError):
            flags.append("invalid_" + label)
            return None
    start, end = parse("datetimeFrom"), parse("datetimeTo")
    if start and end and end - start != timedelta(hours=1):
        flags.append("not_one_hour_interval")
    parameter = row.get("parameter") or {}
    pollutant = (parameter.get("name") or "").strip().lower()
    units = (parameter.get("units") or "").strip()
    if not pollutant or not units:
        flags.append("missing_pollutant_or_unit")
    value = row.get("value")
    if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value):
        flags.append("missing_or_nonfinite_value")
    elif value < 0:
        flags.append("negative_value")
    source_flagged = (row.get("flagInfo") or {}).get("hasFlags")
    if source_flagged is True or (require_source_flag and source_flagged is not False):
        flags.append("upstream_flagged_or_unknown")
    local = start.astimezone(ZoneInfo("America/New_York")) if start else None
    return {"sensor_id": sensor_id, "location_id": location_id,
        "hour_start_utc": start, "hour_end_utc": end,
        "report_date": local.date() if local else None,
        "report_hour": local.hour if local else None,
        "pollutant_code": pollutant, "measurement_unit": units,
        "value": value, "quality_flags": flags, "is_reportable": not flags,
        "source_flagged": source_flagged}


def deduplicate_observations(records):
    """Discard only exact normalized repeats; conflicting sensor hours fail."""
    unique, skipped = {}, 0
    for row in records:
        # Missing UTC timestamps cannot prove identity: retain every such row.
        if row["hour_start_utc"] is None:
            key = ("unparsed", len(unique))
        else:
            key = (row["sensor_id"], row["hour_start_utc"])
        if key in unique:
            if unique[key] != row:
                raise ValueError("Conflicting measurements for one sensor and UTC hour")
            skipped += 1
        else:
            unique[key] = row
    return list(unique.values()), skipped
