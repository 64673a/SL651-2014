"""下行 / 上行帧编码"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence, Union

from . import constants as C
from .constants import DOWN_DIR_ZERO_LEN, ESC, EOT, ETX, FRAME_START, STX, SYN
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
    """遥测站址：5 字节；字符串为 10 位 Hex（0-9A-F，可含空格）。"""
    if isinstance(remote, bytes):
        if len(remote) != 5:
            raise ValueError("遥测站地址需 5 字节")
        return remote
    s = remote.replace(" ", "").replace("\n", "").replace("\t", "")
    if len(s) != 10 or not all(c in "0123456789ABCDEFabcdef" for c in s):
        raise ValueError(f"无效遥测站地址: {remote}（需 10 位 Hex，0-9A-F）")
    return hex_to_bytes(s)


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
    encoding: str = C.WIRE_HEX_BCD,
    packet_total: Optional[int] = None,
    packet_seq: Optional[int] = None,
) -> bytes:
    """
    构造下行帧：
    7E7E | 遥测站(5) | 中心站(1) | 密码(2) | 功能码(1) | 长度(2, D15=1) | STX | 正文 | 结束符 | CRC
    """
    wire = C.normalize_wire_encoding(encoding)
    if wire == C.WIRE_ASCII:
        from .ascii_codec import build_ascii_down_frame

        return build_ascii_down_frame(
            remote_addr=remote_addr,
            center_addr=center_addr,
            password=password,
            func_code=func_code,
            body=body,
            end_flag=end_flag,
            packet_total=packet_total,
            packet_seq=packet_seq,
        )
    if wire == C.WIRE_AUTO:
        raise ValueError("组帧不能使用 auto，请明确选择 hex_bcd 或 ascii")

    remote = _remote_bytes(remote_addr)
    center = bytes([center_addr & 0xFF])
    pwd = _pwd_bytes(password)
    func = bytes([func_code & 0xFF])
    packet = b""
    stx = STX
    if packet_total is not None or packet_seq is not None:
        if packet_total is None or packet_seq is None:
            raise ValueError("M3 帧必须同时提供 packet_total 和 packet_seq")
        if not (0 <= packet_total <= 0xFFF and 0 <= packet_seq <= 0xFFF):
            raise ValueError("M3 包总数/序号范围为 0~FFF")
        stx = SYN
        packet_value = ((packet_total & 0xFFF) << 12) | (packet_seq & 0xFFF)
        packet = packet_value.to_bytes(3, "big")
    wire_body = packet + body
    body_len = len(wire_body)
    len_field = DOWN_DIR_ZERO_LEN | (body_len & 0x0FFF)
    len_bytes = bytes([(len_field >> 8) & 0xFF, len_field & 0xFF])
    frame = (
        FRAME_START
        + remote
        + center
        + pwd
        + func
        + len_bytes
        + bytes([stx])
        + wire_body
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
    encoding: str = C.WIRE_HEX_BCD,
    packet_total: Optional[int] = None,
    packet_seq: Optional[int] = None,
) -> bytes:
    """
    构造上行帧：
    7E7E | 中心站(1) | 遥测站(5) | 密码(2) | 功能码(1) | 长度(2, D15=0) | STX | 正文 | 结束符 | CRC
    """
    wire = C.normalize_wire_encoding(encoding)
    if wire == C.WIRE_ASCII:
        from .ascii_codec import build_ascii_up_frame

        return build_ascii_up_frame(
            center_addr=center_addr,
            remote_addr=remote_addr,
            password=password,
            func_code=func_code,
            body=body,
            end_flag=end_flag,
            packet_total=packet_total,
            packet_seq=packet_seq,
        )
    if wire == C.WIRE_AUTO:
        raise ValueError("组帧不能使用 auto，请明确选择 hex_bcd 或 ascii")

    remote = _remote_bytes(remote_addr)
    center = bytes([center_addr & 0xFF])
    pwd = _pwd_bytes(password)
    func = bytes([func_code & 0xFF])
    packet = b""
    stx = STX
    if packet_total is not None or packet_seq is not None:
        if packet_total is None or packet_seq is None:
            raise ValueError("M3 帧必须同时提供 packet_total 和 packet_seq")
        if not (0 <= packet_total <= 0xFFF and 0 <= packet_seq <= 0xFFF):
            raise ValueError("M3 包总数/序号范围为 0~FFF")
        stx = SYN
        packet_value = ((packet_total & 0xFFF) << 12) | (packet_seq & 0xFFF)
        packet = packet_value.to_bytes(3, "big")
    wire_body = packet + body
    body_len = len(wire_body)
    len_field = body_len & 0x0FFF
    len_bytes = bytes([(len_field >> 8) & 0xFF, len_field & 0xFF])
    frame = (
        FRAME_START
        + center
        + remote
        + pwd
        + func
        + len_bytes
        + bytes([stx])
        + wire_body
        + bytes([end_flag])
    )
    return frame + crc16_bytes(frame)


def build_ack(frame: ParsedFrame, end_flag: int = ESC) -> bytes:
    """确认应答（正文长度 0，功能码与上行一致）。

    默认结束符 ESC（保持在线），与公司 REF 确认帧样例一致；可传 EOT 要求终端退出。
    """
    remote = frame.header.remote_addr
    center = frame.header.center_addr
    encoding = C.normalize_wire_encoding(frame.header.encoding)
    body = b""
    if encoding == C.WIRE_ASCII and frame.body.serial_no is not None:
        from .ascii_codec import build_ascii_heartbeat_body

        body = build_ascii_heartbeat_body(frame.body.serial_no, frame.body.send_time)
    packet_total = packet_seq = None
    if frame.header.m3:
        packet_total = frame.header.packet_total
        if packet_total is not None:
            packet_seq = (
                packet_total
                if end_flag in (EOT, ESC)
                else frame.header.packet_seq
            )
    return build_down_frame(
        remote_addr=remote,
        center_addr=center,
        password=frame.header.password,
        func_code=frame.header.func_code,
        body=body,
        end_flag=end_flag,
        encoding=encoding,
        packet_total=packet_total,
        packet_seq=packet_seq,
    )


def build_ack_from_raw(raw_up: bytes, end_flag: int = ESC) -> bytes:
    if len(raw_up) < 14:
        raise ValueError("上行帧过短，无法构造应答")
    from .parser import parse_frame

    return build_ack(parse_frame(raw_up), end_flag=end_flag)


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


def build_heartbeat_body(
    serial_no: int,
    send_time: Optional[datetime] = None,
    *,
    encoding: str = C.WIRE_HEX_BCD,
) -> bytes:
    if C.normalize_wire_encoding(encoding) == C.WIRE_ASCII:
        from .ascii_codec import build_ascii_heartbeat_body

        return build_ascii_heartbeat_body(serial_no, send_time)
    sn = bytes([(serial_no >> 8) & 0xFF, serial_no & 0xFF])
    return sn + _now_bcd6(send_time)


def build_report_body(
    serial_no: int,
    remote_addr: str,
    station_type: int = 0x48,
    elements: Optional[Sequence[tuple[int, float | int | str, int, int]]] = None,
    send_time: Optional[datetime] = None,
    observe_time: Optional[datetime] = None,
    *,
    encoding: str = C.WIRE_HEX_BCD,
) -> bytes:
    """
    定时报/加报正文：
    流水号(2) + 发报时间(6) + F1F1 + 站址(5) + 分类码(1) + F0F0 + 观测时间(5) + 要素...
    elements: [(guide, value, data_len, decimals), ...]
    """
    if C.normalize_wire_encoding(encoding) == C.WIRE_ASCII:
        from .ascii_codec import build_ascii_report_body

        return build_ascii_report_body(
            serial_no,
            remote_addr,
            station_type=station_type,
            elements=elements,
            send_time=send_time,
            observe_time=observe_time,
        )

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
