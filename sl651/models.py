"""解析结果数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FieldSpan:
    """字段在原始帧中的字节区间（半开区间 [start, end)）"""

    id: str
    label: str
    start: int
    end: int
    value: str = ""
    group: str = "header"  # header | body | trailer
    color: str = "neutral"  # UI 色：primary/success/info/warning/error/neutral

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "value": self.value,
            "group": self.group,
            "color": self.color,
            "len": max(0, self.end - self.start),
        }


@dataclass
class Element:
    """遥测要素"""

    guide: int
    guide_name: str
    data_len: int
    decimals: int
    raw_hex: str
    value: Optional[float] = None
    value_text: Optional[str] = None
    offset: Optional[int] = None  # 相对正文起点
    length: Optional[int] = None
    guide_code: Optional[str] = None  # ASCII 编码下的原始标识符

    def to_dict(self) -> dict[str, Any]:
        guide_str = self.guide_code or (
            f"FF{(self.guide & 0xFF):02X}" if self.guide > 0xFF else f"{self.guide:02X}"
        )
        d: dict[str, Any] = {
            "guide": guide_str,
            "name": self.guide_name,
            "data_len": self.data_len,
            "decimals": self.decimals,
            "raw": self.raw_hex,
            "value": self.value,
            "value_text": self.value_text,
        }
        if self.offset is not None:
            d["offset"] = self.offset
            d["length"] = self.length
        if self.guide_code:
            d["guide_code"] = self.guide_code
        return d


@dataclass
class FrameHeader:
    center_addr: int
    remote_addr: str
    password: str
    func_code: int
    func_name: str
    body_len: int
    direction: str
    m3: bool
    stx: int
    packet_total: Optional[int] = None
    packet_seq: Optional[int] = None
    encoding: str = "hex_bcd"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "center_addr": f"{self.center_addr:02X}",
            "remote_addr": self.remote_addr,
            "password": self.password,
            "func_code": f"{self.func_code:02X}",
            "func_name": self.func_name,
            "body_len": self.body_len,
            "direction": self.direction,
            "m3": self.m3,
            "encoding": self.encoding,
        }
        if self.m3:
            d["packet_total"] = self.packet_total
            d["packet_seq"] = self.packet_seq
        return d


@dataclass
class FrameBody:
    serial_no: Optional[int] = None
    send_time: Optional[str] = None
    remote_addr: Optional[str] = None
    station_type: Optional[int] = None
    station_type_name: Optional[str] = None
    observe_time: Optional[str] = None
    elements: list[Element] = field(default_factory=list)
    raw_hex: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "serial_no": self.serial_no,
            "send_time": self.send_time,
            "remote_addr": self.remote_addr,
            "station_type": f"{self.station_type:02X}" if self.station_type is not None else None,
            "station_type_name": self.station_type_name,
            "observe_time": self.observe_time,
            "elements": [e.to_dict() for e in self.elements],
            "raw_hex": self.raw_hex,
            "raw_text": self.raw_text,
        }


@dataclass
class ParsedFrame:
    raw: bytes
    raw_hex: str
    header: FrameHeader
    body: FrameBody
    end_flag: int
    end_flag_name: str
    crc: str
    crc_ok: bool
    errors: list[str] = field(default_factory=list)
    fields: list[FieldSpan] = field(default_factory=list)
    body_offset: int = 14
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_hex": self.raw_hex,
            "raw_text": self.raw_text,
            "header": self.header.to_dict(),
            "body": self.body.to_dict(),
            "end_flag": f"{self.end_flag:02X}",
            "end_flag_name": self.end_flag_name,
            "crc": self.crc,
            "crc_ok": self.crc_ok,
            "errors": self.errors,
            "fields": [f.to_dict() for f in self.fields],
            "body_offset": self.body_offset,
            "frame_len": len(self.raw),
        }
