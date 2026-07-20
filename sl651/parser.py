"""SL651-2014 上行帧解析"""

from __future__ import annotations

from . import constants as C
from .crc16 import crc16_bytes, verify
from .hexutil import (
    bcd_to_str,
    bytes_to_hex,
    format_observe_time,
    format_send_time,
    hex_to_bytes,
)
from .models import Element, FieldSpan, FrameBody, FrameHeader, ParsedFrame

_END_NAMES = {
    C.ETX: "ETX 报文结束",
    C.ETB: "ETB 多包中间结束",
    C.EOT: "EOT 传输结束",
    C.ENQ: "ENQ 询问",
    C.ACK: "ACK 肯定确认",
    C.NAK: "NAK 否定应答",
    C.ESC: "ESC 终端保持在线",
}


def _u16(data: bytes, i: int) -> int:
    return (data[i] << 8) | data[i + 1]


def _hex_at(raw: bytes, start: int, end: int) -> str:
    return bytes_to_hex(raw[start:end], sep=" ")


def parse_elements(
    data: bytes, base_offset: int = 0, func_code: int | None = None
) -> list[Element]:
    """解析标识符引导的要素序列：guide(1) + info(1) + value(N)

    func_code 用于区分要素标识符与配置参数标识符（两者取值重叠，见表26注）：
    - 40H/41H → 基本配置表（附录D.1）
    - 42H/43H → 运行参数配置表（附录D.4）
    - 其他 → 常规要素（附录C）
    """
    is_basic_cfg = func_code in C.BASIC_CONFIG_FUNC_CODES

    elements: list[Element] = []
    i = 0
    n = len(data)
    while i + 2 <= n:
        guide = data[i]
        info = data[i + 1]
        data_len = (info & 0xF8) >> 3
        decimals = info & 0x07
        if i + 2 + data_len > n:
            break
        raw = data[i + 2 : i + 2 + data_len]
        raw_hex = bytes_to_hex(raw, sep="")
        name = C.get_guide_name(guide, func_code)
        total_len = 2 + data_len

        value: float | None = None
        value_text: str | None = None

        if guide == C.GUIDE_STATION_ADDR:
            # 测站编码引导符 F1H — BCD 字符串
            value_text = bcd_to_str(raw) if raw else ""
        elif guide == C.GUIDE_OBSERVE_TIME:
            # 观测时间引导符 F0H — 5 字节 BCD 时间
            value_text = format_observe_time(raw) if len(raw) >= 5 else bcd_to_str(raw)
        elif is_basic_cfg and guide in C.BASIC_CONFIG_BCD_GUIDES:
            # 基本配置表中的地址/密码 — BCD/HEX 字符串
            if guide == 0x03:
                value_text = raw_hex.replace(" ", "")
            else:
                value_text = bcd_to_str(raw) if raw else ""
        else:
            try:
                digits = bcd_to_str(raw)
                if "?" not in digits and digits:
                    if decimals > 0:
                        if len(digits) <= decimals:
                            digits = digits.zfill(decimals + 1)
                        int_part = digits[:-decimals] or "0"
                        frac = digits[-decimals:]
                        value = float(f"{int_part}.{frac}")
                        value_text = f"{int_part}.{frac}"
                    else:
                        value = float(digits)
                        value_text = digits
                else:
                    value_text = raw_hex
            except Exception:
                value_text = raw_hex

        elements.append(
            Element(
                guide=guide,
                guide_name=name,
                data_len=data_len,
                decimals=decimals,
                raw_hex=raw_hex,
                value=value,
                value_text=value_text,
                offset=base_offset + i,
                length=total_len,
            )
        )
        i += total_len
    return elements


