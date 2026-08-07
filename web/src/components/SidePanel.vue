<script setup>
import { CalendarDateTime } from "@internationalized/date";
import {
  computed,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  shallowRef,
  useTemplateRef,
  watch,
} from "vue";
import { get, post } from "../api";
import {
  formatDisplayDateTime,
  formatProtocolYmdH,
  formatProtocolYmdHms,
  nowDateTime,
} from "../datetime";
import {
  ELEMENT_QUERY_PRESETS,
  FUNC_DOWN_META,
  WORK_MODE_OPTIONS,
  CHANNEL_TYPE_OPTIONS,
  basicConfigFormToParams,
  defaultBasicConfigForm,
  getElementQueryPreset,
  getFuncMeta,
  guideOptionsFor,
  isHourComboGuide,
  matchedStepForGuide,
  validateBasicConfigForm,
  validatePeriodStep,
} from "../downSchemas";
import { prettySlimParsed } from "../formatJson";
import { patchFrameSendTime, spaceHex as spaceHexFrame } from "../sl651Frame";
import { writeClipboard } from "../clipboard";

const props = defineProps({
  clients: { type: Array, default: () => [] },
  funcCodes: { type: Object, default: () => ({}) },
  rtu: { type: Object, default: null },
  centerPort: { type: [Number, String], default: 9000 },
});
const emit = defineEmits(["refresh", "open-detail"]);
const toast = useToast();

const peer = ref("");
const mode = ref("down");
const downMeta = ref(null);
const down = reactive({
  func_code: "37",
  end_flag: "05",
  remote_addr: "",
  center_addr: "01",
  password: "A000",
  encoding: "hex_bcd",
  serial_no: 0,
  // 38
  // F4 默认：表 C.1 特定搭配 000000（DRH00）
  step_unit: "H",
  step_value: 0,
  // guides（多选 value 列表，如 ["F4","39"]）；3A 由预设写入
  selectedGuides: ["F4", "F5"],
  /** 3A 查询模式：combo | instant */
  elementPreset: "combo",
  // params 40/42
  params: [{ guide: "01", value_hex: "" }],
  /** 40H 固定表单 */
  basicConfig: defaultBasicConfigForm(),
  // 49
  old_password: "A000",
  new_password: "1234",
  // 4B
  ic_enable: true,
  // 4C/4D：8 路开关
  switchOn: [true, false, false, false, false, false, false, false],
  // 4E
  gate_count: 1,
  gateOn: [true, false, false, false, false, false, false, false],
  gate_openings: "0",
  // 4F
  water_control: "on",
});

/**
 * 发报时间：
 * - autoSendTime=true（默认）：发送瞬间取当前时间；预览每秒刷新
 * - autoSendTime=false：使用手动选择的固定时间
 */
const autoSendTime = ref(true);
const sendTimeDt = shallowRef(nowDateTime());
const startTimeDt = shallowRef(null);
const endTimeDt = shallowRef(null);
const sendTimeInput = useTemplateRef("sendTimeInput");
const startTimeInput = useTemplateRef("startTimeInput");
const endTimeInput = useTemplateRef("endTimeInput");

let liveSendTimeTimer = null;

function stopLiveSendTime() {
  if (liveSendTimeTimer) {
    clearInterval(liveSendTimeTimer);
    liveSendTimeTimer = null;
  }
}

function startLiveSendTime() {
  stopLiveSendTime();
  if (!autoSendTime.value) return;
  // 每秒只更新本地时间 → 本地 patch CRC，不请求后端
  sendTimeDt.value = nowDateTime();
  liveSendTimeTimer = setInterval(() => {
    if (autoSendTime.value && mode.value === "down") {
      sendTimeDt.value = nowDateTime();
    }
  }, 1000);
}

function ensurePeriodDefaults() {
  if (!startTimeDt.value || !endTimeDt.value) {
    const end = nowDateTime();
    const start = new CalendarDateTime(end.year, end.month, end.day, 0, 0, 0);
    if (!startTimeDt.value) startTimeDt.value = start;
    if (!endTimeDt.value) endTimeDt.value = end;
  }
}

const hexRaw = ref("");
/** 预览：完整帧 / 正文 / 结束符 / 解析 */
const previewFrame = ref(null); // { hex, body_hex, end_flag, parsedText, error, spaced }
const parseHex = ref("");
const parseEncoding = ref("auto");
const parseLoading = ref(false);
const sending = ref(false);
const previewing = ref(false);

function spaceHex(hex) {
  return spaceHexFrame(hex);
}

/** 仅本地改发报时间 + CRC，不请求后端 */
function patchPreviewSendTime(dt) {
  const cur = previewFrame.value;
  if (!cur?.hex || cur.error) return false;
  const patched = patchFrameSendTime(cur.hex, dt);
  if (!patched) return false;
  previewFrame.value = {
    ...cur,
    hex: patched.hex,
    spaced: patched.spaced,
    body_hex: patched.body_hex || cur.body_hex,
    note: autoSendTime.value ? "实时" : cur.note,
    error: "",
  };
  return true;
}

async function copyText(text, title = "已复制") {
  try {
    await writeClipboard(text || "");
    toast.add({ title, color: "success" });
  } catch {
    toast.add({ title: "复制失败", color: "error" });
  }
}

const rtuForm = reactive({
  remote_addr: "0010100001",
  password: "A000",
  heartbeat: 30,
  report: 60,
  water: 12.34,
  rain: 1.5,
  voltage: 12.6,
  encoding: "hex_bcd",
});
const rtuHex = ref("");
const rtuSending = ref(false);
const rtuMsg = ref("未启动");

const modeItems = [
  { label: "构造下行帧", value: "down" },
  { label: "原始 Hex", value: "hex" },
];

const encodingItems = [
  { label: "HEX/BCD（二进制）", value: "hex_bcd" },
  { label: "ASCII 字符编码", value: "ascii" },
];

const parseEncodingItems = [
  { label: "自动识别（7E7E / 01）", value: "auto" },
  { label: "HEX/BCD（二进制）", value: "hex_bcd" },
  { label: "ASCII 字符编码", value: "ascii" },
];

/** 结束符下拉：短标签，避免侧栏半宽时截断 */
const endItems = computed(() => {
  const short = {
    "05": "05 ENQ",
    "04": "04 EOT",
    "1B": "1B ESC",
    "06": "06 ACK",
    "15": "15 NAK",
  };
  const fromMeta = downMeta.value?.end_flags;
  if (fromMeta?.length) {
    return fromMeta.map((e) => ({
      label: short[e.value] || `${e.value}`,
      value: e.value,
    }));
  }
  return Object.entries(short).map(([value, label]) => ({ value, label }));
});

