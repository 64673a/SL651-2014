"""从字节流中按 7E7E 切分完整帧"""

from __future__ import annotations

from .constants import FRAME_START, MAX_FRAME_LEN, MIN_FRAME_LEN


class FrameSplitter:
    """粘包/半包缓冲切分器"""

    def __init__(self, max_len: int = MAX_FRAME_LEN) -> None:
        self._buf = bytearray()
        self._max_len = max_len

    def feed(self, data: bytes) -> list[bytes]:
        """喂入数据，返回已切出的完整帧列表"""
        self._buf.extend(data)
        frames: list[bytes] = []

        while True:
            # 找帧头
            start = self._buf.find(FRAME_START)
            if start < 0:
                # 保留可能的半个 7E
                if self._buf and self._buf[-1] == 0x7E:
                    self._buf = bytearray(self._buf[-1:])
                else:
                    self._buf.clear()
                break

            if start > 0:
                del self._buf[:start]

            if len(self._buf) < 15:
                # 还不够读出长度字段
                break

            # 上下行标识与长度：偏移 11-12（从 7E7E 起）
            len_field = (self._buf[11] << 8) | self._buf[12]
            body_len = len_field & 0x0FFF
            stx = self._buf[13] if len(self._buf) > 13 else 0
            # 头 14 字节（含 STX）+ 正文 + 结束符 1 + CRC 2
            # M3 时 STX 位为 SYN，其后还有 3 字节包计数，但 body_len 通常含这些
            header_len = 14  # 7E7E..STX
            total = header_len + body_len + 1 + 2

            if total > self._max_len or total < MIN_FRAME_LEN:
                # 长度异常，丢弃当前 7E7E，继续找下一帧
                del self._buf[:2]
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
