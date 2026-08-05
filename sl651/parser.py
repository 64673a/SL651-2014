"""SL651-2014 报文帧解析

对齐《水文监测数据通信规约 SL651-2014》与公司 REF-SL651 报文分析样例。
"""

from __future__ import annotations

from . import constants as C
from .ascii_codec import parse_ascii_frame
from .crc16 import crc16_bytes, verify
from .hexutil import (
    bcd_to_str,
    bytes_to_hex,
    format_observe_time,
    format_send_time,
    hex_to_bytes,
    remote_addr_to_str,
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

# 正文含「站址 F1F1 + 站类 + 观测时间 F0F0 + 要素」的典型上报/应答功能码
_DATA_REPORT_FUNCS = {
    0x30, 0x31, 0x32, 0x33, 0x34, 0x36, 0x37, 0x38, 0x3A, 0x44,
}

# F4H：12 组 × 1 字节 HEX，单位 0.1mm；F5~FC：12 组 × 2 字节 HEX，单位 cm
_HEX_GROUP_GUIDES = {0xF4, 0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC}


def _u16(data: bytes, i: int) -> int:
    return (data[i] << 8) | data[i + 1]


def _hex_at(raw: bytes, start: int, end: int) -> str:
    return bytes_to_hex(raw[start:end], sep=" ")


def _is_invalid_bcd(raw: bytes) -> bool:
    """全 A/F 填充视为无数据/非法（公司样例用 AA，标准 HEX 组用 FF）。"""
    if not raw:
        return False
    return all(b in (0xAA, 0xFF) for b in raw)


def _decode_bcd_value(raw: bytes, decimals: int) -> tuple[float | None, str | None]:
    """BCD 数值解码；支持前导符号半字节（A/B/C/D 等非 0-9 视为负号扩展时按原样返回）。"""
    if _is_invalid_bcd(raw):
        return None, "无数据"
    digits = bcd_to_str(raw)
    if "?" in digits or not digits:
        return None, bytes_to_hex(raw, sep="")
    # 有符号 BCD：首位半字节为符号时常见为 0/1 或 FF 填充已处理
    sign = 1
    if digits[0] in "ABCDEF" or (len(digits) > 1 and digits.startswith("?")):
        return None, bytes_to_hex(raw, sep="")
    try:
        if decimals > 0:
            if len(digits) <= decimals:
                digits = digits.zfill(decimals + 1)
            int_part = digits[:-decimals] or "0"
            frac = digits[-decimals:]
            text = f"{int_part}.{frac}".lstrip("0")
            if text.startswith("."):
                text = "0" + text
            if not text or text == ".":
                text = "0" + (f".{'0' * decimals}" if decimals else "")
            # 规范展示：去掉整数前导零，保留小数
            value = float(f"{int_part}.{frac}") * sign
            value_text = f"{int_part.lstrip('0') or '0'}.{frac}"
            return value, value_text
        value = float(digits) * sign
        return value, str(int(digits)) if digits.isdigit() else digits
    except Exception:
        return None, bytes_to_hex(raw, sep="")


def _format_f4_rain(raw: bytes) -> tuple[list[float | None], str]:
    """F4：每字节 0.1mm，FF=非法。"""
    values: list[float | None] = []
    parts: list[str] = []
    for b in raw:
        if b == 0xFF:
            values.append(None)
            parts.append("—")
        else:
            v = b / 10.0
            values.append(v)
            parts.append(f"{v:g}")
    return values, ",".join(parts)


def _format_f5_level(raw: bytes) -> tuple[list[float | None], str]:
    """F5~FC：每 2 字节 HEX 厘米，FFFF=非法。"""
    values: list[float | None] = []
    parts: list[str] = []
    for i in range(0, len(raw) - 1, 2):
        hi, lo = raw[i], raw[i + 1]
        if hi == 0xFF and lo == 0xFF:
            values.append(None)
            parts.append("—")
        else:
            cm = (hi << 8) | lo
            v = cm / 100.0
            values.append(v)
            parts.append(f"{v:g}")
    return values, ",".join(parts)


def _format_status_bits(raw: bytes) -> str:
    """表58 遥测站状态及报警（4 字节 HEX）。"""
    if len(raw) < 4:
        return bytes_to_hex(raw, sep="")
    word = int.from_bytes(raw[:4], "big")
    parts: list[str] = []
    for bit, (name, mapping) in C.STATION_STATUS_BITS.items():
        val = (word >> bit) & 1
        parts.append(f"{name}:{mapping.get(val, val)}")
    return "; ".join(parts)


def _format_time_step(raw: bytes) -> str:
    """时间步长码 04H：3 字节 BCD dhm（表 C.3）。"""
    if len(raw) < 3:
        return bcd_to_str(raw)
    s = bcd_to_str(raw[:3])
    if "?" in s or len(s) < 6:
        return s
    d, h, m = int(s[0:2]), int(s[2:4]), int(s[4:6])
    if d == 0 and h == 0 and m == 0:
        return "特定搭配(0)"
    if d:
        return f"{d}日"
    if h:
        return f"{h}小时"
    if m:
        return f"{m}分钟"
    return s


def _format_channel(raw: bytes) -> str:
    """基本配置信道：类型(1 BCD) + 地址。"""
    if not raw:
        return ""
    ch = raw[0]
    # 信道类型可能是 BCD 单字节
    ch_type = ((ch >> 4) * 10 + (ch & 0x0F)) if (ch >> 4) <= 9 and (ch & 0x0F) <= 9 else ch
    name = C.CHANNEL_TYPES.get(ch_type, f"类型{ch_type}")
    if ch_type == 0 or len(raw) <= 1:
        return name
    addr = raw[1:]
    if ch_type == 2 and len(addr) >= 9:
        # IPV4: 6 字节 BCD IP + 3 字节 BCD 端口
        ip_s = bcd_to_str(addr[:6])
        port_s = bcd_to_str(addr[6:9])
        if "?" not in ip_s and len(ip_s) >= 12:
            ip = f"{int(ip_s[0:3])}.{int(ip_s[3:6])}.{int(ip_s[6:9])}.{int(ip_s[9:12])}"
            port = int(port_s) if "?" not in port_s else port_s
            return f"{name} {ip}:{port}"
    if ch_type == 1:
        # 短信：目的地常为 HEX/ASCII 号码（可含 A-F）
        try:
            text = addr.decode("ascii", errors="strict")
            if text.isprintable():
                return f"{name} {text}"
        except Exception:
            pass
        return f"{name} {bytes_to_hex(addr, sep='')}"
    return f"{name} {bytes_to_hex(addr, sep='')}"


def _format_basic_config(guide: int, raw: bytes) -> str:
    if guide == 0x01:
        # 4 中心站地址
        return ",".join(str(b) if b else "禁用" for b in raw)
    if guide == 0x02:
        return bcd_to_str(raw)
    if guide == 0x03:
        return bytes_to_hex(raw, sep="")
    if 0x04 <= guide <= 0x0B:
        return _format_channel(raw)
    if guide == 0x0C:
        mode = int(bcd_to_str(raw) or "0") if raw and "?" not in bcd_to_str(raw) else 0
        return C.WORK_MODES.get(mode, bcd_to_str(raw))
    if guide == 0x0D:
        return bytes_to_hex(raw, sep=" ")
    if guide == 0x0F and raw:
        card = raw[0]
        card_name = {0x31: "移动通信卡", 0x32: "北斗卫星通信卡", 1: "移动通信卡", 2: "北斗"}.get(
            card, f"卡类型({card:02X})"
        )
        rest = raw[1:].decode("ascii", errors="replace") if len(raw) > 1 else ""
        return f"{card_name} {rest}"
    return bytes_to_hex(raw, sep="")


def parse_elements(
    data: bytes,
    base_offset: int = 0,
    func_code: int | None = None,
    direction: str | None = None,
) -> list[Element]:
    """解析标识符引导的要素序列。

    标识符结构（表26）：
    - 通常 guide(1) + info(1) + value(N)，N = info>>3，小数位 = info&7
    - guide=FFH 时扩展：FF + ext(1) + info(1) + value(N)
    - F0/F1 实务固定为 F0F0/F1F1 + 5 字节
    - F2/F3 实务固定为 F2F2/F3F3 + 剩余正文（ASCII/JPG）
    - 41H/43H 下行读取请求：仅编列标识符（2 字节），不附带数据体
    """
    is_basic_cfg = func_code in C.BASIC_CONFIG_FUNC_CODES
    is_run_param = func_code in C.RUN_PARAM_FUNC_CODES
    # 读取配置/指定要素的下行查询：标识符后不附数据体（表50/52 等）
    # 38H 下行在时间步长码之后的要素标识也属此类，但步长码本身带数据，
    # 由 remaining==0 分支统一处理，不整段 id_only。
    id_only = direction == "down" and func_code in (0x41, 0x43, 0x3A)

    elements: list[Element] = []
    i = 0
    n = len(data)

    while i < n:
        # 特殊双字节标识：F0F0 观测时间 / F1F1 测站编码
        if i + 2 <= n and data[i] == data[i + 1] == C.GUIDE_OBSERVE_TIME:
            if i + 7 > n:
                break
            raw = data[i + 2 : i + 7]
            text = format_observe_time(raw)
            elements.append(
                Element(
                    guide=C.GUIDE_OBSERVE_TIME,
                    guide_name="观测时间",
                    data_len=5,
                    decimals=0,
                    raw_hex=bytes_to_hex(raw, sep=""),
                    value=None,
                    value_text=text,
                    offset=base_offset + i,
                    length=7,
                )
            )
            i += 7
            continue

        if i + 2 <= n and data[i] == data[i + 1] == C.GUIDE_STATION_ADDR:
            if i + 7 > n:
                break
            raw = data[i + 2 : i + 7]
            text = bcd_to_str(raw)
            elements.append(
                Element(
                    guide=C.GUIDE_STATION_ADDR,
                    guide_name="测站编码",
                    data_len=5,
                    decimals=0,
                    raw_hex=bytes_to_hex(raw, sep=""),
                    value=None,
                    value_text=text,
                    offset=base_offset + i,
                    length=7,
                )
            )
            i += 7
            continue

        # F2F2 人工置数 / F3F3 图片：后续直至正文结束
        if i + 2 <= n and data[i] == 0xF2 and data[i + 1] == 0xF2:
            raw = data[i + 2 :]
            try:
                text = raw.decode("ascii", errors="replace").rstrip("\x00")
            except Exception:
                text = bytes_to_hex(raw, sep="")
            elements.append(
                Element(
                    guide=0xF2,
                    guide_name="人工置数",
                    data_len=len(raw),
                    decimals=0,
                    raw_hex=bytes_to_hex(raw, sep=""),
                    value=None,
                    value_text=text,
                    offset=base_offset + i,
                    length=2 + len(raw),
                )
            )
            break

        if i + 2 <= n and data[i] == 0xF3 and data[i + 1] == 0xF3:
            raw = data[i + 2 :]
            elements.append(
                Element(
                    guide=0xF3,
                    guide_name="图片信息",
                    data_len=len(raw),
                    decimals=0,
                    raw_hex=bytes_to_hex(raw[:32], sep="") + ("..." if len(raw) > 32 else ""),
                    value=None,
                    value_text=f"JPG {len(raw)} 字节",
                    offset=base_offset + i,
                    length=2 + len(raw),
                )
            )
            break

        if i + 2 > n:
            break

        # FF 扩展标识符（表26）
        ext_id: int | None = None
        if data[i] == 0xFF:
            if i + 3 > n:
                break
            ext_id = data[i + 1]
            guide = 0xFF
            info = data[i + 2]
            hdr_len = 3
            name = f"扩展要素(FF{ext_id:02X})"
            # 公司自定义：FF11 振弦水位0
            if ext_id == 0x11:
                name = "振弦水位0"
        else:
            guide = data[i]
            info = data[i + 1]
            hdr_len = 2
            name = C.get_guide_name(guide, func_code)

        data_len = (info & 0xF8) >> 3
        decimals = info & 0x07

        # 0EH 中继站：info 全 8 位表示长度
        if is_basic_cfg and guide == 0x0E:
            data_len = info

        # 下行查询只带标识符（guide+info），data_len 仅描述期望定义
        if id_only and ext_id is None:
            elements.append(
                Element(
                    guide=guide,
                    guide_name=name,
                    data_len=data_len,
                    decimals=decimals,
                    raw_hex="",
                    value=None,
                    value_text="(查询标识)",
                    offset=base_offset + i,
                    length=hdr_len,
                )
            )
            i += hdr_len
            continue

        # 查询帧常见「仅标识符」：info 声明了数据定义，但正文不再附带数据体
        remaining = n - i - hdr_len
        if remaining < data_len:
            if remaining == 0:
                elements.append(
                    Element(
                        guide=guide if ext_id is None else (0xFF00 | ext_id),
                        guide_name=name,
                        data_len=0,
                        decimals=decimals,
                        raw_hex="",
                        value=None,
                        value_text="(仅标识符)",
                        offset=base_offset + i,
                        length=hdr_len,
                    )
                )
                i += hdr_len
                continue
            if guide in (0xF2, 0xF3) and i + 2 <= n:
                raw = data[i + 2 :]
                elements.append(
                    Element(
                        guide=guide,
                        guide_name=name,
                        data_len=len(raw),
                        decimals=0,
                        raw_hex=bytes_to_hex(raw, sep=""),
                        value=None,
                        value_text=raw.decode("ascii", errors="replace")
                        if guide == 0xF2
                        else f"数据 {len(raw)} 字节",
                        offset=base_offset + i,
                        length=2 + len(raw),
                    )
                )
            break

        raw = data[i + hdr_len : i + hdr_len + data_len]
        raw_hex = bytes_to_hex(raw, sep="")
        total_len = hdr_len + data_len
        value: float | None = None
        value_text: str | None = None

        if guide == C.GUIDE_STATION_ADDR:
            value_text = bcd_to_str(raw) if raw else ""
        elif guide == C.GUIDE_OBSERVE_TIME:
            value_text = format_observe_time(raw) if len(raw) >= 5 else bcd_to_str(raw)
        elif is_basic_cfg:
            value_text = _format_basic_config(guide, raw)
        elif is_run_param:
            value, value_text = _decode_bcd_value(raw, decimals)
            if value_text is None:
                value_text = raw_hex
        elif guide == 0x04:
            # 时间步长码
            value_text = _format_time_step(raw)
        elif guide == 0x45:
            # 状态及报警：4 字节 HEX 位图
            value_text = _format_status_bits(raw)
        elif guide in _HEX_GROUP_GUIDES:
            if guide == 0xF4:
                _, value_text = _format_f4_rain(raw)
            else:
                _, value_text = _format_f5_level(raw)
        elif guide == 0xFF and ext_id is not None:
            value, value_text = _decode_bcd_value(raw, decimals)
        else:
            value, value_text = _decode_bcd_value(raw, decimals)

        elements.append(
            Element(
                guide=guide if ext_id is None else (0xFF00 | ext_id),
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


def _switch_bits_text(status: bytes, n: int, unit: str = "路") -> str:
    """按表71/74/77：第 i 位对应第 i+1 路，1=开 0=关。"""
    parts: list[str] = []
    for i in range(n):
        bi, bit = i // 8, i % 8
        on = 0
        if bi < len(status):
            on = (status[bi] >> bit) & 1
        parts.append(f"{i + 1}号{unit}{'开' if on else '关'}")
    return "、".join(parts) if parts else ""


def _parse_switch_control(
    body: bytes, pos: int, fb: FrameBody, add, unit: str = "泵"
) -> int:
    """4C/4D 下行/上行控制数据：后续字节数(1) + 状态字节(s)。表71/74。"""
    if pos >= len(body):
        return pos
    n_follow = body[pos]
    add("ctrl_len", "后续数据字节数", pos, pos + 1, str(n_follow), "info")
    pos += 1
    if n_follow <= 0 or pos >= len(body):
        return pos
    end = min(len(body), pos + n_follow)
    status = body[pos:end]
    n_bits = min(n_follow * 8, 32)
    text = _switch_bits_text(status, n_bits, unit=unit)
    raw = bytes_to_hex(status, sep="")
    add("ctrl_status", f"{unit}开关状态", pos, end, text or raw, "primary")
    fb.elements.append(
        Element(
            guide=0x4C if unit == "泵" else 0x4D,
            guide_name=f"{unit}开关状态",
            data_len=len(status),
            decimals=0,
            raw_hex=raw,
            value_text=text or raw,
            offset=pos,
            length=len(status),
        )
    )
    return end


def _parse_gate_control(body: bytes, pos: int, fb: FrameBody, add) -> int:
    """4E 闸门：闸门数(1) + 状态字节(ceil(n/8)) + 开度 2B BCD×n。表77。"""
    if pos >= len(body):
        return pos
    n = body[pos]
    add("gate_count", "闸门数", pos, pos + 1, str(n), "info")
    fb.elements.append(
        Element(
            guide=0x4E,
            guide_name="闸门数",
            data_len=1,
            decimals=0,
            raw_hex=f"{n:02X}",
            value=float(n),
            value_text=str(n),
            offset=pos,
            length=1,
        )
    )
    pos += 1
    if n <= 0:
        return pos
    n_status = max(1, (n + 7) // 8)
    if pos >= len(body):
        return pos
    end_st = min(len(body), pos + n_status)
    status = body[pos:end_st]
    text = _switch_bits_text(status, n, unit="闸门")
    raw_st = bytes_to_hex(status, sep="")
    add("gate_status", "闸门开关", pos, end_st, text or raw_st, "primary")
    fb.elements.append(
        Element(
            guide=0x4E,
            guide_name="闸门开关",
            data_len=len(status),
            decimals=0,
            raw_hex=raw_st,
            value_text=text or raw_st,
            offset=pos,
            length=len(status),
        )
    )
    pos = end_st
    for i in range(n):
        if pos + 2 > len(body):
            break
        raw = body[pos : pos + 2]
        digits = bcd_to_str(raw)
        if "?" in digits:
            val_text = bytes_to_hex(raw, sep="")
            cm = None
        else:
            cm = int(digits)
            val_text = f"{cm} cm"
        add(f"gate_open_{i + 1}", f"闸门{i + 1}开度", pos, pos + 2, val_text, "success")
        fb.elements.append(
            Element(
                guide=0x4E,
                guide_name=f"闸门{i + 1}开度",
                data_len=2,
                decimals=0,
                raw_hex=bytes_to_hex(raw, sep=""),
                value=float(cm) if cm is not None else None,
                value_text=val_text,
                offset=pos,
                length=2,
            )
        )
        pos += 2
    return pos


def _parse_water_control(body: bytes, pos: int, fb: FrameBody, add) -> int:
    """4F 水量定值：1 字节 FF=投入 / 00=退出。表80。"""
    if pos >= len(body):
        return pos
    b = body[pos]
    if b == 0xFF:
        text = "投入 (FF)"
    elif b == 0x00:
        text = "退出 (00)"
    else:
        text = f"{b:02X}"
    add("water_ctrl", "定值控制", pos, pos + 1, text, "primary")
    fb.elements.append(
        Element(
            guide=0x4F,
            guide_name="定值控制",
            data_len=1,
            decimals=0,
            raw_hex=f"{b:02X}",
            value_text=text,
            offset=pos,
            length=1,
        )
    )
    return pos + 1


def _parse_period_query_down(body: bytes, fb: FrameBody, add) -> int:
    """38H 下行：流水号+发报时间+起始时间(4)+结束时间(4)+时间步长+要素标识。"""
    pos = 8
    if pos + 4 <= len(body):
        start = body[pos : pos + 4]
        text = bcd_to_str(start)
        if len(text) >= 8 and "?" not in text:
            text = f"20{text[0:2]}-{text[2:4]}-{text[4:6]} {text[6:8]}:00"
        fb.elements.append(
            Element(
                guide=0x00,
                guide_name="起始时间",
                data_len=4,
                decimals=0,
                raw_hex=bytes_to_hex(start, sep=""),
                value_text=text,
                offset=pos,
                length=4,
            )
        )
        add("start_time", "起始时间", pos, pos + 4, text, "success")
        pos += 4
    if pos + 4 <= len(body):
        end = body[pos : pos + 4]
        text = bcd_to_str(end)
        if len(text) >= 8 and "?" not in text:
            text = f"20{text[0:2]}-{text[2:4]}-{text[4:6]} {text[6:8]}:00"
        fb.elements.append(
            Element(
                guide=0x00,
                guide_name="结束时间",
                data_len=4,
                decimals=0,
                raw_hex=bytes_to_hex(end, sep=""),
                value_text=text,
                offset=pos,
                length=4,
            )
        )
        add("end_time", "结束时间", pos, pos + 4, text, "success")
        pos += 4
    return pos


def _parse_software_version(body: bytes, pos: int, fb: FrameBody, add) -> int:
    """45H 上行：站址后为 1 字节长度 + ASCII 版本串。"""
    if pos >= len(body):
        return pos
    # 可选 F1F1 站址
    if pos + 7 <= len(body) and body[pos] == 0xF1 and body[pos + 1] == 0xF1:
        fb.remote_addr = remote_addr_to_str(body[pos + 2 : pos + 7])
        add("addr_guide", "站址标识 F1F1", pos, pos + 2, "F1 F1", "neutral")
        add("body_remote", "遥测站址(正文)", pos + 2, pos + 7, fb.remote_addr or "", "primary")
        pos += 7
    if pos >= len(body):
        return pos
    ver_len = body[pos]
    add("ver_len", "版本信息长度", pos, pos + 1, str(ver_len), "info")
    pos += 1
    raw = body[pos : pos + ver_len] if pos + ver_len <= len(body) else body[pos:]
    text = raw.decode("ascii", errors="replace")
    fb.elements.append(
        Element(
            guide=0x45,
            guide_name="软件版本",
            data_len=len(raw),
            decimals=0,
            raw_hex=bytes_to_hex(raw, sep=""),
            value_text=text,
            offset=pos - 1,
            length=1 + len(raw),
        )
    )
    add("version", "软件版本", pos - 1, pos + len(raw), text, "primary")
    return pos + len(raw)


def _append_element_spans(
    spans_add, elements: list[Element], start_idx: int = 0
) -> None:
    for idx, el in enumerate(elements, start=start_idx):
        if el.offset is None or el.length is None:
            continue
        s, e = el.offset, el.offset + el.length
        val = el.value_text if el.value_text is not None else el.raw_hex
        if el.value is not None and el.value_text is None:
            val = str(el.value)
        if el.guide > 0xFF:
            fid = f"elem_{idx}_{el.guide:04X}"
            label = f"[FF{(el.guide & 0xFF):02X}] {el.guide_name}"
        else:
            fid = f"elem_{idx}_{el.guide:02X}"
            label = f"[{el.guide:02X}] {el.guide_name}"
        spans_add(fid, label, s, e, val or "", "primary")


def _parse_body(
    body: bytes, func_code: int, direction: str = "up"
) -> tuple[FrameBody, list[tuple[str, str, int, int, str, str]]]:
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

    # 链路维持 2F：仅流水号 + 发报时间
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

    # 38H 下行查询时段：起始/结束时间在站址之前
    if (
        func_code == 0x38
        and direction == "down"
        and pos < len(body)
        and not (pos + 2 <= len(body) and body[pos] == 0xF1 and body[pos + 1] == 0xF1)
    ):
        pos = _parse_period_query_down(body, fb, add)

    # 45H 软件版本
    if func_code == 0x45:
        _parse_software_version(body, pos, fb, add)
        return fb, spans

    # 35H/39H 人工置数：流水号+时间后直接 F2F2 + ASCII
    if func_code in (0x35, 0x39):
        if pos < len(body):
            els = parse_elements(
                body[pos:], base_offset=pos, func_code=func_code, direction=direction
            )
            fb.elements.extend(els)
            _append_element_spans(add, els)
        return fb, spans

    # 4C/4D/4E/4F 控制命令：流水号+时间后为控制数据（非要素标识）
    # 上行 4C/4D/4E 在站址 F1F1 之后也可能跟控制数据，此处先处理「无 F1F1 的下行」
    if func_code in (0x4C, 0x4D, 0x4E, 0x4F) and pos < len(body):
        if not (pos + 2 <= len(body) and body[pos] == 0xF1 and body[pos + 1] == 0xF1):
            if func_code == 0x4C:
                _parse_switch_control(body, pos, fb, add, unit="泵")
            elif func_code == 0x4D:
                _parse_switch_control(body, pos, fb, add, unit="阀门")
            elif func_code == 0x4E:
                _parse_gate_control(body, pos, fb, add)
            else:
                _parse_water_control(body, pos, fb, add)
            return fb, spans

    # 站址 F1F1（可选）
    if pos + 7 <= len(body) and body[pos] == 0xF1 and body[pos + 1] == 0xF1:
        fb.remote_addr = remote_addr_to_str(body[pos + 2 : pos + 7])
        add("addr_guide", "站址标识 F1F1", pos, pos + 2, "F1 F1", "neutral")
        add("body_remote", "遥测站址(正文)", pos + 2, pos + 7, fb.remote_addr or "", "primary")
        pos += 7
        # 站类：仅数据类报文且下一字节为已知站类码时解析
        if (
            func_code in _DATA_REPORT_FUNCS
            and pos < len(body)
            and body[pos] in C.STATION_TYPES
        ):
            st = body[pos]
            fb.station_type = st
            fb.station_type_name = C.STATION_TYPES[st]
            add(
                "station_type",
                "站类",
                pos,
                pos + 1,
                f"{st:02X} ({fb.station_type_name})",
                "warning",
            )
            pos += 1

    # 观测时间 F0F0（可选，数据报首段）
    if pos + 7 <= len(body) and body[pos] == 0xF0 and body[pos + 1] == 0xF0:
        fb.observe_time = format_observe_time(body[pos + 2 : pos + 7])
        add("obs_guide", "观测时间标识 F0F0", pos, pos + 2, "F0 F0", "neutral")
        add("observe_time", "观测时间", pos + 2, pos + 7, fb.observe_time or "", "success")
        pos += 7

    # 上行 4C/4D/4E：站址后为控制状态数据（表73/76/79）
    if func_code in (0x4C, 0x4D, 0x4E, 0x4F) and pos < len(body):
        if func_code == 0x4C:
            _parse_switch_control(body, pos, fb, add, unit="泵")
        elif func_code == 0x4D:
            _parse_switch_control(body, pos, fb, add, unit="阀门")
        elif func_code == 0x4E:
            _parse_gate_control(body, pos, fb, add)
        else:
            _parse_water_control(body, pos, fb, add)
        return fb, spans

    if pos < len(body):
        els = parse_elements(
            body[pos:], base_offset=pos, func_code=func_code, direction=direction
        )
        # 时段查询下行的起始/结束时间已在 elements 中，追加要素
        if fb.elements:
            fb.elements.extend(els)
            _append_element_spans(add, els, start_idx=len(fb.elements) - len(els))
        else:
            fb.elements = els
            for el in els:
                if el.guide == C.GUIDE_OBSERVE_TIME and el.value_text and not fb.observe_time:
                    fb.observe_time = el.value_text
            _append_element_spans(add, els)
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

    for fid, label, s, e, val, color in body_fields:
        add(fid, label, body_offset + s, body_offset + e, val, "body", color)

    end_pos = n - 3
    covered: set[int] = set()
    for f in fields:
        if f.group == "body":
            for i in range(f.start, f.end):
                covered.add(i)
    residual: list[int] = []
    for i in range(body_offset, end_pos):
        if i not in covered:
            residual.append(i)
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
                _hex_at(raw, start, prev + 1),
                "body",
                "neutral",
            )
            if idx is not None:
                start = prev = idx

    add("end", "结束符", n - 3, n - 2, f"{end_flag:02X} ({end_name})", "trailer", "neutral")
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


def parse_frame(raw: bytes, encoding: str = C.WIRE_AUTO) -> ParsedFrame:
    """解析完整一帧；默认按 SOH/7E7E 自动识别线路编码。"""
    wire = C.normalize_wire_encoding(encoding, default=C.WIRE_AUTO)
    if wire == C.WIRE_ASCII or (wire == C.WIRE_AUTO and raw[:1] == bytes([C.SOH])):
        return parse_ascii_frame(raw)

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
        remote = remote_addr_to_str(raw[3:8])
    else:
        remote = remote_addr_to_str(raw[2:7])
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
        parsed_body, body_fields = _parse_body(body, func, direction=direction)
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


def parse_hex(hex_str: str, encoding: str = C.WIRE_AUTO) -> ParsedFrame:
    return parse_frame(hex_to_bytes(hex_str), encoding=encoding)
