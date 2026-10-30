import json
import re
import time
from typing import Any, Callable

from .config import CACHE_DIR


def _path(source: str, key: str):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key)
    return CACHE_DIR / source / f"{safe}.json"


def cached(source: str, key: str, ttl_hours: float, fetch: Callable[[], Any]) -> Any:
    """Return a fresh cached value or call `fetch`. None results are not cached so they get retried."""
    path = _path(source, key)
    if path.exists():
        try:
            payload = json.loads(path.read_text())
            if time.time() - payload["ts"] < ttl_hours * 3600:
                return payload["data"]
        except (json.JSONDecodeError, KeyError):
            pass
    data = fetch()
    if data is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ts": time.time(), "data": data}))
    return data
