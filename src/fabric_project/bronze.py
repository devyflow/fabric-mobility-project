"""Preserve exact source bytes; successful payloads are addressed by SHA-256."""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


class BronzeStore:
    def __init__(self, root):
        self.root = Path(root)

    def save(self, source, payload, extension, source_url, run_id):
        if not re.fullmatch(r"[a-z0-9_]+", source):
            raise ValueError("Invalid source identifier")
        if extension not in ("json", "csv", "csv.gz", "geojson", "parquet"):
            raise ValueError("Unsupported payload extension")
        digest = hashlib.sha256(payload).hexdigest()
        path = self.root / source / f"{digest}.{extension}"
        already_present = path.exists()
        if already_present:
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Existing Bronze payload failed integrity verification")
        else:
            write_atomic(path, payload)
        return {
            "source": source, "sha256": digest, "bytes": len(payload),
            "path": path.relative_to(self.root).as_posix(), "source_url": source_url,
            "run_id": run_id, "ingested_at_utc": utc_now(),
            "reused_identical_payload": already_present,
        }

    def write_manifest(self, run_id, records):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run ID")
        path = self.root / "_runs" / f"{run_id}.json"
        write_atomic(path, json.dumps(records, indent=2).encode("utf-8"))
        return path
