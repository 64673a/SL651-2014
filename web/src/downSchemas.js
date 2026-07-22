/**
 * 下行功能码表单 schema（与 sl651/down_builder.py / 国标+REF 对齐）
 * 前端内置，不依赖 /api/down-meta 也能切换表单。
 */

/** @typedef {"simple"|"period"|"guides"|"params"|"password"|"ic"|"switches"|"gate"|"water"|"init_flag"} SchemaKind */

/**
 * @type {Record<string, {
 *   schema: SchemaKind,
 *   end_flag: string,
 *   title: string,
 *   body_desc: string,
 *   guideSource?: "element"|"basic"|"run",
 *   defaultGuides?: string[],
 * }}
 */
export const FUNC_DOWN_META = {
  "30": {
    schema: "simple",
    end_flag: "1B",
    title: "确认 · 测试报",
    body_desc: "仅流水号 + 发报时间（确认帧）",
  },
  "31": {
    schema: "simple",
    end_flag: "1B",
    title: "确认 · 均匀时段报",
    body_desc: "仅流水号 + 发报时间（确认帧）",
  },
  "32": {
    schema: "simple",
    end_flag: "1B",
    title: "确认 · 定时报",
    body_desc: "仅流水号 + 发报时间（确认帧）",
  },
  "33": {
    schema: "simple",
    end_flag: "1B",
    title: "确认 · 加报",
    body_desc: "仅流水号 + 发报时间（确认帧）",
  },
  "34": {
    schema: "simple",
    end_flag: "1B",
    title: "确认 · 小时报",
    body_desc: "仅流水号 + 发报时间（确认帧）",
  },
  "35": {
    schema: "simple",
    end_flag: "1B",
    title: "确认 · 人工置数报",
    body_desc: "仅流水号 + 发报时间（确认帧）",
  },
  "36": {
    schema: "simple",
    end_flag: "05",
    title: "查询图片",
    body_desc: "流水号 + 发报时间",
  },
  "37": {
    schema: "simple",
    end_flag: "05",
    title: "查询实时数据",
    body_desc: "流水号 + 发报时间",
  },
  "38": {
    schema: "period",
    end_flag: "05",
    title: "查询时段数据",
    // 表44 注2：一般情况下宜编列 1 个要素；ASCII 才允许多要素。本工具 HEX/BCD → 单选
    body_desc: "流水号 + 发报时间 + 起始(4) + 结束(4) + 步长(0418+dhm) + 1个要素标识(HEX 宜单要素)",
    guideSource: "element",
    defaultGuides: ["F4"],
  },
  "39": {
    schema: "simple",
    end_flag: "05",
    title: "查询人工置数",
    body_desc: "流水号 + 发报时间",
  },
  "3A": {
    schema: "guides",
    end_flag: "05",
    title: "查询指定要素",
    body_desc: "流水号 + 发报时间 + 要素标识序列(guide+info，无数据体)",
    guideSource: "element",
    defaultGuides: ["F4"],
  },
  "40": {
    schema: "params",
    end_flag: "05",
    title: "修改基本配置",
    body_desc: "流水号 + 发报时间 + 参数标识 + 数据",
    guideSource: "basic",
  },
  "41": {
    schema: "guides",
    end_flag: "05",
    title: "读取基本配置",
    body_desc: "流水号 + 发报时间 + 配置参数标识(仅 id)",
    guideSource: "basic",
    defaultGuides: ["01", "02", "03", "04", "05", "0C", "0D", "0F"],
  },
  "42": {
    schema: "params",
    end_flag: "05",
    title: "修改运行参数",
    body_desc: "流水号 + 发报时间 + 参数标识 + 数据",
    guideSource: "run",
  },
  "43": {
    schema: "guides",
    end_flag: "05",
    title: "读取运行参数",
    body_desc: "流水号 + 发报时间 + 运行参数标识(仅 id)",
    guideSource: "run",
    defaultGuides: ["20", "21", "22", "23", "24", "25", "26", "27", "28", "30", "38", "40", "41"],
  },
  "44": {
    schema: "simple",
    end_flag: "05",
    title: "查询水泵电机数据",
    body_desc: "流水号 + 发报时间",
  },
  "45": {
    schema: "simple",
    end_flag: "05",
    title: "查询软件版本",
    body_desc: "流水号 + 发报时间",
  },
  "46": {
    schema: "simple",
    end_flag: "05",
    title: "查询状态报警",
    body_desc: "流水号 + 发报时间",
  },
  "47": {
    schema: "init_flag",
    end_flag: "05",
    title: "初始化固态存储",
    body_desc: "流水号 + 发报时间 + 97 00",
  },
  "48": {
    schema: "init_flag",
    end_flag: "05",
    title: "恢复出厂设置",
    body_desc: "流水号 + 发报时间 + 98 00",
  },
  "49": {
    schema: "password",
    end_flag: "05",
    title: "修改密码",
    body_desc: "流水号 + 发报时间 + 03 10 旧密码 + 03 10 新密码",
  },
  "4A": {
    schema: "simple",
    end_flag: "05",
    title: "设置时钟",
    body_desc: "流水号 + 发报时间（发报时间即校时时间）",
  },
  "4B": {
    schema: "ic",
    end_flag: "05",
    title: "设置 IC 卡状态",
    body_desc: "流水号 + 发报时间 + 45 20 + 4 字节状态(BIT9)",
  },
  "4C": {
    schema: "switches",
    end_flag: "05",
    title: "控制水泵开关",
    body_desc: "流水号 + 发报时间 + len + 状态字节(D0=1号泵…)",
    switchLabel: "水泵",
  },
  "4D": {
    schema: "switches",
    end_flag: "05",
    title: "控制阀门开关",
    body_desc: "流水号 + 发报时间 + len + 状态字节(D0=1号阀…)",
    switchLabel: "阀门",
  },
  "4E": {
    schema: "gate",
    end_flag: "05",
    title: "控制闸门开关",
    body_desc: "流水号 + 发报时间 + 闸数 + 状态 + 开度(BCD cm)",
  },
  "4F": {
    schema: "water",
    end_flag: "05",
    title: "水量定值控制",
    body_desc: "流水号 + 发报时间 + FF(投入)/00(退出)",
  },
  "50": {
    schema: "simple",
    end_flag: "05",
    title: "查询事件记录",
    body_desc: "流水号 + 发报时间",
  },
  "51": {
    schema: "simple",
    end_flag: "05",
    title: "查询时钟",
    body_desc: "流水号 + 发报时间",
  },
};