const stepUnitItems = [
  { label: "分钟", value: "N" },
  { label: "小时", value: "H" },
  { label: "日", value: "D" },
];

const waterItems = [
  { label: "投入 (FF)", value: "on" },
  { label: "退出 (00)", value: "off" },
];

/** 当前功能码元数据（本地表优先，API 可覆盖名称） */
const funcMeta = computed(() => {
  const local = getFuncMeta(down.func_code);
  const api = downMeta.value?.func_codes?.[down.func_code];
  return {
    ...local,
    name: api?.name || local.title,
    schema: local.schema,
    end_flag: local.end_flag,
  };
});

const schema = computed(() => funcMeta.value.schema);

/** 遥测站上行 / 链路维持：不下发，从下行调试功能码下拉排除 */
const UPLINK_ONLY_FUNCS = new Set(["2F", "30", "31", "32", "33", "34", "35"]);

const funcOptions = computed(() => {
  const names = {};
  // 本地 + API + props 合并名称
  for (const [code, m] of Object.entries(FUNC_DOWN_META)) {
    names[code] = m.title;
  }
  const api = downMeta.value?.func_codes || {};
  for (const [code, v] of Object.entries(api)) {
    names[code] = v.name || names[code];
  }
  for (const [code, name] of Object.entries(props.funcCodes || {})) {
    if (!names[code]) names[code] = name;
  }
  return Object.keys(names)
    .filter((c) => !UPLINK_ONLY_FUNCS.has(c))
    .sort((a, b) => parseInt(a, 16) - parseInt(b, 16))
    .map((code) => ({
      label: `${code} ${names[code]}`,
      value: code,
    }));
});

const peerItems = computed(() =>
  (props.clients || []).map((c) => ({
    label: `${c.peer} (${c.remote_addr || "?"})`,
    value: c.peer,
  }))
);

const guideSelectItems = computed(() => {
  const src = funcMeta.value.guideSource || "element";
  // API 列表优先（更全），否则本地常用
  if (src === "basic" && downMeta.value?.basic_config_guides?.length) {
    return downMeta.value.basic_config_guides.map((g) => ({
      value: g.code,
      label: `${g.code} ${g.name}`,
    }));
  }
  if (src === "run" && downMeta.value?.run_param_guides?.length) {
    return downMeta.value.run_param_guides.map((g) => ({
      value: g.code,
      label: `${g.code} ${g.name}`,
    }));
  }
  if (src === "element" && downMeta.value?.element_guides?.length) {
    // 只取常用子集 + 特殊 F4 等
    const prefer = new Set([
      "F4", "F5",
      "21", "22", "23", "24",
      "1A", "1B", "1C", "1D", "1E", "1F",
      "20", "26",
      "38", "39", "3A", "3B", "27", "45",
    ]);
    // 按 prefer 顺序排列，避免 API 返回顺序打乱常用项
    const byCode = Object.fromEntries(
      downMeta.value.element_guides.map((g) => [g.code, g])
    );
    const fromApi = [...prefer]
      .filter((code) => byCode[code])
      .map((code) => ({ value: code, label: `${code} ${byCode[code].name}` }));
    if (fromApi.length) return fromApi;
  }
  return guideOptionsFor(src);
});

const switchLabel = computed(() => funcMeta.value.switchLabel || "通道");

/** 38 时段查询：国标 HEX 宜单要素，与 selectedGuides[0] 双向同步 */
const periodGuide = computed({
  get() {
    return (down.selectedGuides && down.selectedGuides[0]) || "F4";
  },
  set(v) {
    const g = v ? String(v).toUpperCase() : "F4";
    down.selectedGuides = v ? [g] : ["F4"];
    applyStepForGuide(g);
  },
});

/** F4~FC：步长锁死为特定搭配 000000 */
const periodStepLocked = computed(() => isHourComboGuide(periodGuide.value));

const periodStepHint = computed(() => {
  const m = matchedStepForGuide(periodGuide.value);
  return m?.label || "";
});

function applyStepForGuide(guide) {
  const m = matchedStepForGuide(guide);
  if (!m) return;
  down.step_unit = m.unit;
  down.step_value = m.value;
}

function applyElementPreset(presetValue) {
  const p = getElementQueryPreset(presetValue);
  down.elementPreset = p.value;
  down.selectedGuides = [...p.guides];
}

const elementPresetItems = ELEMENT_QUERY_PRESETS.map((p) => ({
  value: p.value,
  label: p.label,
}));

const currentElementPreset = computed(() => getElementQueryPreset(down.elementPreset));

const isElementQuery3A = computed(
  () => String(down.func_code || "").toUpperCase() === "3A"
);

const isBasicConfig40 = computed(
  () => String(down.func_code || "").toUpperCase() === "40"
);

const workModeItems = WORK_MODE_OPTIONS;
const channelTypeItems = CHANNEL_TYPE_OPTIONS;
const mainChannelType = computed(() => Number(down.basicConfig?.main_channel_type) || 0);

function bitsFromBools(arr) {
  let bits = 0;
  (arr || []).forEach((on, i) => {
    if (on) bits |= 1 << i;
  });
  return bits;
}

function applyFuncDefaults(code) {
  const m = getFuncMeta(code);
  down.end_flag = m.end_flag;
  if (String(code).toUpperCase() === "3A") {
    applyElementPreset(m.elementPreset || "combo");
  } else if (m.defaultGuides?.length) {
    down.selectedGuides = [...m.defaultGuides];
  } else if (m.schema === "guides" || m.schema === "period") {
    down.selectedGuides = m.guideSource === "basic" ? ["01", "02", "03"] : ["F4"];
  }
  if (m.schema === "period") {
    applyStepForGuide((down.selectedGuides && down.selectedGuides[0]) || "F4");
    ensurePeriodDefaults();
  }
  if (String(code).toUpperCase() === "40") {
    down.basicConfig = defaultBasicConfigForm();
    down.params = basicConfigFormToParams(down.basicConfig);
  } else if (m.schema === "params" && (!down.params?.length || !down.params[0].guide)) {
    const def = m.guideSource === "run" ? "20" : "01";
    down.params = [{ guide: def, value_hex: "" }];
  }
  if (autoSendTime.value) {
    sendTimeDt.value = nowDateTime();
  } else if (!sendTimeDt.value) {
    sendTimeDt.value = nowDateTime();
  }
}

/** 仅随身份字段变化回填；忽略 down_count/last_seen，避免发送后盖掉手改内容 */
let lastFilledPeerKey = "";

function clientFillKey(c) {
  if (!c) return "";
  return [c.peer, c.remote_addr || "", c.center_addr || "", c.password || ""].join("|");
}

