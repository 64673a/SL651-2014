"""模拟 RTU（遥测站）：连接中心站，上报心跳/定时报，接收下行"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from datetime import datetime
from typing import Optional

from . import constants as C
from .encoder import (
    build_heartbeat_body,
    build_report_body,
    build_up_frame,
)
from .framer import FrameSplitter
from .hexutil import bytes_to_hex
from .parser import parse_frame


class SimulatedRtu:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9000,
        center_addr: int = 0x01,
        remote_addr: str = "0010100001",
        password: str = "A000",
        station_type: int = 0x48,
        heartbeat_interval: float = 60.0,
        report_interval: float = 300.0,
        auto_report: bool = True,
        encoding: str = C.WIRE_HEX_BCD,
        water_level: float = 12.34,
        rain: float = 1.5,
        voltage: float = 12.6,
    ) -> None:
        self.host = host
        self.port = port
        self.center_addr = center_addr
        self.remote_addr = remote_addr
        self.password = password
        self.station_type = station_type
        self.heartbeat_interval = heartbeat_interval
        self.report_interval = report_interval
        self.auto_report = auto_report
        self.encoding = C.normalize_wire_encoding(encoding)
        if self.encoding == C.WIRE_AUTO:
            raise ValueError("模拟 RTU 必须明确选择 hex_bcd 或 ascii，不能使用 auto")
        self.water_level = water_level
        self.rain = rain
        self.voltage = voltage

        self._serial = 0
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._connected = False

    def _next_sn(self) -> int:
        self._serial = (self._serial + 1) & 0xFFFF
        return self._serial

    def connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=5)
        self._sock.settimeout(1.0)
        self._connected = True
        print(f"[RTU {self.remote_addr}] 已连接中心站 {self.host}:{self.port}")

    def close(self) -> None:
        self._stop.set()
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def send_frame(self, frame: bytes, label: str = "") -> None:
        if not self._sock:
            raise RuntimeError("未连接")
        with self._lock:
            self._sock.sendall(frame)
        print(f"[RTU] 上行 {label}: {bytes_to_hex(frame)}")

    def send_heartbeat(self) -> bytes:
        sn = self._next_sn()
        body = build_heartbeat_body(sn, encoding=self.encoding)
        frame = build_up_frame(
            self.center_addr,
            self.remote_addr,
            self.password,
            0x2F,
            body,
            encoding=self.encoding,
        )
        self.send_frame(frame, f"2F 链路维持 sn={sn}")
        return frame

    def send_report(self, func_code: int = 0x32) -> bytes:
        sn = self._next_sn()
        elements = [
            (0x39, self.water_level, 4, 2),  # 瞬时水位
            (0x20, self.rain, 3, 1),  # 当前降雨量
            (0x26, self.rain * 2, 3, 1),  # 日降水量
            (0x38, self.voltage, 2, 2),  # 电源电压
        ]
        body = build_report_body(
            sn,
            self.remote_addr,
            station_type=self.station_type,
            elements=elements,
            encoding=self.encoding,
        )
        frame = build_up_frame(
            self.center_addr,
            self.remote_addr,
            self.password,
            func_code,
            body,
            encoding=self.encoding,
        )
        name = {0x32: "定时报", 0x33: "加报", 0x34: "小时报"}.get(func_code, f"{func_code:02X}")
        self.send_frame(frame, f"{func_code:02X} {name} sn={sn}")
        return frame

    def send_hex(self, hex_str: str) -> bytes:
        from .hexutil import hex_to_bytes

        raw = hex_to_bytes(hex_str)
        if not raw:
            raise ValueError("hex 为空")
        self.send_frame(raw, "自定义")
        return raw

    def _recv_loop(self) -> None:
        assert self._sock is not None
        splitter = FrameSplitter(encoding=self.encoding)
        while not self._stop.is_set():
            try:
                data = self._sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                print("[RTU] 中心站断开")
                self._connected = False
                break
            for raw in splitter.feed(data):
                try:
                    frame = parse_frame(raw, encoding=self.encoding)
                    h = frame.header
                    print(
                        f"[RTU] 收到下行 {h.func_code:02X}({h.func_name}) "
                        f"from center={h.center_addr:02X} crc={'OK' if frame.crc_ok else 'FAIL'}"
                    )
                    print(f"      {bytes_to_hex(raw)}")
                except Exception as e:
                    print(f"[RTU] 下行解析失败: {e} raw={bytes_to_hex(raw)}")

    def _schedule_loop(self) -> None:
        last_hb = 0.0
        last_rp = 0.0
        # 连接后立即上报一次
        try:
            self.send_heartbeat()
            if self.auto_report:
                time.sleep(0.3)
                self.send_report(0x32)
            last_hb = last_rp = time.time()
        except Exception as e:
            print(f"[RTU] 初始上报失败: {e}")

        while not self._stop.is_set() and self._connected:
            now = time.time()
            try:
                if self.heartbeat_interval > 0 and now - last_hb >= self.heartbeat_interval:
                    self.send_heartbeat()
                    last_hb = now
                if (
                    self.auto_report
                    and self.report_interval > 0
                    and now - last_rp >= self.report_interval
                ):
                    self.send_report(0x32)
                    last_rp = now
            except Exception as e:
                print(f"[RTU] 上报失败: {e}")
                break
            time.sleep(0.2)

    def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            try:
                self.connect()
            except Exception as e:
                print(f"[RTU] 连接失败: {e}，3s 后重试...")
                time.sleep(3)
                continue

            recv_t = threading.Thread(target=self._recv_loop, daemon=True)
            recv_t.start()
            try:
                self._schedule_loop()
            except KeyboardInterrupt:
                print("\n[RTU] 退出")
                break
            finally:
                self.close()
                recv_t.join(timeout=1)

            if not self._stop.is_set():
                print("[RTU] 3s 后重连...")
                time.sleep(3)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SL651 模拟 RTU")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--center", type=lambda x: int(x, 0), default=0x01, help="中心站地址")
    p.add_argument("--remote", default="0010100001", help="遥测站地址 10 位")
    p.add_argument("--password", default="A000")
    p.add_argument("--station-type", type=lambda x: int(x, 0), default=0x48)
    p.add_argument("--heartbeat", type=float, default=30.0, help="心跳间隔秒，0=关闭")
    p.add_argument("--report", type=float, default=60.0, help="定时报间隔秒，0=关闭")
    p.add_argument(
        "--encoding",
        choices=[C.WIRE_HEX_BCD, C.WIRE_ASCII],
        default=C.WIRE_HEX_BCD,
        help="线路编码；模拟 RTU 发送时不能使用 auto",
    )
    p.add_argument("--water", type=float, default=12.34)
    p.add_argument("--rain", type=float, default=1.5)
    p.add_argument("--voltage", type=float, default=12.6)
    p.add_argument("--once", choices=["heartbeat", "report", "alarm"], help="只发一帧后退出")
    args = p.parse_args(argv)

    rtu = SimulatedRtu(
        host=args.host,
        port=args.port,
        center_addr=args.center,
        remote_addr=args.remote,
        password=args.password,
        station_type=args.station_type,
        heartbeat_interval=args.heartbeat,
        report_interval=args.report,
        encoding=args.encoding,
        water_level=args.water,
        rain=args.rain,
        voltage=args.voltage,
    )

    if args.once:
        rtu.connect()
        if args.once == "heartbeat":
            rtu.send_heartbeat()
        elif args.once == "report":
            rtu.send_report(0x32)
        else:
            rtu.send_report(0x33)
        # 等一下应答
        try:
            rtu._sock.settimeout(2)
            data = rtu._sock.recv(4096)
            if data:
                print(f"[RTU] 应答: {bytes_to_hex(data)}")
        except Exception:
            pass
        rtu.close()
        return 0

    rtu.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
