"""SL651-2014 ASCII wire-frame and body codec.

The protocol calls this the ASCII character encoding frame.  Control bytes
remain binary (SOH/STX/SYN/ETX...), while header fields, CRC, and ordinary
body groups are transmitted as ASCII characters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence, Union

from . import constants as C
from .crc16 import crc16_bytes
from .hexutil import bytes_to_hex, hex_to_bytes
from .models import Element, FieldSpan, FrameBody, FrameHeader, ParsedFrame

ASCII_HEADER_LEN = 24  # SOH + fields + STX/SYN
ASCII_CRC_LEN = 4
ASCII_MIN_FRAME_LEN = ASCII_HEADER_LEN + 1 + 1 + ASCII_CRC_LEN

_END_NAMES = {
    C.ETX: "ETX 报文结束",
    C.ETB: "ETB 多包中间结束",
    C.EOT: "EOT 传输结束",
    C.ENQ: "ENQ 询问",
    C.ACK: "ACK 肯定确认",
    C.NAK: "NAK 否定应答",
    C.ESC: "ESC 终端保持在线",
}

_ASCII_TO_GUIDE = {
    code.upper(): guide for guide, (code, _name) in C.ELEMENT_GUIDES.items()
}


def _ascii_display(raw: bytes) -> str:
    names = {
        C.SOH: "<SOH>",
        C.STX: "<STX>",
        C.SYN: "<SYN>",
        C.ETX: "<ETX>",
        C.ETB: "<ETB>",
        C.ENQ: "<ENQ>",
        C.EOT: "<EOT>",
        C.ACK: "<ACK>",
        C.NAK: "<NAK>",
        C.ESC: "<ESC>",
    }
    out: list[str] = []
    for b in raw:
        if b in names:
            out.append(names[b])
        elif 0x20 <= b <= 0x7E:
            out.append(chr(b))
        else:
            out.append(f"\\x{b:02X}")
    return "".join(out)


def _ascii_field(raw: bytes, start: int, end: int, label: str) -> str:
    value = raw[start:end]
    try:
        text = value.decode("ascii")
    except UnicodeDecodeError as e:
        raise ValueError(f"{label}不是 ASCII 字段") from e
    if not text or any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError(f"{label}不是十六进制 ASCII 字段: {text!r}")
    return text.upper()


def _remote_text(remote: Union[str, bytes]) -> str:
    if isinstance(remote, bytes):
        if len(remote) != 5:
            raise ValueError("遥测站地址需 5 字节")
        return remote.hex().upper()
    text = "".join(str(remote).split()).upper()
    if len(text) != 10 or any(c not in "0123456789ABCDEF" for c in text):
        raise ValueError(f"无效遥测站地址: {remote}（需 10 位 Hex）")
    return text


def _password_text(password: Union[str, bytes]) -> str:
    if isinstance(password, bytes):
        return password[:2].ljust(2, b"\x00").hex().upper()
    text = "".join(str(password).split()).upper()
    if not text:
        text = "0000"
    if any(c not in "0123456789ABCDEF" for c in text):
        raise ValueError(f"无效密码: {password}")
    return text.zfill(4)[-4:]


def _digits(value: Optional[Union[str, datetime]], count: int, *, now: bool = True) -> str:
    if isinstance(value, datetime):
        if count == 12:
            return value.strftime("%y%m%d%H%M%S")
        if count == 10:
            return value.strftime("%y%m%d%H%M")
        if count == 8:
            return value.strftime("%y%m%d%H")
    text = "".join(c for c in str(value or "") if c.isdigit())
    if text.startswith("20") and len(text) >= count + 2:
        text = text[2:]
    if not text and now:
        return _digits(datetime.now(), count, now=False)
    return text.zfill(count)[-count:]


def _serial_text(serial_no: int) -> str:
    # The body field is the original 2-byte HEX serial converted to four
    # ASCII characters, matching the protocol's HEX-to-ASCII rule.
    return f"{int(serial_no) & 0xFFFF:04X}"


def _format_send_text(text: str) -> str:
    if len(text) >= 12 and text.isdigit():
        return f"20{text[0:2]}-{text[2:4]}-{text[4:6]} {text[6:8]}:{text[8:10]}:{text[10:12]}"
    return text


def _format_observe_text(text: str) -> str:
    if len(text) >= 10 and text.isdigit():
        return f"20{text[0:2]}-{text[2:4]}-{text[4:6]} {text[6:8]}:{text[8:10]}"
    return text


def _guide_code(guide: Union[int, str], func_code: Optional[int] = None) -> str:
    if isinstance(guide, str):
        text = guide.strip().upper()
        if text and not all(c in "0123456789ABCDEF" for c in text):
            return text
        try:
            guide = int(text, 16)
        except ValueError:
            return text
    g = int(guide) & 0xFF
    if func_code in C.BASIC_CONFIG_FUNC_CODES or func_code in C.RUN_PARAM_FUNC_CODES:
        return f"{g:02X}"
    if func_code in (0x47, 0x48, 0x49, 0x4B, 0x4C, 0x4D, 0x4E):
        return f"{g:02X}"
    entry = C.ELEMENT_GUIDES.get(g)
    if entry:
        return entry[0]
    # Appendix D configuration identifiers are binary guide bytes converted
    # to ASCII, so their two-character HEX form is the canonical text form.
    return f"{g:02X}"


def _value_text(value: float | int | str, decimals: int = 0) -> str:
    if isinstance(value, str):
        return value
    if decimals:
        return f"{float(value):.{decimals}f}"
    return str(int(value))


def _group(code: str, value: Optional[str] = None) -> str:
    return code if value is None else f"{code} {value}"


def _join_body(prefix: str, groups: Sequence[str]) -> bytes:
    if not groups:
        return prefix.encode("ascii")
    return (prefix + " " + " ".join(groups) + " ").encode("ascii")


def build_ascii_heartbeat_body(
    serial_no: int, send_time: Optional[Union[str, datetime]] = None
) -> bytes:
    return (_serial_text(serial_no) + _digits(send_time, 12)).encode("ascii")


def build_ascii_report_body(
    serial_no: int,
    remote_addr: str,
    station_type: int = 0x48,
    elements: Optional[Sequence[tuple[int, float | int | str, int, int]]] = None,
    send_time: Optional[Union[str, datetime]] = None,
    observe_time: Optional[Union[str, datetime]] = None,
) -> bytes:
    groups = [
        _group("ST", _remote_text(remote_addr)),
        C.STATION_TYPE_ASCII.get(station_type & 0xFF, f"{station_type & 0xFF:02X}"),
        _group("TT", _digits(observe_time or send_time, 10)),
    ]
    for guide, value, _data_len, decimals in elements or ():
        groups.append(_group(_guide_code(guide), _value_text(value, decimals)))
    return _join_body(_serial_text(serial_no) + _digits(send_time, 12), groups)


def _raw_hex_value(value_hex: str) -> str:
    return hex_to_bytes(str(value_hex).replace(" ", "")).hex().upper()


def build_ascii_down_body(
    func_code: int,
    *,
    serial_no: int = 0,
    send_time: Optional[Union[datetime, str]] = None,
    body_hex: Optional[str] = None,
    body_text: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    step_unit: str = "N",
    step_value: int = 5,
    guides: Optional[Sequence[Union[int, str]]] = None,
    params: Optional[Sequence[dict[str, Any]]] = None,
    old_password: Optional[str] = None,
    new_password: Optional[str] = None,
    ic_enable: Optional[bool] = None,
    switch_bits: Optional[int] = None,
    gate_count: Optional[int] = None,
    gate_bits: Optional[int] = None,
    gate_openings_cm: Optional[Sequence[int]] = None,
    water_control: Optional[str] = None,
) -> bytes:
    """Build an ASCII body from the same semantic inputs as down_builder."""
    if body_text is not None and str(body_text) != "":
        return str(body_text).encode("ascii")
    if body_hex is not None and str(body_hex).strip():
        return hex_to_bytes(str(body_hex))

    fc = func_code & 0xFF
    prefix = _serial_text(serial_no) + _digits(send_time, 12)
    simple = {0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x39, 0x44, 0x45, 0x46, 0x4A, 0x50, 0x51}
    if fc in simple:
        return prefix.encode("ascii")

    if fc == 0x38:
        unit = (step_unit or "N").upper()[0]
        step = f"DR{unit}{max(0, int(step_value)) % 100:02d}"
        groups = [_digits(start_time, 8, now=False), _digits(end_time, 8, now=False), step]
        groups.extend(_guide_code(g, fc) for g in (guides or [0xF4]))
        return _join_body(prefix, groups)

    if fc in (0x3A, 0x41, 0x43):
        glist = list(guides or [])
        if not glist:
            if fc == 0x3A:
                glist = [0xF4]
            elif fc == 0x41:
                glist = [0x01, 0x02, 0x03, 0x04, 0x05, 0x0C, 0x0D, 0x0F]
            else:
                glist = [0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x30, 0x38, 0x40, 0x41]
        return _join_body(prefix, [_guide_code(g, fc) for g in glist])

    if fc in (0x40, 0x42):
        groups = []
        for item in params or ():
            code = _guide_code(item.get("guide", 0), fc)
            value = str(item.get("value_hex", "") or "")
            groups.append(_group(code, _raw_hex_value(value) if value else None))
        return _join_body(prefix, groups)

    if fc in (0x47, 0x48):
        return _join_body(prefix, [_group("97" if fc == 0x47 else "98", "00")])

    if fc == 0x49:
        return _join_body(prefix, [_group("03", _password_text(old_password or "0000")), _group("03", _password_text(new_password or "0000"))])

    if fc == 0x4B:
        status = (1 << 9) if ic_enable else 0
        return _join_body(prefix, [_group("45", f"{status:08X}")])

    if fc in (0x4C, 0x4D):
        return _join_body(prefix, [_group("01", f"{int(switch_bits or 0) & 0xFF:02X}")])

    if fc == 0x4E:
        n = max(1, int(gate_count or 1))
        bits = int(gate_bits or 0)
        openings = list(gate_openings_cm or [0] * n)
        groups = [f"{n:02X}", f"{bits & 0xFF:02X}"]
        groups.extend(f"{int(cm) & 0xFFFF:04d}" for cm in openings[:n])
        return _join_body(prefix, groups)

    if fc == 0x4F:
        return _join_body(prefix, ["FF" if (water_control or "on").lower() in ("on", "1", "ff", "true", "投入") else "00"])

    return prefix.encode("ascii")


def _parse_numeric(text: str) -> tuple[Optional[float], int, int]:
    if text.upper() == "M":
        return None, 0, 0
    try:
        value = float(text)
    except ValueError:
        return None, len(text), 0
    clean = text.lstrip("+-")
    decimals = len(clean.partition(".")[2]) if "." in clean else 0
    data_len = len(clean.replace(".", ""))
    return value, data_len, decimals


def _ascii_element(
    code: str,
    value: str,
    body: bytes,
    start: int,
    end: int,
    func_code: int,
) -> Element:
    guide = _ASCII_TO_GUIDE.get(code.upper(), 0)
    if not guide and len(code) == 2 and all(c in "0123456789ABCDEFabcdef" for c in code):
        guide = int(code, 16)
    if not guide and code.upper().startswith("DR"):
        guide = 0x04
    numeric, data_len, decimals = _parse_numeric(value)
    name = C.get_guide_name(guide, func_code) if guide else code
    if code.upper() == "ST":
        name = "测站编码"
    elif code.upper() == "TT":
        name = "观测时间引导符"
    return Element(
        guide=guide,
        guide_name=name,
        data_len=data_len,
        decimals=decimals,
        raw_hex=bytes_to_hex(value.encode("ascii", errors="replace"), sep=""),
        value=numeric,
        value_text="无数据" if value.upper() == "M" else value,
        offset=start,
        length=end - start,
        guide_code=code,
    )


def _token(data: bytes, pos: int) -> tuple[int, int, str] | None:
    n = len(data)
    while pos < n and data[pos] == 0x20:
        pos += 1
    if pos >= n:
        return None
    start = pos
    while pos < n and data[pos] != 0x20:
        pos += 1
    try:
        text = data[start:pos].decode("ascii")
    except UnicodeDecodeError:
        text = bytes_to_hex(data[start:pos], sep="")
    return start, pos, text


def parse_ascii_body(
    body: bytes, func_code: int, direction: str = "up"
) -> tuple[FrameBody, list[tuple[str, str, int, int, str, str]]]:
    fb = FrameBody(raw_hex=bytes_to_hex(body, sep=""), raw_text=_ascii_display(body))
    spans: list[tuple[str, str, int, int, str, str]] = []
    n = len(body)
    if n < 16:
        return fb, spans

    prefix = body[:16]
    try:
        serial_text = prefix[:4].decode("ascii")
        send_text = prefix[4:16].decode("ascii")
        serial_no = int(serial_text, 16)
        fb.serial_no = serial_no
        fb.send_time = _format_send_text(send_text)
        spans.append(("serial_no", "流水号", 0, 4, serial_text, "info"))
        spans.append(("send_time", "发报时间", 4, 16, fb.send_time, "success"))
    except (UnicodeDecodeError, ValueError):
        return fb, spans

    pos = 16
    # 38H has two query times and a DRxnn step token before element guides.
    if func_code == 0x38 and direction == "down":
        labels = (("period_start", "起始时间"), ("period_end", "结束时间"), ("step", "时间步长"))
        for fid, label in labels:
            item = _token(body, pos)
            if not item:
                break
            start, pos, text = item
            spans.append((fid, label, start, pos, text, "info"))

    id_only = direction == "down" and func_code in (0x3A, 0x41, 0x43)
    if func_code == 0x38 and direction == "down":
        id_only = True

    while pos < n:
        while pos < n and body[pos] == 0x20:
            pos += 1
        if pos >= n:
            break
        if pos + 2 <= n and body[pos : pos + 2] in (b"\xF2\xF2", b"\xF3\xF3"):
            guide = 0xF2 if body[pos] == 0xF2 else 0xF3
            raw = body[pos + 2 :]
            code = "RGZS" if guide == 0xF2 else "PIC"
            value_text = raw.decode("ascii", errors="replace") if guide == 0xF2 else bytes_to_hex(raw, sep="")
            fb.elements.append(
                Element(
                    guide=guide,
                    guide_name=C.get_guide_name(guide, func_code),
                    data_len=len(raw),
                    decimals=0,
                    raw_hex=bytes_to_hex(raw, sep=""),
                    value_text=value_text,
                    offset=pos,
                    length=n - pos,
                    guide_code=code,
                )
            )
            spans.append((f"guide_{pos}", code, pos, n, value_text, "info"))
            break

        code_item = _token(body, pos)
        if not code_item:
            break
        code_start, code_end, code = code_item
        code_up = code.upper()
        pos = code_end
        # DRxnn carries its interval in the identifier itself. Other
        # identifiers always consume the next token as data; a numeric value
        # such as "12" is valid ASCII data and must not be mistaken for the
        # next hexadecimal identifier.
        value_item = None if id_only or code_up.startswith("DR") else _token(body, pos)

        if value_item:
            value_start, value_end, value = value_item
            pos = value_end
        else:
            value_start = value_end = code_end
            value = ""

        if code_up == "ST" and value:
            fb.remote_addr = value.upper()
            spans.append((f"guide_{code_start}", "测站编码引导符", code_start, code_end, code_up, "primary"))
            spans.append(("body_remote", value_start, value_start, value_end, value, "primary"))
            el = _ascii_element(code_up, value, body, code_start, value_end, func_code)
            fb.elements.append(el)
            spans[-1] = ("body_remote", "遥测站址(正文)", value_start, value_end, value, "primary")
            station = _token(body, value_end)
            if station and len(station[2]) == 1:
                st = next((k for k, v in C.STATION_TYPE_ASCII.items() if v == station[2].upper()), None)
                if st is not None:
                    fb.station_type = st
                    fb.station_type_name = C.STATION_TYPES.get(st)
                    spans.append(("station_type", "站类", station[0], station[1], station[2], "warning"))
                    pos = station[1]
            continue

        if code_up == "TT" and value:
            fb.observe_time = _format_observe_text(value)
            spans.append((f"guide_{code_start}", "观测时间引导符", code_start, code_end, code_up, "success"))
            spans.append(("observe_time", "观测时间", value_start, value_end, fb.observe_time, "success"))
            fb.elements.append(_ascii_element(code_up, value, body, code_start, value_end, func_code))
            continue

        label = C.get_guide_name(_ASCII_TO_GUIDE.get(code_up, 0), func_code) if code_up in _ASCII_TO_GUIDE else code
        guide_label = f"{label}引导符"
        spans.append((f"guide_{code_start}", guide_label, code_start, code_end, code_up, "info"))
        if value:
            spans.append((f"value_{value_start}", f"{label}数据", value_start, value_end, value, "info"))
            fb.elements.append(_ascii_element(code_up, value, body, code_start, value_end, func_code))
        else:
            fb.elements.append(_ascii_element(code_up, "", body, code_start, code_end, func_code))

    return fb, spans


def _ascii_layout(
    raw: bytes,
    header: FrameHeader,
    body_fields: list[tuple[str, str, int, int, str, str]],
    body_offset: int,
    end_flag: int,
    end_name: str,
    crc_hex: str,
    crc_ok: bool,
) -> list[FieldSpan]:
    fields: list[FieldSpan] = []

    def add(fid: str, label: str, start: int, end: int, value: str, group: str, color: str) -> None:
        if 0 <= start < end <= len(raw):
            fields.append(FieldSpan(fid, label, start, end, value, group, color))

    add("sof", "帧起始符", 0, 1, "01 (SOH)", "header", "neutral")
    if header.direction == "up":
        add("center", "中心站地址", 1, 3, raw[1:3].decode("ascii"), "header", "primary")
        add("remote", "遥测站地址", 3, 13, raw[3:13].decode("ascii"), "header", "primary")
    else:
        add("remote", "遥测站地址", 1, 11, raw[1:11].decode("ascii"), "header", "primary")
        add("center", "中心站地址", 11, 13, raw[11:13].decode("ascii"), "header", "primary")
    add("password", "密码", 13, 17, raw[13:17].decode("ascii"), "header", "warning")
    add("func", "功能码", 17, 19, raw[17:19].decode("ascii"), "header", "error")
    add("len", "上下行标识+长度", 19, 23, raw[19:23].decode("ascii"), "header", "info")
    add("stx", "正文起始符", 23, 24, f"{raw[23]:02X} ({'SYN' if header.m3 else 'STX'})", "header", "neutral")

    for fid, label, start, end, value, color in body_fields:
        add(fid, label, body_offset + start, body_offset + end, value, "body", color)

    if header.m3:
        packet_start = 24
        add("pkt_total", "包总数", packet_start, packet_start + 3, str(header.packet_total), "header", "warning")
        add("pkt_seq", "包序号", packet_start + 3, packet_start + 6, str(header.packet_seq), "header", "warning")

    end_pos = len(raw) - ASCII_CRC_LEN - 1
    covered: set[int] = set()
    for f in fields:
        if f.group == "body":
            covered.update(range(f.start, f.end))

    # 空格是 ASCII 正文的合法分隔符，交给字节图的专用样式显示；
    # 其他没有字段覆盖的内容则明确标成未解析，避免看起来像数据丢失。
    residual: list[int] = [
        i
        for i in range(body_offset, end_pos)
        if i not in covered and raw[i] != 0x20
    ]
    if residual:
        start = residual[0]
        prev = residual[0]
        for idx in residual[1:] + [None]:
            if idx is not None and idx == prev + 1:
                prev = idx
                continue
            add(
                f"residual_{start}",
                "未解析正文",
                start,
                prev + 1,
                _ascii_display(raw[start : prev + 1]),
                "body",
                "warning",
            )
            if idx is not None:
                start = prev = idx

    add("end", "结束符", end_pos, end_pos + 1, f"{end_flag:02X} ({end_name})", "trailer", "neutral")
    add("crc", "CRC16", len(raw) - ASCII_CRC_LEN, len(raw), f"{crc_hex} ({'通过' if crc_ok else '失败'})", "trailer", "success" if crc_ok else "error")
    return fields


def parse_ascii_frame(raw: bytes) -> ParsedFrame:
    if len(raw) < ASCII_MIN_FRAME_LEN:
        raise ValueError(f"ASCII 帧过短: {len(raw)} < {ASCII_MIN_FRAME_LEN}")
    if raw[0] != C.SOH:
        raise ValueError(f"ASCII 帧起始符错误: {raw[0]:02X}，期望 01")
    if raw[23] not in (C.STX, C.SYN):
        raise ValueError(f"ASCII 正文起始符错误: {raw[23]:02X}")

    center_text = _ascii_field(raw, 1, 3, "中心站地址")
    remote_text = _ascii_field(raw, 3, 13, "遥测站地址")
    direction_text = raw[19:20]
    if direction_text not in (b"0", b"8"):
        raise ValueError(f"ASCII 上下行标识错误: {direction_text!r}，期望 0 或 8")
    down = direction_text == b"8"
    if down:
        remote_text = _ascii_field(raw, 1, 11, "遥测站地址")
        center_text = _ascii_field(raw, 11, 13, "中心站地址")
    password = _ascii_field(raw, 13, 17, "密码")
    func = int(_ascii_field(raw, 17, 19, "功能码"), 16)
    len_text = _ascii_field(raw, 19, 23, "长度")
    len_field = int(len_text, 16)
    body_len = len_field & 0x0FFF
    m3 = raw[23] == C.SYN
    expected_len = ASCII_HEADER_LEN + body_len + 1 + ASCII_CRC_LEN
    errors: list[str] = []
    if len(raw) != expected_len:
        errors.append(f"正文长度不一致: 字段={body_len}, 实际帧长度={len(raw)}, 期望={expected_len}")

    try:
        got_crc_text = raw[-ASCII_CRC_LEN:].decode("ascii").upper()
        got_crc = bytes.fromhex(got_crc_text)
        crc_ok = crc16_bytes(raw[:-ASCII_CRC_LEN]) == got_crc
    except (UnicodeDecodeError, ValueError):
        got_crc_text = _ascii_display(raw[-ASCII_CRC_LEN:])
        crc_ok = False
    if not crc_ok:
        expect = bytes_to_hex(crc16_bytes(raw[:-ASCII_CRC_LEN]), sep="")
        errors.append(f"CRC 校验失败: 报文={got_crc_text}, 计算={expect}")

    end_flag = raw[-ASCII_CRC_LEN - 1]
    end_name = _END_NAMES.get(end_flag, f"未知结束符({end_flag:02X})")
    if (down and end_flag not in C.DOWN_END_FLAGS) or (not down and end_flag not in C.UP_END_FLAGS):
        errors.append(f"结束符不符合方向: {end_flag:02X}")

    packet_total = packet_seq = None
    body_offset = ASCII_HEADER_LEN
    if m3:
        if len(raw) < body_offset + 6 + 1 + ASCII_CRC_LEN:
            raise ValueError("ASCII M3 帧过短")
        packet_total = int(raw[24:27].decode("ascii"), 16)
        packet_seq = int(raw[27:30].decode("ascii"), 16)
        body_offset += 6

    end_pos = len(raw) - ASCII_CRC_LEN - 1
    body = raw[body_offset:end_pos]
    header = FrameHeader(
        center_addr=int(center_text, 16),
        remote_addr=remote_text,
        password=password,
        func_code=func,
        func_name=C.FUNC_CODES.get(func, f"未知功能码({func:02X})"),
        body_len=body_len,
        direction="down" if down else "up",
        m3=m3,
        stx=raw[23],
        packet_total=packet_total,
        packet_seq=packet_seq,
        encoding=C.WIRE_ASCII,
    )

    try:
        parsed_body, body_fields = parse_ascii_body(body, func, header.direction)
    except Exception as e:
        errors.append(f"ASCII 正文解析异常: {e}")
        parsed_body = FrameBody(raw_hex=bytes_to_hex(body, sep=""), raw_text=_ascii_display(body))
        body_fields = []

    crc_hex = got_crc_text
    fields = _ascii_layout(raw, header, body_fields, body_offset, end_flag, end_name, crc_hex, crc_ok)
    return ParsedFrame(
        raw=raw,
        raw_hex=bytes_to_hex(raw),
        raw_text=_ascii_display(raw),
        header=header,
        body=parsed_body,
        end_flag=end_flag,
        end_flag_name=end_name,
        crc=crc_hex,
        crc_ok=crc_ok,
        errors=errors,
        fields=fields,
        body_offset=body_offset,
    )


def _build_ascii_frame(
    *,
    direction: str,
    center_addr: int,
    remote_addr: Union[str, bytes],
    password: Union[str, bytes],
    func_code: int,
    body: bytes,
    end_flag: int,
    packet_total: Optional[int] = None,
    packet_seq: Optional[int] = None,
) -> bytes:
    remote = _remote_text(remote_addr)
    center = f"{center_addr & 0xFF:02X}"
    password_text = _password_text(password)
    func = f"{func_code & 0xFF:02X}"
    packet = b""
    stx = C.STX
    if packet_total is not None or packet_seq is not None:
        if packet_total is None or packet_seq is None:
            raise ValueError("M3 ASCII 帧必须同时提供 packet_total 和 packet_seq")
        if not (0 <= packet_total <= 0xFFF and 0 <= packet_seq <= 0xFFF):
            raise ValueError("ASCII M3 包总数/序号范围为 0~FFF")
        stx = C.SYN
        packet = f"{packet_total:03X}{packet_seq:03X}".encode("ascii")
    wire_body_len = len(packet) + len(body)
    if wire_body_len > C.MAX_BODY_LEN:
        raise ValueError(f"ASCII 正文过长: {wire_body_len} > {C.MAX_BODY_LEN}")
    direction_char = "8" if direction == "down" else "0"
    length_text = f"{direction_char}{wire_body_len:03X}"
    if direction == "up":
        header = f"{center}{remote}{password_text}{func}{length_text}".encode("ascii")
    else:
        header = f"{remote}{center}{password_text}{func}{length_text}".encode("ascii")
    frame = bytes([C.SOH]) + header + bytes([stx]) + packet + body + bytes([end_flag & 0xFF])
    crc = bytes_to_hex(crc16_bytes(frame), sep="").encode("ascii")
    return frame + crc


def build_ascii_down_frame(
    remote_addr: Union[str, bytes],
    center_addr: int,
    password: Union[str, bytes],
    func_code: int,
    body: bytes = b"",
    end_flag: int = C.EOT,
    packet_total: Optional[int] = None,
    packet_seq: Optional[int] = None,
) -> bytes:
    return _build_ascii_frame(
        direction="down",
        center_addr=center_addr,
        remote_addr=remote_addr,
        password=password,
        func_code=func_code,
        body=body,
        end_flag=end_flag,
        packet_total=packet_total,
        packet_seq=packet_seq,
    )


def build_ascii_up_frame(
    center_addr: int,
    remote_addr: Union[str, bytes],
    password: Union[str, bytes],
    func_code: int,
    body: bytes = b"",
    end_flag: int = C.ETX,
    packet_total: Optional[int] = None,
    packet_seq: Optional[int] = None,
) -> bytes:
    return _build_ascii_frame(
        direction="up",
        center_addr=center_addr,
        remote_addr=remote_addr,
        password=password,
        func_code=func_code,
        body=body,
        end_flag=end_flag,
        packet_total=packet_total,
        packet_seq=packet_seq,
    )
