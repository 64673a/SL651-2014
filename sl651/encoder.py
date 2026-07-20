"""下行 / 上行帧编码"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence, Union

from .constants import DOWN_DIR_ZERO_LEN, EOT, ETX, FRAME_START, STX
from .crc16 import crc16_bytes
from .hexutil import hex_to_bytes
from .models import ParsedFrame


def _bcd_digits(digits: str, nbytes: int) -> bytes:
    """十进制数字字符串 -> BCD 字节，不足左侧补 0"""
    s = "".join(c for c in digits if c.isdigit())
    s = s.zfill(nbytes * 2)[-nbytes * 2 :]
    out = bytearray()
    for i in range(0, len(s), 2):
        out.append((int(s[i]) << 4) | int(s[i + 1]))
    return bytes(out)


def _remote_bytes(remote: Union[str, bytes]) -> bytes:
    if isinstance(remote, bytes):
        if len(remote) != 5:
            raise ValueError("遥测站地址需 5 字节")
        return remote
    s = remote.replace(" ", "")
    if len(s) == 10 and all(c in "0123456789ABCDEFabcdef" for c in s):
        # 优先按 BCD 数字；若含 A-F 则按 hex
        if all(c in "0123456789" for c in s):
            return _bcd_digits(s, 5)
        return hex_to_bytes(s)
    raise ValueError(f"无效遥测站地址: {remote}")


def _pwd_bytes(password: Union[str, bytes]) -> bytes:
    if isinstance(password, bytes):
        return password[:2].ljust(2, b"\x00")
    return hex_to_bytes(password.replace(" ", "").zfill(4)[-4:])


def _now_bcd6(dt: Optional[datetime] = None) -> bytes:
    dt = dt or datetime.now()
    s = dt.strftime("%y%m%d%H%M%S")
    return _bcd_digits(s, 6)


def _now_bcd5(dt: Optional[datetime] = None) -> bytes:
    dt = dt or datetime.now()
    s = dt.strftime("%y%m%d%H%M")
    return _bcd_digits(s, 5)


def build_down_frame(
    remote_addr: Union[str, bytes],
    center_addr: int,
    password: Union[str, bytes],
    func_code: int,
    body: bytes = b"",
    end_flag: int = EOT,
) -> bytes:
    """
    构造下行帧：
    7E7E | 遥测站(5) | 中心站(1) | 密码(2) | 功能码(1) | 长度(2, D15=1) | STX | 正文 | 结束符 | CRC
    """
    remote = _remote_bytes(remote_addr)
    center = bytes([center_addr & 0xFF])
    pwd = _pwd_bytes(password)
    func = bytes([func_code & 0xFF])
    body_len = len(body)
    len_field = DOWN_DIR_ZERO_LEN | (body_len & 0x0FFF)
    len_bytes = bytes([(len_field >> 8) & 0xFF, len_field & 0xFF])
    frame = (
        FRAME_START
        + remote
        + center
        + pwd
        + func
        + len_bytes
        + bytes([STX])
        + body
        + bytes([end_flag])
    )
    return frame + crc16_bytes(frame)


def build_up_frame(
    center_addr: int,
    remote_addr: Union[str, bytes],
    password: Union[str, bytes],
    func_code: int,
    body: bytes = b"",
    end_flag: int = ETX,
) -> bytes:
    """
    构造上行帧：
    7E7E | 中心站(1) | 遥测站(5) | 密码(2) | 功能码(1) | 长度(2, D15=0) | STX | 正文 | 结束符 | CRC
    """
    remote = _remote_bytes(remote_addr)
    center = bytes([center_addr & 0xFF])
    pwd = _pwd_bytes(password)
    func = bytes([func_code & 0xFF])
    body_len = len(body)
    len_field = body_len & 0x0FFF
    len_bytes = bytes([(len_field >> 8) & 0xFF, len_field & 0xFF])
    frame = (
        FRAME_START
        + center
        + remote
        + pwd
        + func
        + len_bytes
        + bytes([STX])
        + body
        + bytes([end_flag])
    )
    return frame + crc16_bytes(frame)


def build_ack(frame: ParsedFrame, end_flag: int = EOT) -> bytes:
    """确认应答（正文长度 0，功能码与上行一致）"""
    if frame.header.direction == "up":
        remote = frame.raw[3:8]
        center = frame.header.center_addr
    else:
        remote = frame.raw[2:7]
        center = frame.header.center_addr
    return build_down_frame(
        remote_addr=remote,
        center_addr=center,
        password=frame.header.password,
        func_code=frame.header.func_code,
        body=b"",
        end_flag=end_flag,
    )


def build_ack_from_raw(raw_up: bytes, end_flag: int = EOT) -> bytes:
    if len(raw_up) < 14:
        raise ValueError("上行帧过短，无法构造应答")
    return build_down_frame(
        remote_addr=raw_up[3:8],
        center_addr=raw_up[2],
        password=raw_up[8:10],
        func_code=raw_up[10],
        body=b"",
        end_flag=end_flag,
    )


def encode_element(guide: int, value: float | int | str, data_len: int, decimals: int) -> bytes:
    """编码单个要素：guide + info + BCD 数据"""
    info = ((data_len & 0x1F) << 3) | (decimals & 0x07)
    if isinstance(value, str):
        digits = "".join(c for c in value if c.isdigit() or c == ".")
        if "." in digits:
            a, _, b = digits.partition(".")
            digits = a + b.ljust(decimals, "0")[:decimals] if decimals else a
        digits = digits.zfill(data_len * 2)[-data_len * 2 :]
    else:
        scale = 10**decimals
        n = int(round(float(value) * scale))
        digits = str(abs(n)).zfill(data_len * 2)[-data_len * 2 :]
    return bytes([guide & 0xFF, info]) + _bcd_digits(digits, data_len)


def build_heartbeat_body(serial_no: int, send_time: Optional[datetime] = None) -> bytes:
    sn = bytes([(serial_no >> 8) & 0xFF, serial_no & 0xFF])
    return sn + _now_bcd6(send_time)


def build_report_body(
    serial_no: int,
    remote_addr: str,
    station_type: int = 0x48,
    elements: Optional[Sequence[tuple[int, float | int | str, int, int]]] = None,
    send_time: Optional[datetime] = None,
    observe_time: Optional[datetime] = None,
) -> bytes:
    """
    定时报/加报正文：
    流水号(2) + 发报时间(6) + F1F1 + 站址(5) + 分类码(1) + F0F0 + 观测时间(5) + 要素...
    elements: [(guide, value, data_len, decimals), ...]
    """
    sn = bytes([(serial_no >> 8) & 0xFF, serial_no & 0xFF])
    body = bytearray()
    body += sn
    body += _now_bcd6(send_time)
    body += bytes([0xF1, 0xF1])
    body += _remote_bytes(remote_addr)
    body += bytes([station_type & 0xFF])
    body += bytes([0xF0, 0xF0])
    body += _now_bcd5(observe_time or send_time)
    for guide, value, data_len, decimals in elements or ():
        body += encode_element(guide, value, data_len, decimals)
    return bytes(body)
