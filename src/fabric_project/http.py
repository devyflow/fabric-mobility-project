"""Read-only HTTP with bounded retries; never log authentication headers."""

import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def read_bytes(url, headers=None, attempts=3, timeout=40):
    request = Request(url, headers={"User-Agent": "FabricLearningProject/0.1", **(headers or {})})
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise RuntimeError(f"HTTP {error.code}; request failed") from None
            # Honor numeric Retry-After without allowing an unbounded sleep.
            retry_after = error.headers.get("Retry-After", "")
            delay = min(30, max(2 ** attempt, int(retry_after))) if retry_after.isdigit() else 2 ** attempt
            time.sleep(delay)
        except (URLError, TimeoutError):
            if attempt == attempts - 1:
                raise RuntimeError("Network request failed after bounded retries") from None
            time.sleep(2 ** attempt)
    raise RuntimeError("No HTTP attempts configured")
