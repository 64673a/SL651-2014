"""解析结果终端展示"""

from __future__ import annotations

from .models import ParsedFrame


def format_frame(frame: ParsedFrame, verbose: bool = True) -> str:
    h = frame.header
    b = frame.body
    lines = [
        "─" * 60,
        f"原始报文: {frame.raw_hex}",
        f"CRC: {frame.crc}  {'✓ 通过' if frame.crc_ok else '✗ 失败'}",
        f"结束符: {frame.end_flag:02X} ({frame.end_flag_name})",
        "",
        "【帧头】",
        f"  中心站地址 : {h.center_addr:02X}",
        f"  遥测站地址 : {h.remote_addr}",
        f"  密码       : {h.password}",
        f"  功能码     : {h.func_code:02X} ({h.func_name})",
        f"  方向       : {'上行' if h.direction == 'up' else '下行'}",
        f"  正文长度   : {h.body_len}",
        f"  传输模式   : {'M3 多包' if h.m3 else 'M1/M2/M4 单包'}",
    ]
    if h.m3:
        lines.append(f"  包总数/序号: {h.packet_total} / {h.packet_seq}")

    lines.append("")
    lines.append("【正文】")
    if b.serial_no is not None:
        lines.append(f"  流水号     : {b.serial_no}")
    if b.send_time:
        lines.append(f"  发报时间   : {b.send_time}")
    if b.remote_addr:
        lines.append(f"  站址(正文) : {b.remote_addr}")
    if b.station_type is not None:
        lines.append(f"  站类       : {b.station_type:02X} ({b.station_type_name})")
    if b.observe_time:
        lines.append(f"  观测时间   : {b.observe_time}")

    if b.elements:
        lines.append("")
        lines.append("【要素】")
        for e in b.elements:
            val = e.value_text if e.value_text is not None else e.raw_hex
            if e.value is not None:
                val = f"{e.value}  (raw={e.raw_hex})"
            lines.append(
                f"  [{e.guide:02X}] {e.guide_name}: {val}  "
                f"(len={e.data_len}, dec={e.decimals})"
            )
    elif verbose and b.raw_hex and b.serial_no is None and not b.send_time:
        lines.append(f"  正文原始   : {b.raw_hex}")

    if frame.errors:
        lines.append("")
        lines.append("【警告】")
        for err in frame.errors:
            lines.append(f"  ! {err}")

    lines.append("─" * 60)
    return "\n".join(lines)