def _parse_body(body: bytes, func_code: int) -> tuple[FrameBody, list[tuple[str, str, int, int, str, str]]]:
    """
    解析正文。
    返回 (FrameBody, body_fields) 其中 body_fields 为相对正文起点的
    (id, label, start, end, value, color)
    """
    fb = FrameBody(raw_hex=bytes_to_hex(body, sep=""))
    spans: list[tuple[str, str, int, int, str, str]] = []
    if not body:
        return fb, spans

    def add(fid: str, label: str, s: int, e: int, val: str, color: str = "info") -> None:
        if 0 <= s < e <= len(body):
            spans.append((fid, label, s, e, val, color))

    if func_code == 0x2F:
        if len(body) >= 2:
            fb.serial_no = _u16(body, 0)
            add("serial_no", "流水号", 0, 2, str(fb.serial_no), "info")
        if len(body) >= 8:
            fb.send_time = format_send_time(body[2:8])
            add("send_time", "发报时间", 2, 8, fb.send_time or "", "success")
        return fb, spans

    if len(body) >= 2:
        fb.serial_no = _u16(body, 0)
        add("serial_no", "流水号", 0, 2, str(fb.serial_no), "info")
    if len(body) >= 8:
        fb.send_time = format_send_time(body[2:8])
        add("send_time", "发报时间", 2, 8, fb.send_time or "", "success")

    pos = 8
    if pos + 7 <= len(body) and body[pos] == 0xF1 and body[pos + 1] == 0xF1:
        fb.remote_addr = bcd_to_str(body[pos + 2 : pos + 7])
        add("addr_guide", "站址标识 F1F1", pos, pos + 2, "F1 F1", "neutral")
        add("body_remote", "遥测站址(正文)", pos + 2, pos + 7, fb.remote_addr or "", "primary")
        if pos + 7 < len(body):
            st = body[pos + 7]
            fb.station_type = st
            fb.station_type_name = C.STATION_TYPES.get(st, f"未知({st:02X})")
            add(
                "station_type",
                "站类",
                pos + 7,
                pos + 8,
                f"{st:02X} ({fb.station_type_name})",
                "warning",
            )
        pos += 8

    if pos + 7 <= len(body) and body[pos] == 0xF0 and body[pos + 1] == 0xF0:
        fb.observe_time = format_observe_time(body[pos + 2 : pos + 7])
        add("obs_guide", "观测时间标识 F0F0", pos, pos + 2, "F0 F0", "neutral")
        add("observe_time", "观测时间", pos + 2, pos + 7, fb.observe_time or "", "success")
        pos += 7

    if pos < len(body):
        fb.elements = parse_elements(body[pos:], base_offset=pos, func_code=func_code)
        for idx, el in enumerate(fb.elements):
            if el.offset is None or el.length is None:
                continue
            s, e = el.offset, el.offset + el.length
            val = el.value_text if el.value_text is not None else el.raw_hex
            if el.value is not None:
                val = str(el.value)
            add(
                f"elem_{idx}_{el.guide:02X}",
                f"[{el.guide:02X}] {el.guide_name}",
                s,
                e,
                val,
                "primary",
            )
    return fb, spans


def _build_layout(
    raw: bytes,
    direction: str,
    header: FrameHeader,
    body_fields: list[tuple[str, str, int, int, str, str]],
    body_offset: int,
    end_flag: int,
    end_name: str,
    crc_hex: str,
    crc_ok: bool,
) -> list[FieldSpan]:
    fields: list[FieldSpan] = []
    n = len(raw)

    def add(
        fid: str,
        label: str,
        start: int,
        end: int,
        value: str,
        group: str,
        color: str,
    ) -> None:
        if start < 0 or end > n or start >= end:
            return
        fields.append(
            FieldSpan(
                id=fid,
                label=label,
                start=start,
                end=end,
                value=value,
                group=group,
                color=color,
            )
        )

    # 帧头
    add("sof", "帧起始符", 0, 2, _hex_at(raw, 0, 2), "header", "neutral")

    if direction == "up":
        add("center", "中心站地址", 2, 3, f"{raw[2]:02X}", "header", "primary")
        add("remote", "遥测站地址", 3, 8, header.remote_addr, "header", "primary")
        add("password", "密码", 8, 10, header.password, "header", "warning")
        add("func", "功能码", 10, 11, f"{header.func_code:02X} {header.func_name}", "header", "error")
        add(
            "len",
            "上下行标识+长度",
            11,
            13,
            f"{_hex_at(raw, 11, 13)} (len={header.body_len})",
            "header",
            "info",
        )
        add(
            "stx",
            "正文起始符",
            13,
            14,
            f"{raw[13]:02X} ({'SYN' if header.m3 else 'STX'})",
            "header",
            "neutral",
        )
    else:
        add("remote", "遥测站地址", 2, 7, header.remote_addr, "header", "primary")
        add("center", "中心站地址", 7, 8, f"{raw[7]:02X}", "header", "primary")
        add("password", "密码", 8, 10, header.password, "header", "warning")
        add("func", "功能码", 10, 11, f"{header.func_code:02X} {header.func_name}", "header", "error")
        add(
            "len",
            "上下行标识+长度",
            11,
            13,
            f"{_hex_at(raw, 11, 13)} (len={header.body_len}, 下行)",
            "header",
            "info",
        )
        add(
            "stx",
            "正文起始符",
            13,
            14,
            f"{raw[13]:02X} ({'SYN' if header.m3 else 'STX'})",
            "header",
            "neutral",
        )

    if header.m3 and n >= 17:
        add("pkt_total", "包总数", 14, 15, str(header.packet_total), "header", "warning")
        add("pkt_seq", "包序号", 15, 17, str(header.packet_seq), "header", "warning")

    # 正文字段（相对偏移 → 绝对）
    for fid, label, s, e, val, color in body_fields:
        add(fid, label, body_offset + s, body_offset + e, val, "body", color)

    # 若正文有未覆盖残片
    end_pos = n - 3
    covered = set()
    for f in fields:
        if f.group == "body":
            for i in range(f.start, f.end):
                covered.add(i)
    residual = []
    for i in range(body_offset, end_pos):
        if i not in covered:
            residual.append(i)
    if residual:
        # 合并连续区间
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
                _hex_at(raw, start, prev + 1),
                "body",
                "neutral",
            )
            if idx is not None:
                start = prev = idx

    # 结束符 + CRC
    add("end", "结束符", n - 3, n - 2, f"{end_flag:02X} ({end_name})", "trailer", "warning")
    add(
        "crc",
        "CRC16",
        n - 2,
        n,
        f"{crc_hex} ({'通过' if crc_ok else '失败'})",
        "trailer",
        "success" if crc_ok else "error",
    )
    return fields


