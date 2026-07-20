"""中心站 TCP / 串口接收服务"""

from __future__ import annotations

import socket
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from .encoder import build_ack
from .formatter import format_frame
from .framer import FrameSplitter
from .hexutil import bytes_to_hex
from .models import ParsedFrame
from .parser import parse_frame

OnFrame = Callable[[ParsedFrame, str], None]  # frame, peer


class CenterStationServer:
    """
    中心站调试服务：
    - TCP 监听，接收 RTU 上行帧
    - 解析并打印
    - 可选自动确认应答
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9000,
        auto_ack: bool = True,
        on_frame: Optional[OnFrame] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.auto_ack = auto_ack
        self.on_frame = on_frame or self._default_on_frame
        self._stop = threading.Event()
        self._sock: Optional[socket.socket] = None
        self._threads: list[threading.Thread] = []

    def _default_on_frame(self, frame: ParsedFrame, peer: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{ts}] 来自 {peer}")
        print(format_frame(frame))

    def start(self) -> None:
        self._stop.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(32)
        self._sock.settimeout(1.0)
        print(f"[中心站] TCP 监听 {self.host}:{self.port}  auto_ack={self.auto_ack}")
        print("[中心站] 等待 RTU 连接... (Ctrl+C 退出)")

        try:
            while not self._stop.is_set():
                try:
                    conn, addr = self._sock.accept()
                except socket.timeout:
                    continue
                peer = f"{addr[0]}:{addr[1]}"
                print(f"[中心站] RTU 已连接 {peer}")
                t = threading.Thread(target=self._handle_client, args=(conn, peer), daemon=True)
                t.start()
                self._threads.append(t)
        except KeyboardInterrupt:
            print("\n[中心站] 正在停止...")
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _handle_client(self, conn: socket.socket, peer: str) -> None:
        splitter = FrameSplitter()
        conn.settimeout(1.0)
        try:
            while not self._stop.is_set():
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    print(f"[中心站] {peer} 断开")
                    break

                print(f"[中心站] {peer} 收到 {len(data)} 字节: {bytes_to_hex(data)}")
                for raw in splitter.feed(data):
                    try:
                        frame = parse_frame(raw)
                    except Exception as e:
                        print(f"[中心站] {peer} 解析失败: {e}")
                        print(f"  raw: {bytes_to_hex(raw)}")
                        continue

                    self.on_frame(frame, peer)

                    if self.auto_ack and frame.header.direction == "up":
                        try:
                            ack = build_ack(frame)
                            conn.sendall(ack)
                            print(f"[中心站] 已应答 -> {peer}: {bytes_to_hex(ack)}")
                        except Exception as e:
                            print(f"[中心站] 应答失败: {e}")
        finally:
            try:
                conn.close()
            except OSError:
                pass


def run_serial(
    port: str,
    baudrate: int = 9600,
    auto_ack: bool = True,
    on_frame: Optional[OnFrame] = None,
) -> None:
    """串口模式（需 pyserial）"""
    try:
        import serial
    except ImportError as e:
        raise SystemExit("串口模式需要安装 pyserial: pip install pyserial") from e

    on_frame = on_frame or (
        lambda f, p: print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] 来自 {p}\n{format_frame(f)}")
    )
    splitter = FrameSplitter()
    ser = serial.Serial(port, baudrate=baudrate, timeout=0.5)
    print(f"[中心站] 串口 {port} @ {baudrate}  auto_ack={auto_ack}")
    print("[中心站] 等待数据... (Ctrl+C 退出)")
    try:
        while True:
            data = ser.read(4096)
            if not data:
                continue
            peer = port
            print(f"[中心站] {peer} 收到 {len(data)} 字节: {bytes_to_hex(data)}")
            for raw in splitter.feed(data):
                try:
                    frame = parse_frame(raw)
                except Exception as e:
                    print(f"[中心站] 解析失败: {e}")
                    continue
                on_frame(frame, peer)
                if auto_ack and frame.header.direction == "up":
                    ack = build_ack(frame)
                    ser.write(ack)
                    print(f"[中心站] 已应答: {bytes_to_hex(ack)}")
    except KeyboardInterrupt:
        print("\n[中心站] 停止")
    finally:
        ser.close()
