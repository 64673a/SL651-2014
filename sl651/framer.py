"""从字节流中按 SL651 两种帧起始符切分完整帧"""

from __future__ import annotations

from . import constants as C


ASCII_HEADER_LEN = 24  # SOH + ASCII header fields + STX/SYN
ASCII_CRC_LEN = 4
ASCII_MIN_FRAME_LEN = ASCII_HEADER_LEN + 1 + 1 + ASCII_CRC_LEN


class FrameSplitter:
    """粘包/半包缓冲切分器"""

    def __init__(self, max_len: int = C.MAX_FRAME_LEN, encoding: str = C.WIRE_AUTO) -> None:
        self._buf = bytearray()
        self._max_len = max_len
        self._encoding = C.normalize_wire_encoding(encoding, default=C.WIRE_AUTO)

    def _find_start(self) -> tuple[int, str] | None:
        candidates: list[tuple[int, str]] = []
        if self._encoding in (C.WIRE_HEX_BCD, C.WIRE_AUTO):
            pos = self._buf.find(C.FRAME_START)
            if pos >= 0:
                candidates.append((pos, C.WIRE_HEX_BCD))
        if self._encoding in (C.WIRE_ASCII, C.WIRE_AUTO):
            pos = self._buf.find(bytes([C.SOH]))
            if pos >= 0:
                candidates.append((pos, C.WIRE_ASCII))
        if not candidates:
            return None
        return min(candidates, key=lambda item: item[0])

    def feed(self, data: bytes) -> list[bytes]:
        """喂入数据，返回已切出的完整帧列表"""
        self._buf.extend(data)
        frames: list[bytes] = []

        while True:
            found = self._find_start()
            if found is None:
                # 保留可能的半个 7E
                if (
                    self._encoding in (C.WIRE_HEX_BCD, C.WIRE_AUTO)
                    and self._buf
                    and self._buf[-1] == 0x7E
                ):
                    self._buf = bytearray(self._buf[-1:])
                else:
                    self._buf.clear()
                break

            start, encoding = found
            if start > 0:
                del self._buf[:start]

            if encoding == C.WIRE_ASCII:
                if len(self._buf) < 23:
                    break
                try:
                    length_text = bytes(self._buf[19:23]).decode("ascii")
                    if length_text[0] not in "08" or any(
                        c not in "0123456789abcdefABCDEF" for c in length_text[1:]
                    ):
                        raise ValueError("ASCII 长度字段格式错误")
                    body_len = int(length_text[1:], 16)
                except (UnicodeDecodeError, ValueError):
                    # 当前 SOH 不是有效帧头，丢弃一个字节继续找后续帧。
                    del self._buf[:1]
                    continue
                total = ASCII_HEADER_LEN + body_len + 1 + ASCII_CRC_LEN
                min_len = ASCII_MIN_FRAME_LEN
            else:
                if len(self._buf) < 15:
                    # 还不够读出长度字段
                    break
                # 上下行标识与长度：偏移 11-12（从 7E7E 起）
                len_field = (self._buf[11] << 8) | self._buf[12]
                body_len = len_field & 0x0FFF
                # 头 14 字节（含 STX）+ 正文 + 结束符 1 + CRC 2
                total = 14 + body_len + 1 + 2
                min_len = C.MIN_FRAME_LEN

            if total > self._max_len or total < min_len:
                # 长度异常，丢弃当前帧起始符，继续找下一帧。
                del self._buf[:1 if encoding == C.WIRE_ASCII else 2]
                continue

            if len(self._buf) < total:
                break

            frame = bytes(self._buf[:total])
            del self._buf[:total]
            frames.append(frame)

        return frames

    def clear(self) -> None:
        self._buf.clear()

    @property
    def buffered(self) -> int:
        return len(self._buf)
