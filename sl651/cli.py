"""命令行入口"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .formatter import format_frame
from .framer import FrameSplitter
from .hexutil import hex_to_bytes
from .parser import parse_frame


def _extract_frames(data: bytes) -> list[bytes]:
    splitter = FrameSplitter()
    frames = splitter.feed(data)
    if not frames and data[:2] == b"\x7e\x7e":
        frames = [data]
    return frames


def cmd_parse(args: argparse.Namespace) -> int:
    hex_str = args.hex
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            hex_str = f.read()
    if not hex_str or not hex_str.strip():
        print("请提供 --hex 或 --file", file=sys.stderr)
        return 2

    try:
        data = hex_to_bytes(hex_str)
    except Exception as e:
        print(f"hex 格式错误: {e}", file=sys.stderr)
        return 2

    frames = _extract_frames(data)
    if not frames:
        print("未找到有效帧（需以 7E7E 开头）", file=sys.stderr)
        return 1

    ok = 0
    for i, raw in enumerate(frames):
        try:
            frame = parse_frame(raw)
        except Exception as e:
            print(f"帧 {i + 1} 解析失败: {e}", file=sys.stderr)
            continue
        ok += 1
        if args.json:
            print(json.dumps(frame.to_dict(), ensure_ascii=False, indent=2))
        else:
            if len(frames) > 1:
                print(f"\n======== 帧 {i + 1}/{len(frames)} ========")
            print(format_frame(frame))
    return 0 if ok else 1


def cmd_listen(args: argparse.Namespace) -> int:
    from .server import CenterStationServer, run_serial

    if args.serial:
        run_serial(args.serial, baudrate=args.baud, auto_ack=not args.no_ack)
    else:
        CenterStationServer(
            host=args.host,
            port=args.port,
            auto_ack=not args.no_ack,
        ).start()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from .webapp import run_web

    run_web(
        host=args.host,
        port=args.port,
        tcp_port=args.tcp_port,
        auto_ack=not args.no_ack,
    )
    return 0


def cmd_rtu(args: argparse.Namespace) -> int:
    from .rtu import main as rtu_main

    argv = [
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--center",
        hex(args.center) if isinstance(args.center, int) else str(args.center),
        "--remote",
        args.remote,
        "--password",
        args.password,
        "--heartbeat",
        str(args.heartbeat),
        "--report",
        str(args.report),
        "--water",
        str(args.water),
        "--rain",
        str(args.rain),
        "--voltage",
        str(args.voltage),
    ]
    if args.once:
        argv.extend(["--once", args.once])
    return rtu_main(argv)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sl651",
        description="SL651-2014 中心站 RTU 调试助手",
    )
    p.add_argument("-V", "--version", action="version", version=f"sl651 {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("parse", help="离线解析十六进制报文")
    sp.add_argument("--hex", "-x", help="十六进制字符串（可含空格）")
    sp.add_argument("--file", "-f", help="从文件读取 hex")
    sp.add_argument("--json", action="store_true", help="以 JSON 输出")
    sp.set_defaults(func=cmd_parse)

    sl = sub.add_parser("listen", help="启动中心站监听（TCP 或串口，无 Web）")
    sl.add_argument("--host", default="0.0.0.0")
    sl.add_argument("--port", "-p", type=int, default=9000)
    sl.add_argument("--serial", "-s", help="串口设备")
    sl.add_argument("--baud", type=int, default=9600)
    sl.add_argument("--no-ack", action="store_true")
    sl.set_defaults(func=cmd_listen)

    sw = sub.add_parser("web", help="启动 Web 调试控制台（含中心站 TCP）")
    sw.add_argument("--host", default="0.0.0.0", help="Web 监听地址")
    sw.add_argument("--port", "-p", type=int, default=8080, help="Web 端口")
    sw.add_argument("--tcp-port", type=int, default=9000, help="RTU TCP 端口")
    sw.add_argument("--no-ack", action="store_true", help="关闭自动应答")
    sw.set_defaults(func=cmd_web)

    sr = sub.add_parser("rtu", help="启动模拟 RTU")
    sr.add_argument("--host", default="127.0.0.1", help="中心站地址")
    sr.add_argument("--port", type=int, default=9000, help="中心站 TCP 端口")
    sr.add_argument("--center", type=lambda x: int(x, 0), default=0x01)
    sr.add_argument("--remote", default="0010100001")
    sr.add_argument("--password", default="A000")
    sr.add_argument("--heartbeat", type=float, default=30.0)
    sr.add_argument("--report", type=float, default=60.0)
    sr.add_argument("--water", type=float, default=12.34)
    sr.add_argument("--rain", type=float, default=1.5)
    sr.add_argument("--voltage", type=float, default=12.6)
    sr.add_argument("--once", choices=["heartbeat", "report", "alarm"])
    sr.set_defaults(func=cmd_rtu)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
