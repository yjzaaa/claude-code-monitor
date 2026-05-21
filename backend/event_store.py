"""事件存储 - 内存缓存 + JSONL 文件持久化"""

import json
import threading
import time
from collections import deque
from pathlib import Path
from datetime import datetime


class EventStore:
    def __init__(self, log_path: str = "logs/events.jsonl", max_events: int = 1000):
        self._events: deque = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._tool_counts: dict[str, int] = {}
        self._session_start: float | None = None
        self._status: str = "idle"  # idle | running | error
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def add_event(self, event: dict):
        """添加一个事件，写入内存和文件"""
        event["timestamp"] = time.time()
        event["time_str"] = datetime.now().strftime("%H:%M:%S")

        with self._lock:
            # 更新状态
            event_type = event.get("event")
            if event_type == "session_start":
                self._session_start = time.time()
                self._status = "running"
                self._tool_counts.clear()
            elif event_type == "Stop":
                self._status = "idle"
            elif event_type == "PreToolUse":
                self._status = "running"
                tool = event.get("tool", "unknown")
                self._tool_counts[tool] = self._tool_counts.get(tool, 0) + 1

            self._events.append(event)

        # 持久化（不持锁写入文件）
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_events(self, since: float = 0) -> list[dict]:
        """获取指定时间戳之后的事件"""
        with self._lock:
            return [e for e in self._events if e["timestamp"] > since]

    def get_status(self) -> dict:
        """获取当前状态摘要"""
        with self._lock:
            uptime = 0.0
            if self._session_start and self._status == "running":
                uptime = time.time() - self._session_start

            return {
                "status": self._status,
                "uptime": round(uptime, 1),
                "tool_counts": dict(self._tool_counts),
                "total_tools": sum(self._tool_counts.values()),
                "event_count": len(self._events),
            }

    def reset(self):
        """重置所有状态"""
        with self._lock:
            self._events.clear()
            self._tool_counts.clear()
            self._session_start = None
            self._status = "idle"
