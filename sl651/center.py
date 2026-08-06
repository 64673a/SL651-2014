"""中心站核心：多 RTU 会话、自动应答、下行发送、报文记录"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from . import constants as C
from .bus import MessageBus, bus
from .encoder import build_ack, build_down_frame
from .framer import FrameSplitter
from .hexutil import bytes_to_hex, hex_to_bytes
from .parser import parse_frame

# 6.6.4.2：链路维持报（2FH）用于保活，明确「没有下行报文」
_NO_AUTO_ACK_FUNCS = {0x2F}

# 无上行数据超过该秒数则踢掉（应对断电后的半开 TCP）
_DEFAULT_IDLE_TIMEOUT = 180.0


@dataclass
class ClientInfo:
    peer: str
    remote_addr: str = ""
    center_addr: int = 0
    password: str = ""
    encoding: str = ""
    connected_at: str = ""
    last_seen: str = ""
    up_count: int = 0
    down_count: int = 0


class CenterHub:
    """可嵌入 Web 的中心站"""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9000,
        auto_ack: bool = True,
        encoding: str = C.WIRE_HEX_BCD,
        message_bus: Optional[MessageBus] = None,
        idle_timeout: float = _DEFAULT_IDLE_TIMEOUT,
    ) -> None:
        self.host = host
        self.port = port
        self.auto_ack = auto_ack
        self.encoding = C.normalize_wire_encoding(encoding)
        self.idle_timeout = idle_timeout
        self.bus = message_bus or bus
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._clients: dict[str, socket.socket] = {}
        self._info: dict[str, ClientInfo] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _enable_tcp_keepalive(conn: socket.socket) -> None:
        """开启 TCP keepalive，便于 OS 发现对端断电后的死连接。"""
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        # Linux: TCP_KEEPIDLE；macOS: TCP_KEEPALIVE（首次探测前空闲秒数）
        if hasattr(socket, "TCP_KEEPIDLE"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
        elif hasattr(socket, "TCP_KEEPALIVE"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, 60)
        if hasattr(socket, "TCP_KEEPINTVL"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        if hasattr(socket, "TCP_KEEPCNT"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

    # ── 生命周期 ──────────────────────────────────────────

    def start(self, blocking: bool = False) -> None:
        self._stop.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(32)
        self._sock.settimeout(1.0)
        self.bus.emit(
            "system",
            {"msg": f"中心站监听 {self.host}:{self.port}", "auto_ack": self.auto_ack},
        )
        if blocking:
            self._accept_loop()
        else:
            self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self._accept_thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for peer, conn in list(self._clients.items()):
                try:
                    conn.close()
                except OSError:
                    pass
            self._clients.clear()
            self._info.clear()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self.bus.emit("system", {"msg": "中心站已停止"})

    @property
    def running(self) -> bool:
        return self._sock is not None and not self._stop.is_set()

    # ── 客户端 ────────────────────────────────────────────

    def list_clients(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "peer": c.peer,
                    "remote_addr": c.remote_addr,
                    "center_addr": f"{c.center_addr:02X}",
                    "password": c.password,
                    "encoding": c.encoding,
                    "connected_at": c.connected_at,
                    "last_seen": c.last_seen,
                    "up_count": c.up_count,
                    "down_count": c.down_count,
                }
                for c in self._info.values()
            ]

    def send_raw(self, peer: str, data: bytes, note: str = "下行原始") -> dict:
        with self._lock:
            conn = self._clients.get(peer)
            info = self._info.get(peer)
        if not conn:
            raise ValueError(f"客户端不存在或已断开: {peer}")

        conn.sendall(data)
        raw_hex = bytes_to_hex(data)
        parsed = None
        err = None
        try:
            parsed = parse_frame(data).to_dict()
        except Exception as e:
            err = str(e)

        if info:
            info.down_count += 1
            info.last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        rec = self.bus.publish("down", peer, raw_hex, parsed=parsed, error=err, note=note)
        self.bus.emit("clients", self.list_clients())
        return rec.to_dict()

    def send_hex(self, peer: str, hex_str: str, note: str = "下行 hex") -> dict:
        return self.send_raw(peer, hex_to_bytes(hex_str), note=note)

    def send_down(
        self,
        peer: str,
        func_code: int,
        body_hex: str = "",
        remote_addr: str | None = None,
        center_addr: int | None = None,
        password: str | None = None,
        end_flag: int = 0x04,
        encoding: str | None = None,
        note: str = "下行调试",
    ) -> dict:
        with self._lock:
            info = self._info.get(peer)
        if not info:
            raise ValueError(f"客户端不存在: {peer}")

        remote = remote_addr or info.remote_addr or "0000000000"
        center = center_addr if center_addr is not None else (info.center_addr or 1)
        pwd = password or info.password or "0000"
        body = hex_to_bytes(body_hex) if str(body_hex or "").strip() else b""
        wire = C.normalize_wire_encoding(encoding, default=self.encoding)
        if wire == C.WIRE_AUTO:
            raise ValueError("下行组帧不能使用 auto，请明确选择 hex_bcd 或 ascii")

        # 若 remote 仍为空，尝试从 peer 无法推断时用 0
        if not remote or remote == "0000000000":
            # 允许直接按 hex 5 字节
            pass

        frame = build_down_frame(
            remote_addr=remote if len(remote) >= 10 else remote.zfill(10),
            center_addr=center,
            password=pwd,
            func_code=func_code,
            body=body,
            end_flag=end_flag,
            encoding=wire,
        )
        return self.send_raw(peer, frame, note=note)

    def send_ack(self, peer: str, raw_up_hex: str) -> dict:
        raw = hex_to_bytes(raw_up_hex)
        frame = parse_frame(raw)
        ack = build_ack(frame)
        return self.send_raw(peer, ack, note="手动确认")

    # ── 内部 ──────────────────────────────────────────────

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            peer = f"{addr[0]}:{addr[1]}"
            self._enable_tcp_keepalive(conn)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self._lock:
                self._clients[peer] = conn
                self._info[peer] = ClientInfo(peer=peer, connected_at=now, last_seen=now)
            self.bus.emit("system", {"msg": f"RTU 连接 {peer}"})
            self.bus.emit("clients", self.list_clients())
            t = threading.Thread(target=self._handle_client, args=(conn, peer), daemon=True)
            t.start()

    def _handle_client(self, conn: socket.socket, peer: str) -> None:
        splitter = FrameSplitter()
        conn.settimeout(1.0)
        last_recv = time.monotonic()
        reason = "断开"
        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    # recv 超时本身不代表断线；断电时对端可能不发 FIN，需靠空闲超时踢掉
                    if self.idle_timeout > 0 and (time.monotonic() - last_recv) >= self.idle_timeout:
                        reason = "空闲超时断开"
                        break
                    continue
                except OSError:
                    break
                if not data:
                    break
                last_recv = time.monotonic()

                for raw in splitter.feed(data):
                    raw_hex = bytes_to_hex(raw)
                    try:
                        frame = parse_frame(raw)
                        parsed = frame.to_dict()
                        err = None
                    except Exception as e:
                        frame = None
                        parsed = None
                        err = str(e)

                    with self._lock:
                        info = self._info.get(peer)
                        if info:
                            info.up_count += 1
                            info.last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            if frame and frame.header.direction == "up":
                                info.remote_addr = frame.header.remote_addr
                                info.center_addr = frame.header.center_addr
                                info.password = frame.header.password
                                info.encoding = frame.header.encoding

                    self.bus.publish(
                        "up",
                        peer,
                        raw_hex,
                        parsed=parsed,
                        error=err,
                        note="上行接收",
                    )
                    self.bus.emit("clients", self.list_clients())

                    if (
                        self.auto_ack
                        and frame
                        and frame.header.direction == "up"
                        and frame.header.func_code not in _NO_AUTO_ACK_FUNCS
                    ):
                        try:
                            ack = build_ack(frame)
                            conn.sendall(ack)
                            with self._lock:
                                if peer in self._info:
                                    self._info[peer].down_count += 1
                            self.bus.publish(
                                "down",
                                peer,
                                bytes_to_hex(ack),
                                parsed=parse_frame(ack).to_dict(),
                                note="自动确认",
                            )
                        except Exception as e:
                            self.bus.publish(
                                "system",
                                peer,
                                "",
                                error=f"自动应答失败: {e}",
                                note="error",
                            )
        finally:
            try:
                conn.close()
            except OSError:
                pass
            with self._lock:
                self._clients.pop(peer, None)
                self._info.pop(peer, None)
            self.bus.emit("system", {"msg": f"RTU {reason} {peer}"})
            self.bus.emit("clients", self.list_clients())


# Web 与 CLI 共享的中心站实例
hub = CenterHub()