function fillFromClient(c) {
  if (!c) return;
  if (c.remote_addr) down.remote_addr = c.remote_addr;
  if (c.center_addr) down.center_addr = c.center_addr;
  if (c.password) down.password = c.password;
  lastFilledPeerKey = clientFillKey(c);
}

watch(
  () => props.clients,
  (list) => {
    if (!list?.length) {
      peer.value = "";
      lastFilledPeerKey = "";
      return;
    }
    const cur = list.find((c) => c.peer === peer.value);
    if (cur) {
      const key = clientFillKey(cur);
      // 首连时常先无站址，上行后再补齐；此时 key 变化才回填
      if (key !== lastFilledPeerKey) fillFromClient(cur);
      return;
    }
    peer.value = list[0].peer;
    fillFromClient(list[0]);
  },
  { immediate: true, deep: true }
);

watch(peer, (p) => {
  if (!p) return;
  const c = (props.clients || []).find((x) => x.peer === p);
  if (c) fillFromClient(c);
});

watch(
  () => down.func_code,
  (code) => applyFuncDefaults(code),
  { immediate: true }
);

watch(
  () => props.rtu,
  (r) => {
    rtuMsg.value = r?.running
      ? `运行中 · ${r.remote_addr} → ${r.host}:${r.port}`
      : "未启动";
  },
  { immediate: true }
);

/**
 * 完整帧 Hex 刷新策略：
 * - 结构参数变化 → 校验通过才防抖请求 /api/build-down
 * - 自动发报时间每秒 → 仅本地 patch（失败且无缓存时也不打后端，避免 400 风暴）
 */
let hexRefreshTimer = null;
let hexRefreshSeq = 0;
/** 最近一次结构组帧是否成功（用于时间 tick 是否允许 patch / 是否禁止补打后端） */
let lastStructureBuildOk = false;
/** 上次成功/失败的结构指纹，相同则跳过重复请求 */
let lastStructureKey = "";

function structureKey() {
  return JSON.stringify({
    mode: mode.value,
    auto: autoSendTime.value,
    func: down.func_code,
    end: down.end_flag,
    remote: down.remote_addr,
    center: down.center_addr,
    pwd: down.password,
    encoding: down.encoding,
    sn: down.serial_no,
    step_u: down.step_unit,
    step_v: down.step_value,
    guides: down.selectedGuides,
    elemPreset: down.elementPreset,
    params: down.params,
    basicCfg: down.basicConfig,
    old_p: down.old_password,
    new_p: down.new_password,
    ic: down.ic_enable,
    sw: down.switchOn,
    gc: down.gate_count,
    go: down.gateOn,
    gop: down.gate_openings,
    water: down.water_control,
    st: startTimeDt.value
      ? [startTimeDt.value.year, startTimeDt.value.month, startTimeDt.value.day, startTimeDt.value.hour]
      : null,
    et: endTimeDt.value
      ? [endTimeDt.value.year, endTimeDt.value.month, endTimeDt.value.day, endTimeDt.value.hour]
      : null,
    hexRaw: mode.value === "hex" ? hexRaw.value : "",
  });
}

/** 与后端 encoder 对齐的轻量校验；不通过则不请求接口 */
function validateBuildParams() {
  if (mode.value === "hex") return null;

  const remote = String(down.remote_addr || "").replace(/\s+/g, "");
  if (!remote) return "请填写遥测站址";
  if (!(remote.length === 10 && /^[0-9A-Fa-f]+$/.test(remote))) {
    return "遥测站址无效（需 10 位 Hex，0-9A-F）";
  }

  const center = String(down.center_addr || "").replace(/\s+/g, "");
  if (center && !/^[0-9A-Fa-f]{1,2}$/.test(center)) {
    return "中心站地址无效（1–2 位 Hex）";
  }

  const pwd = String(down.password || "").replace(/\s+/g, "");
  if (pwd && !/^[0-9A-Fa-f]{1,4}$/.test(pwd)) {
    return "密码无效（最多 4 位 Hex）";
  }

  if (schema.value === "period") {
    const g = (down.selectedGuides || [])[0];
    const stepErr = validatePeriodStep(down.step_unit, down.step_value, g);
    if (stepErr) return stepErr;
  }

  return null;
}

function scheduleHexRefresh() {
  if (hexRefreshTimer) clearTimeout(hexRefreshTimer);
  hexRefreshTimer = setTimeout(() => {
    hexRefreshTimer = null;
    refreshHex(autoSendTime.value ? "实时" : "");
  }, 320);
}

// 结构参数（不含 sendTimeDt）
watch(
  () => [
    mode.value,
    autoSendTime.value,
    down.func_code,
    down.end_flag,
    down.remote_addr,
    down.center_addr,
    down.password,
    down.encoding,
    down.serial_no,
    down.step_unit,
    down.step_value,
    down.selectedGuides,
    down.elementPreset,
    down.params,
    down.basicConfig,
    down.old_password,
    down.new_password,
    down.ic_enable,
    down.switchOn,
    down.gate_count,
    down.gateOn,
    down.gate_openings,
    down.water_control,
    startTimeDt.value,
    endTimeDt.value,
    hexRaw.value,
  ],
  () => scheduleHexRefresh(),
  { deep: true, immediate: true }
);

// 发报时间：自动模式只本地 patch；无有效帧时不补打后端（防 400 风暴）
watch(sendTimeDt, (dt) => {
  if (!dt || mode.value !== "down") return;
  if (autoSendTime.value) {
    if (lastStructureBuildOk && previewFrame.value?.hex) {
      patchPreviewSendTime(dt);
    }
    return;
  }
  // 手动时间：时间本身不在 structureKey 里，需单独触发组帧
  lastStructureKey = "";
  scheduleHexRefresh();
});

watch(autoSendTime, (on) => {
  if (on) startLiveSendTime();
  else stopLiveSendTime();
});

watch(mode, (m) => {
  if (m === "down" && autoSendTime.value) startLiveSendTime();
  else if (m !== "down") stopLiveSendTime();
});

onMounted(async () => {
  if (autoSendTime.value) startLiveSendTime();
  try {
    const r = await get("/api/down-meta");
    if (r.ok !== false) {
      downMeta.value = r;
      const meta = r.func_codes?.[down.func_code];
      if (meta?.end_flag) down.end_flag = meta.end_flag;
    }
  } catch {
    /* 旧后端无此接口时忽略 */
  }
});

onUnmounted(() => {
  stopLiveSendTime();
  if (hexRefreshTimer) clearTimeout(hexRefreshTimer);
});

function selectClient(c) {
  peer.value = c.peer;
  fillFromClient(c);
}

/**
 * 检查当前功能码正文是否齐全。
 * @returns {string|null} 不完整时的提示文案；完整返回 null
 */
