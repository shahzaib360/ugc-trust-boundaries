"""Small, dependency-free HTTP helpers with retries and an on-disk gzip cache."""

from __future__ import annotations

import gzip
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "ugc-trust-boundaries-research/0.1 (+https://github.com/shahzaib360/ugc-trust-boundaries)"


def fetch(url: str, retries: int = 5, timeout: float = 60.0) -> bytes:
    delay = 2.0
    last: Exception | None = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
        time.sleep(delay)
        delay *= 2
    raise RuntimeError(f"failed to fetch {url}: {last}")


def cached_fetch(url: str, path: Path) -> bytes:
    """Fetch ``url`` once; later calls read the gzip copy at ``path``."""
    if path.exists():
        with gzip.open(path, "rb") as fh:
            return fh.read()
    data = fetch(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(data)
    tmp.replace(path)
    return data
