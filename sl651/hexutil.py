"""十六进制工具"""

from __future__ import annotations


def normalize_hex(s: str) -> str:
    """去掉空格、0x、换行，统一大写"""
    s = s.replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", "")
    s = s.replace("0x", "").replace("0X", "")
    if len(s) % 2 != 0:
        raise ValueError(f"hex 长度必须为偶数: len={len(s)}")
    return s.upper()


def hex_to_bytes(s: str) -> bytes:
    return bytes.fromhex(normalize_hex(s))


def bytes_to_hex(data: bytes, sep: str = " ") -> str:
    if not sep:
        return data.hex().upper()
    return sep.join(f"{b:02X}" for b in data)


def bcd_to_str(data: bytes) -> str:
    """BCD 字节转十进制字符串，非法半字节用 '?'"""
    out = []
    for b in data:
        hi, lo = (b >> 4) & 0x0F, b & 0x0F
        out.append(str(hi) if hi <= 9 else "?")
        out.append(str(lo) if lo <= 9 else "?")
    return "".join(out)


def bcd_to_int(data: bytes) -> int:
    s = bcd_to_str(data)
    if "?" in s:
        raise ValueError(f"非法 BCD: {data.hex()}")
    return int(s) if s else 0


def format_send_time(data: bytes) -> str:
    """6 字节 YYMMDDHHmmSS (BCD) -> 20YY-MM-DD HH:MM:SS"""
    if len(data) < 6:
        return data.hex().upper()
    s = bcd_to_str(data[:6])
    if len(s) < 12 or "?" in s:
        return "20" + s
    return f"20{s[0:2]}-{s[2:4]}-{s[4:6]} {s[6:8]}:{s[8:10]}:{s[10:12]}"


def format_observe_time(data: bytes) -> str:
    """5 字节 YYMMDDHHmm (BCD) -> 20YY-MM-DD HH:MM"""
    if len(data) < 5:
        return data.hex().upper()
    s = bcd_to_str(data[:5])
    if len(s) < 10 or "?" in s:
        return "20" + s
    return f"20{s[0:2]}-{s[2:4]}-{s[4:6]} {s[6:8]}:{s[8:10]}"