export function getFuncMeta(code) {
  const c = String(code || "").toUpperCase().padStart(2, "0");
  return (
    FUNC_DOWN_META[c] || {
      schema: "simple",
      end_flag: "05",
      title: `功能码 ${c}`,
      body_desc: "流水号 + 发报时间（未知功能码默认）",
    }
  );
}

/** 常用要素（3A/38） */
export const ELEMENT_GUIDE_OPTIONS = [
  { value: "F4", label: "F4 DRP 1小时5分钟雨量" },
  { value: "20", label: "20 PJ 当前降水量" },
  { value: "22", label: "22 PN05 5分钟雨量" },
  { value: "26", label: "26 PT 累计雨量" },
  { value: "38", label: "38 VT 电源电压" },
  { value: "39", label: "39 Z 河道水位" },
  { value: "3A", label: "3A ZB 库下水位" },
  { value: "3B", label: "3B ZU 库上水位" },
  { value: "27", label: "27 Q 瞬时流量" },
  { value: "1A", label: "1A P1 1小时雨量" },
  { value: "45", label: "45 ZT 状态报警" },
];

/** 基本配置表 D.1 */
export const BASIC_GUIDE_OPTIONS = [
  { value: "01", label: "01 中心站地址" },
  { value: "02", label: "02 遥测站地址" },
  { value: "03", label: "03 密码" },
  { value: "04", label: "04 中心站1主信道" },
  { value: "05", label: "05 中心站1备用信道" },
  { value: "0C", label: "0C 工作方式" },
  { value: "0D", label: "0D 采集要素设置" },
  { value: "0F", label: "0F 通信设备识别号" },
];

/** 运行参数常用 */
export const RUN_GUIDE_OPTIONS = [
  { value: "20", label: "20 定时报时间间隔" },
  { value: "21", label: "21 加报时间间隔" },
  { value: "22", label: "22 降水量日起始时间" },
  { value: "23", label: "23 采样间隔" },
  { value: "24", label: "24 水位存储间隔" },
  { value: "25", label: "25 雨量计分辨力" },
  { value: "26", label: "26 水位计分辨力" },
  { value: "27", label: "27 雨量加报阈值" },
  { value: "28", label: "28 水位基值1" },
  { value: "30", label: "30 水位修正基值1" },
  { value: "38", label: "38 加报水位1" },
  { value: "40", label: "40 加报水位以上阈值" },
  { value: "41", label: "41 加报水位以下阈值" },
];

export function guideOptionsFor(source) {
  if (source === "basic") return BASIC_GUIDE_OPTIONS;
  if (source === "run") return RUN_GUIDE_OPTIONS;
  return ELEMENT_GUIDE_OPTIONS;
}
