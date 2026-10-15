"""The Flo Assistant's send log: what went where, kept on this PC.

One JSON line per request in `<user dir>/ai_log/YYYY-MM-DD.jsonl`, so
"show me what left the machine" has an answer that outlives the chat. A
request repeats the whole conversation, so a line holds only what is new
since the line before it (and the system prompt only when it changed) —
read in order, a day's file is the conversation as the server received it.

The folder is owner-only, like the key file: it holds column names and
whatever else the chosen level let through. A log that cannot be written
never stops a send — the outbox in the dock still shows every request.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from ..paths import user_data_dir

LOG_FOLDER = "ai_log"


def log_dir() -> Path:
    return user_data_dir() / LOG_FOLDER


class SendLog:
    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = directory
        self.reset()

    def reset(self) -> None:
        """A new conversation: the next line starts from the beginning."""
        self._sent = 0
        self._system = None

    def new_messages(self, entry: dict) -> list:
        """What this request adds to the one before it."""
        messages = entry.get("messages") or []
        out = []
        if messages and messages[0].get("role") == "system":
            if messages[0].get("content") != self._system:
                out.append(messages[0])
            start = max(self._sent, 1)
        else:
            start = self._sent
        return out + list(messages[start:])

    def write(self, entry: dict, meta: dict) -> Optional[Path]:
        record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S",
                                        time.localtime(entry.get("time"))),
                  **meta, "tools": entry.get("tools", []),
                  "messages": self.new_messages(entry)}
        messages = entry.get("messages") or []
        self._sent = len(messages)
        if messages and messages[0].get("role") == "system":
            self._system = messages[0].get("content")
        folder = self.directory or log_dir()
        path = folder / time.strftime("%Y-%m-%d.jsonl",
                                      time.localtime(entry.get("time")))
        try:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str,
                                        ensure_ascii=False) + "\n")
        except OSError:
            return None
        return path
