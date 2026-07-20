"""CRC16/MODBUS（多项式 0xA001，初值 0xFFFF）— SL651 帧校验"""

_POLY = 0xA001
_INIT = 0xFFFF


def crc16(data: bytes) -> int:
    """计算 CRC16，返回 16 位整数（高字节在前，与报文一致）"""
    res = _INIT
    for b in data:
        res ^= b
        for _ in range(8):
            if res & 0x0001:
                res = (res >> 1) ^ _POLY
            else:
                res >>= 1
    return res & 0xFFFF


def crc16_bytes(data: bytes) -> bytes:
    """返回 2 字节 CRC（高字节在前）"""
    c = crc16(data)
    return bytes([(c >> 8) & 0xFF, c & 0xFF])


def verify(data_with_crc: bytes) -> bool:
    """校验整帧（含末尾 2 字节 CRC）"""
    if len(data_with_crc) < 2:
        return False
    body, got = data_with_crc[:-2], data_with_crc[-2:]
    return crc16_bytes(body) == got
