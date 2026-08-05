/** 前端展示用：保留协议摘要，避免把布局和重复原文塞进 JSON。 */

function omitNulls(obj) {
  if (obj == null || typeof obj !== "object" || Array.isArray(obj)) return obj;
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v === null || v === undefined || v === "") continue;
    if (Array.isArray(v) && v.length === 0) continue;
    out[k] = v;
  }
  return out;
}

/**
 * 精简 ParsedFrame.to_dict：布局字段由界面单独展示，不放入 JSON 摘要。
 */
export function slimParsed(parsed) {
  if (!parsed || typeof parsed !== "object") return parsed;
  const header = parsed.header
    ? omitNulls({
        center_addr: parsed.header.center_addr,
        remote_addr: parsed.header.remote_addr,
        password: parsed.header.password,
        func_code: parsed.header.func_code,
        func_name: parsed.header.func_name,
        body_len: parsed.header.body_len,
        direction: parsed.header.direction,
        encoding: parsed.header.encoding,
        m3: parsed.header.m3,
        packet_total: parsed.header.packet_total,
        packet_seq: parsed.header.packet_seq,
      })
    : undefined;

  const body = parsed.body
    ? omitNulls({
        serial_no: parsed.body.serial_no,
        send_time: parsed.body.send_time,
        remote_addr:
          parsed.body.remote_addr && parsed.body.remote_addr !== parsed.header?.remote_addr
            ? parsed.body.remote_addr
            : undefined,
        station_type: parsed.body.station_type,
        station_type_name: parsed.body.station_type_name,
        observe_time: parsed.body.observe_time,
        text: parsed.body.raw_text,
        elements: parsed.body.elements?.map((element) =>
          omitNulls({
            guide: element.guide_code || element.guide,
            name: element.name,
            value: element.value != null ? element.value : element.value_text,
            raw: element.raw,
          })
        ),
      })
    : undefined;

  return omitNulls({
    header,
    body,
    end: omitNulls({ flag: parsed.end_flag, name: parsed.end_flag_name }),
    crc: omitNulls({ value: parsed.crc, ok: parsed.crc_ok }),
    errors: parsed.errors?.length ? parsed.errors : undefined,
  });
}

/**
 * 消息记录展示：只保留元数据 + raw_hex + 精简 parsed。
 */
export function slimMessage(msg) {
  if (!msg || typeof msg !== "object") return msg;
  return omitNulls({
    id: msg.id,
    ts: msg.ts,
    direction: msg.direction,
    peer: msg.peer,
    note: msg.note,
    error: msg.error,
    raw_hex: msg.raw_hex,
    parsed: msg.parsed ? slimParsed(msg.parsed) : undefined,
  });
}

export function prettySlimMessage(msg) {
  return JSON.stringify(slimMessage(msg), null, 2);
}

export function prettySlimParsed(parsed) {
  return JSON.stringify(slimParsed(parsed), null, 2);
}