def parse_frame(raw: bytes) -> ParsedFrame:
    """解析完整一帧（含 7E7E ... CRC）"""
    errors: list[str] = []
    raw_hex = bytes_to_hex(raw)

    if len(raw) < C.MIN_FRAME_LEN:
        raise ValueError(f"帧过短: {len(raw)} < {C.MIN_FRAME_LEN}")

    if raw[0:2] != C.FRAME_START:
        raise ValueError(f"帧起始符错误: {raw[0:2].hex()}，期望 7E7E")

    crc_ok = verify(raw)
    crc_hex = bytes_to_hex(raw[-2:], sep="")
    if not crc_ok:
        expect = bytes_to_hex(crc16_bytes(raw[:-2]), sep="")
        errors.append(f"CRC 校验失败: 报文={crc_hex}, 计算={expect}")

    end_flag = raw[-3]
    end_name = _END_NAMES.get(end_flag, f"未知结束符({end_flag:02X})")

    len_field = _u16(raw, 11)
    direction = "down" if (len_field & 0x8000) else "up"
    body_len = len_field & 0x0FFF
    password = bytes_to_hex(raw[8:10], sep="")
    func = raw[10]
    stx = raw[13]
    m3 = stx == C.SYN

    if direction == "up":
        center = raw[2]
        remote = bcd_to_str(raw[3:8])
    else:
        remote = bcd_to_str(raw[2:7])
        center = raw[7]

    packet_total = packet_seq = None
    body_offset = 14
    if m3:
        if len(raw) < 17:
            raise ValueError("M3 帧过短")
        packet_total = raw[14]
        packet_seq = _u16(raw, 15) & 0x0FFF
        body_offset = 17

    end_pos = len(raw) - 3
    body = raw[body_offset:end_pos]

    if body_len and len(body) != body_len and not m3:
        errors.append(f"正文长度不一致: 字段={body_len}, 实际={len(body)}")

    header = FrameHeader(
        center_addr=center,
        remote_addr=remote,
        password=password,
        func_code=func,
        func_name=C.FUNC_CODES.get(func, f"未知功能码({func:02X})"),
        body_len=body_len,
        direction=direction,
        m3=m3,
        stx=stx,
        packet_total=packet_total,
        packet_seq=packet_seq,
    )

    body_fields: list[tuple[str, str, int, int, str, str]] = []
    try:
        parsed_body, body_fields = _parse_body(body, func)
    except Exception as e:
        errors.append(f"正文解析异常: {e}")
        parsed_body = FrameBody(raw_hex=bytes_to_hex(body, sep=""))

    fields = _build_layout(
        raw,
        direction,
        header,
        body_fields,
        body_offset,
        end_flag,
        end_name,
        crc_hex,
        crc_ok,
    )

    return ParsedFrame(
        raw=raw,
        raw_hex=raw_hex,
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


def parse_hex(hex_str: str) -> ParsedFrame:
    return parse_frame(hex_to_bytes(hex_str))
