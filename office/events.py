"""
Event stream for the live dashboard.

The runtime appends one JSON line per state change to office/logs/events.jsonl.
The dashboard tails that file. Separate processes, no sockets, no setup.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_FILE = LOG_DIR / "events.jsonl"
_lock = threading.Lock()


def emit(type: str, agent: str, run_id: str, depth: int = 0, **detail) -> dict:
    ev = {"ts": time.time(), "type": type, "agent": agent, "run_id": run_id, "depth": depth, **detail}
    line = json.dumps(ev, ensure_ascii=False)
    with _lock:
        with open(EVENTS_FILE, "a") as f:
            f.write(line + "\n")
    return ev


def read_tail(max_lines: int = 300) -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    with open(EVENTS_FILE, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        block = 65536
        data = b""
        while size > 0 and data.count(b"\n") <= max_lines:
            step = min(block, size)
            size -= step
            f.seek(size)
            data = f.read(step) + data
    lines = data.decode("utf-8", "ignore").splitlines()[-max_lines:]
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return out


def follow(start_offset: int | None = None):
    """Generator yielding new events as they are appended. start_offset=None starts at end of file."""
    pos = start_offset
    while True:
        if not EVENTS_FILE.exists():
            time.sleep(0.5)
            continue
        with open(EVENTS_FILE, "r") as f:
            if pos is None:
                f.seek(0, os.SEEK_END)
                pos = f.tell()
            else:
                f.seek(pos)
            while True:
                line = f.readline()
                if not line:
                    pos = f.tell()
                    break
                if line.endswith("\n"):
                    pos = f.tell()
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        pass
                else:
                    break  # partial line, wait
        time.sleep(0.4)
