/**
 * 前端轻量帧工具：本地改发报时间 + 重算 CRC，避免实时预览每秒打后端。
 * 与 sl651/crc16.py 一致：CRC16/MODBUS 0xA001，初值 0xFFFF，高字节在前。
 */

const POLY = 0xa001;
const INIT = 0xffff;

/** 帧内：7E7E(2)+遥测站5+中心1+密码2+功能码1+长度2+STX(1)=14，正文流水号2后即为发报时间 */
export const SEND_TIME_ABS_OFFSET = 16; // 绝对字节偏移
export const SEND_TIME_LEN = 6;

export function crc16(data) {
  let res = INIT;
  for (let i = 0; i < data.length; i++) {
    res ^= data[i];
    for (let b = 0; b < 8; b++) {
      if (res & 1) res = (res >> 1) ^ POLY;
      else res >>= 1;
    }
  }
  return res & 0xffff;
}

export function crc16Bytes(data) {
  const c = crc16(data);
  return [(c >> 8) & 0xff, c & 0xff];
}

export function hexToBytes(hex) {
  const s = String(hex || "").replace(/\s+/g, "");
  if (s.length % 2) throw new Error("hex 长度须为偶数");
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(s.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

export function bytesToHex(bytes, sep = "") {
  const parts = [];
  for (let i = 0; i < bytes.length; i++) {
    parts.push(bytes[i].toString(16).toUpperCase().padStart(2, "0"));
  }
  return sep ? parts.join(sep) : parts.join("");
}

export function spaceHex(hex) {
  const s = String(hex || "").replace(/\s+/g, "").toUpperCase();
  return s.replace(/(.{2})/g, "$1 ").trim();
}

/** CalendarDateTime 类对象 → 6 字节 BCD YYMMDDHHmmSS */
export function bcd6FromDateTime(dt) {
  if (!dt) return null;
  const yy = dt.year % 100;
  const vals = [yy, dt.month, dt.day, dt.hour ?? 0, dt.minute ?? 0, dt.second ?? 0];
  const out = new Uint8Array(6);
  for (let i = 0; i < 6; i++) {
    const v = Math.max(0, Math.min(99, Number(vals[i]) || 0));
    out[i] = ((Math.floor(v / 10) & 0xf) << 4) | (v % 10);
  }
  return out;
}

/**
 * 在已组好的完整帧上只改发报时间并重算 CRC。
 * @returns {{ hex: string, spaced: string, body_hex?: string } | null}
 */
export function patchFrameSendTime(frameHex, dt) {
  try {
    const raw = hexToBytes(frameHex);
    if (raw.length < SEND_TIME_ABS_OFFSET + SEND_TIME_LEN + 1 + 2) return null;
    if (raw[0] === 0x01) {
      if (raw.length < 24 + 16 + 1 + 4) return null;
      const stx = raw[23];
      const bodyStart = stx === 0x16 ? 30 : 24;
      const text = bcd6TextFromDateTime(dt);
      if (!text || bodyStart + 16 > raw.length) return null;
      for (let i = 0; i < text.length; i++) raw[bodyStart + 4 + i] = text.charCodeAt(i);
      const crc = bytesToHex(crc16Bytes(raw.subarray(0, raw.length - 4)));
      if (crc.length !== 4) return null;
      for (let i = 0; i < 4; i++) raw[raw.length - 4 + i] = crc.charCodeAt(i);
      const hex = bytesToHex(raw);
      return {
        hex,
        spaced: spaceHex(hex),
        body_hex: bytesToHex(raw.subarray(bodyStart, raw.length - 5)),
      };
    }
    if (raw[0] !== 0x7e || raw[1] !== 0x7e) return null;
    const t = bcd6FromDateTime(dt);
    if (!t) return null;
    for (let i = 0; i < 6; i++) raw[SEND_TIME_ABS_OFFSET + i] = t[i];
    const crc = crc16Bytes(raw.subarray(0, raw.length - 2));
    raw[raw.length - 2] = crc[0];
    raw[raw.length - 1] = crc[1];
    const hex = bytesToHex(raw);
    // 正文 = STX 之后、结束符之前
    const lenField = (raw[11] << 8) | raw[12];
    const bodyLen = lenField & 0x0fff;
    const bodyStart = 14;
    const body = raw.subarray(bodyStart, bodyStart + bodyLen);
    return {
      hex,
      spaced: spaceHex(hex),
      body_hex: bytesToHex(body),
    };
  } catch {
    return null;
  }
}

function bcd6TextFromDateTime(dt) {
  if (!dt) return null;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(Number(dt.year) % 100)}${p(dt.month)}${p(dt.day)}${p(dt.hour ?? 0)}${p(dt.minute ?? 0)}${p(dt.second ?? 0)}`;
}
