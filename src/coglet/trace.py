"""CogletTrace — jsonl event recorder for post-mortem debugging of async event flows.

Pass to CogletRuntime(trace=CogletTrace("path.jsonl")) to transparently record
all transmit() and enact() events with timestamps. Use CogletTrace.load() to
read traces back for analysis or replay.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class CogletTrace:
    """Records transmit/guide events to a jsonl file for replay debugging.

    Usage:
        trace = CogletTrace("trace.jsonl")
        runtime = CogletRuntime(trace=trace)
        # ... run coglets ...
        trace.close()
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._file = open(self._path, "w")
        self._start = time.monotonic()

    def record(self, coglet_type: str, op: str, target: str, data: Any) -> None:
        entry = {
            "t": round(time.monotonic() - self._start, 4),
            "coglet": coglet_type,
            "op": op,
            "target": target,
        }
        try:
            entry["data"] = data
            line = json.dumps(entry, default=str)
        except (TypeError, ValueError):
            entry["data"] = repr(data)
            line = json.dumps(entry, default=str)
        self._file.write(line + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    @staticmethod
    def load(path: str | Path) -> list[dict]:
        """Load a trace file for inspection."""
        entries = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
