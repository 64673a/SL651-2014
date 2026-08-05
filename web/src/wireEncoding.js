const LABELS = {
  ascii: "ASCII",
  hex_bcd: "HEX/BCD",
};

export function wireEncoding(message) {
  const value = String(message?.encoding || message?.parsed?.header?.encoding || "")
    .trim()
    .toLowerCase();
  if (value === "ascii" || value === "text") return "ascii";
  if (value === "hex_bcd" || value === "hex" || value === "bcd") return "hex_bcd";

  const raw = String(message?.raw_hex || message?.parsed?.raw_hex || "")
    .replace(/\s+/g, "")
    .toUpperCase();
  if (raw.startsWith("01")) return "ascii";
  if (raw.startsWith("7E7E")) return "hex_bcd";
  return "";
}

export function wireEncodingLabel(message) {
  return LABELS[wireEncoding(message)] || "未知";
}

export function wireEncodingColor(message) {
  const encoding = wireEncoding(message);
  if (encoding === "ascii") return "primary";
  if (encoding === "hex_bcd") return "neutral";
  return "warning";
}