function checkBodyIncomplete() {
  const s = schema.value;
  if (s === "period") {
    const miss = [];
    if (!startTimeDt.value) miss.push("起始时间");
    if (!endTimeDt.value) miss.push("结束时间");
    if (!(down.selectedGuides || []).length) miss.push("查询要素（仅 1 个）");
    if (miss.length) return `时段查询正文不完整，请填写：${miss.join("、")}`;
    const g = (down.selectedGuides || [])[0];
    const stepErr = validatePeriodStep(down.step_unit, down.step_value, g);
    if (stepErr) return stepErr;
    return null;
  }
  if (s === "guides") {
    if (!(down.selectedGuides || []).length) {
      return "请至少选择一个标识符（要素/配置参数）";
    }
    return null;
  }
  if (s === "params") {
    if (isBasicConfig40.value) {
      return validateBasicConfigForm(down.basicConfig);
    }
    const rows = (down.params || []).filter((p) => String(p.guide || "").trim());
    if (!rows.length) return "请至少添加一行参数（标识 + 数据 Hex）";
    const emptyData = rows.filter((p) => !String(p.value_hex || "").trim());
    if (emptyData.length) {
      return `参数数据不完整：标识 ${emptyData.map((p) => p.guide).join(", ")} 缺少数据 Hex`;
    }
    return null;
  }
  if (s === "password") {
    const miss = [];
    if (!String(down.old_password || "").trim()) miss.push("旧密码");
    if (!String(down.new_password || "").trim()) miss.push("新密码");
    if (miss.length) return `修改密码正文不完整，请填写：${miss.join("、")}`;
    return null;
  }
  if (s === "gate") {
    if (!(Number(down.gate_count) > 0)) return "请填写闸门数量";
    return null;
  }
  // simple / ic / switches / water / init_flag：公共头即可
  return null;
}

const bodyIncompleteHint = computed(() => checkBodyIncomplete());

function buildPayload() {
  const payload = {
    peer: peer.value,
    mode: "down",
    func_code: down.func_code,
    end_flag: down.end_flag,
    remote_addr: down.remote_addr,
    center_addr: down.center_addr,
    password: down.password,
    encoding: down.encoding,
    serial_no: Number(down.serial_no) || 0,
  };
  // 自动：组帧瞬间 now()；手动：选择器（不回写 sendTimeDt，避免触发循环刷新）
  const t = autoSendTime.value
    ? nowDateTime()
    : sendTimeDt.value || nowDateTime();
  payload.send_time = formatProtocolYmdHms(t);

  const s = schema.value;
  if (s === "period") {
    const st = formatProtocolYmdH(startTimeDt.value);
    const et = formatProtocolYmdH(endTimeDt.value);
    if (st) payload.start_time = st;
    if (et) payload.end_time = et;
    // HEX/BCD：只编 1 个要素标识；F4~FC 强制特定搭配步长
    const g = (down.selectedGuides || [])[0];
    payload.guides = g ? [g] : ["F4"];
    const guide = payload.guides[0];
    if (isHourComboGuide(guide)) {
      payload.step_unit = "H";
      payload.step_value = 0;
    } else {
      payload.step_unit = down.step_unit;
      payload.step_value = Number(down.step_value) || 5;
    }
  } else if (s === "guides") {
    payload.guides = [...(down.selectedGuides || [])];
  } else if (s === "params") {
    if (isBasicConfig40.value) {
      payload.params = basicConfigFormToParams(down.basicConfig);
    } else {
      payload.params = (down.params || [])
        .filter((p) => p.guide)
        .map((p) => ({ guide: p.guide, value_hex: p.value_hex || "" }));
    }
  } else if (s === "password") {
    payload.old_password = down.old_password;
    payload.new_password = down.new_password;
  } else if (s === "ic") {
    payload.ic_enable = !!down.ic_enable;
  } else if (s === "switches") {
    payload.switch_bits = bitsFromBools(down.switchOn);
  } else if (s === "gate") {
    payload.gate_count = Number(down.gate_count) || 1;
    payload.gate_bits = bitsFromBools(down.gateOn);
    payload.gate_openings_cm = String(down.gate_openings || "0")
      .split(/[,\s]+/)
      .filter(Boolean)
      .map((x) => Number(x) || 0);
  } else if (s === "water") {
    payload.water_control = down.water_control;
  }
  return payload;
}

function setPreviewFromBuild(r, note = "") {
  if (!r?.ok) {
    previewFrame.value = {
      hex: "",
      spaced: "",
      body_hex: "",
      end_flag: "",
      parsedText: "",
      error: r?.error || "组帧失败",
      note,
      incomplete: "",
    };
    return;
  }
  const hex = (r.hex || r.record?.raw_hex || "").replace(/\s+/g, "").toUpperCase();
  const body = (r.body_hex || "").replace(/\s+/g, "").toUpperCase();
  previewFrame.value = {
    hex,
    spaced: spaceHex(hex),
    body_hex: body,
    end_flag: r.end_flag || down.end_flag,
    parsedText: r.parsed ? prettySlimParsed(r.parsed) : "",
    error: "",
    note,
    incomplete: "",
  };
}

async function sendDown() {
  if (mode.value === "hex") {
    const hex = (hexRaw.value || "").replace(/\s+/g, "").toUpperCase();
    if (!hex) {
      toast.add({ title: "请输入原始 Hex", color: "warning" });
      return;
    }
  } else {
    const hint = checkBodyIncomplete();
    if (hint) {
      toast.add({ title: hint, color: "warning" });
      return;
    }
  }
  if (!peer.value) {
    toast.add({ title: "请先连接 RTU", color: "warning" });
    return;
  }
  sending.value = true;
  try {
    // 发送前：自动模式下再取一次当前时间，保证与发出帧一致
    if (mode.value !== "hex") {
      if (autoSendTime.value) sendTimeDt.value = nowDateTime();
      const built = await post("/api/build-down", buildPayload());
      setPreviewFromBuild(built, built.ok ? "即将发送" : "");
      if (!built.ok) {
        toast.add({ title: built.error || "组帧失败", color: "error" });
        return;
      }
    } else {
      const hex = (hexRaw.value || "").replace(/\s+/g, "").toUpperCase();
      previewFrame.value = {
        hex,
        spaced: spaceHex(hex),
        body_hex: "",
        end_flag: "",
        parsedText: "",
        error: "",
        note: "即将发送",
      };
    }

    const r =
      mode.value === "hex"
        ? await post("/api/send", { peer: peer.value, mode: "hex", hex: hexRaw.value })
        : await post("/api/send", buildPayload());
    if (!r.ok) {
      toast.add({ title: r.error || "发送失败", color: "error" });
    } else {
      const sentHex = (r.record?.raw_hex || previewFrame.value?.hex || "")
        .replace(/\s+/g, "")
        .toUpperCase();
      if (previewFrame.value) {
        previewFrame.value.hex = sentHex;
        previewFrame.value.spaced = spaceHex(sentHex);
        previewFrame.value.note = "已发送";
        if (r.record?.parsed) {
          previewFrame.value.parsedText = prettySlimParsed(r.record.parsed);
        }
      }
      toast.add({ title: "下行已发送", color: "success" });
    }
  } finally {
    sending.value = false;
  }
}

