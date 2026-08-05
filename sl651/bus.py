"""报文事件总线：中心站 <-> Web 实时推送 + SQLite 持久化"""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Deque, Optional

from .store import MessageStore, store as default_store


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


@dataclass
class MessageRecord:
    """一条收发记录"""

    id: str
    ts: str
    direction: str  # up | down | system
    peer: str
    raw_hex: str
    parsed: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "ts": self.ts,
            "direction": self.direction,
            "peer": self.peer,
            "raw_hex": self.raw_hex,
            "parsed": self.parsed,
            "error": self.error,
            "note": self.note,
        }
        if self.parsed:
            h = self.parsed.get("header") or {}
            b = self.parsed.get("body") or {}
            d["crc_ok"] = self.parsed.get("crc_ok")
            d["encoding"] = h.get("encoding")
            d["func_code"] = h.get("func_code")
            d["func_name"] = h.get("func_name")
            d["remote_addr"] = h.get("remote_addr") or b.get("remote_addr")
            d["center_addr"] = h.get("center_addr")
            d["serial_no"] = b.get("serial_no")
            d["send_time"] = b.get("send_time")
        return d


Listener = Callable[[dict[str, Any]], None]


class MessageBus:
    """内存环形缓存 + SQLite 持久化 + 订阅推送"""

    def __init__(
        self,
        max_history: int = 500,
        message_store: Optional[MessageStore] = None,
        persist: bool = True,
        console_log: bool = True,
    ) -> None:
        self._history: Deque[MessageRecord] = deque(maxlen=max_history)
        self._listeners: list[Listener] = []
        self._lock = threading.RLock()
        self._seq = 0
        self.store = message_store if message_store is not None else default_store
        self.persist = persist
        self.console_log = console_log

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.append(listener)

        def unsub() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsub

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        """优先从 SQLite 取最近记录，失败则回退内存"""
        if self.persist and self.store:
            try:
                return self.store.recent(limit)
            except Exception:
                pass
        with self._lock:
            items = list(self._history)[-limit:]
        return [m.to_dict() for m in items]

    def clear_memory(self) -> None:
        """仅清空内存环形缓存（不影响 SQLite）"""
        with self._lock:
            self._history.clear()

    def clear_store(self) -> int:
        """仅清空 SQLite（不影响内存缓存）"""
        if self.persist and self.store:
            try:
                return self.store.clear()
            except Exception as e:
                print(f"[bus] 清空数据库失败: {e}")
        return 0

    def clear(self) -> None:
        """清空内存 + 数据库"""
        self.clear_memory()
        self.clear_store()

    def publish(
        self,
        direction: str,
        peer: str,
        raw_hex: str,
        parsed: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        note: str = "",
    ) -> MessageRecord:
        with self._lock:
            self._seq += 1
            rec = MessageRecord(
                id=f"{int(time.time() * 1000)}-{self._seq}-{uuid.uuid4().hex[:6]}",
                ts=_now_iso(),
                direction=direction,
                peer=peer,
                raw_hex=raw_hex,
                parsed=parsed,
                error=error,
                note=note,
            )
            self._history.append(rec)
            listeners = list(self._listeners)

        data = rec.to_dict()

        if self.persist and self.store and direction != "system":
            try:
                self.store.insert(data)
            except Exception as e:
                print(f"[bus] 持久化失败: {e}")

        if self.console_log:
            self._log_console(data)

        event = {"type": "message", "data": data}
        for fn in listeners:
            try:
                fn(event)
            except Exception:
                pass
        return rec

    def emit(self, event_type: str, data: Any) -> None:
        event = {"type": event_type, "data": data}
        with self._lock:
            listeners = list(self._listeners)
        if self.console_log and event_type == "system":
            msg = data.get("msg") if isinstance(data, dict) else data
            print(f"[system] {msg}")
        for fn in listeners:
            try:
                fn(event)
            except Exception:
                pass

    @staticmethod
    def _log_console(data: dict[str, Any]) -> None:
        direction = data.get("direction", "?")
        peer = data.get("peer", "")
        func = data.get("func_name") or data.get("func_code") or data.get("note") or ""
        crc = data.get("crc_ok")
        crc_s = "CRC✓" if crc is True else "CRC✗" if crc is False else ""
        raw = (data.get("raw_hex") or "")[:80]
        err = data.get("error") or ""
        line = f"[{data.get('ts')}] {direction:6} {peer:18} {func} {crc_s}"
        if raw:
            line += f" | {raw}{'...' if len(data.get('raw_hex') or '') > 80 else ''}"
        print(line)
        if crc is False or err:
            detail = err or (data.get("parsed") or {}).get("errors") or []
            print(f"         ! {detail}")


# 全局单例
bus = MessageBus()
