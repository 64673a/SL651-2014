"""命令行入口"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from . import constants as C
from .formatter import format_frame
from .framer import FrameSplitter
from .hexutil import hex_to_bytes
from .parser import parse_frame


def _extract_frames(data: bytes, encoding: str = C.WIRE_AUTO) -> list[bytes]:
    splitter = FrameSplitter(encoding=encoding)
    frames = splitter.feed(data)
    if not frames and (data[:2] == b"\x7e\x7e" or data[:1] == bytes([C.SOH])):
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

    frames = _extract_frames(data, args.encoding)
    if not frames:
        print("未找到有效帧（需以 7E7E 或 SOH(01H) 开头）", file=sys.stderr)
        return 1

    ok = 0
    for i, raw in enumerate(frames):
        try:
            frame = parse_frame(raw, encoding=args.encoding)
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


def cmd_web(args: argparse.Namespace) -> int:
    from .webapp import run_web

    run_web(
        host=args.host,
        port=args.port,
        tcp_port=args.tcp_port,
        auto_ack=not args.no_ack,
        encoding=args.encoding,
    )
    return 0


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
    sp.add_argument(
        "--encoding",
        choices=[C.WIRE_AUTO, C.WIRE_HEX_BCD, C.WIRE_ASCII],
        default=C.WIRE_AUTO,
    )
    sp.set_defaults(func=cmd_parse)

    sw = sub.add_parser("web", help="启动 Web 调试控制台（含中心站 TCP）")
    sw.add_argument("--host", default="0.0.0.0", help="Web 监听地址")
    sw.add_argument("--port", "-p", type=int, default=8080, help="Web 端口")
    sw.add_argument("--tcp-port", type=int, default=9000, help="RTU TCP 端口")
    sw.add_argument("--no-ack", action="store_true", help="关闭自动应答")
    sw.add_argument(
        "--encoding",
        choices=[C.WIRE_AUTO, C.WIRE_HEX_BCD, C.WIRE_ASCII],
        default=C.WIRE_HEX_BCD,
    )
    sw.set_defaults(func=cmd_web)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
