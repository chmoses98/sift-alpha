"""Bounded retry for transient network failures on pinned, hash-verified reads.

Only transport-level/transient errors are retried (timeouts, connection errors, truncated bodies, HTTP 408/425/429/5xx).
Permanent client errors (other 4xx) and everything the caller verifies afterwards (redirect, size, hash) are NOT retried or
weakened: callers still check the payload against a pinned digest."""
from __future__ import annotations

import http.client
import time
from urllib.error import HTTPError
from urllib.request import urlopen

ATTEMPTS = 4
BACKOFF = (2, 4, 8)
TRANSIENT_HTTP = {408, 425, 429}


def transient(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in TRANSIENT_HTTP or exc.code >= 500
    return isinstance(exc, (OSError, TimeoutError, http.client.HTTPException))


def read_with_retry(request, timeout, max_bytes, opener=urlopen, sleep=time.sleep, expect_url=None, attempts=ATTEMPTS):
    """Open + read up to max_bytes (+1 so oversize is detectable). Raises the last error after `attempts` tries."""
    last = None
    for n in range(attempts):
        try:
            with opener(request, timeout=timeout) as resp:
                if expect_url is not None and resp.geturl() != expect_url:
                    raise ValueError("Unexpected redirect: don't access unapproved host")
                return resp.read(max_bytes + 1)
        except ValueError:
            raise
        except BaseException as exc:      # noqa: BLE001 - classified below, non-transient re-raised
            if not transient(exc):
                raise
            last = exc
            if n < attempts - 1:
                sleep(BACKOFF[min(n, len(BACKOFF) - 1)])
    raise last
