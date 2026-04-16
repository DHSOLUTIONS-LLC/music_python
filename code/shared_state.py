"""
shared_state.py — In-memory progress store with TTL cleanup.
"""
import threading
import time
from typing import Any, Dict, Optional

_store: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_TTL_SECONDS = 3600

def set_progress(session_id: str, data: Dict[str, Any]) -> None:
    with _lock:
        _store[session_id] = {**data, "_ts": time.time()}

def get_progress(session_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        entry = _store.get(session_id)
        if entry is None:
            return None
        return {k: v for k, v in entry.items() if k != "_ts"}

def delete_progress(session_id: str) -> None:
    with _lock:
        _store.pop(session_id, None)

def clear_all_progress() -> None:
    with _lock:
        _store.clear()

def cleanup_stale(ttl: int = _TTL_SECONDS) -> int:
    cutoff = time.time() - ttl
    with _lock:
        stale = [sid for sid, v in _store.items() if v.get("_ts", 0) < cutoff]
        for sid in stale:
            del _store[sid]
    return len(stale)
