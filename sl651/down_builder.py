"""下行正文构造：按功能码生成 body + 默认结束符。

对齐：
- sl651-2014.md 表 25/41–85、附录 C/D
- REF-SL651报文分析 公司样例（golden）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence, Union

from . import constants as C
from .encoder import _bcd_digits, _now_bcd6
from .hexutil import hex_to_bytes


def default_down_end_flag(func_code: int) -> int:
    """功能码默认结束符：查询/控制 ENQ，确认类 ESC。"""
    return C.DOWN_END_FLAG_BY_FUNC.get(func_code & 0xFF, C.ENQ)


def down_body_schema(func_code: int) -> str:
    return C.DOWN_BODY_SCHEMA.get(func_code & 0xFF, "simple")


def _info_byte(data_len: int, decimals: int = 0) -> int:
    return ((data_len & 0x1F) << 3) | (decimals & 0x07)


def _parse_guide(g: Union[int, str]) -> int:
    if isinstance(g, int):
        return g & 0xFF
    s = str(g).strip().replace("0x", "").replace("0X", "")
    return int(s, 16) & 0xFF


def _sn_time(serial_no: int, send_time: Optional[datetime] = None) -> bytes:
    sn = bytes([(serial_no >> 8) & 0xFF, serial_no & 0xFF])
    return sn + _now_bcd6(send_time)


def _digits_from_time_str(s: str, n_digits: int) -> str:
    """从 ISO / YYMMDDHH… / 带分隔符字符串提取数字。"""
    raw = "".join(c for c in str(s) if c.isdigit())
    if len(raw) >= 14 and raw.startswith("20"):
        # 20YYMMDDHHmmSS → 去掉世纪
        raw = raw[2:]
    elif len(raw) >= 12 and raw.startswith("20") and n_digits <= 10:
        raw = raw[2:]
    return raw.zfill(n_digits)[-n_digits:]


def encode_bcd_time(s: Optional[str], nbytes: int, now_if_empty: bool = True) -> bytes:
    """字符串 → BCD 时间。nbytes=6 为 YYMMDDHHmmSS，4 为 YYMMDDHH。"""
    n_digits = nbytes * 2
    if not s:
        if not now_if_empty:
            raise ValueError("时间不能为空")
        dt = datetime.now()
        if nbytes == 6:
            digits = dt.strftime("%y%m%d%H%M%S")
        elif nbytes == 5:
            digits = dt.strftime("%y%m%d%H%M")
        else:
            digits = dt.strftime("%y%m%d%H")
        return _bcd_digits(digits, nbytes)
    return _bcd_digits(_digits_from_time_str(s, n_digits), nbytes)


def encode_time_step(unit: str = "N", value: int = 5) -> bytes:
    """附录 C.3：04 18 + 3 字节 BCD（日/时/分三选一非零）。

    unit: D=日, H=小时, N=分钟
    """
    u = (unit or "N").upper()
    v = max(0, int(value)) % 100
    d = h = m = 0
    if u in ("D", "DAY", "日"):
        d = v
    elif u in ("H", "HOUR", "时", "小时"):
        h = v
    else:
        m = v
    dhm = f"{d:02d}{h:02d}{m:02d}"
    return bytes([0x04, 0x18]) + _bcd_digits(dhm, 3)


def _default_info_for_guide(guide: int, func_code: int | None = None) -> int:
    """生成 id-only 的 info 字节。"""
    g = guide & 0xFF
    if func_code is not None:
        if func_code in C.BASIC_CONFIG_FUNC_CODES:
            if g in C.BASIC_CONFIG_INFO_DEFAULTS:
                return C.BASIC_CONFIG_INFO_DEFAULTS[g]
        if func_code in C.RUN_PARAM_FUNC_CODES or func_code in (0x47, 0x48):
            if g in C.RUN_PARAM_INFO_DEFAULTS:
                return C.RUN_PARAM_INFO_DEFAULTS[g]
    pair = C.ELEMENT_INFO_DEFAULTS.get(g)
    if pair:
        return _info_byte(pair[0], pair[1])
    return 0x00


def encode_id_only(guide: int, func_code: int | None = None, info: int | None = None) -> bytes:
    """guide(1) + info(1)，无数据体。"""
    g = guide & 0xFF
    ib = info if info is not None else _default_info_for_guide(g, func_code)
    return bytes([g, ib & 0xFF])


def encode_param(guide: int, value_hex: str, func_code: int | None = None) -> bytes:
    """guide + info + 数据。info 优先按 value 长度推断。"""
    g = guide & 0xFF
    raw = hex_to_bytes(value_hex) if value_hex and str(value_hex).strip() else b""
    if raw:
        # 有数据：data_len = len(raw)，decimals 尽量用默认表
        pair = C.ELEMENT_INFO_DEFAULTS.get(g)
        decimals = pair[1] if pair else 0
        if func_code in C.BASIC_CONFIG_FUNC_CODES:
            # 配置项常用 HEX 无小数
            decimals = 0
        info = _info_byte(len(raw), decimals)
        # 0EH 中继：info 全 8 位表示长度
        if func_code in C.BASIC_CONFIG_FUNC_CODES and g == 0x0E:
            info = len(raw) & 0xFF
        return bytes([g, info]) + raw
    return encode_id_only(g, func_code)


def build_down_body(
    func_code: int,
    *,
    serial_no: int = 0,
    send_time: Optional[Union[datetime, str]] = None,
    body_hex: Optional[str] = None,
    # 38H
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    step_unit: str = "N",
    step_value: int = 5,
    # 3A / 41 / 43 / 38 要素
    guides: Optional[Sequence[Union[int, str]]] = None,
    # 40 / 42
    params: Optional[Sequence[dict[str, Any]]] = None,
    # 49H
    old_password: Optional[str] = None,
    new_password: Optional[str] = None,
    # 4B
    ic_enable: Optional[bool] = None,
    # 4C / 4D
    switch_bits: Optional[int] = None,
    # 4E
    gate_count: Optional[int] = None,
    gate_bits: Optional[int] = None,
    gate_openings_cm: Optional[Sequence[int]] = None,
    # 4F
    water_control: Optional[str] = None,
) -> bytes:
    """按功能码构造下行正文。body_hex 非空时直接使用。"""
    if body_hex is not None and str(body_hex).strip():
        return hex_to_bytes(str(body_hex))

    fc = func_code & 0xFF
    st: Optional[datetime]
    if isinstance(send_time, datetime) or send_time is None:
        st = send_time
        prefix = _sn_time(serial_no, st)
    else:
        # 字符串时间：流水号 + 固定 BCD
        prefix = bytes([(serial_no >> 8) & 0xFF, serial_no & 0xFF]) + encode_bcd_time(
            str(send_time), 6, now_if_empty=True
        )

    # 简单查询 / 确认 / 校时
    if fc in (
        0x30,
        0x31,
        0x32,
        0x33,
        0x34,
        0x35,
        0x36,
        0x37,
        0x39,
        0x44,
        0x45,
        0x46,
        0x4A,
        0x50,
        0x51,
    ):
        return prefix

    # 38H 时段查询
    if fc == 0x38:
        body = bytearray(prefix)
        body += encode_bcd_time(start_time, 4)
        body += encode_bcd_time(end_time, 4)
        body += encode_time_step(step_unit, step_value)
        for g in guides or [0xF4]:
            body += encode_id_only(_parse_guide(g), fc)
        return bytes(body)

    # 3A 指定要素 / 41 读基本配置 / 43 读运行参数
    if fc in (0x3A, 0x41, 0x43):
        body = bytearray(prefix)
        glist = list(guides or [])
        if not glist:
            if fc == 0x3A:
                glist = [0xF4]
            elif fc == 0x41:
                glist = [0x01, 0x02, 0x03, 0x04, 0x05, 0x0C, 0x0D, 0x0F]
            else:
                glist = [0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x30, 0x38, 0x40, 0x41]
        for g in glist:
            body += encode_id_only(_parse_guide(g), fc)
        return bytes(body)

    # 40 / 42 修改配置
    if fc in (0x40, 0x42):
        body = bytearray(prefix)
        for p in params or []:
            g = _parse_guide(p.get("guide", 0))
            body += encode_param(g, str(p.get("value_hex", "") or ""), fc)
        return bytes(body)

    # 47 初始化固态
    if fc == 0x47:
        return prefix + encode_id_only(0x97, 0x47)

    # 48 恢复出厂
    if fc == 0x48:
        return prefix + encode_id_only(0x98, 0x48)

    # 49 修改密码：03 10 + old(2) + 03 10 + new(2)
    if fc == 0x49:
        old = hex_to_bytes((old_password or "0000").replace(" ", "").zfill(4)[-4:])
        new = hex_to_bytes((new_password or "0000").replace(" ", "").zfill(4)[-4:])
        return prefix + bytes([0x03, 0x10]) + old + bytes([0x03, 0x10]) + new

    # 4B IC 卡状态：45 20 + 4 字节（BIT9）
    if fc == 0x4B:
        status = 0
        if ic_enable:
            status |= 1 << 9
        st_bytes = status.to_bytes(4, "big")
        return prefix + bytes([0x45, 0x20]) + st_bytes

    # 4C / 4D 水泵/阀门：len + 状态字节
    if fc in (0x4C, 0x4D):
        bits = int(switch_bits or 0) & 0xFF
        return prefix + bytes([0x01, bits])

    # 4E 闸门：count + 状态字节… + 开度 2B BCD each
    if fc == 0x4E:
        n = max(1, int(gate_count or 1))
        bits = int(gate_bits or 0)
        n_status = (n + 7) // 8
        status = bits.to_bytes(n_status, "little")
        openings = list(gate_openings_cm or [0] * n)
        body = bytearray(prefix)
        body.append(n & 0xFF)
        body += status
        for cm in openings[:n]:
            body += _bcd_digits(str(int(cm)).zfill(4)[-4:], 2)
        return bytes(body)

    # 4F 水量定值：FF 投入 / 00 退出
    if fc == 0x4F:
        on = (water_control or "on").lower() in ("on", "1", "ff", "true", "投入")
        return prefix + bytes([0xFF if on else 0x00])

    # 未知功能码：仅前缀
    return prefix


def build_down_command(
    remote_addr: str,
    center_addr: int,
    password: str,
    func_code: int,
    *,
    end_flag: Optional[int] = None,
    **body_kwargs: Any,
) -> tuple[bytes, bytes, int]:
    """组完整下行帧。返回 (frame, body, end_flag)。"""
    from .encoder import build_down_frame

    body = build_down_body(func_code, **body_kwargs)
    ef = end_flag if end_flag is not None else default_down_end_flag(func_code)
    frame = build_down_frame(
        remote_addr=remote_addr,
        center_addr=center_addr,
        password=password,
        func_code=func_code,
        body=body,
        end_flag=ef,
    )
    return frame, body, ef


def down_meta() -> dict[str, Any]:
    """供前端渲染的元数据。"""
    func_meta = {}
    for fc, name in C.FUNC_CODES.items():
        if fc < 0x30:
            continue
        ef = default_down_end_flag(fc)
        func_meta[f"{fc:02X}"] = {
            "name": name,
            "schema": down_body_schema(fc),
            "end_flag": f"{ef:02X}",
            "end_flag_name": {
                C.ENQ: "ENQ 询问",
                C.EOT: "EOT 结束退出",
                C.ESC: "ESC 结束保持在线",
                C.ACK: "ACK 确认",
                C.NAK: "NAK 否认",
            }.get(ef, f"{ef:02X}"),
        }

    def _guides_list(src: dict, limit: int | None = None) -> list[dict]:
        items = []
        for k, v in src.items():
            if isinstance(v, tuple):
                label = v[1] if len(v) > 1 else str(v)
            else:
                label = str(v)
            items.append({"code": f"{k:02X}", "name": label})
        if limit:
            return items[:limit]
        return items

    return {
        "func_codes": func_meta,
        "end_flags": [
            {"value": "05", "label": "05 ENQ 询问（查询/控制）"},
            {"value": "04", "label": "04 EOT 结束退出"},
            {"value": "1B", "label": "1B ESC 结束保持在线"},
            {"value": "06", "label": "06 ACK 确认"},
            {"value": "15", "label": "15 NAK 否认"},
        ],
        "element_guides": [
            {"code": f"{k:02X}", "name": v[1]}
            for k, v in C.ELEMENT_GUIDES.items()
            if k < 0xF0 or k in (0xF4, 0xF5, 0xF6)
        ],
        "basic_config_guides": [
            {"code": f"{k:02X}", "name": v} for k, v in C.BASIC_CONFIG_GUIDES.items()
        ],
        "run_param_guides": [
            {"code": f"{k:02X}", "name": v}
            for k, v in list(C.RUN_PARAM_GUIDES.items())[:40]
        ],
        "step_units": [
            {"value": "N", "label": "分钟"},
            {"value": "H", "label": "小时"},
            {"value": "D", "label": "日"},
        ],
    }


def parse_down_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """从 API JSON 抽取 build_down_body 关键字参数。"""
    kwargs: dict[str, Any] = {}

    if payload.get("body_hex"):
        kwargs["body_hex"] = payload["body_hex"]

    sn = payload.get("serial_no", 0)
    try:
        kwargs["serial_no"] = int(str(sn), 0) if str(sn).startswith(("0x", "0X")) else int(sn)
    except (TypeError, ValueError):
        kwargs["serial_no"] = 0

    if payload.get("send_time"):
        kwargs["send_time"] = payload["send_time"]

    if payload.get("start_time"):
        kwargs["start_time"] = payload["start_time"]
    if payload.get("end_time"):
        kwargs["end_time"] = payload["end_time"]
    if payload.get("step_unit"):
        kwargs["step_unit"] = payload["step_unit"]
    if payload.get("step_value") is not None:
        try:
            kwargs["step_value"] = int(payload["step_value"])
        except (TypeError, ValueError):
            kwargs["step_value"] = 5

    guides = payload.get("guides")
    if guides is None and payload.get("guides_text"):
        # "F4,39,20" 或 "F4 39"
        text = str(payload["guides_text"]).replace(",", " ").replace(";", " ")
        guides = [p for p in text.split() if p.strip()]
    if guides is not None:
        kwargs["guides"] = guides

    if payload.get("params") is not None:
        kwargs["params"] = payload["params"]

    if payload.get("old_password") is not None:
        kwargs["old_password"] = payload["old_password"]
    if payload.get("new_password") is not None:
        kwargs["new_password"] = payload["new_password"]

    if payload.get("ic_enable") is not None:
        kwargs["ic_enable"] = bool(payload["ic_enable"])

    if payload.get("switch_bits") is not None:
        try:
            kwargs["switch_bits"] = int(str(payload["switch_bits"]), 0)
        except ValueError:
            kwargs["switch_bits"] = 0

    if payload.get("gate_count") is not None:
        kwargs["gate_count"] = int(payload["gate_count"])
    if payload.get("gate_bits") is not None:
        kwargs["gate_bits"] = int(str(payload["gate_bits"]), 0)
    if payload.get("gate_openings_cm") is not None:
        kwargs["gate_openings_cm"] = payload["gate_openings_cm"]

    if payload.get("water_control") is not None:
        kwargs["water_control"] = payload["water_control"]

    return kwargs