/** 结构组帧：校验失败 / 相同指纹 不重复请求后端 */
async function refreshHex(note = "") {
  if (mode.value === "hex") {
    const hex = (hexRaw.value || "").replace(/\s+/g, "").toUpperCase();
    lastStructureBuildOk = !!hex;
    lastStructureKey = structureKey();
    previewFrame.value = {
      hex,
      spaced: spaceHex(hex),
      body_hex: "",
      end_flag: "",
      parsedText: "",
      error: "",
      note: note || (hex ? "" : ""),
      incomplete: "",
    };
    return;
  }

  const key = structureKey();
  // 指纹相同：成功则只 patch 时间；失败则静默（避免 deep watch / 定时器重复 400）
  if (key === lastStructureKey) {
    if (lastStructureBuildOk && autoSendTime.value && sendTimeDt.value && previewFrame.value?.hex) {
      patchPreviewSendTime(sendTimeDt.value);
    }
    return;
  }

  const clientErr = validateBuildParams();
  if (clientErr) {
    lastStructureBuildOk = false;
    lastStructureKey = key;
    previewFrame.value = {
      hex: "",
      spaced: "",
      body_hex: "",
      end_flag: "",
      parsedText: "",
      error: clientErr,
      note: "",
      incomplete: checkBodyIncomplete() || "",
    };
    return;
  }

  const incomplete = checkBodyIncomplete();
  const seq = ++hexRefreshSeq;
  previewing.value = true;
  try {
    const r = await post("/api/build-down", buildPayload());
    if (seq !== hexRefreshSeq) return;
    lastStructureKey = key;
    lastStructureBuildOk = !!r.ok;
    setPreviewFromBuild(r, r.ok ? note : "");
    if (previewFrame.value) {
      previewFrame.value.incomplete = incomplete || "";
    }
    if (r.ok && autoSendTime.value && sendTimeDt.value) {
      patchPreviewSendTime(sendTimeDt.value);
    }
  } catch (e) {
    if (seq !== hexRefreshSeq) return;
    lastStructureKey = key;
    lastStructureBuildOk = false;
    setPreviewFromBuild({ ok: false, error: String(e) });
  } finally {
    if (seq === hexRefreshSeq) previewing.value = false;
  }
}

function addParamRow() {
  down.params.push({ guide: "", value_hex: "" });
}

function removeParamRow(i) {
  if (down.params.length <= 1) return;
  down.params.splice(i, 1);
}

async function doParse() {
  const hex = String(parseHex.value || "").trim();
  if (!hex) {
    toast.add({ title: "请粘贴报文 hex", color: "warning" });
    return;
  }
  parseLoading.value = true;
  try {
    const r = await post("/api/parse", { hex, encoding: parseEncoding.value });
    if (!r.ok) {
      toast.add({ title: r.error || "解析失败", color: "error" });
      return;
    }
    const parsed = r.parsed || {};
    const header = parsed.header || {};
    const body = parsed.body || {};
    emit("open-detail", {
      id: `offline-${Date.now()}`,
      ts: formatDisplayDateTime(nowDateTime()),
      direction: header.direction || "up",
      peer: "离线解析",
      raw_hex: parsed.raw_hex || hex.replace(/\s+/g, "").toUpperCase(),
      parsed,
      note: "离线解析",
      crc_ok: parsed.crc_ok,
      encoding: header.encoding,
      func_code: header.func_code,
      func_name: header.func_name,
      remote_addr: header.remote_addr || body.remote_addr,
      center_addr: header.center_addr,
      serial_no: body.serial_no,
      send_time: body.send_time,
    });
  } finally {
    parseLoading.value = false;
  }
}

async function rtuStart() {
  const r = await post("/api/rtu/start", {
    ...rtuForm,
    port: Number(props.centerPort) || 9000,
    encoding: rtuForm.encoding,
  });
  rtuMsg.value = r.ok ? "启动中..." : "失败: " + r.error;
  toast.add({
    title: r.ok ? "模拟 RTU 已启动" : r.error || "启动失败",
    color: r.ok ? "success" : "error",
  });
  setTimeout(() => emit("refresh"), 800);
}

async function rtuStop() {
  await post("/api/rtu/stop");
  rtuMsg.value = "已停止";
  toast.add({ title: "模拟 RTU 已停止", color: "neutral" });
  emit("refresh");
}

async function rtuSend(kind) {
  const r = await post("/api/rtu/send", {
    kind,
    water: rtuForm.water,
    rain: rtuForm.rain,
    voltage: rtuForm.voltage,
  });
  if (!r.ok) toast.add({ title: r.error || "失败", color: "error" });
  else toast.add({ title: `已发送 ${kind}`, color: "success" });
}

async function rtuSendHex() {
  const hex = (rtuHex.value || "").trim();
  if (!hex) {
    toast.add({ title: "请输入自定义 Hex", color: "warning" });
    return;
  }
  rtuSending.value = true;
  try {
    const r = await post("/api/rtu/send", { kind: "hex", hex });
    if (!r.ok) toast.add({ title: r.error || "发送失败", color: "error" });
    else toast.add({ title: "自定义 Hex 已发送", color: "success" });
  } finally {
    rtuSending.value = false;
  }
}
</script>

