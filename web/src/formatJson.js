/** 前端展示用：去掉与顶层/UI 重复的字段，输出更干净的 JSON */

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
 * 精简 ParsedFrame.to_dict：去掉与外层 raw_hex 重复项，body 去空，fields 保留（布局用）。
 */
export function slimParsed(parsed) {
  if (!parsed || typeof parsed !== "object") return parsed;
  const body = parsed.body
    ? omitNulls({
        serial_no: parsed.body.serial_no,
        send_time: parsed.body.send_time,
        remote_addr: parsed.body.remote_addr,
        station_type: parsed.body.station_type,
        station_type_name: parsed.body.station_type_name,
        observe_time: parsed.body.observe_time,
        elements: parsed.body.elements,
      })
    : undefined;

  return omitNulls({
    header: parsed.header,
    body,
    end_flag: parsed.end_flag,
    end_flag_name: parsed.end_flag_name,
    crc: parsed.crc,
    crc_ok: parsed.crc_ok,
    errors: parsed.errors?.length ? parsed.errors : undefined,
    fields: parsed.fields?.length ? parsed.fields : undefined,
    body_offset: parsed.body_offset,
    frame_len: parsed.frame_len,
  });
}

/**
 * 消息记录展示：只保留元数据 + raw_hex + 精简 parsed，
 * 去掉 bus 展平的 crc_ok/func_code 等顶层摘要（已在 parsed.header/body 中）。
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
