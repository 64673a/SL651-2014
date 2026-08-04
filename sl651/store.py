"""SQLite 报文持久化"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

# 默认只保留最近 N 天；环境变量 SL651_RETENTION_DAYS 可覆盖，0 表示不自动清理
DEFAULT_RETENTION_DAYS = 3
# 后台清理周期（秒）
_RETENTION_INTERVAL_SEC = 3600


def default_retention_days() -> int:
    raw = os.environ.get("SL651_RETENTION_DAYS")
    if raw is None or raw.strip() == "":
        return DEFAULT_RETENTION_DAYS
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_RETENTION_DAYS


class MessageStore:
    def __init__(
        self,
        db_path: str | Path,
        retention_days: int | None = None,
        auto_purge: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = (
            default_retention_days() if retention_days is None else max(0, int(retention_days))
        )
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        self._purge_stop = threading.Event()
        self._purge_thread: Optional[threading.Thread] = None
        if auto_purge and self.retention_days > 0:
            deleted = self.purge_older_than(self.retention_days)
            if deleted:
                print(
                    f"[DB] 已清理 {deleted} 条超过 {self.retention_days} 天的报文"
                    f"（保留 {self.retention_days} 天）"
                )
            self._start_retention_loop()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id          TEXT PRIMARY KEY,
                    ts          TEXT NOT NULL,
                    direction   TEXT NOT NULL,
                    peer        TEXT NOT NULL DEFAULT '',
                    raw_hex     TEXT NOT NULL DEFAULT '',
                    note        TEXT NOT NULL DEFAULT '',
                    error       TEXT,
                    crc_ok      INTEGER,
                    func_code   TEXT,
                    func_name   TEXT,
                    remote_addr TEXT,
                    center_addr TEXT,
                    serial_no   INTEGER,
                    send_time   TEXT,
                    parsed_json TEXT,
                    created_at  TEXT DEFAULT (datetime('now','localtime'))
                );
                CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_dir ON messages(direction);
                CREATE INDEX IF NOT EXISTS idx_messages_peer ON messages(peer);
                CREATE INDEX IF NOT EXISTS idx_messages_func ON messages(func_code);
                CREATE INDEX IF NOT EXISTS idx_messages_crc ON messages(crc_ok);
                """
            )
            self._conn.commit()

    def insert(self, rec: dict[str, Any]) -> None:
        parsed = rec.get("parsed") or {}
        header = parsed.get("header") or {}
        body = parsed.get("body") or {}
        crc_ok = parsed.get("crc_ok")
        if crc_ok is True:
            crc_val: Optional[int] = 1
        elif crc_ok is False:
            crc_val = 0
        else:
            crc_val = None

        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO messages (
                    id, ts, direction, peer, raw_hex, note, error,
                    crc_ok, func_code, func_name, remote_addr, center_addr,
                    serial_no, send_time, parsed_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec["id"],
                    rec["ts"],
                    rec.get("direction") or "",
                    rec.get("peer") or "",
                    rec.get("raw_hex") or "",
                    rec.get("note") or "",
                    rec.get("error"),
                    crc_val,
                    header.get("func_code"),
                    header.get("func_name"),
                    header.get("remote_addr") or body.get("remote_addr"),
                    header.get("center_addr"),
                    body.get("serial_no"),
                    body.get("send_time"),
                    json.dumps(parsed, ensure_ascii=False) if parsed else None,
                ),
            )
            self._conn.commit()

    def query(
        self,
        *,
        direction: Optional[str] = None,
        peer: Optional[str] = None,
        func_code: Optional[str] = None,
        crc_ok: Optional[bool] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where: list[str] = []
        params: list[Any] = []

        if direction and direction != "all":
            where.append("direction = ?")
            params.append(direction)
        if peer:
            where.append("peer LIKE ?")
            params.append(f"%{peer}%")
        if func_code:
            where.append("func_code = ?")
            params.append(func_code.upper())
        if crc_ok is True:
            where.append("crc_ok = 1")
        elif crc_ok is False:
            where.append("crc_ok = 0")
        if keyword:
            where.append(
                "(raw_hex LIKE ? OR note LIKE ? OR error LIKE ? OR remote_addr LIKE ?"
                " OR func_name LIKE ? OR peer LIKE ?)"
            )
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw, kw, kw])

        clause = (" WHERE " + " AND ".join(where)) if where else ""
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) AS c FROM messages{clause}", params
            ).fetchone()["c"]
            rows = self._conn.execute(
                f"""
                SELECT * FROM messages{clause}
                ORDER BY ts DESC, rowid DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()

        items = [self._row_to_dict(r) for r in rows]
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items,
        }

    def get(self, msg_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM messages WHERE id = ?", (msg_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        result = self.query(limit=limit, offset=0)
        # 前端实时区通常要时间正序
        return list(reversed(result["items"]))

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
            by_dir = {
                r["direction"]: r["c"]
                for r in self._conn.execute(
                    "SELECT direction, COUNT(*) AS c FROM messages GROUP BY direction"
                )
            }
            crc_fail = self._conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE crc_ok = 0"
            ).fetchone()["c"]
        return {"total": total, "by_direction": by_dir, "crc_fail": crc_fail}

    def clear(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM messages")
            self._conn.commit()
            return cur.rowcount

    def purge_older_than(self, days: int, *, vacuum: bool = True) -> int:
        """删除早于保留天数的报文。days<=0 时不删除。"""
        if days <= 0:
            return 0
        cutoff_mod = f"-{int(days)} days"
        with self._lock:
            # ts 含毫秒（YYYY-MM-DD HH:MM:SS.mmm），与 SQLite datetime 字符串比较仍正确
            cur = self._conn.execute(
                """
                DELETE FROM messages
                WHERE ts < datetime('now', 'localtime', ?)
                   OR (ts IS NULL OR ts = '')
                      AND created_at < datetime('now', 'localtime', ?)
                """,
                (cutoff_mod, cutoff_mod),
            )
            deleted = cur.rowcount
            self._conn.commit()
            if deleted > 0 and vacuum:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    self._conn.execute("VACUUM")
                except sqlite3.Error as e:
                    print(f"[DB] VACUUM 失败（已删除 {deleted} 条）: {e}")
        return deleted

    def _start_retention_loop(self) -> None:
        if self._purge_thread and self._purge_thread.is_alive():
            return

        def _loop() -> None:
            while not self._purge_stop.wait(_RETENTION_INTERVAL_SEC):
                try:
                    n = self.purge_older_than(self.retention_days)
                    if n:
                        print(
                            f"[DB] 定时清理 {n} 条超过 {self.retention_days} 天的报文"
                        )
                except Exception as e:
                    print(f"[DB] 定时清理失败: {e}")

        self._purge_thread = threading.Thread(
            target=_loop, name="sl651-db-retention", daemon=True
        )
        self._purge_thread.start()

    def close(self) -> None:
        self._purge_stop.set()
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        parsed = None
        if d.get("parsed_json"):
            try:
                parsed = json.loads(d["parsed_json"])
            except json.JSONDecodeError:
                parsed = None
        crc = d.get("crc_ok")
        return {
            "id": d["id"],
            "ts": d["ts"],
            "direction": d["direction"],
            "peer": d["peer"],
            "raw_hex": d["raw_hex"],
            "note": d["note"],
            "error": d["error"],
            "crc_ok": True if crc == 1 else False if crc == 0 else None,
            "func_code": d.get("func_code"),
            "func_name": d.get("func_name"),
            "remote_addr": d.get("remote_addr"),
            "center_addr": d.get("center_addr"),
            "serial_no": d.get("serial_no"),
            "send_time": d.get("send_time"),
            "parsed": parsed,
        }


# 默认库路径：项目 data/messages.db（可被环境变量覆盖）
def default_db_path() -> Path:
    env = os.environ.get("SL651_DB")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data" / "messages.db"


store = MessageStore(default_db_path())
