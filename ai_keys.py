import os
import itertools
import threading
from typing import Optional, Iterator, List, Tuple

_lock = threading.Lock()
_keys: List[Tuple[str, str]] = []
_cycle: Optional[Iterator[int]] = None


def load_keys() -> None:
    """(Re)load API keys from environment.

    GEMINI_API_KEYS: comma-separated list of keys.
    Fallback: single key in GEMINI_API_KEY.
    Creates a round-robin iterator of index positions.
    """
    global _keys, _cycle
    raw = os.getenv("GEMINI_API_KEYS", "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        _keys = [(f"k{i+1}", k) for i, k in enumerate(parts)]
    else:
        single = os.getenv("GEMINI_API_KEY")
        _keys = [("k1", single)] if single else []
    if not _keys:
        raise RuntimeError(
            "No Gemini API keys configured (set GEMINI_API_KEYS or GEMINI_API_KEY)."
        )
    _cycle = itertools.cycle(range(len(_keys)))


def get_next_key() -> Tuple[str, str]:
    """Return (label, api_key) using round-robin selection.

    Lazily initializes keys on first call. Thread-safe.
    """
    global _cycle
    with _lock:
        if _cycle is None:
            load_keys()
        # _cycle now guaranteed
        idx = next(_cycle)  # type: ignore[arg-type]
        return _keys[idx]


# Optional eager load (can be commented out if you prefer full laziness)
# try:
#     load_keys()
# except Exception:
#     pass