<template>
  <aside class="flex flex-col gap-3">
    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-cable" class="size-4 text-primary" />
          <span class="text-sm font-semibold">已连接 RTU</span>
        </div>
      </template>

      <UEmpty v-if="!clients.length" icon="i-lucide-unplug" title="暂无连接" description="等待 RTU 接入 TCP 端口" />
      <div v-else class="flex flex-col gap-2 max-h-44 overflow-auto">
        <UButton
          v-for="c in clients"
          :key="c.peer"
          :variant="peer === c.peer ? 'soft' : 'ghost'"
          :color="peer === c.peer ? 'primary' : 'neutral'"
          class="justify-start"
          block
          @click="selectClient(c)"
        >
          <div class="text-left w-full">
            <div class="font-mono text-xs">{{ c.peer }}</div>
            <div class="text-xs text-muted">站址 {{ c.remote_addr || "-" }} · ↑{{ c.up_count }} ↓{{ c.down_count }}</div>
          </div>
        </UButton>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-send" class="size-4 text-primary" />
          <span class="text-sm font-semibold">下行调试</span>
        </div>
      </template>

      <div class="flex flex-col gap-3">
        <UFormField label="目标 peer">
          <USelect
            v-model="peer"
            :items="peerItems"
            :placeholder="peerItems.length ? '选择 RTU' : '无可用连接'"
            value-key="value"
            class="w-full"
            :disabled="!peerItems.length"
          />
        </UFormField>
        <UFormField label="模式">
          <USelect v-model="mode" :items="modeItems" value-key="value" class="w-full" />
        </UFormField>

        <template v-if="mode === 'down'">
          <UFormField label="线路编码">
            <USelect v-model="down.encoding" :items="encodingItems" value-key="value" class="w-full" />
          </UFormField>
          <UFormField label="功能码">
            <USelect
              v-model="down.func_code"
              :items="funcOptions"
              value-key="value"
              class="w-full"
              :ui="{
                base: 'w-full',
                trailing: 'pe-2',
                content: 'min-w-[var(--reka-select-trigger-width)] max-w-[min(90vw,28rem)]',
                itemLabel: 'whitespace-normal break-all',
                value: 'truncate',
              }"
            />
          </UFormField>

          <div class="grid grid-cols-2 gap-2">
            <UFormField label="结束符">
              <USelect v-model="down.end_flag" :items="endItems" value-key="value" class="w-full" />
            </UFormField>
            <UFormField label="中心站">
              <UInput v-model="down.center_addr" placeholder="01" />
            </UFormField>
          </div>
          <UFormField label="遥测站址">
            <UInput v-model="down.remote_addr" placeholder="0010100001" class="w-full" />
          </UFormField>
          <div class="grid grid-cols-2 gap-2">
            <UFormField label="密码">
              <UInput v-model="down.password" />
            </UFormField>
            <UFormField label="流水号">
              <UInput v-model.number="down.serial_no" type="number" min="0" />
            </UFormField>
          </div>
          <UFormField label="发报时间">
            <div class="flex flex-col gap-2 w-full">
              <UCheckbox v-model="autoSendTime" label="发送时自动（预览实时刷新）" />
              <div class="flex items-center gap-2 w-full">
                <UInputDate
                  ref="sendTimeInput"
                  v-model="sendTimeDt"
                  locale="zh-CN"
                  granularity="second"
                  :hour-cycle="24"
                  :disabled="autoSendTime"
                  class="flex-1 min-w-0"
                >
                  <template #trailing>
                    <UPopover v-if="!autoSendTime" :reference="sendTimeInput?.inputsRef?.[0]?.$el">
                      <UButton
                        color="neutral"
                        variant="link"
                        size="sm"
                        icon="i-lucide-calendar-clock"
                        aria-label="选择发报时间"
                        class="px-0"
                      />
                      <template #content>
                        <UCalendar v-model="sendTimeDt" locale="zh-CN" class="p-2" />
                      </template>
                    </UPopover>
                  </template>
                </UInputDate>
                <UButton
                  v-if="!autoSendTime"
                  size="sm"
                  color="neutral"
                  variant="soft"
                  class="shrink-0"
                  @click="sendTimeDt = nowDateTime()"
                >
                  现在
                </UButton>
              </div>
            </div>
          </UFormField>

          <!-- 正文参数：随功能码 schema 切换表单 -->
          <div
            class="rounded-lg border border-primary/30 bg-primary/5 p-3 flex flex-col gap-3"
          >
            <div class="text-sm font-semibold text-highlighted">正文参数</div>

            <!-- simple：无需额外字段 -->
            <template v-if="schema === 'simple'">
              <p class="text-xs text-muted m-0">本功能码无需额外正文参数</p>
            </template>

            <!-- 38 时段 -->
            <template v-else-if="schema === 'period'">
              <UFormField label="起始时间">
                <UInputDate
                  ref="startTimeInput"
                  v-model="startTimeDt"
                  locale="zh-CN"
                  granularity="hour"
                  :hour-cycle="24"
                  class="w-full"
                >
                  <template #trailing>
                    <UPopover :reference="startTimeInput?.inputsRef?.[0]?.$el">
                      <UButton
                        color="neutral"
                        variant="link"
                        size="sm"
                        icon="i-lucide-calendar"
                        class="px-0"
                      />
                      <template #content>
                        <UCalendar v-model="startTimeDt" locale="zh-CN" class="p-2" />
                      </template>
                    </UPopover>
                  </template>
                </UInputDate>
              </UFormField>
              <UFormField label="结束时间">
                <UInputDate
                  ref="endTimeInput"
                  v-model="endTimeDt"
                  locale="zh-CN"
                  granularity="hour"
                  :hour-cycle="24"
                  class="w-full"
                >
                  <template #trailing>
                    <UPopover :reference="endTimeInput?.inputsRef?.[0]?.$el">
                      <UButton
                        color="neutral"
                        variant="link"
                        size="sm"
                        icon="i-lucide-calendar"
                        class="px-0"
                      />
                      <template #content>
                        <UCalendar v-model="endTimeDt" locale="zh-CN" class="p-2" />
                      </template>
                    </UPopover>
                  </template>
                </UInputDate>
              </UFormField>
              <template v-if="periodStepLocked">
                <UFormField label="时间步长">
                  <UInput
                    model-value="特定搭配 000000（F4/F5… 固定，内含每5分钟）"
                    disabled
                    class="w-full"
                  />
                </UFormField>
              </template>
              <template v-else>
                <div class="grid grid-cols-2 gap-2">
                  <UFormField label="时间步长单位">
                    <USelect
                      v-model="down.step_unit"
                      :items="stepUnitItems"
                      value-key="value"
                      class="w-full"
                    />
                  </UFormField>
                  <UFormField label="步长值">
                    <UInput
                      v-model.number="down.step_value"
                      type="number"
                      min="1"
                      :max="down.step_unit === 'D' ? 31 : down.step_unit === 'H' ? 23 : 59"
                    />
                  </UFormField>
                </div>
                <p v-if="periodStepHint" class="text-xs text-muted m-0 -mt-1">
                  建议匹配步长：{{ periodStepHint }}
                </p>
              </template>
              <UFormField label="查询要素">
                <USelect
                  v-model="periodGuide"
                  :items="guideSelectItems"
                  value-key="value"
                  class="w-full"
                />
              </UFormField>
            </template>

            <!-- 3A 指定要素：仅两种预设 -->
            <template v-else-if="schema === 'guides' && isElementQuery3A">
              <UFormField label="查询模式">
                <USelect
                  :model-value="down.elementPreset"
                  :items="elementPresetItems"
                  value-key="value"
                  class="w-full"
                  @update:model-value="applyElementPreset"
                />
              </UFormField>
              <ul class="text-xs text-muted m-0 pl-4 list-disc space-y-0.5">
                <li v-for="name in currentElementPreset.names" :key="name">
                  {{ name }}
                </li>
              </ul>
            </template>

            <!-- 41 / 43 标识符多选 -->
            <template v-else-if="schema === 'guides'">
              <UFormField
                :label="
                  funcMeta.guideSource === 'basic'
                    ? '读取哪些基本配置项'
                    : funcMeta.guideSource === 'run'
                      ? '读取哪些运行参数'
                      : '查询哪些要素'
                "
              >
                <USelect
                  v-model="down.selectedGuides"
                  :items="guideSelectItems"
                  value-key="value"
                  multiple
                  class="w-full"
                />
              </UFormField>
              <p class="text-[10px] text-muted font-mono m-0">
                已选：{{ (down.selectedGuides || []).join(" ") || "（空）" }}
              </p>
            </template>

            <!-- 40 修改基本配置：固定可编辑项 -->
            <template v-else-if="schema === 'params' && isBasicConfig40">
              <UFormField label="中心站地址（4 个，0=禁用）">
                <div class="grid grid-cols-4 gap-1">
                  <UInput
                    v-for="(_, i) in down.basicConfig.centers"
                    :key="i"
                    v-model.number="down.basicConfig.centers[i]"
                    type="number"
                    min="0"
                    max="255"
                    :placeholder="`中心${i + 1}`"
                  />
                </div>
              </UFormField>
              <UFormField label="遥测站地址">
                <UInput v-model="down.basicConfig.remote_addr" placeholder="0011223344" class="font-mono" />
              </UFormField>
              <UFormField label="主信道类型">
                <USelect
                  v-model="down.basicConfig.main_channel_type"
                  :items="channelTypeItems"
                  value-key="value"
                  class="w-full"
                />
              </UFormField>
              <div v-if="mainChannelType === 2" class="grid grid-cols-3 gap-2">
                <UFormField label="主信道 IP" class="col-span-2">
                  <UInput v-model="down.basicConfig.main_ip" placeholder="118.178.94.91" />
                </UFormField>
                <UFormField label="端口">
                  <UInput v-model.number="down.basicConfig.main_port" type="number" min="1" max="65535" />
                </UFormField>
              </div>
              <UFormField v-else-if="mainChannelType === 1" label="主信道短信号码">
                <UInput v-model="down.basicConfig.main_phone" placeholder="013987654321" class="font-mono" />
              </UFormField>
              <UFormField
                v-else-if="mainChannelType > 2"
                label="主信道地址（Hex）"
              >
                <UInput
                  v-model="down.basicConfig.main_addr_hex"
                  placeholder="按信道类型填写地址 Hex"
                  class="font-mono"
                />
              </UFormField>
              <UFormField label="备用短信号码">
                <UInput v-model="down.basicConfig.backup_phone" placeholder="013987654321" class="font-mono" />
              </UFormField>
              <UFormField label="工作方式">
                <USelect
                  v-model="down.basicConfig.work_mode"
                  :items="workModeItems"
                  value-key="value"
                  class="w-full"
                />
              </UFormField>
              <UFormField label="采集要素">
                <UInput model-value="降水量 + 水位1" disabled class="w-full" />
              </UFormField>
              <UFormField label="移动通信卡识别号">
                <UInput v-model="down.basicConfig.device_id" placeholder="013012345678" class="font-mono" />
              </UFormField>
            </template>

            <!-- 42 改运行参数 -->
            <template v-else-if="schema === 'params'">
              <p class="text-xs text-muted m-0">
                每行一组：参数标识 + 数据 Hex（数据长度自动写入 info 字节）
              </p>
              <div v-for="(p, i) in down.params" :key="i" class="flex gap-1 items-end">
                <UFormField label="标识" class="w-28">
                  <UInputMenu
                    v-model="p.guide"
                    :items="guideSelectItems.map((g) => g.value)"
                    placeholder="01"
                    class="w-full font-mono text-xs"
                  />
                </UFormField>
                <UFormField label="数据 Hex" class="flex-1">
                  <UInput v-model="p.value_hex" placeholder="必填，如 01 或 BCD" class="font-mono text-xs" />
                </UFormField>
                <UButton
                  size="sm"
                  color="neutral"
                  variant="ghost"
                  icon="i-lucide-trash-2"
                  @click="removeParamRow(i)"
                />
              </div>
              <UButton size="sm" color="neutral" variant="soft" icon="i-lucide-plus" @click="addParamRow">
                添加参数行
              </UButton>
            </template>

            <!-- 49 密码 -->
            <template v-else-if="schema === 'password'">
              <div class="grid grid-cols-2 gap-2">
                <UFormField label="旧密码 (HEX)">
                  <UInput v-model="down.old_password" class="font-mono" placeholder="A000" />
                </UFormField>
                <UFormField label="新密码 (HEX)">
                  <UInput v-model="down.new_password" class="font-mono" placeholder="1234" />
                </UFormField>
              </div>
              <p class="text-[10px] text-muted m-0">编码：03 10 + 旧2字节 + 03 10 + 新2字节</p>
            </template>

            <!-- 4B IC -->
            <template v-else-if="schema === 'ic'">
              <UCheckbox v-model="down.ic_enable" label="启用 IC 卡功能（状态 BIT9=1）" />
              <p class="text-[10px] text-muted m-0">编码：45 20 + 4 字节状态字</p>
            </template>

            <!-- 4C / 4D 开关 -->
            <template v-else-if="schema === 'switches'">
              <div class="text-xs font-medium">{{ switchLabel }} 1–8（勾选=开）</div>
              <div class="grid grid-cols-4 gap-2">
                <UCheckbox
                  v-for="i in 8"
                  :key="i"
                  v-model="down.switchOn[i - 1]"
                  :label="`${switchLabel}${i}`"
                />
              </div>
              <p class="text-[10px] text-muted font-mono m-0">
                位图 = 0x{{ bitsFromBools(down.switchOn).toString(16).toUpperCase().padStart(2, "0") }}
              </p>
            </template>

            <!-- 4E 闸门 -->
            <template v-else-if="schema === 'gate'">
              <UFormField label="闸门数量">
                <UInput v-model.number="down.gate_count" type="number" min="1" max="16" />
              </UFormField>
              <div class="text-xs font-medium">闸门开关（勾选=开）</div>
              <div class="grid grid-cols-4 gap-2">
                <UCheckbox
                  v-for="i in Math.min(8, Number(down.gate_count) || 1)"
                  :key="'g' + i"
                  v-model="down.gateOn[i - 1]"
                  :label="`闸${i}`"
                />
              </div>
              <UFormField label="开度 cm" hint="逗号分隔，与闸门顺序对应">
                <UInput v-model="down.gate_openings" placeholder="0,10,20" class="font-mono text-xs" />
              </UFormField>
            </template>

            <!-- 4F 定值 -->
            <template v-else-if="schema === 'water'">
              <UFormField label="定值控制命令">
                <USelect v-model="down.water_control" :items="waterItems" value-key="value" class="w-full" />
              </UFormField>
              <p class="text-[10px] text-muted m-0">编码 1 字节：FF=投入，00=退出</p>
            </template>

            <!-- 47 / 48 -->
            <template v-else-if="schema === 'init_flag'">
              <UAlert
                color="warning"
                variant="subtle"
                icon="i-lucide-triangle-alert"
                :title="down.func_code === '47' ? '将写入标识 97 00' : '将写入标识 98 00'"
                :description="
                  down.func_code === '47'
                    ? '初始化固态存储（清除历史数据），请确认目标 RTU'
                    : '恢复出厂设置，请确认目标 RTU'
                "
              />
            </template>
          </div>

          <UAlert
            v-if="mode === 'down' && bodyIncompleteHint"
            color="warning"
            variant="subtle"
            icon="i-lucide-info"
            :title="bodyIncompleteHint"
            class="mt-0"
          />

          <div class="flex gap-2">
            <UButton color="primary" icon="i-lucide-send" :loading="sending" @click="sendDown">发送</UButton>
          </div>
        </template>
        <template v-else>
          <UFormField label="原始 Hex">
            <UTextarea
              v-model="hexRaw"
              :rows="5"
              placeholder="7E7E... 或 01...（ASCII）"
              class="w-full font-mono text-xs"
              :ui="{ base: 'w-full min-h-[7rem]' }"
            />
          </UFormField>
          <div class="flex gap-2">
            <UButton color="primary" icon="i-lucide-send" :loading="sending" @click="sendDown">发送 Hex</UButton>
          </div>
        </template>

        <!-- 完整帧 Hex：参数变化自动刷新 + 复制 -->
        <div class="rounded-lg border border-default p-3 flex flex-col gap-2">
          <div class="flex items-center justify-between gap-2">
            <div class="text-xs font-semibold text-highlighted">
              完整帧 Hex
              <span v-if="previewFrame?.note" class="text-muted font-normal">· {{ previewFrame.note }}</span>
              <span v-if="previewing" class="text-muted font-normal">· 生成中…</span>
            </div>
            <UButton
              size="xs"
              color="neutral"
              variant="soft"
              icon="i-lucide-copy"
              :disabled="!previewFrame?.hex"
              @click="copyText(previewFrame?.hex, '已复制 Hex')"
            >
              复制
            </UButton>
          </div>
          <p v-if="previewFrame?.error" class="text-xs text-error m-0">{{ previewFrame.error }}</p>
          <pre
            class="font-mono text-xs whitespace-pre-wrap break-all m-0 p-2 rounded bg-elevated border border-default min-h-[3.5rem] max-h-36 overflow-auto"
          >{{ previewFrame?.spaced || previewFrame?.hex || "参数变化后自动生成…" }}</pre>
        </div>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-cpu" class="size-4 text-primary" />
          <span class="text-sm font-semibold">模拟 RTU</span>
        </div>
      </template>

      <div class="flex flex-col gap-3">
        <div class="grid grid-cols-2 gap-2">
          <UFormField label="站址"><UInput v-model="rtuForm.remote_addr" /></UFormField>
          <UFormField label="密码"><UInput v-model="rtuForm.password" /></UFormField>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <UFormField label="心跳(秒)"><UInput v-model.number="rtuForm.heartbeat" type="number" /></UFormField>
          <UFormField label="定时报(秒)"><UInput v-model.number="rtuForm.report" type="number" /></UFormField>
        </div>
        <div class="grid grid-cols-3 gap-2">
          <UFormField label="水位"><UInput v-model.number="rtuForm.water" type="number" step="0.01" /></UFormField>
          <UFormField label="雨量"><UInput v-model.number="rtuForm.rain" type="number" step="0.1" /></UFormField>
          <UFormField label="电压"><UInput v-model.number="rtuForm.voltage" type="number" step="0.01" /></UFormField>
        </div>
        <UFormField label="线路编码">
          <USelect v-model="rtuForm.encoding" :items="encodingItems" value-key="value" class="w-full" />
        </UFormField>
        <div class="flex flex-wrap gap-2">
          <UButton color="primary" icon="i-lucide-play" @click="rtuStart">启动</UButton>
          <UButton color="neutral" variant="soft" icon="i-lucide-square" @click="rtuStop">停止</UButton>
        </div>
        <div class="flex flex-wrap gap-2">
          <UButton size="sm" color="neutral" variant="outline" @click="rtuSend('heartbeat')">发心跳</UButton>
          <UButton size="sm" color="neutral" variant="outline" @click="rtuSend('report')">发定时报</UButton>
          <UButton size="sm" color="neutral" variant="outline" @click="rtuSend('alarm')">发加报</UButton>
        </div>
        <UFormField label="自定义上行 Hex">
          <UTextarea
            v-model="rtuHex"
            :rows="5"
            placeholder="7E7E... 或 01... 完整帧（含 CRC）"
            class="w-full font-mono text-xs"
            :ui="{ base: 'w-full min-h-[7rem]' }"
          />
        </UFormField>
        <UButton color="primary" icon="i-lucide-send" :loading="rtuSending" @click="rtuSendHex">
          发送 Hex
        </UButton>
        <p class="text-xs text-muted">{{ rtuMsg }}</p>
      </div>
    </UCard>

    <UCard>
      <template #header>
        <div class="flex items-center gap-2">
          <UIcon name="i-lucide-binary" class="size-4 text-primary" />
          <span class="text-sm font-semibold">离线解析</span>
        </div>
      </template>
      <div class="flex flex-col gap-3">
        <UFormField label="线路编码">
          <USelect
            v-model="parseEncoding"
            :items="parseEncodingItems"
            value-key="value"
            class="w-full"
          />
        </UFormField>
        <UTextarea
          v-model="parseHex"
          :rows="4"
          placeholder="粘贴 7E7E... 或 01...（ASCII）报文"
          class="w-full font-mono text-xs"
          :ui="{ base: 'w-full min-h-[6rem]' }"
        />
        <UButton
          color="primary"
          icon="i-lucide-scan-search"
          :loading="parseLoading"
          @click="doParse"
        >
          解析并查看详情
        </UButton>
      </div>
    </UCard>
  </aside>
</template>
