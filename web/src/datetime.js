/**
 * 统一时间展示：年-月-日（YYYY-MM-DD …）
 * 协议编码仍用 YYMMDDHHmmSS / YYMMDDHH（见 formatProtocol*）
 */
import { CalendarDateTime, getLocalTimeZone, now } from "@internationalized/date";

export function nowDateTime() {
  const n = now(getLocalTimeZone());
  return new CalendarDateTime(n.year, n.month, n.day, n.hour, n.minute, n.second);
}

/** 展示：YYYY-MM-DD HH:mm:ss */
export function formatDisplayDateTime(dt) {
  if (!dt) return "";
  const y = String(dt.year).padStart(4, "0");
  const m = String(dt.month).padStart(2, "0");
  const d = String(dt.day).padStart(2, "0");
  const hh = String(dt.hour ?? 0).padStart(2, "0");
  const mi = String(dt.minute ?? 0).padStart(2, "0");
  const ss = String(dt.second ?? 0).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mi}:${ss}`;
}

/** 展示：YYYY-MM-DD HH（时段查询到小时） */
export function formatDisplayDateHour(dt) {
  if (!dt) return "";
  return formatDisplayDateTime(dt).slice(0, 13);
}

/** 协议正文：YYMMDDHHmmSS */
export function formatProtocolYmdHms(dt) {
  if (!dt) return "";
  const yy = String(dt.year % 100).padStart(2, "0");
  const mm = String(dt.month).padStart(2, "0");
  const dd = String(dt.day).padStart(2, "0");
  const hh = String(dt.hour ?? 0).padStart(2, "0");
  const mi = String(dt.minute ?? 0).padStart(2, "0");
  const ss = String(dt.second ?? 0).padStart(2, "0");
  return `${yy}${mm}${dd}${hh}${mi}${ss}`;
}

/** 协议正文：YYMMDDHH */
export function formatProtocolYmdH(dt) {
  const s = formatProtocolYmdHms(dt);
  return s ? s.slice(0, 8) : "";
}

/** Date / 字符串 → 展示用 YYYY-MM-DD HH:mm:ss[.SSS] */
export function formatAnyToDisplay(value) {
  if (value == null || value === "") return "";
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    const p = (n, w = 2) => String(n).padStart(w, "0");
    return (
      `${value.getFullYear()}-${p(value.getMonth() + 1)}-${p(value.getDate())} ` +
      `${p(value.getHours())}:${p(value.getMinutes())}:${p(value.getSeconds())}`
    );
  }
  const s = String(value).trim();
  // 已是 20YY-MM-DD …
  if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.replace("T", " ").slice(0, 19);
  // 纯数字 12/14 位 BCD 风格
  const dig = s.replace(/\D/g, "");
  if (dig.length >= 12) {
    const y = dig.length >= 14 && dig.startsWith("20") ? dig.slice(0, 4) : `20${dig.slice(0, 2)}`;
    const rest = dig.length >= 14 && dig.startsWith("20") ? dig.slice(4) : dig.slice(2);
    return `${y}-${rest.slice(0, 2)}-${rest.slice(2, 4)} ${rest.slice(4, 6)}:${rest.slice(6, 8)}:${rest.slice(8, 10)}`;
  }
  if (dig.length >= 8) {
    const y = dig.length >= 10 && dig.startsWith("20") ? dig.slice(0, 4) : `20${dig.slice(0, 2)}`;
    const rest = dig.length >= 10 && dig.startsWith("20") ? dig.slice(4) : dig.slice(2);
    return `${y}-${rest.slice(0, 2)}-${rest.slice(2, 4)} ${rest.slice(4, 6) || "00"}`;
  }
  return s;
}
